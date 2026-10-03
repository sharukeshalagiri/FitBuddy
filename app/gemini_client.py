"""Single shared google-genai client plus structured-JSON / text call helpers with retries."""
import logging
import time
from typing import TypeVar

import httpx
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app import config

log = logging.getLogger("fitbuddy.gemini")
T = TypeVar("T", bound=BaseModel)

_client = None

# Time limits per user request (seconds). A plan request (retry, invalid-JSON retry and
# fallback model included) never runs longer than PLAN_TIME_LIMIT; each HTTP timeout is
# capped to the time that is left. The tip gets one short attempt, so plan + tip <= 60 s.
PLAN_TIME_LIMIT = 50.0
TIP_TIME_LIMIT = 10.0
# Don't start an extra attempt (retry or fallback) with less time than this left.
# It equals TIP_TIME_LIMIT, so the tip can never get a second attempt.
MIN_ATTEMPT_SECONDS = 10.0
RETRY_DELAY_SECONDS = 2.0

# Errors where trying a different model can help (busy primary, or no access to it).
FALLBACK_KINDS = {"overloaded", "model_not_found"}


class GeminiError(Exception):
    """Typed error for any AI failure. Routes turn this into a friendly message / HTTP 502."""

    def __init__(self, message: str, kind: str = "api"):
        super().__init__(message)
        # "not_configured" | "model_not_found" | "auth" | "overloaded" | "timeout" |
        # "network" | "invalid_output" | "api"
        self.kind = kind


def get_client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise GeminiError("Gemini API key is not configured", "not_configured")
        from google import genai
        _client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=config.GEMINI_TIMEOUT_SECONDS * 1000),
        )
    return _client


def _is_transient(exc: Exception) -> bool:
    """Server errors (5xx), rate limits (429), timeouts and connection problems."""
    if isinstance(exc, errors.ServerError):
        return True
    if isinstance(exc, errors.ClientError):
        return exc.code == 429
    return isinstance(exc, httpx.TransportError)  # includes httpx.TimeoutException


def _to_gemini_error(exc: Exception, model: str) -> GeminiError:
    if isinstance(exc, errors.ClientError) and exc.code == 404:
        log.error("Gemini model not found: '%s'. Check GEMINI_*_MODEL in .env. (%s)", model, exc)
        return GeminiError(f"Model '{model}' was not found", "model_not_found")
    if isinstance(exc, errors.ClientError) and exc.code in (401, 403):
        log.error("Gemini rejected the API key (%s): %s", exc.code, exc)
        return GeminiError("Gemini API key was rejected", "auth")
    log.error("Gemini call to %s failed: %r", model, exc)
    if isinstance(exc, httpx.TimeoutException):
        return GeminiError("The AI service took too long to respond", "timeout")
    if isinstance(exc, httpx.TransportError):
        return GeminiError("Could not reach the AI service", "network")
    if _is_transient(exc):
        return GeminiError("The AI service is busy right now", "overloaded")
    return GeminiError("The AI service rejected the request", "api")


def _seconds_left(deadline: float) -> float:
    return deadline - time.monotonic()


def _check_time_for_extra_attempt(deadline: float, wait: float = 0.0) -> None:
    """Raise instead of starting a retry/fallback when too little time is left."""
    left = _seconds_left(deadline)
    if left - wait < MIN_ATTEMPT_SECONDS:
        log.error("Gemini time limit nearly spent (%.1fs left); giving up", max(left, 0.0))
        raise GeminiError("The AI service took too long to respond", "timeout")


def _with_timeout(gen_config, deadline: float):
    """Copy of gen_config whose HTTP timeout is min(configured timeout, time left)."""
    seconds = min(float(config.GEMINI_TIMEOUT_SECONDS), _seconds_left(deadline))
    timeout_ms = max(int(seconds * 1000), 1)
    return gen_config.model_copy(update={"http_options": types.HttpOptions(timeout=timeout_ms)})


def _call(model: str, contents: str, gen_config, deadline: float):
    """Call Gemini once, retrying once on a transient error if there is time for it."""
    client = get_client()
    retried = False
    while True:
        try:
            return client.models.generate_content(model=model, contents=contents,
                                                  config=_with_timeout(gen_config, deadline))
        except Exception as exc:
            if retried or not _is_transient(exc):
                raise _to_gemini_error(exc, model) from exc
            _check_time_for_extra_attempt(deadline, wait=RETRY_DELAY_SECONDS)
            log.warning("Transient Gemini error from %s (%r), retrying...", model, exc)
        retried = True
        time.sleep(RETRY_DELAY_SECONDS)


def generate_structured(model: str, system: str, prompt: str, schema: type[T],
                        fallback_model: str | None = None) -> tuple[T, str]:
    """Ask Gemini for JSON matching `schema`; return (validated model, model id used).

    If the primary model is overloaded or not found, try `fallback_model` once.
    All attempts share PLAN_TIME_LIMIT seconds.
    """
    deadline = time.monotonic() + PLAN_TIME_LIMIT
    gen_config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.7,
    )
    models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
    for i, current in enumerate(models):
        if i > 0:
            _check_time_for_extra_attempt(deadline)
            log.warning("Falling back from %s to %s", models[i - 1], current)
        try:
            return _validated_call(current, prompt, gen_config, schema, deadline), current
        except GeminiError as exc:
            if exc.kind not in FALLBACK_KINDS or current == models[-1]:
                raise


def _validated_call(model: str, prompt: str, gen_config, schema: type[T], deadline: float) -> T:
    """Call the model and validate its JSON; one extra attempt if the output is invalid."""
    last_error = None
    for attempt in range(2):
        if attempt > 0:
            _check_time_for_extra_attempt(deadline)
        started = time.perf_counter()
        response = _call(model, prompt, gen_config, deadline)
        log.info("Gemini %s structured call took %.2fs", model, time.perf_counter() - started)
        try:
            return schema.model_validate_json((response.text or "").strip())
        except ValidationError as exc:
            last_error = exc
            log.warning("Gemini returned invalid %s JSON: %s", schema.__name__, exc)
    raise GeminiError("The AI returned an invalid plan", "invalid_output") from last_error


def generate_text(model: str, system: str, prompt: str) -> str:
    """Short plain-text answer (the tip): one attempt within TIP_TIME_LIMIT seconds."""
    gen_config = types.GenerateContentConfig(system_instruction=system, temperature=0.7,
                                             max_output_tokens=300)
    deadline = time.monotonic() + TIP_TIME_LIMIT
    started = time.perf_counter()
    response = _call(model, prompt, gen_config, deadline)
    log.info("Gemini %s text call took %.2fs", model, time.perf_counter() - started)
    text = (response.text or "").strip()
    if not text:
        raise GeminiError("The AI returned an empty response", "invalid_output")
    return text

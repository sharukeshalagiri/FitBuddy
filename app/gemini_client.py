"""Single shared google-genai client plus structured-JSON / text call helpers with retries."""
import logging
import time
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app import config

log = logging.getLogger("fitbuddy.gemini")
T = TypeVar("T", bound=BaseModel)

_client = None


class GeminiError(Exception):
    """Typed error for any AI failure. Routes turn this into a friendly message / HTTP 502."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind  # "not_configured" | "model_not_found" | "invalid_output" | "api" | ...


def get_client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise GeminiError("Gemini API key is not configured", "not_configured")
        from google import genai
        from google.genai import types
        _client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=config.GEMINI_TIMEOUT_SECONDS * 1000),
        )
    return _client


def _is_transient(exc: Exception) -> bool:
    from google.genai import errors
    if isinstance(exc, errors.ServerError):
        return True
    if isinstance(exc, errors.ClientError) and getattr(exc, "code", None) == 429:
        return True
    name = type(exc).__name__.lower()
    return "timeout" in name or "connect" in name


def _call(model: str, contents: str, gen_config, retries: int = 1):
    from google.genai import errors
    client = get_client()
    attempt = 0
    while True:
        try:
            return client.models.generate_content(model=model, contents=contents, config=gen_config)
        except errors.ClientError as exc:
            if exc.code == 404:
                log.error("Gemini model not found: '%s'. Check GEMINI_*_MODEL in .env. (%s)",
                          model, exc)
                raise GeminiError(f"Model '{model}' was not found", "model_not_found") from exc
            if exc.code in (401, 403):
                log.error("Gemini rejected the API key (%s): %s", exc.code, exc)
                raise GeminiError("Gemini API key was rejected", "auth") from exc
            if attempt < retries and _is_transient(exc):
                attempt += 1
                log.warning("Transient Gemini error (%s), retrying...", exc)
                time.sleep(2)
                continue
            if _is_transient(exc):
                log.error("Gemini rate-limited (%s): %s", model, exc)
                raise GeminiError("The AI service is busy right now", "overloaded") from exc
            log.error("Gemini client error: %s", exc)
            raise GeminiError("The AI service rejected the request", "api") from exc
        except Exception as exc:  # server errors, timeouts, network
            if attempt < retries and _is_transient(exc):
                attempt += 1
                log.warning("Transient Gemini error (%s), retrying...", exc)
                time.sleep(2)
                continue
            log.error("Gemini call failed (%s): %r", model, exc)
            kind = "overloaded" if _is_transient(exc) else "api"
            raise GeminiError("The AI service is unavailable right now", kind) from exc


# Errors where trying a different model can help (busy primary, or no access to it).
FALLBACK_KINDS = {"overloaded", "model_not_found"}


def generate_structured(model: str, system: str, prompt: str, schema: Type[T],
                        fallback_model: Optional[str] = None) -> tuple[T, str]:
    """Ask Gemini for JSON matching `schema`; return (validated model, model id used).

    If the primary model is overloaded or not found, try `fallback_model` once.
    """
    models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
    for i, m in enumerate(models):
        try:
            return _structured_once(m, system, prompt, schema), m
        except GeminiError as exc:
            if exc.kind in FALLBACK_KINDS and i < len(models) - 1:
                log.warning("Gemini %s failed (%s); falling back to %s", m, exc.kind, models[i + 1])
                continue
            raise
    raise AssertionError("unreachable")


def _structured_once(model: str, system: str, prompt: str, schema: Type[T]) -> T:
    from google.genai import types
    gen_config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.7,
    )
    last_err: Optional[Exception] = None
    for _ in range(2):  # one extra attempt if the model returns invalid JSON
        started = time.perf_counter()
        response = _call(model, prompt, gen_config)
        log.info("Gemini %s structured call took %.2fs", model, time.perf_counter() - started)
        text = (response.text or "").strip()
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            last_err = exc
            log.warning("Gemini returned invalid %s JSON: %s", schema.__name__, exc)
    raise GeminiError("The AI returned an invalid plan", "invalid_output") from last_err


def generate_text(model: str, system: str, prompt: str) -> str:
    from google.genai import types
    gen_config = types.GenerateContentConfig(system_instruction=system, temperature=0.7,
                                             max_output_tokens=300)
    started = time.perf_counter()
    response = _call(model, prompt, gen_config)
    log.info("Gemini %s text call took %.2fs", model, time.perf_counter() - started)
    text = (response.text or "").strip()
    if not text:
        raise GeminiError("The AI returned an empty response", "invalid_output")
    return text

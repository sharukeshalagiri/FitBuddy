"""Application configuration loaded from environment / .env file."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


DEFAULT_ADMIN_PASSWORD = "admin123"
_INSECURE_SECRET_KEYS = {"", "change-me"}


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_secret_key(raw: str | None) -> str:
    """Keep a real SECRET_KEY; replace an unset/placeholder one with a random key."""
    key = (raw or "").strip()
    return secrets.token_urlsafe(32) if key in _INSECURE_SECRET_KEYS else key


def startup_warnings(raw_secret_key: str | None, admin_password: str) -> list[str]:
    """Insecure-config warnings; logged by main.py once logging is configured."""
    warnings = []
    if (raw_secret_key or "").strip() in _INSECURE_SECRET_KEYS:
        warnings.append("SECRET_KEY is unset or 'change-me': using a random key, so admin "
                        "sessions won't survive restarts. Set SECRET_KEY in .env.")
    if not admin_password.strip():
        warnings.append("ADMIN_PASSWORD is empty: admin access is disabled. "
                        "Set ADMIN_PASSWORD in .env.")
    elif admin_password == DEFAULT_ADMIN_PASSWORD:
        warnings.append("ADMIN_PASSWORD is the default 'admin123': change it in .env.")
    return warnings


GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
GEMINI_WORKOUT_MODEL = os.getenv("GEMINI_WORKOUT_MODEL", "gemini-3.8-flash").strip()
GEMINI_TIP_MODEL = os.getenv("GEMINI_TIP_MODEL", "gemini-3.5-flash-lite").strip()
# Used for plans/revisions when the workout model is overloaded or not found. Empty = off.
GEMINI_WORKOUT_FALLBACK_MODEL = os.getenv("GEMINI_WORKOUT_FALLBACK_MODEL",
                                          "gemini-3.5-flash-lite").strip()
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "45"))

# Demo mode: no API key, or explicitly forced on.
DEMO_MODE = _bool(os.getenv("DEMO_MODE")) or not GEMINI_API_KEY

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
SECRET_KEY = _resolve_secret_key(os.getenv("SECRET_KEY"))
STARTUP_WARNINGS = startup_warnings(os.getenv("SECRET_KEY"), ADMIN_PASSWORD)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fitbuddy.db")

MAX_FEEDBACK_LENGTH = 500

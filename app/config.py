"""Application configuration loaded from environment / .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
GEMINI_WORKOUT_MODEL = os.getenv("GEMINI_WORKOUT_MODEL", "gemini-3.8-flash").strip()
GEMINI_TIP_MODEL = os.getenv("GEMINI_TIP_MODEL", "gemini-3.5-flash-lite").strip()
# Used for plans/revisions when the workout model is overloaded or not found. Empty = off.
GEMINI_WORKOUT_FALLBACK_MODEL = os.getenv("GEMINI_WORKOUT_FALLBACK_MODEL",
                                          "gemini-3.5-flash-lite").strip()
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "45"))

# Demo mode: no API key, or explicitly forced on.
DEMO_MODE = _bool(os.getenv("DEMO_MODE")) or not GEMINI_API_KEY

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fitbuddy.db")

MAX_FEEDBACK_LENGTH = 500

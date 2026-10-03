"""Pydantic schemas: request bodies and the structured WorkoutPlan returned by Gemini."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

COMMON_GOALS = ["weight loss", "muscle gain", "general fitness", "flexibility", "endurance"]
Intensity = Literal["low", "medium", "high"]
Experience = Literal["beginner", "intermediate", "advanced"]


# ---------- Structured plan (also used as Gemini response_schema) ----------

class Exercise(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: str
    rest_seconds: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("sets", "rest_seconds")
    @classmethod
    def positive_if_set(cls, v: Optional[int], info) -> Optional[int]:
        # Checked here rather than with Field(ge=1) to keep the Gemini response_schema simple.
        if v is not None and v < 1:
            raise ValueError(f"{info.field_name} must be a positive number, got {v}")
        return v


class Day(BaseModel):
    day: int = Field(ge=1, le=7)
    focus: str
    is_rest_day: bool
    warmup: str
    exercises: list[Exercise]
    cooldown: str


class WorkoutPlan(BaseModel):
    title: str
    summary: str
    days: list[Day]
    safety_notes: list[str]

    @field_validator("days")
    @classmethod
    def exactly_seven_days(cls, days: list[Day]) -> list[Day]:
        if len(days) != 7:
            raise ValueError(f"plan must have exactly 7 days, got {len(days)}")
        numbers = sorted(d.day for d in days)
        if numbers != list(range(1, 8)):
            raise ValueError(f"plan days must be numbered 1-7, each once, got {numbers}")
        return days

    @model_validator(mode="after")
    def has_rest_day(self) -> "WorkoutPlan":
        if not any(d.is_rest_day for d in self.days):
            raise ValueError("plan must include at least one rest or active-recovery day")
        return self


def wrap_untrusted(tag: str, text: str) -> str:
    """Fence user text in <tag>...</tag>; '<'/'>' are replaced so it can't close the tag."""
    safe = str(text).replace("<", "‹").replace(">", "›")
    return f"<{tag}>{safe}</{tag}>"


# ---------- Requests ----------

def _clean_goal(v: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ValueError("goal is required")
    return v.lower() if v.lower() in COMMON_GOALS else v


class UserInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=13, le=90)
    weight_kg: float = Field(ge=25, le=300)
    goal: str = Field(min_length=1, max_length=200)
    intensity: Intensity
    experience: Experience = "beginner"

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("goal")
    @classmethod
    def clean_goal(cls, v: str) -> str:
        return _clean_goal(v)


class QuickWorkoutRequest(BaseModel):
    """Body for POST /generate-workout/gemini (no DB write)."""
    goal: str = Field(min_length=1, max_length=200)
    intensity: Intensity
    age: Optional[int] = Field(default=None, ge=13, le=90)
    weight: Optional[float] = Field(default=None, ge=25, le=300)
    experience: Experience = "beginner"

    @field_validator("goal")
    @classmethod
    def clean_goal(cls, v: str) -> str:
        return _clean_goal(v)


class FeedbackRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=500)

    @field_validator("feedback")
    @classmethod
    def strip_feedback(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("feedback is required")
        return v

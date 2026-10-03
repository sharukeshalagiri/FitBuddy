"""Pydantic schemas: request bodies and the structured WorkoutPlan returned by Gemini."""
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

from app import config

MIN_AGE = 13
MAX_AGE = 90
MIN_WEIGHT_KG = 25
MAX_WEIGHT_KG = 300
MAX_GOAL_LENGTH = 200
MAX_NAME_LENGTH = 100
HEAVY_WEIGHT_KG = 110  # the plan prompt favours low-impact cardio from this body weight

COMMON_GOALS = ["weight loss", "muscle gain", "general fitness", "flexibility", "endurance"]
Intensity = Literal["low", "medium", "high"]
Experience = Literal["beginner", "intermediate", "advanced"]


# ---------- Structured plan (also used as Gemini response_schema) ----------

class Exercise(BaseModel):
    name: str
    sets: int | None = None
    reps: str
    rest_seconds: int | None = None
    notes: str | None = None

    @field_validator("sets", "rest_seconds")
    @classmethod
    def positive_if_set(cls, v: int | None, info) -> int | None:
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
    """Strip the goal and normalise common goals to lower case."""
    v = v.strip()
    if not v:
        raise ValueError("goal is required")
    return v.lower() if v.lower() in COMMON_GOALS else v


Goal = Annotated[str, Field(min_length=1, max_length=MAX_GOAL_LENGTH), AfterValidator(_clean_goal)]


class UserInput(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    age: int = Field(ge=MIN_AGE, le=MAX_AGE)
    weight_kg: float = Field(ge=MIN_WEIGHT_KG, le=MAX_WEIGHT_KG)
    goal: Goal
    intensity: Intensity
    experience: Experience = "beginner"

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v


class QuickWorkoutRequest(BaseModel):
    """Body for POST /generate-workout/gemini (no DB write)."""
    goal: Goal
    intensity: Intensity
    age: int | None = Field(default=None, ge=MIN_AGE, le=MAX_AGE)
    weight: float | None = Field(default=None, ge=MIN_WEIGHT_KG, le=MAX_WEIGHT_KG)
    experience: Experience = "beginner"


class FeedbackRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=config.MAX_FEEDBACK_LENGTH)

    @field_validator("feedback")
    @classmethod
    def strip_feedback(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("feedback is required")
        return v

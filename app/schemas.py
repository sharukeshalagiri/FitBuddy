"""Pydantic schemas: request bodies and the structured WorkoutPlan returned by Gemini."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

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
        return days


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

"""Pure-function tests: demo-mode plans and revisions follow the same safety rules."""
import re

import pytest

from app.demo_data import (LIBRARY, SCHEDULES, SENIOR_NOTE, TEEN_NOTE, VOLUME, _goal_key,
                           demo_revise_plan, demo_workout_plan)
from app.schemas import WorkoutPlan

LEVELS = ("beginner", "intermediate", "advanced")
HIGH_IMPACT = re.compile(r"Jump|Box|Sprint|Burpees|Tempo Run")
GEAR = re.compile(r"machine|barbell|dumbbell|kettlebell", re.I)


def names(plan: dict) -> list[str]:
    return [ex["name"] for d in plan["days"] for ex in d["exercises"]]


def introduced(before: dict, after: dict) -> set[str]:
    return set(names(after)) - set(names(before))


def assert_valid(plan: dict) -> None:
    WorkoutPlan.model_validate(plan)
    assert [d["day"] for d in plan["days"]] == list(range(1, 8))
    assert any(d["is_rest_day"] for d in plan["days"])


def test_teen_beginner_more_cardio_uses_beginner_moves():
    plan = demo_workout_plan("muscle gain", "high", "beginner", age=15)
    new = demo_revise_plan(plan, "more cardio", experience="beginner", age=15, intensity="high")
    cardio = [d for d in new["days"] if d["focus"] == "Steady-State Cardio"]
    assert cardio
    assert {"Brisk Walking", "Stationary Bike"} <= {ex["name"] for ex in cardio[0]["exercises"]}
    assert not {"Jogging", "Rowing Machine", "Side Plank"} & set(names(new))
    assert all(ex["sets"] <= 3 for d in new["days"] for ex in d["exercises"] if ex["sets"])
    assert TEEN_NOTE in new["safety_notes"]
    assert_valid(new)


def test_advanced_teen_treated_as_intermediate_in_revisions():
    plan = demo_workout_plan("muscle gain", "high", "advanced", age=16)
    new = demo_revise_plan(plan, "more cardio, no equipment",
                           experience="advanced", age=16, intensity="high")
    advanced = {n for kind in LIBRARY.values() for n, _ in kind["advanced"]}
    assert not advanced & set(names(new))
    assert {"Jogging", "Rowing Machine"} & set(names(demo_revise_plan(
        plan, "more cardio", experience="advanced", age=16, intensity="high")))
    assert all(ex["sets"] <= 3 for d in new["days"] for ex in d["exercises"] if ex["sets"])


@pytest.mark.parametrize("experience", LEVELS)
@pytest.mark.parametrize("feedback", ["more cardio", "no equipment", "more cardio, no equipment"])
def test_senior_revision_adds_no_high_impact(experience, feedback):
    plan = demo_workout_plan("weight loss", "high", experience, age=65)
    new = demo_revise_plan(plan, feedback, experience=experience, age=65, intensity="high")
    assert not [n for n in introduced(plan, new) if HIGH_IMPACT.search(n)]
    assert SENIOR_NOTE in new["safety_notes"]
    assert new["safety_notes"].count(SENIOR_NOTE) == 1
    assert_valid(new)


def test_senior_generation_uses_low_impact_cardio_and_hiit():
    plan = demo_workout_plan("endurance", "high", "advanced", age=70)
    bad = {"Jump Squats", "Burpees", "Box Jumps", "Sprint Intervals", "Tempo Run", "Jogging"}
    assert not bad & set(names(plan))


def test_age_notes_added_when_missing_from_previous_version():
    plan = demo_workout_plan("general fitness", "medium", "beginner")
    teen = demo_revise_plan(plan, "more cardio", age=14)
    senior = demo_revise_plan(plan, "more cardio", age=72)
    assert TEEN_NOTE in teen["safety_notes"] and SENIOR_NOTE in senior["safety_notes"]


@pytest.mark.parametrize("goal", SCHEDULES)
@pytest.mark.parametrize("experience", LEVELS)
def test_no_equipment_removes_gear(goal, experience):
    plan = demo_workout_plan(goal, "high", experience, age=30)
    new = demo_revise_plan(plan, "no equipment please", experience=experience, age=30,
                           intensity="high")
    assert not [n for n in names(new) if GEAR.search(n)]
    assert "Leg Press Machine" not in names(new)
    assert_valid(new)


@pytest.mark.parametrize("goal", SCHEDULES)
def test_repeated_rest_revisions_stay_valid(goal):
    plan = demo_workout_plan(goal, "high", "intermediate", age=30)
    for _ in range(5):
        plan = demo_revise_plan(plan, "add a rest day", experience="intermediate", age=30,
                                intensity="high")
        assert_valid(plan)
        assert sum(not d["is_rest_day"] for d in plan["days"]) >= 3


def test_revision_restores_rest_day_if_missing():
    plan = demo_workout_plan("general fitness", "medium")
    for d in plan["days"]:
        d["is_rest_day"] = False
    assert_valid(demo_revise_plan(plan, "shorter workouts"))


def test_old_call_style_still_works():
    plan = demo_workout_plan("muscle gain", "medium", "intermediate")
    new = demo_revise_plan(plan, "more cardio")
    assert "Revised: swapped day" in new["summary"]
    assert "Brisk Walking" in names(new)  # falls back to the safest (beginner) level
    assert_valid(new)


@pytest.mark.parametrize("goal", SCHEDULES)
@pytest.mark.parametrize("intensity", VOLUME)
@pytest.mark.parametrize("experience", LEVELS)
@pytest.mark.parametrize("age", [15, 30, 65])
def test_all_plans_and_revisions_validate(goal, intensity, experience, age):
    plan = demo_workout_plan(goal, intensity, experience, age=age, weight=80)
    assert_valid(plan)
    for fb in ["more cardio", "add a rest day", "shorter workouts", "no equipment",
               "more cardio, rest, short, no equipment", "nothing relevant"]:
        new = demo_revise_plan(plan, fb, experience=experience, age=age, intensity=intensity)
        assert_valid(new)
        if age == 15:
            assert all(ex["sets"] <= 3 for d in new["days"] for ex in d["exercises"]
                       if ex["sets"])


@pytest.mark.parametrize("goal,expected", [
    ("lean muscle", "muscle gain"),
    ("reduce fatigue", "general fitness"),
    ("brunch with friends", "general fitness"),
    ("lose fat", "weight loss"),
    ("run a marathon", "endurance"),
    ("more yoga", "flexibility"),
    ("weight loss", "weight loss"),
    ("muscle gain", "muscle gain"),
    ("general fitness", "general fitness"),
    ("flexibility", "flexibility"),
    ("Endurance", "endurance"),
])
def test_goal_key(goal, expected):
    assert _goal_key(goal) == expected


def test_update_plan_route_passes_user_profile(client):
    r = client.post("/generate-plan", json={"name": "Teen", "age": 15, "weight_kg": 55,
                                            "goal": "muscle gain", "intensity": "high",
                                            "experience": "beginner"})
    uid = r.json()["user_id"]
    r = client.post(f"/update-plan/{uid}", json={"feedback": "More cardio"})
    assert r.status_code == 200
    plan = r.json()["updated_plan"]
    names = {e["name"] for d in plan["days"] for e in d["exercises"]}
    assert not names & {"Jogging", "Rowing Machine", "Tempo Run"}
    assert all((e["sets"] or 0) <= 3 for d in plan["days"] for e in d["exercises"])
    assert TEEN_NOTE in plan["safety_notes"]

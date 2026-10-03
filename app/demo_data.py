"""Deterministic fallback plans, tips and revisions used when no Gemini key is configured.

Everything here is pure and repeatable so tests and load tests are stable.
"""
import copy
import re

# Exercise libraries per session type and experience. Beginners get bodyweight/machines.
LIBRARY = {
    "upper": {
        "beginner": [("Incline Push-Ups", "Keep a straight line from head to heels"),
                     ("Seated Machine Row", "Squeeze shoulder blades together"),
                     ("Machine Shoulder Press", "Don't arch your lower back"),
                     ("Band Bicep Curls", "Keep elbows tucked")],
        "intermediate": [("Dumbbell Bench Press", "Lower with control to chest level"),
                         ("Bent-Over Dumbbell Row", "Flat back, pull to hip"),
                         ("Seated Dumbbell Shoulder Press", "Brace your core"),
                         ("Lat Pulldown", "Pull the bar to upper chest")],
        "advanced": [("Barbell Bench Press", "Feet planted, controlled descent"),
                     ("Pull-Ups", "Full range of motion"),
                     ("Standing Overhead Press", "Squeeze glutes, ribs down"),
                     ("Weighted Dips", "Lean slightly forward, elbows tracked")],
    },
    "lower": {
        "beginner": [("Bodyweight Squats", "Knees track over toes"),
                     ("Glute Bridges", "Drive through heels"),
                     ("Leg Press Machine", "Don't lock knees at the top"),
                     ("Standing Calf Raises", "Pause at the top")],
        "intermediate": [("Goblet Squats", "Chest up, sit between hips"),
                         ("Dumbbell Romanian Deadlift", "Hinge at hips, soft knees"),
                         ("Walking Lunges", "Front knee over ankle"),
                         ("Leg Curl Machine", "Slow on the way down")],
        "advanced": [("Barbell Back Squat", "Brace before each rep"),
                     ("Conventional Deadlift", "Bar close to shins, neutral spine"),
                     ("Bulgarian Split Squats", "Stay tall through the torso"),
                     ("Hip Thrusts", "Full hip extension at the top")],
    },
    "full": {
        "beginner": [("Bodyweight Squats", "Knees track over toes"),
                     ("Wall Push-Ups", "Body in one straight line"),
                     ("Resistance Band Rows", "Squeeze shoulder blades"),
                     ("Bird-Dog", "Move slowly, keep hips level")],
        "intermediate": [("Dumbbell Thrusters", "Use legs to drive the press"),
                         ("Push-Ups", "Elbows at ~45 degrees"),
                         ("Renegade Rows", "Minimise hip rotation"),
                         ("Reverse Lunges", "Step back softly")],
        "advanced": [("Kettlebell Swings", "Snap hips, don't squat it"),
                     ("Barbell Front Squat", "Elbows high"),
                     ("Weighted Pull-Ups", "Controlled negatives"),
                     ("Clean and Press", "Bar path close to body")],
    },
    "cardio": {
        "beginner": [("Brisk Walking", "Steady conversational pace"),
                     ("Stationary Bike", "Light-to-moderate resistance")],
        "intermediate": [("Jogging", "Relaxed shoulders, light steps"),
                         ("Rowing Machine", "Legs, then back, then arms")],
        "advanced": [("Tempo Run", "Comfortably hard pace"),
                     ("Rowing Intervals", "Powerful drive, controlled recovery")],
    },
    "hiit": {
        "beginner": [("Marching High Knees", "Stay tall"),
                     ("Step-Back Burpees (no jump)", "Move at your own pace"),
                     ("Low-Impact Jacks", "Arms fully overhead")],
        "intermediate": [("Jump Squats", "Land softly"),
                         ("Mountain Climbers", "Hips in line with shoulders"),
                         ("Burpees", "Full extension at the top")],
        "advanced": [("Box Jumps", "Step down, don't jump down"),
                     ("Battle Ropes", "Drive from the hips"),
                     ("Sprint Intervals", "Full recovery between efforts")],
    },
    "core": {
        "beginner": [("Forearm Plank", "Don't let hips sag"),
                     ("Dead Bug", "Lower back pressed to floor")],
        "intermediate": [("Side Plank", "Stack hips and shoulders"),
                         ("Bicycle Crunches", "Slow and controlled")],
        "advanced": [("Hanging Knee Raises", "No swinging"),
                     ("Ab Wheel Rollouts", "Stop before your back arches")],
    },
    "mobility": {
        "beginner": [("Cat-Cow", "Move with your breath"),
                     ("World's Greatest Stretch", "Hold each side"),
                     ("Hip Flexor Stretch", "Tuck pelvis slightly")],
        "intermediate": [("Sun Salutation Flow", "Smooth transitions"),
                         ("Pigeon Pose", "Keep hips square"),
                         ("Thoracic Rotations", "Rotate from mid-back")],
        "advanced": [("Yoga Flow (Vinyasa)", "Breathe through each pose"),
                     ("Deep Squat Hold", "Heels down, chest up"),
                     ("Jefferson Curl (light)", "Very slow, light load")],
    },
}

# Weekly layouts per goal. "rest" = full rest, "recovery" = active recovery.
SCHEDULES = {
    "weight loss": ["full", "cardio", "hiit", "recovery", "full", "cardio", "rest"],
    "muscle gain": ["upper", "lower", "recovery", "upper", "lower", "full", "rest"],
    "general fitness": ["full", "cardio", "core", "recovery", "full", "hiit", "rest"],
    "flexibility": ["mobility", "core", "mobility", "recovery", "mobility", "full", "rest"],
    "endurance": ["cardio", "full", "cardio", "recovery", "hiit", "cardio", "rest"],
}

FOCUS = {
    "upper": "Upper Body Strength", "lower": "Lower Body Strength",
    "full": "Full Body Strength", "cardio": "Steady-State Cardio",
    "hiit": "HIIT Conditioning", "core": "Core & Stability",
    "mobility": "Mobility & Flexibility", "recovery": "Active Recovery", "rest": "Rest Day",
}

# (sets, reps, rest_seconds) per intensity for strength-type work
VOLUME = {"low": (2, "10–12", 90), "medium": (3, "8–12", 75), "high": (4, "6–10", 60)}
CARDIO_TIME = {"low": "20 min", "medium": "30 min", "high": "40 min"}
HIIT_WORK = {"low": "20 sec on / 40 sec off", "medium": "30 sec on / 30 sec off",
             "high": "40 sec on / 20 sec off"}

TIPS = {
    "weight loss": "Build each meal around a palm-sized portion of protein and a plate half-full "
                   "of vegetables to stay full longer. Drink a glass of water before meals and aim "
                   "for 7–9 hours of sleep, since poor sleep increases cravings.",
    "muscle gain": "Include a quality protein source such as eggs, dairy, legumes, fish or chicken "
                   "in every meal, and have a protein-and-carb snack within a couple of hours "
                   "after training. Muscles grow during recovery, so prioritise consistent sleep.",
    "general fitness": "Eat a colourful mix of whole foods—fruit, vegetables, whole grains and "
                       "lean protein—and keep a water bottle with you through the day. Take at "
                       "least one easy day a week so your body can recover and adapt.",
    "flexibility": "Stretch when your muscles are warm, such as after a workout or a warm shower, "
                   "and breathe slowly into each hold. Staying well hydrated and eating "
                   "anti-inflammatory foods like berries and leafy greens supports recovery.",
    "endurance": "Fuel longer sessions with easily digested carbohydrates such as oats, bananas "
                 "or rice a few hours beforehand, and rehydrate afterwards. Build mileage "
                 "gradually and keep most sessions at a comfortable, conversational effort.",
}


LEVELS = ("beginner", "intermediate", "advanced")

TEEN_NOTE = "Focus on technique over heavy weights; train under supervision when using equipment."
SENIOR_NOTE = ("Prioritise balance and controlled movements; check with your doctor before "
               "increasing intensity.")

# 60+: cardio/HIIT come from the beginner (low-impact) library so no jumps, sprints or runs.
LOW_IMPACT_KINDS = ("cardio", "hiit")

# Genuinely equipment-free swaps for "no equipment" feedback. No jumping moves, so they are
# safe for every age group.
BODYWEIGHT = {
    "beginner": [("Bodyweight Squats", "Knees track over toes"),
                 ("Wall Push-Ups", "Body in one straight line"),
                 ("Glute Bridges", "Drive through heels"),
                 ("Bird-Dog", "Move slowly, keep hips level"),
                 ("Standing Calf Raises", "Pause at the top")],
    "intermediate": [("Bodyweight Squats", "Knees track over toes"),
                     ("Push-Ups", "Elbows at ~45 degrees"),
                     ("Reverse Lunges", "Step back softly"),
                     ("Glute Bridges", "Drive through heels"),
                     ("Superman Hold", "Lift chest and legs together, neck neutral")],
    "advanced": [("Bulgarian Split Squats", "Rear foot on a chair or step, stay tall"),
                 ("Decline Push-Ups", "Feet on a chair, body in one line"),
                 ("Walking Lunges", "Front knee over ankle"),
                 ("Single-Leg Glute Bridges", "Keep hips level"),
                 ("Pike Push-Ups", "Hips high, lower head between hands")],
}
BODYWEIGHT_CARDIO = [("Brisk Walking", "Steady conversational pace"),
                     ("Marching in Place", "Lift knees to hip height, swing arms")]
# Exercise names that need gear; replaced by the "no equipment" rule.
EQUIPMENT = re.compile(r"\b(machine|barbell|dumbbell|kettlebell|band|bike|rows?|rowing|pulldown|"
                       r"ropes?|weighted|box|wheel|hanging|pull-ups?|dips|press|deadlift|"
                       r"goblet|curls?|thrusts?)\b", re.I)


def _goal_key(goal: str) -> str:
    g = (goal or "").lower()
    for key in SCHEDULES:
        if key in g:
            return key

    def has(pattern: str) -> bool:  # whole-word match, so "fatigue" isn't "fat"
        return re.search(rf"\b({pattern})\b", g) is not None

    # "muscle" is checked before "lean" so "lean muscle" means muscle gain.
    if has(r"muscles?|strength|stronger|strong|bulk(ing)?"):
        return "muscle gain"
    if has(r"lose|losing|fat|slim|lean"):
        return "weight loss"
    if has(r"run|running|runner|marathons?|stamina|cardio"):
        return "endurance"
    if has(r"stretch(ing)?|yoga|mobility|flexible"):
        return "flexibility"
    return "general fitness"


def _profile(experience: str | None, age: int | None, intensity: str | None) -> dict:
    """Normalise the user inputs that drive safety rules (shared by generation and revision)."""
    experience = experience if experience in LEVELS else "beginner"
    intensity = intensity if intensity in VOLUME else "medium"
    teen = age is not None and age < 18
    if teen and experience == "advanced":
        experience = "intermediate"
    return {"experience": experience, "intensity": intensity, "teen": teen,
            "senior": age is not None and age >= 60}


def _rest_day(day: int) -> dict:
    return {"day": day, "focus": FOCUS["rest"], "is_rest_day": True,
            "warmup": "Optional 10-minute easy walk.",
            "exercises": [],
            "cooldown": "Gentle full-body stretching and focus on hydration and sleep."}


def _recovery_day(day: int) -> dict:
    return {"day": day, "focus": FOCUS["recovery"], "is_rest_day": True,
            "warmup": "5 minutes of easy walking.",
            "exercises": [
                {"name": "Easy Walk or Light Cycling", "sets": None, "reps": "20–30 min",
                 "rest_seconds": None, "notes": "Keep effort very light"},
                {"name": "Foam Rolling", "sets": None, "reps": "5–10 min",
                 "rest_seconds": None, "notes": "Spend 30–60 sec on each tight area"},
            ],
            "cooldown": "5 minutes of deep breathing and gentle stretches."}


def _session(kind: str, day: int, p: dict) -> dict:
    if kind == "rest":
        return _rest_day(day)
    if kind == "recovery":
        return _recovery_day(day)

    experience, intensity = p["experience"], p["intensity"]
    level = "beginner" if p["senior"] and kind in LOW_IMPACT_KINDS else experience
    moves = LIBRARY[kind][level]
    sets, reps, rest = VOLUME[intensity]
    if p["teen"]:  # age-appropriate: no heavy max lifts, moderate rep ranges
        sets, reps = min(sets, 3), "10–15"
    exercises = []
    for name, cue in moves:
        if kind == "cardio":
            exercises.append({"name": name, "sets": None, "reps": CARDIO_TIME[intensity],
                              "rest_seconds": None, "notes": cue})
        elif kind == "hiit":
            exercises.append({"name": name, "sets": sets, "reps": HIIT_WORK[intensity],
                              "rest_seconds": 60, "notes": cue})
        elif kind == "mobility":
            exercises.append({"name": name, "sets": 2, "reps": "30–60 sec",
                              "rest_seconds": 15, "notes": cue})
        elif kind == "core":
            exercises.append({"name": name, "sets": sets, "reps": "30–45 sec",
                              "rest_seconds": 45, "notes": cue})
        else:
            exercises.append({"name": name, "sets": sets, "reps": reps,
                              "rest_seconds": rest, "notes": cue})
    if kind in ("upper", "lower", "full", "cardio"):
        extra = LIBRARY["core"][experience][0]
        exercises.append({"name": extra[0], "sets": 2, "reps": "30–45 sec",
                          "rest_seconds": 45, "notes": extra[1]})

    warmup = ("5–10 minutes of light cardio followed by dynamic stretches "
              "(arm circles, leg swings, hip openers).")
    if kind == "mobility":
        warmup = "5 minutes of gentle joint rotations from neck to ankles."
    return {"day": day, "focus": FOCUS[kind], "is_rest_day": False, "warmup": warmup,
            "exercises": exercises,
            "cooldown": "5–10 minutes of walking and static stretching for the muscles worked."}


def _add_age_notes(safety: list, p: dict) -> list:
    """Append the teen / 60+ safety notes if they apply and aren't already there."""
    for needed, note in ((p["teen"], TEEN_NOTE), (p["senior"], SENIOR_NOTE)):
        if needed and note not in safety:
            safety.append(note)
    return safety


def demo_workout_plan(goal: str, intensity: str, experience: str = "beginner",
                      age: int | None = None, weight: float | None = None) -> dict:
    key = _goal_key(goal)
    p = _profile(experience, age, intensity)
    experience, intensity = p["experience"], p["intensity"]
    days = [_session(kind, i + 1, p) for i, kind in enumerate(SCHEDULES[key])]

    who = f"{experience} level"
    if age:
        who += f", age {age}"
    safety = _add_age_notes([
        "Stop any exercise that causes sharp pain, dizziness or chest discomfort.",
        "Warm up before every session and progress load gradually.",
        "Stay hydrated before, during and after training.",
    ], p)
    if weight and weight >= 110:
        safety.append("Favour low-impact options (bike, rower, swimming) to protect your joints.")

    return {
        "title": f"7-Day {key.title()} Plan ({intensity.title()} Intensity)",
        "summary": f"A {intensity}-intensity week built for {goal} ({who}), balancing "
                   f"training days with recovery.",
        "days": days,
        "safety_notes": safety,
    }


def demo_nutrition_tip(goal: str, age: int | None = None) -> str:
    tip = TIPS[_goal_key(goal)]
    if age is not None and age < 18:
        tip += " As a teenager, eat regular balanced meals rather than restricting food."
    return tip


# ---------- Revision rules: each takes (days, p) and returns a change description or None ----------

def _training_idx(days: list) -> list:
    return [i for i, d in enumerate(days) if not d["is_rest_day"]]


def _more_cardio(days: list, p: dict) -> str | None:
    strength = [i for i in _training_idx(days)
                if "Strength" in days[i]["focus"] or "Core" in days[i]["focus"]]
    if not strength:
        return None
    i = strength[-1]
    days[i] = _session("cardio", i + 1, p)
    return f"swapped day {i + 1} for cardio"


def _more_rest(days: list, p: dict) -> str | None:
    # Only ever turns a training day into a rest day, so existing rest days are never removed.
    trains = _training_idx(days)
    if len(trains) <= 3:
        return None
    i = trains[len(trains) // 2]
    days[i] = _rest_day(i + 1)
    return f"made day {i + 1} a rest day"


def _shorter(days: list, p: dict) -> str:
    for d in days:
        if d["exercises"] and not d["is_rest_day"]:
            d["exercises"] = d["exercises"][:3]
            for ex in d["exercises"]:
                if ex.get("sets") and ex["sets"] > 2:
                    ex["sets"] -= 1
    return "shortened workouts"


def _bodyweight(days: list, p: dict) -> str:
    strength_moves = BODYWEIGHT[p["experience"]]
    for d in days:
        if d["is_rest_day"]:
            continue
        pool = BODYWEIGHT_CARDIO if d["focus"] == FOCUS["cardio"] else strength_moves
        used = {ex["name"] for ex in d["exercises"]}
        for ex in d["exercises"]:
            if EQUIPMENT.search(ex["name"]):
                name, cue = next((m for m in pool if m[0] not in used), pool[0])
                used.add(name)
                ex["name"], ex["notes"] = name, cue
        d["focus"] = d["focus"].replace("Strength", "Bodyweight")
    return "switched to bodyweight exercises"


REVISION_RULES = [
    (lambda fb: "cardio" in fb, _more_cardio),
    (lambda fb: re.search(r"\brest\b|recover|tired|sore", fb), _more_rest),
    (lambda fb: any(w in fb for w in ("short", "less time", "quick", "busy")), _shorter),
    (lambda fb: any(w in fb for w in ("no equipment", "home", "bodyweight", "no gym")), _bodyweight),
]


def demo_revise_plan(plan: dict, feedback: str, *, experience: str | None = None,
                     age: int | None = None, intensity: str | None = None) -> dict:
    """Simple keyword-driven revision of the latest plan, using the same safety profile as
    generation (experience level, intensity, teen and 60+ rules)."""
    p = _profile(experience, age, intensity)
    new = copy.deepcopy(plan)
    fb = (feedback or "").lower()
    days = new["days"]
    changes = [c for match, rule in REVISION_RULES if match(fb) and (c := rule(days, p))]

    if p["teen"]:  # cap volume on anything carried over from the previous version
        for d in days:
            for ex in d["exercises"]:
                if ex.get("sets") and ex["sets"] > 3:
                    ex["sets"] = 3
    if not any(d["is_rest_day"] for d in days):  # guard: always keep one rest day
        days[-1] = _rest_day(len(days))
        changes.append(f"made day {len(days)} a rest day")
    new["safety_notes"] = _add_age_notes(list(new.get("safety_notes") or []), p)

    if not changes:
        changes.append("kept the structure and added a note")
    new["summary"] = (plan.get("summary", "") + f" Revised: {', '.join(changes)}.").strip()
    for n, d in enumerate(days, start=1):
        d["day"] = n
    return new

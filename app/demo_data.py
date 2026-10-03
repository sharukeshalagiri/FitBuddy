"""Deterministic fallback plans, tips and revisions used when no Gemini key is configured.

Everything here is pure and repeatable so tests and load tests are stable.
"""
import copy
import re
from collections import Counter

from app.schemas import HEAVY_WEIGHT_KG

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
                     ("Barbell Hip Thrusts", "Full hip extension at the top")],
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
    # Cardio days get ONE main item: the two options are joined as "A or B".
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
                     ("Squat Step-Backs", "Step back and forward at your own pace"),
                     ("Low-Impact Jacks", "Step out to the side, arms fully overhead")],
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

# Joint-friendly cardio for heavier users, over-60s and anyone with pain or an injury.
LOW_IMPACT_CARDIO = {
    "beginner": [("Stationary Bike", "Light-to-moderate resistance"),
                 ("Incline Walking", "Brisk pace, upright posture")],
    "intermediate": [("Stationary Bike", "Moderate resistance, steady cadence"),
                     ("Rowing Machine", "Legs, then back, then arms")],
    "advanced": [("Rowing Intervals", "Powerful drive, controlled recovery"),
                 ("Swimming", "Long, relaxed strokes")],
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
STRENGTH_KINDS = ("upper", "lower", "full")

WARMUPS = {
    "upper": ["5 minutes of easy cardio, then arm circles, shoulder rolls and a few slow "
              "push-ups to prime the shoulders.",
              "5 minutes of rowing or skipping, then band pull-aparts, wall slides and "
              "scapular push-ups."],
    "lower": ["5 minutes of brisk walking, then leg swings, hip openers and slow bodyweight squats.",
              "5 minutes of easy cycling, then glute bridges, walking lunges and ankle circles."],
    "full": ["5 minutes of light cardio, then arm circles, leg swings and inchworms.",
             "5 minutes of marching or easy cycling, then hip hinges, torso twists and slow "
             "squats to a box or chair."],
    "cardio": ["5 minutes at an easy pace, building gradually up to your working pace.",
               "5 minutes easy, then 3 short pick-ups of 20 seconds to get ready for the intervals.",
               "10 minutes at a very easy, conversational pace before settling in."],
    "hiit": ["8 minutes of marching and side steps, then dynamic lunges and arm swings, "
             "finishing with two short practice efforts.",
             "6 minutes of easy cardio, then squats, hip openers and two half-speed rounds."],
    "core": ["5 minutes of light cardio, then cat-cow, slow dead bugs and glute bridges.",
             "5 minutes of walking, then pelvic tilts, bird-dogs and a short plank hold."],
    "mobility": ["5 minutes of gentle joint rotations from neck to ankles.",
                 "5 minutes of slow walking, then shoulder rolls, hip circles and cat-cow.",
                 "3 minutes of deep breathing, then gentle neck, wrist and ankle circles."],
}
COOLDOWNS = {
    "upper": ["5 minutes of chest, shoulder and upper-back stretches.",
              "Doorway chest stretch, cross-body shoulder stretch and child's pose."],
    "lower": ["5 minutes of walking, then hamstring, quad and calf stretches.",
              "Pigeon or figure-4 stretch, hip flexor stretch and a calf stretch on a step."],
    "full": ["5-10 minutes of walking and static stretching for the muscles worked.",
             "Easy walk, then a slow forward fold, lunge stretch and chest opener."],
    "cardio": ["5 minutes at a slow pace, then calf and hip flexor stretches.",
               "5 minutes of easy walking, then hamstring and quad stretches.",
               "Slow walk until breathing settles, then a gentle full-body stretch."],
    "hiit": ["5 minutes of easy walking until breathing settles, then light stretching.",
             "Slow marching, then quad, calf and shoulder stretches."],
    "core": ["Child's pose and a gentle lying spinal twist, 1 minute each.",
             "Cobra stretch and knees-to-chest, 1 minute each."],
    "mobility": ["5 minutes of slow breathing in a relaxed seated or lying position.",
                 "Legs up the wall for 3 minutes, then slow breathing.",
                 "A short body scan lying down, about 3 minutes."],
}

# (sets, reps, rest_seconds) per intensity for loaded strength work
VOLUME = {"low": (2, "10–12", 90), "medium": (3, "8–12", 75), "high": (4, "6–10", 60)}
# Bodyweight moves get MORE reps as intensity rises (they can't get heavier).
BODYWEIGHT_REPS = {"low": "8–12", "medium": "10–15", "high": "12–20"}
CARDIO_MINUTES = {"low": 20, "medium": 30, "high": 40}
HIIT_WORK = {"low": "20 sec on / 40 sec off", "medium": "30 sec on / 30 sec off",
             "high": "40 sec on / 20 sec off"}
# Core moves done for reps; anything not listed is a timed hold.
CORE_REPS = {"Dead Bug": "8–10 per side", "Bicycle Crunches": "12–20",
             "Hanging Knee Raises": "10–15", "Ab Wheel Rollouts": "8–12",
             "Lying Leg Raises": "10–15", "Bird-Dog": "8–10 per side"}

# Balance work added to strength days for over-60s.
BALANCE = [("Single-Leg Stand", "Hold a chair or wall for support if needed", "20–30 sec per side"),
           ("Heel-to-Toe Walk", "Look ahead, slow steady steps", "10 steps, 2 lengths"),
           ("Step-Ups to a Low Step", "Hold a rail, step down slowly", "8–10 per leg")]
BALANCE_NAMES = {name for name, _, _ in BALANCE}

TIPS = {
    "weight loss": "Build each meal around a palm-sized portion of protein and a plate half-full "
                   "of vegetables to stay full longer. Drink a glass of water before meals and aim "
                   "for 7–9 hours of sleep, since poor sleep increases cravings.",
    "muscle gain": "Include a quality protein source such as eggs, dairy, legumes, fish or chicken "
                   "in every meal, and have a protein-and-carb snack within a couple of hours "
                   "after training. Muscles grow during recovery, so prioritise consistent sleep.",
    "general fitness": "Eat a colourful mix of whole foods (fruit, vegetables, whole grains and "
                       "lean protein) and keep a water bottle with you through the day. Take at "
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
TEEN_LEVEL_NOTE = "Level set to intermediate for under-18s; advanced lifts wait until you're 18."
SENIOR_NOTE = ("Prioritise balance and controlled movements; check with your doctor before "
               "increasing intensity.")
SENIOR_LEVEL_NOTE = "Strength moves use beginner-level options for over-60s."
LOW_IMPACT_NOTE = ("Cardio and conditioning use low-impact options (bike, rower, incline walking, "
                   "swimming) to protect your joints.")
INJURY_NOTE = ("You mentioned an injury or pain: avoid movements that aggravate it and check "
               "with a doctor or physiotherapist before training it.")
UNCHANGED = "No automatic change matched your feedback; the plan is unchanged."

# Jumping, sprinting and running moves, swapped out for low-impact users.
HIGH_IMPACT = re.compile(r"\b(jump\w*|box|sprints?|burpees?|tempo run|jog\w*|run|running|"
                         r"plyo\w*|skipping|hops?)\b", re.I)
LOW_IMPACT_SWAPS = {
    "Jump Squats": ("Squat to Calf Raise", "Rise onto your toes at the top, no jump"),
    "Burpees": ("Squat Step-Backs", "Step back and forward, no jump"),
    "Box Jumps": ("Step-Ups to a Low Step", "Drive through the whole foot"),
    "Sprint Intervals": ("Speed Skater Steps", "Step side to side quickly, one foot always down"),
}
# Heavy loaded lifts, swapped for beginner moves when the user reports pain or an injury.
HEAVY = re.compile(r"\b(barbell|deadlift|weighted|kettlebell|clean)\b", re.I)

# Exercise names that need gear (a pull-up bar counts as gear; a chair or step doesn't).
EQUIPMENT = re.compile(r"\b(machines?|barbell|dumbbells?|kettlebell|bands?|bike|cycling|rower|"
                       r"rowing|rows?|pulldown|ropes?|weighted|box|wheel|hanging|pull-ups?|press|"
                       r"deadlift|goblet|curls?|foam|swimming)\b", re.I)
# Equipment-free replacements for the "no equipment" rule, per session type. No jumping.
BODYWEIGHT = {
    "upper": [("Push-Ups (knees down if needed)", "Body in one straight line"),
              ("Pike Push-Ups", "Hips high, lower head between hands"),
              ("Chair Dips", "Hands on a sturdy chair, elbows point back"),
              ("Superman Hold", "Lift chest and legs together, neck neutral")],
    "lower": [("Bodyweight Squats", "Knees track over toes"),
              ("Reverse Lunges", "Step back softly"),
              ("Glute Bridges", "Drive through heels"),
              ("Standing Calf Raises", "Pause at the top"),
              ("Bulgarian Split Squats", "Rear foot on a chair, stay tall")],
    "full": [("Bodyweight Squats", "Knees track over toes"),
             ("Push-Ups (knees down if needed)", "Body in one straight line"),
             ("Reverse Lunges", "Step back softly"),
             ("Superman Hold", "Lift chest and legs together, neck neutral"),
             ("Glute Bridges", "Drive through heels")],
    "core": [("Forearm Plank", "Don't let hips sag"),
             ("Dead Bug", "Lower back pressed to floor"),
             ("Lying Leg Raises", "Lower back stays on the floor"),
             ("Side Plank", "Stack hips and shoulders")],
    "hiit": [("Mountain Climbers", "Hips in line with shoulders"),
             ("Squat Step-Backs", "Step back and forward at your own pace"),
             ("Low-Impact Jacks", "Step out to the side, arms fully overhead"),
             ("Marching High Knees", "Stay tall")],
    "mobility": [("Standing Forward Fold", "Soft knees, let your head hang"),
                 ("Cat-Cow", "Move with your breath"),
                 ("Hip Flexor Stretch", "Tuck pelvis slightly")],
    "recovery": [("Gentle Full-Body Stretching", "Hold each stretch 20–30 sec")],
}
BODYWEIGHT_CARDIO = ("Brisk Walking or Marching in Place", "Steady pace, swing your arms")
CORE_NAMES = ({n for lvl in LIBRARY["core"].values() for n, _ in lvl}
              | {n for n, _ in BODYWEIGHT["core"]})


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
    if has(r"run|running|runner|marathons?|stamina|cardio|\d+k"):
        return "endurance"
    if has(r"stretch(ing)?|yoga|mobility|flexible"):
        return "flexibility"
    return "general fitness"


def _profile(experience: str | None, age: int | None, intensity: str | None,
             weight: float | None = None) -> dict:
    """Normalise the user inputs that drive safety rules (shared by generation and revision)."""
    chosen = experience if experience in LEVELS else "beginner"
    teen = age is not None and age < 18
    senior = age is not None and age >= 60
    heavy = weight is not None and weight >= HEAVY_WEIGHT_KG
    level = chosen
    if teen and chosen == "advanced":
        level = "intermediate"
    if senior:
        level = "beginner"
    return {"chosen": chosen, "level": level,
            "intensity": intensity if intensity in VOLUME else "medium",
            "teen": teen, "senior": senior, "heavy": heavy,
            "low_impact": senior or heavy, "injured": False}


def _kind_of(day: dict) -> str | None:
    """Work out the session type from a day's focus text."""
    focus = day["focus"].lower()
    for word, kind in (("recovery", "recovery"), ("rest", "rest"), ("upper", "upper"),
                       ("lower", "lower"), ("full", "full"), ("hiit", "hiit"),
                       ("cardio", "cardio"), ("core", "core"), ("mobility", "mobility"),
                       ("flexib", "mobility"), ("yoga", "mobility")):
        if word in focus:
            return kind
    return None


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


def _strength_reps(name: str, p: dict) -> str:
    if p["teen"]:  # age-appropriate: no heavy max lifts, moderate rep ranges
        return "10–15"
    if EQUIPMENT.search(name):
        return VOLUME[p["intensity"]][1]
    return BODYWEIGHT_REPS[p["intensity"]]


def _exercise(kind: str, name: str, cue: str, sets: int, p: dict) -> dict:
    rest = VOLUME[p["intensity"]][2]
    if kind == "hiit":
        return {"name": name, "sets": sets, "reps": HIIT_WORK[p["intensity"]],
                "rest_seconds": 60, "notes": f"{cue}. Each set is one round."}
    if kind == "mobility":
        return {"name": name, "sets": 2, "reps": "30–60 sec", "rest_seconds": 15, "notes": cue}
    if kind == "core":
        return {"name": name, "sets": sets, "reps": CORE_REPS.get(name, "30–45 sec"),
                "rest_seconds": 45, "notes": cue}
    return {"name": name, "sets": sets, "reps": _strength_reps(name, p),
            "rest_seconds": rest, "notes": cue}


def _cardio_choice(p: dict, low_impact: bool) -> tuple[str, str]:
    """One main cardio item, e.g. ("Brisk Walking or Stationary Bike", cue)."""
    options = (LOW_IMPACT_CARDIO if low_impact else LIBRARY["cardio"])[p["level"]]
    return " or ".join(name for name, _ in options), options[0][1]


def _cardio_item(p: dict, minutes: int, variant: int = 0) -> dict:
    """Steady cardio, then intervals, then a longer easy session when cardio repeats in a week."""
    name, cue = _cardio_choice(p, p["low_impact"])
    style = variant % 3
    if style == 1:
        rounds = max(minutes // 4, 4)
        effort = "brisk" if p["low_impact"] else "hard"
        return {"name": f"{name} Intervals", "sets": rounds,
                "reps": f"2 min {effort} / 2 min easy", "rest_seconds": None,
                "notes": f"{effort.capitalize()} means breathing harder but still in control. "
                         "Each set is one round."}
    if style == 2:
        return {"name": name, "sets": None, "reps": f"{minutes + 10} min",
                "rest_seconds": None, "notes": "Easy, conversational pace the whole time"}
    return {"name": name, "sets": None, "reps": f"{minutes} min", "rest_seconds": None,
            "notes": cue}


def _session(kind: str, day: int, p: dict, variant: int = 0) -> dict:
    """Build one day. `variant` rotates the exercise order when a session type repeats."""
    if kind == "rest":
        return _rest_day(day)
    if kind == "recovery":
        return _recovery_day(day)

    level = p["level"]
    sets = VOLUME[p["intensity"]][0]
    if p["teen"]:
        sets = min(sets, 3)
    if kind == "cardio":
        exercises = [_cardio_item(p, CARDIO_MINUTES[p["intensity"]], variant)]
    else:
        moves = LIBRARY[kind][level]
        shift = variant % len(moves)
        exercises = [_exercise(kind, name, cue, sets, p)
                     for name, cue in moves[shift:] + moves[:shift]]
    if kind in STRENGTH_KINDS or kind == "cardio":
        core_moves = LIBRARY["core"][level]
        name, cue = core_moves[variant % len(core_moves)]
        exercises.append(_exercise("core", name, cue, 2, p))
    if p["senior"] and kind in STRENGTH_KINDS + ("core",):
        name, cue, reps = BALANCE[day % len(BALANCE)]
        exercises.append({"name": name, "sets": 2, "reps": reps, "rest_seconds": 30,
                          "notes": cue})
    if p["low_impact"]:
        _make_low_impact([{"exercises": exercises}], p)
    warmups, cooldowns = WARMUPS[kind], COOLDOWNS[kind]
    return {"day": day, "focus": FOCUS[kind], "is_rest_day": False,
            "warmup": warmups[variant % len(warmups)], "exercises": exercises,
            "cooldown": cooldowns[variant % len(cooldowns)]}


def _next_variant(days: list, kind: str, skip: int) -> int:
    """How many other days already have this session type (so an added day isn't a copy)."""
    return sum(1 for j, d in enumerate(days) if j != skip and not d["is_rest_day"]
               and _kind_of(d) == kind)


def _relabel(days: list) -> None:
    """Label repeated session types A, B, C so the week reads clearly (standard focuses only)."""
    kinds = [None if d["is_rest_day"] else _kind_of(d) for d in days]
    counts = Counter(k for k in kinds if k)
    seen = Counter()
    for kind, d in zip(kinds, days):
        if not kind or not d["focus"].startswith(FOCUS[kind]):
            continue
        if counts[kind] > 1:
            d["focus"] = f"{FOCUS[kind]} {'ABCDEFG'[seen[kind]]}"
            seen[kind] += 1
        else:
            d["focus"] = FOCUS[kind]


def _make_low_impact(days: list, p: dict) -> int:
    """Swap jumping/running moves for low-impact ones. Returns how many were swapped."""
    swapped = 0
    for d in days:
        for ex in d["exercises"]:
            if not HIGH_IMPACT.search(ex["name"]):
                continue
            if ex["sets"] is None:  # a timed cardio item
                ex["name"], ex["notes"] = _cardio_choice(p, low_impact=True)
            else:
                ex["name"], ex["notes"] = LOW_IMPACT_SWAPS.get(
                    ex["name"], ("Low-Impact Jacks", "Step out to the side, no jump"))
            swapped += 1
    return swapped


def _add_profile_notes(safety: list, p: dict) -> list:
    """Append any profile-based safety notes that aren't already there."""
    rules = ((p["teen"], TEEN_NOTE),
             (p["teen"] and p["chosen"] == "advanced", TEEN_LEVEL_NOTE),
             (p["senior"], SENIOR_NOTE),
             (p["senior"] and p["chosen"] != "beginner", SENIOR_LEVEL_NOTE),
             (p["heavy"], LOW_IMPACT_NOTE),
             (p["injured"], INJURY_NOTE))
    for needed, note in rules:
        if needed and note not in safety:
            safety.append(note)
    return safety


def demo_workout_plan(goal: str, intensity: str, experience: str = "beginner",
                      age: int | None = None, weight: float | None = None) -> dict:
    key = _goal_key(goal)
    p = _profile(experience, age, intensity, weight)
    intensity = p["intensity"]

    days, seen = [], Counter()
    for i, kind in enumerate(SCHEDULES[key]):
        days.append(_session(kind, i + 1, p, variant=seen[kind]))
        seen[kind] += 1
    _relabel(days)

    who = f"{p['level']} level"
    if age:
        who += f", age {age}"
    goal_text = (goal or "").strip()
    if goal_text and goal_text.lower() != key:
        who += f"; your goal: {goal_text}"
    summary = f"A {intensity}-intensity {key} week ({who}), balancing training days with recovery."
    if p["heavy"]:
        summary += " Cardio and conditioning are low-impact to protect your joints."
    if p["teen"] and p["chosen"] == "advanced":
        summary += " Level set to intermediate for under-18s."

    safety = _add_profile_notes([
        "Stop any exercise that causes sharp pain, dizziness or chest discomfort.",
        "Warm up before every session and progress load gradually.",
        "Stay hydrated before, during and after training.",
    ], p)
    return {
        "title": f"7-Day {key.title()} Plan ({intensity.title()} Intensity)",
        "summary": summary,
        "days": days,
        "safety_notes": safety,
    }


def demo_nutrition_tip(goal: str, age: int | None = None) -> str:
    tip = TIPS[_goal_key(goal)]
    if age is not None and age < 18:
        tip += " As a teenager, eat regular balanced meals rather than restricting food."
    return tip


# ---------- Feedback matching ----------

NEGATORS = {"not", "no", "never", "dont", "without", "less", "fewer", "avoid", "hate", "stop"}


def _said(fb: str, pattern: str) -> bool:
    """True if the pattern appears in the feedback without a negation just before it
    (e.g. "not tired", "no cardio", "don't want rest" don't count)."""
    for m in re.finditer(pattern, fb):
        clause = re.split(r"[,.;!?]|\bbut\b|\band\b", fb[:m.start()])[-1]
        words = re.findall(r"[a-z']+", clause)[-3:]
        if not any(w in NEGATORS or w.endswith("n't") for w in words):
            return True
    return False


# ---------- Revision rules: each takes (days, p) and returns a change description or None ----------

def _training_idx(days: list) -> list:
    return [i for i, d in enumerate(days) if not d["is_rest_day"]]


def _of_kind(days: list, kinds: tuple) -> list:
    return [i for i in _training_idx(days) if _kind_of(days[i]) in kinds]


def _injury(days: list, p: dict) -> str:
    p["injured"] = p["low_impact"] = True
    _make_low_impact(days, p)
    for d in days:
        kind = _kind_of(d) if _kind_of(d) in LIBRARY else "full"
        used = {ex["name"] for ex in d["exercises"]}
        for ex in d["exercises"]:
            if HEAVY.search(ex["name"]):
                name, cue = next((m for m in LIBRARY[kind]["beginner"] if m[0] not in used),
                                 LIBRARY[kind]["beginner"][0])
                used.add(name)
                ex["name"], ex["notes"] = name, cue
                ex["reps"] = _strength_reps(name, p)
    return "added an injury safety note and switched to low-impact, lighter moves"


def _no_jumping(days: list, p: dict) -> str | None:
    if p["injured"]:  # already handled by the injury rule
        return None
    p["low_impact"] = True
    swapped = _make_low_impact(days, p)
    if not swapped:
        return "checked for jumping moves (the plan had none)"
    return f"replaced {swapped} jumping or high-impact move(s) with low-impact options"


def _more_cardio(days: list, p: dict) -> str:
    # Keep at least two strength days so the goal's main training isn't lost.
    core = _of_kind(days, ("core",))
    strength = _of_kind(days, STRENGTH_KINDS)
    if core or len(strength) > 2:
        i = core[-1] if core else strength[-1]
        days[i] = _session("cardio", i + 1, p, _next_variant(days, "cardio", i))
        return f"turned day {i + 1} into a cardio day"
    added = []
    for i in strength:
        if not any(ex["name"].startswith("Cardio Finisher") for ex in days[i]["exercises"]):
            days[i]["exercises"].append({
                "name": f"Cardio Finisher: {BODYWEIGHT_CARDIO[0]}", "sets": None,
                "reps": "10 min", "rest_seconds": None, "notes": BODYWEIGHT_CARDIO[1]})
            added.append(str(i + 1))
    if added:
        return f"added a 10-minute cardio finisher to day(s) {', '.join(added)}"
    return "kept the plan's strength days, so no more cardio could be added"


def _more_rest(days: list, p: dict) -> str:
    trains = _training_idx(days)
    if len(trains) <= 3:
        return "kept at least three training days, so no extra rest day was added"
    strength = _of_kind(days, STRENGTH_KINDS)
    others = [i for i in trains if i not in strength]
    candidates = others or (strength if len(strength) > 2 else [])
    if not candidates:
        return "kept the plan's strength days, so no extra rest day was added"
    i = candidates[len(candidates) // 2]
    days[i] = _rest_day(i + 1)
    return f"made day {i + 1} a rest day"


def _more_training(days: list, p: dict) -> str:
    rest_like = [i for i, d in enumerate(days) if d["is_rest_day"]]
    if len(rest_like) < 2:
        return "kept your only rest day, so no training day was added"
    recovery = [i for i in rest_like if days[i]["exercises"]] or rest_like
    i = recovery[0]
    days[i] = _session("full", i + 1, p, _next_variant(days, "full", i))
    return f"turned day {i + 1} into a full-body training day"


def _more_yoga(days: list, p: dict) -> str:
    candidates = _of_kind(days, ("cardio", "hiit", "core"))
    strength = _of_kind(days, STRENGTH_KINDS)
    if not candidates and len(strength) > 2:
        candidates = strength
    if candidates:
        i = candidates[-1]
        days[i] = _session("mobility", i + 1, p, _next_variant(days, "mobility", i))
        return f"turned day {i + 1} into a mobility and yoga session"
    for i, d in enumerate(days):
        names = [ex["name"] for ex in d["exercises"]]
        if d["is_rest_day"] and names and "Sun Salutation Flow" not in names:
            d["exercises"].append({"name": "Sun Salutation Flow", "sets": 2, "reps": "5 rounds",
                                   "rest_seconds": 30, "notes": "Slow, smooth transitions"})
            return f"added a yoga flow to day {i + 1}"
    return "the plan already includes as much yoga and mobility as it can hold"


def _shorter_minutes(reps: str) -> str:
    m = re.fullmatch(r"(\d+) min", reps)
    if not m:
        return reps
    minutes = int(m.group(1))
    shorter = {40: 25, 30: 20, 20: 15}.get(minutes, max(10, minutes * 2 // 3))
    return f"{shorter} min"


def _shorter(days: list, p: dict) -> str:
    for i in _training_idx(days):
        d = days[i]
        d["exercises"] = d["exercises"][:3]
        for ex in d["exercises"]:
            if ex.get("sets") and ex["sets"] > 2:
                ex["sets"] -= 1
            ex["reps"] = _shorter_minutes(ex["reps"])
    return "shortened workouts (fewer exercises, sets and minutes)"


def _bodyweight(days: list, p: dict) -> str:
    for d in days:
        kind = _kind_of(d) or "full"
        used = {ex["name"] for ex in d["exercises"]}
        for ex in d["exercises"]:
            if not EQUIPMENT.search(ex["name"]):
                continue
            if ex["sets"] is None:  # timed cardio item
                if "foam" in ex["name"].lower():
                    ex["name"], ex["notes"] = BODYWEIGHT["recovery"][0]
                elif kind == "recovery":
                    ex["name"], ex["notes"] = "Easy Walk", "Keep effort very light"
                else:
                    ex["name"], ex["notes"] = BODYWEIGHT_CARDIO
                continue
            slot = "core" if ex["name"] in CORE_NAMES else kind
            pool = BODYWEIGHT.get(slot, BODYWEIGHT["full"])
            name, cue = next((m for m in pool if m[0] not in used), pool[0])
            used.add(name)
            ex["name"], ex["notes"] = name, cue
            if slot == "core":
                ex["reps"] = CORE_REPS.get(name, "30–45 sec")
            elif slot in STRENGTH_KINDS:
                ex["reps"] = _strength_reps(name, p)
    return "switched to equipment-free exercises"


# Order matters: safety rules first, "no equipment" last so it also covers new sessions.
REVISION_RULES = [
    (lambda fb: _said(fb, r"\b(injur\w*|hurts?|hurting|pain\w*|sore\w*|sprain\w*|aches?|aching)\b"),
     _injury),
    (lambda fb: re.search(r"\b(jump\w*|plyo\w*|high[- ]impact|low[- ]impact)\b", fb)
     and not re.search(r"\bmore (jump|plyo)", fb), _no_jumping),
    (lambda fb: _said(fb, r"\bcardio\b"), _more_cardio),
    (lambda fb: _said(fb, r"\b(rest|recover\w*|tired|exhausted|fatigued?|worn out)\b"), _more_rest),
    (lambda fb: _said(fb, r"\bmore (workouts?|training|exercises?|sessions?|days)\b|\btrain more\b"),
     _more_training),
    (lambda fb: _said(fb, r"\b(yoga|stretch\w*|mobility|flexib\w*|pilates)\b"), _more_yoga),
    (lambda fb: _said(fb, r"\b(short\w*|less time|quick\w*|busy)\b"), _shorter),
    (lambda fb: re.search(r"no equipment|without equipment|no gym|at home|home workouts?|"
                          r"bodyweight|don't have (any )?equipment", fb), _bodyweight),
]


def _base_summary(summary: str) -> str:
    """The original summary without earlier revision notes."""
    return re.split(r" (?:Revised:|No automatic change)", summary or "")[0].strip()


def demo_revise_plan(plan: dict, feedback: str, *, experience: str | None = None,
                     age: int | None = None, intensity: str | None = None,
                     weight: float | None = None) -> dict:
    """Simple keyword-driven revision of the latest plan, using the same safety profile as
    generation (experience level, intensity, age and weight rules)."""
    p = _profile(experience, age, intensity, weight)
    new = copy.deepcopy(plan)
    days = new["days"]
    safety = list(new.get("safety_notes") or [])
    if INJURY_NOTE in safety:  # an injury mentioned earlier still applies
        p["injured"] = p["low_impact"] = True
    if p["low_impact"]:
        _make_low_impact(days, p)

    fb = (feedback or "").lower()
    changes = [c for match, rule in REVISION_RULES if match(fb) and (c := rule(days, p))]

    if p["teen"]:  # cap volume on anything carried over from the previous version
        for d in days:
            for ex in d["exercises"]:
                if ex.get("sets") and ex["sets"] > 3:
                    ex["sets"] = 3
    if p["senior"] and not any(ex["name"] in BALANCE_NAMES for d in days for ex in d["exercises"]):
        trains = _of_kind(days, STRENGTH_KINDS) or _training_idx(days)
        if trains:
            name, cue, reps = BALANCE[0]
            days[trains[0]]["exercises"].append({"name": name, "sets": 2, "reps": reps,
                                                 "rest_seconds": 30, "notes": cue})
    if not any(d["is_rest_day"] for d in days):  # guard: always keep one rest day
        days[-1] = _rest_day(len(days))
        changes.append(f"made day {len(days)} a rest day")
    for n, d in enumerate(days, start=1):
        d["day"] = n
    _relabel(days)
    new["safety_notes"] = _add_profile_notes(safety, p)

    base = _base_summary(plan.get("summary", ""))
    if changes:
        new["summary"] = f"{base} Revised: {'; '.join(changes)}.".strip()
    else:
        new["summary"] = f"{base} {UNCHANGED}".strip()
    return new

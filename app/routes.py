"""All HTML (form-based, POST/redirect/GET) and JSON API routes.

Routes that call Gemini are plain `def` so FastAPI runs them in a threadpool and the sync
SDK calls never block the event loop.
"""
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import ValidationError

from app import config, database as db
from app.gemini_client import GeminiError
from app.gemini_flash_generator import generate_nutrition_tip_with_flash
from app.gemini_generator import generate_workout_gemini
from app.schemas import COMMON_GOALS, FeedbackRequest, QuickWorkoutRequest, UserInput
from app.updated_plan import update_workout_plan

log = logging.getLogger("fitbuddy.routes")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals.update(demo_mode=lambda: config.DEMO_MODE, common_goals=COMMON_GOALS)

ADMIN_COOKIE = "fitbuddy_admin"
ADMIN_MAX_AGE = 8 * 3600
_signer = URLSafeTimedSerializer(config.SECRET_KEY, salt="fitbuddy-admin")

AI_ERROR_MSG = ("Sorry, our AI coach couldn't create your plan right now. "
                "Please try again in a moment.")


# ----------------------------- helpers -----------------------------

def _friendly_errors(exc: ValidationError) -> list[str]:
    msgs = []
    for err in exc.errors():
        field = " ".join(str(p) for p in err["loc"]).replace("_kg", "").replace("_", " ")
        msgs.append(f"{field.capitalize()}: {err['msg']}")
    return msgs


def _create_plan_for(data: UserInput) -> tuple[int, int, dict, str]:
    """Generate plan + tip, then persist user and v1. Raises GeminiError (nothing saved)."""
    plan, source, _ = generate_workout_gemini(data.goal, data.intensity, data.experience,
                                              data.age, data.weight_kg)
    tip = _tip_or_fallback(data.goal, data.age)
    user_id = db.save_user(data.name, data.age, data.weight_kg, data.goal,
                           data.intensity, data.experience)
    version = db.save_plan(user_id, plan, tip, source)
    return user_id, version, plan, tip


def _tip_or_fallback(goal: str, age: Optional[int]) -> str:
    """The tip is secondary: if the tip model fails, use the curated tip, never an error."""
    try:
        return generate_nutrition_tip_with_flash(goal, age)[0]
    except GeminiError as exc:
        log.warning("Tip generation failed (%s); using curated tip", exc)
        from app.demo_data import demo_nutrition_tip
        return demo_nutrition_tip(goal, age)


def _revise(user_id: int, feedback: str) -> tuple[int, dict]:
    user = db.get_user(user_id)
    latest = db.get_latest_plan(user_id)
    if not user or not latest:
        raise HTTPException(404, "No plan found for this user")
    revised, source = update_workout_plan(latest.plan, feedback, user)
    version = db.update_plan(user_id, revised, feedback, latest.nutrition_tip, source)
    return version, revised


def is_admin(request: Request) -> bool:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return False
    try:
        return _signer.loads(token, max_age=ADMIN_MAX_AGE) == "admin"
    except (BadSignature, SignatureExpired):
        return False


def _render_plan(request: Request, user_id: int, version: Optional[int] = None,
                 status_code: int = 200, **extra) -> HTMLResponse:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    history = db.get_plan_history(user_id)
    if not history:
        raise HTTPException(404, "No plan found for this user")
    latest = history[-1]
    if version is None:
        current = latest
    else:
        current = next((p for p in history if p.version == version), None)
        if current is None:
            raise HTTPException(404, "Plan version not found")
    ctx = {"user": user, "current": current, "plan": current.plan, "history": history,
           "is_latest": current.version == latest.version, "latest": latest,
           "updated": False, "error": None, "feedback_value": ""}
    ctx.update(extra)
    return templates.TemplateResponse(request, "result.html", ctx, status_code=status_code)


# ----------------------------- HTML routes -----------------------------

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"errors": [], "form": {}})


@router.post("/generate-workout", response_class=HTMLResponse, include_in_schema=False)
def generate_workout_form(
    request: Request,
    name: str = Form(""), age: str = Form(""), weight: str = Form(""),
    goal: str = Form(""), goal_other: str = Form(""),
    intensity: str = Form(""), experience: str = Form("beginner"),
):
    form = {"name": name, "age": age, "weight": weight, "goal": goal,
            "goal_other": goal_other, "intensity": intensity, "experience": experience}
    chosen_goal = goal_other if goal == "other" else goal
    try:
        data = UserInput(name=name, age=age or None, weight_kg=weight or None,
                         goal=chosen_goal, intensity=intensity, experience=experience)
    except ValidationError as exc:
        return templates.TemplateResponse(request, "index.html",
                                          {"errors": _friendly_errors(exc), "form": form},
                                          status_code=422)
    try:
        user_id, *_ = _create_plan_for(data)
    except GeminiError:
        return templates.TemplateResponse(request, "index.html",
                                          {"errors": [AI_ERROR_MSG], "form": form},
                                          status_code=502)
    return RedirectResponse(f"/plan/{user_id}", status_code=303)


@router.get("/plan/{user_id}", response_class=HTMLResponse, include_in_schema=False)
def view_plan(request: Request, user_id: int, updated: int = 0):
    return _render_plan(request, user_id, updated=bool(updated))


@router.get("/plan/{user_id}/version/{version}", response_class=HTMLResponse,
            include_in_schema=False)
def view_plan_version(request: Request, user_id: int, version: int):
    return _render_plan(request, user_id, version)


@router.post("/submit-feedback", response_class=HTMLResponse, include_in_schema=False)
def submit_feedback(request: Request, user_id: int = Form(...), feedback: str = Form("")):
    try:
        fb = FeedbackRequest(feedback=feedback)
    except ValidationError:
        return _render_plan(request, user_id, status_code=422, feedback_value=feedback,
                            error=f"Please enter feedback (1–{config.MAX_FEEDBACK_LENGTH} characters).")
    try:
        _revise(user_id, fb.feedback)
    except GeminiError:
        return _render_plan(request, user_id, status_code=502, feedback_value=feedback,
                            error="Sorry, we couldn't update your plan right now. "
                                  "Your current plan is unchanged — please try again.")
    return RedirectResponse(f"/plan/{user_id}?updated=1", status_code=303)


# ----------------------------- Admin -----------------------------

@router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
def admin_login_page(request: Request):
    if is_admin(request):
        return RedirectResponse("/view-all-users", status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {"error": None})


@router.post("/admin/login", response_class=HTMLResponse, include_in_schema=False)
def admin_login(request: Request, password: str = Form("")):
    import hmac
    if not hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode()):
        return templates.TemplateResponse(request, "admin_login.html",
                                          {"error": "Incorrect password."}, status_code=401)
    resp = RedirectResponse("/view-all-users", status_code=303)
    resp.set_cookie(ADMIN_COOKIE, _signer.dumps("admin"), max_age=ADMIN_MAX_AGE,
                    httponly=True, samesite="lax")
    return resp


@router.get("/admin/logout", include_in_schema=False)
def admin_logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(ADMIN_COOKIE)
    return resp


@router.get("/view-all-users", response_class=HTMLResponse, include_in_schema=False)
def view_all_users(request: Request, deleted: int = 0):
    if not is_admin(request):
        return templates.TemplateResponse(
            request, "admin_login.html",
            {"error": "Please log in to view the admin dashboard."}, status_code=401)
    return templates.TemplateResponse(request, "all_users.html",
                                      {"rows": db.get_all_users(), "deleted": bool(deleted)})


@router.post("/admin/delete-user/{user_id}", include_in_schema=False)
def admin_delete_user(request: Request, user_id: int):
    if not is_admin(request):
        raise HTTPException(401, "Admin login required")
    if not db.delete_user(user_id):
        raise HTTPException(404, "User not found")
    return RedirectResponse("/view-all-users?deleted=1", status_code=303)


# ----------------------------- JSON API -----------------------------

@router.post("/generate-workout/gemini", tags=["API"])
def api_generate_workout(body: QuickWorkoutRequest):
    """Generate a 7-day plan without saving anything."""
    try:
        plan, _, model = generate_workout_gemini(body.goal, body.intensity, body.experience,
                                                 body.age, body.weight)
    except GeminiError as exc:
        raise HTTPException(502, f"AI generation failed: {exc}")
    return {"model": model, "workout_plan": plan}


@router.get("/nutrition-tip", tags=["API"])
def api_nutrition_tip(goal: str, age: Optional[int] = None):
    goal = goal.strip()
    if not goal or len(goal) > 200:
        raise HTTPException(422, "goal must be 1–200 characters")
    if age is not None and not 13 <= age <= 90:
        raise HTTPException(422, "age must be between 13 and 90")
    try:
        tip, _ = generate_nutrition_tip_with_flash(goal, age)
    except GeminiError as exc:
        raise HTTPException(502, f"AI generation failed: {exc}")
    return {"goal": goal, "nutrition_tip": tip}


@router.post("/generate-plan", tags=["API"])
def api_generate_plan(body: UserInput):
    """Create a user, generate their plan + tip and store version 1."""
    try:
        user_id, version, plan, tip = _create_plan_for(body)
    except GeminiError as exc:
        raise HTTPException(502, f"AI generation failed: {exc}")
    return {"user_id": user_id, "version": version, "workout_plan": plan, "nutrition_tip": tip}


@router.post("/update-plan/{user_id}", tags=["API"])
def api_update_plan(user_id: int, body: FeedbackRequest):
    """Revise the user's latest plan using feedback; stores a new version."""
    try:
        version, revised = _revise(user_id, body.feedback)
    except GeminiError as exc:
        raise HTTPException(502, f"AI revision failed: {exc}")
    return {"user_id": user_id, "version": version, "updated_plan": revised}


@router.get("/api/users/{user_id}/plans", tags=["API"])
def api_plan_history(user_id: int):
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return {
        "user_id": user.id, "name": user.name, "age": user.age, "weight_kg": user.weight_kg,
        "goal": user.goal, "intensity": user.intensity, "experience": user.experience,
        "plans": [p.to_dict() for p in db.get_plan_history(user_id)],
    }


@router.get("/api/health", tags=["API"])
def api_health():
    return {
        "status": "ok",
        "db": "ok" if db.db_ok() else "error",
        "gemini_configured": bool(config.GEMINI_API_KEY),
        "demo_mode": config.DEMO_MODE,
        "models": {"workout": config.GEMINI_WORKOUT_MODEL, "tip": config.GEMINI_TIP_MODEL,
                   "workout_fallback": config.GEMINI_WORKOUT_FALLBACK_MODEL or None},
    }

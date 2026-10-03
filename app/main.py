"""FastAPI application entry point: `uvicorn app.main:app --reload`."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException
from fastapi.staticfiles import StaticFiles

from app import config
from app.database import init_db
from app.routes import router, templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fitbuddy")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    for msg in config.STARTUP_WARNINGS:
        logging.getLogger("fitbuddy.config").warning(msg)
    if config.DEMO_MODE:
        log.info("FitBuddy running in DEMO MODE (no Gemini key or DEMO_MODE=true)")
    else:
        log.info("FitBuddy using Gemini: workout=%s tip=%s",
                 config.GEMINI_WORKOUT_MODEL, config.GEMINI_TIP_MODEL)
    yield


app = FastAPI(
    title="FitBuddy – AI Fitness Plan Generator",
    description="Personalized 7-day workout plans and nutrition tips using Google Gemini.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    """JSON for API clients, a friendly page for browsers."""
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse(
            request, "error.html", {"status": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code)
    return await http_exception_handler(request, exc)

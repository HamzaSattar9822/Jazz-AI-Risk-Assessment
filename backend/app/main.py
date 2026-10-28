import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.methodology.engine import METHODOLOGY_VERSION
from app.seed import seed_users

logger = logging.getLogger(__name__)

# Docker/Render packs the portal as /app/static/index.html.
# Local runs can also serve the HTML file from the repo root.
_PORTAL_CANDIDATES = [
    Path("/app/static/index.html"),
    Path(__file__).resolve().parents[1] / "static" / "index.html",
    Path(__file__).resolve().parents[2] / "DDA.html",
    Path(__file__).resolve().parents[2] / "Ai_risk_assessment_icon_toggle.html",
]


def _portal_html() -> Path | None:
    for path in _PORTAL_CANDIDATES:
        if path.is_file():
            return path
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_users(db)
    logger.info("JazzWorld AI approval API ready (%s)", METHODOLOGY_VERSION)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="JazzWorld AI Approval API",
        summary="Intake, duplicate check, and AIRA risk scoring for the Responsible AI Office.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=r"https://.*\.onrender\.com",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        from app.mail.service import mail_status

        mail = mail_status(settings)
        return {
            "status": "ok",
            "methodology": METHODOLOGY_VERSION,
            "llmConfigured": settings.llm_configured,
            "llmModel": settings.llm_model if settings.llm_configured else None,
            "emailConfigured": bool(mail["configured"] and mail["provider"] != "log"),
            "mail": mail,
        }

    portal_html = _portal_html()

    @app.get("/")
    def root():
        if portal_html is not None:
            return FileResponse(portal_html)
        return {
            "service": "JazzWorld AI Approval API",
            "docs": "/docs",
            "health": "/health",
            "portal": "/app",
        }

    @app.get("/app")
    def portal():
        if portal_html is None:
            return {"message": "Portal HTML was not packaged with this build."}
        return FileResponse(portal_html)

    app.include_router(router, prefix="/api/v1")
    if portal_html is not None and portal_html.parent.is_dir():
        # Optional assets directory when packaged as /app/static/
        static_dir = portal_html.parent
        if static_dir.name == "static":
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


app = create_app()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.methodology.engine import METHODOLOGY_VERSION
from app.seed import seed_users

logger = logging.getLogger(__name__)


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

    @app.get("/")
    def root():
        return {"service": "JazzWorld AI Approval API", "docs": "/docs", "health": "/health"}

    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()

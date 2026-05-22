"""Entrypoint FastAPI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.db.pool import close_pool, get_pool
from src.routes import api_router
from src.settings import get_settings


def _setup_logging() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    await get_pool()
    yield
    await close_pool()


app = FastAPI(
    title="Redactia API",
    version="0.0.1",
    description="API REST para la plataforma editorial Redactia",
    lifespan=lifespan,
)
app.include_router(api_router)

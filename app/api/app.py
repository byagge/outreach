from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    accounts,
    bases,
    collect,
    contacts,
    filters,
    history,
    proxies,
    run,
    settings,
    system,
    texts,
)
from app.config import ensure_dirs, get_settings
from app.context import ctx
from app.store import Store


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    store = Store()
    await store.init()
    ctx.store = store
    yield


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title="Outreach API",
        version="2.1.0",
        description="Полный HTTP API системы outreach (аккаунты, базы, прокси, рассылка, сбор).",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router, prefix="/v1")
    app.include_router(settings.router, prefix="/v1")
    app.include_router(accounts.router, prefix="/v1")
    app.include_router(proxies.router, prefix="/v1")
    app.include_router(bases.router, prefix="/v1")
    app.include_router(contacts.router, prefix="/v1")
    app.include_router(texts.router, prefix="/v1")
    app.include_router(filters.router, prefix="/v1")
    app.include_router(collect.router, prefix="/v1")
    app.include_router(run.router, prefix="/v1")
    app.include_router(history.router, prefix="/v1")

    @app.get("/")
    async def root():
        return {
            "ok": True,
            "service": "outreach-api",
            "docs": "/docs",
            "public_url": cfg.api_public_url,
            "api_prefix": "/v1",
        }

    return app


app = create_app()

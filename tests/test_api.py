from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure API key before app import path uses settings
os.environ.setdefault("API_KEY", "test-key-for-pytest")


@pytest.fixture
async def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-for-pytest")
    from app.config import get_settings

    get_settings.cache_clear()

    from app.api.app import create_app
    from app.config import DB_PATH
    import app.config as cfg

    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(cfg, "TEXTS_DIR", tmp_path / "texts")
    monkeypatch.setattr(cfg, "UPLOADS_DIR", tmp_path / "uploads")

    import app.store as store_mod

    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "api.db")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # lifespan
        async with app.router.lifespan_context(app):
            yield ac
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_health_no_auth(client):
    r = await client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_stats_requires_key(client):
    r = await client.get("/v1/stats")
    assert r.status_code == 401
    r = await client.get("/v1/stats", headers={"X-API-Key": "test-key-for-pytest"})
    assert r.status_code == 200
    assert "counts" in r.json()


@pytest.mark.asyncio
async def test_bases_crud(client):
    h = {"X-API-Key": "test-key-for-pytest"}
    r = await client.post("/v1/bases", headers=h, json={"name": "api-base"})
    assert r.status_code == 200
    base_id = r.json()["base"]["id"]
    r = await client.post(
        f"/v1/bases/{base_id}/contacts",
        headers=h,
        json={"text": "@alice_api_test_1\n@bobby_api_test_2"},
    )
    assert r.status_code == 200
    assert r.json()["added"] == 2
    r = await client.get("/v1/stats", headers=h)
    assert r.json()["counts"]["pending"] >= 2

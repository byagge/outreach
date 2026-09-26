from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.context import ctx
from app.store import Store


@pytest.fixture
async def api_client(tmp_path: Path, monkeypatch):
    db = Store(tmp_path / "api.db")
    await db.init()
    ctx.store = db
    monkeypatch.setenv("API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, db
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_campaigns_api_crud(api_client):
    client, store = api_client
    headers = {"X-API-Key": "test-key"}

    r = await client.get("/v1/campaigns", headers=headers)
    assert r.status_code == 200
    assert r.json()["ok"]
    assert any(c["is_main"] for c in r.json()["items"])

    r = await client.post("/v1/campaigns", headers=headers, json={"name": "API Camp"})
    assert r.status_code == 200
    camp_id = r.json()["campaign"]["id"]

    base = await store.add_base("b1", isolated=1, enabled=0)
    acc = await store.add_account("a1")
    await store.update_account(acc.id, telethon_session="x.session")
    tx = await store.add_text("hi", [], title="t1")

    r = await client.put(
        f"/v1/campaigns/{camp_id}/bases",
        headers=headers,
        json={"ids": [base.id]},
    )
    assert r.json()["base_ids"] == [base.id]

    r = await client.put(
        f"/v1/campaigns/{camp_id}/accounts",
        headers=headers,
        json={"ids": [acc.id]},
    )
    assert acc.id in r.json()["account_ids"]

    r = await client.put(
        f"/v1/campaigns/{camp_id}/texts",
        headers=headers,
        json={"ids": [tx.id]},
    )
    assert tx.id in r.json()["text_ids"]

    r = await client.get(f"/v1/campaigns/{camp_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] == 0
    assert body["base_ids"] == [base.id]

    r = await client.post(
        f"/v1/bases/{base.id}/assign",
        headers=headers,
        json={"campaign_id": camp_id},
    )
    assert r.status_code == 200

    r = await client.patch(
        f"/v1/texts/{tx.id}",
        headers=headers,
        json={"title": "edited", "text": "new body"},
    )
    assert r.status_code == 200
    assert r.json()["text"]["title"] == "edited"
    assert r.json()["text"]["text"] == "new body"

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.contacts import Classified
from app.store import Store


@pytest.fixture
async def store(tmp_path: Path):
    db = Store(tmp_path / "t.db")
    await db.init()
    return db


@pytest.mark.asyncio
async def test_bases_toggle_and_claim(store: Store):
    base = await store.add_base("test")
    await store.add_contacts(
        [Classified("username", "one", 0.9, "t", raw="@one", display="@one")],
        base.id,
    )
    off = await store.toggle_base(base.id)
    assert off and not off.enabled
    assert await store.claim_contact() is None
    on = await store.toggle_base(base.id)
    assert on and on.enabled
    contact = await store.claim_contact()
    assert contact and contact.value == "one"


@pytest.mark.asyncio
async def test_blocklist_skips(store: Store):
    base_id = await store.default_base_id()
    await store.add_contacts(
        [Classified("username", "blocked", 0.9, "t", raw="@blocked", display="@blocked")],
        base_id,
    )
    await store.add_blocklist(
        [Classified("username", "blocked", 0.9, "t", raw="@blocked", display="@blocked")]
    )
    assert await store.claim_contact() is None


@pytest.mark.asyncio
async def test_banwords_settings(store: Store):
    settings = await store.outreach_settings()
    assert settings.delay_min == 60
    assert settings.delay_max == 120
    assert settings.variant_mode == "random"
    assert settings.continuous is True

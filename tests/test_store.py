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
async def test_add_and_claim(store: Store):
    added, skipped = await store.add_contacts(
        [
            Classified("username", "alpha", 0.9, "t", raw="@alpha", display="@alpha"),
            Classified("username", "alpha", 0.9, "t", raw="@alpha", display="@alpha"),
            Classified("phone", "+7999", 0.9, "t", raw="+7999", display="+7999"),
        ]
    )
    assert added == 2
    assert skipped == 1
    first = await store.claim_contact()
    second = await store.claim_contact()
    third = await store.claim_contact()
    assert first and second and third is None
    await store.finish_contact(first.id, "sent", account_id=None)
    counts = await store.counts()
    assert counts.sent == 1
    assert counts.pending == 0


@pytest.mark.asyncio
async def test_proxy_rebalance(store: Store):
    from app.utils.proxy import parse_proxy_blob

    await store.add_account("a")
    await store.add_account("b")
    items = parse_proxy_blob("1.1.1.1:1080\n2.2.2.2:1080\n3.3.3.3:1080\n4.4.4.4:1080")
    added, _ = await store.add_proxies(items)
    assert added == 4
    a1 = (await store.list_accounts())[0]
    a2 = (await store.list_accounts())[1]
    p1 = await store.proxies_for_account(a1.id)
    p2 = await store.proxies_for_account(a2.id)
    assert len(p1) == 2
    assert len(p2) == 2
    first = await store.next_proxy(a1.id)
    second = await store.next_proxy(a1.id)
    third = await store.next_proxy(a1.id)
    assert first and second and third
    assert {first.id, second.id} == {p.id for p in p1}
    assert third.id == first.id

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.brain import between_accounts, pick_variant
from app.ai.contacts import Classified
from app.models import TextVariant
from app.store import Store
from app.utils.proxy import parse_proxy_blob
from app.utils.work_hours import parse_work_hours


@pytest.fixture
async def store(tmp_path: Path):
    db = Store(tmp_path / "fix.db")
    await db.init()
    return db


@pytest.mark.asyncio
async def test_assign_unbound_keeps_manual_bind(store: Store):
    a1 = await store.add_account("a1")
    a2 = await store.add_account("a2")
    items = parse_proxy_blob("1.1.1.1:1080\n2.2.2.2:1080")
    await store.add_proxies(items)
    proxies = await store.list_proxies()
    # Manual: bind both proxies only to a1
    await store.bind_proxy(a1.id, proxies[0].id, True)
    await store.bind_proxy(a1.id, proxies[1].id, True)
    await store.bind_proxy(a2.id, proxies[0].id, False)
    await store.bind_proxy(a2.id, proxies[1].id, False)
    # Soft assign should not wipe
    await store.assign_unbound_proxies()
    p1 = await store.proxies_for_account(a1.id)
    p2 = await store.proxies_for_account(a2.id)
    assert {p.id for p in p1} == {proxies[0].id, proxies[1].id}
    assert p2 == []


@pytest.mark.asyncio
async def test_peek_proxy_does_not_advance(store: Store):
    a = await store.add_account("a")
    await store.add_proxies(parse_proxy_blob("1.1.1.1:1080\n2.2.2.2:1080"))
    first = await store.peek_proxy(a.id)
    second = await store.peek_proxy(a.id)
    assert first and second and first.id == second.id
    third = await store.next_proxy(a.id)
    assert third and third.id == first.id
    fourth = await store.peek_proxy(a.id)
    assert fourth and fourth.id != first.id


@pytest.mark.asyncio
async def test_global_unique_contact_across_bases(store: Store):
    b1 = await store.add_base("one")
    b2 = await store.add_base("two")
    item = Classified("username", "same", 0.9, "t", raw="@same", display="@same")
    a1, s1 = await store.add_contacts([item], b1.id)
    a2, s2 = await store.add_contacts([item], b2.id)
    assert a1 == 1 and s1 == 0
    assert a2 == 0 and s2 == 1


@pytest.mark.asyncio
async def test_blocklist_restore(store: Store):
    base = await store.default_base_id()
    item = Classified("username", "x", 0.9, "t", raw="@x", display="@x")
    await store.add_contacts([item], base)
    await store.add_blocklist([item])
    assert await store.claim_contact() is None
    blocks = await store.list_blocklist()
    await store.remove_block(blocks[0].id)
    # contact was skipped with blocklist — should return to pending
    c = await store.claim_contact()
    assert c and c.value == "x"


@pytest.mark.asyncio
async def test_reset_errors_skips_sending(store: Store):
    base = await store.default_base_id()
    await store.add_contacts(
        [Classified("username", "s", 0.9, "t", raw="@s", display="@s")],
        base,
    )
    c = await store.claim_contact()
    assert c and c.status == "sending"
    n = await store.reset_errors_to_pending()
    assert n == 0
    listed = await store.list_contacts(status="sending")
    assert len(listed) == 1


def test_between_accounts_allows_zero():
    assert between_accounts(0, 0) == 0.0
    v = between_accounts(0, 5)
    assert 0 <= v <= 5


def test_pick_variant_photo_only():
    t = TextVariant(id=1, text="", photo_path="/tmp/a.jpg", enabled=1)
    assert pick_variant([t], "random", 0) is t


def test_parse_work_hours():
    assert parse_work_hours("09:00-21:00") == ("09:00", "21:00")
    assert parse_work_hours("24/7") == ("", "")
    assert parse_work_hours("9-21") is None
    assert parse_work_hours("abc") is None

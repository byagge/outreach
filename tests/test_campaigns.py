from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.contacts import Classified
from app.jobs.outreach import build_campaign_scope, main_scope
from app.store import Store
from app.ui.screens import texts_html
from app.models import TextVariant


@pytest.fixture
async def store(tmp_path: Path):
    db = Store(tmp_path / "camp.db")
    await db.init()
    return db


@pytest.mark.asyncio
async def test_isolated_base_not_in_main_queue(store: Store):
    base = await store.add_base("sep", isolated=1, enabled=0)
    await store.add_contacts(
        [Classified("username", "iso1", 0.9, "t", raw="@iso1", display="@iso1")],
        base.id,
    )
    assert await store.claim_contact() is None
    assert await store.count_pending(mailing_only=True) == 0

    main = await store.get_main_campaign()
    await store.assign_base_to_campaign(base.id, main.id)
    base = await store.get_base(base.id)
    assert base and base.isolated == 0 and base.enabled == 1
    c = await store.claim_contact()
    assert c and c.value == "iso1"


@pytest.mark.asyncio
async def test_campaign_scope_and_claim(store: Store):
    camp = await store.add_campaign("C1")
    base = await store.add_base("campbase", isolated=1, enabled=0)
    await store.add_contacts(
        [Classified("username", "cuser", 0.9, "t", raw="@cuser", display="@cuser")],
        base.id,
    )
    await store.assign_base_to_campaign(base.id, camp.id)
    acc = await store.add_account("acc1")
    await store.update_account(acc.id, telethon_session="dummy.session")
    await store.toggle_campaign_account(camp.id, acc.id)
    tx = await store.add_text("hello", [], title="offer1")
    await store.toggle_campaign_text(camp.id, tx.id)

    scope = await build_campaign_scope(store, camp.id)
    assert scope.runtime_kind == "campaign"
    assert scope.base_ids == [base.id]
    assert acc.id in (scope.account_ids or [])
    assert tx.id in (scope.text_ids or [])

    # still not in main
    assert await store.claim_contact(mailing_only=True) is None
    c = await store.claim_contact(base_ids=scope.base_ids, mailing_only=False)
    assert c and c.value == "cuser"


def test_texts_html_paginates_without_cutting_tags():
    items = [
        TextVariant(
            id=i,
            title=f"вариант #{i}",
            text=("Привет мир с длинным текстом оффера. " * 4),
            entities_json="[]",
            enabled=1,
        )
        for i in range(20)
    ]
    html = texts_html(items, page=0)
    assert "стр. 1/" in html
    assert html.count("<tg-emoji") == html.count("</tg-emoji>")
    assert not html.rstrip().endswith('="')
    page2 = texts_html(items, page=2)
    assert "стр. 3/" in page2


def test_main_scope_defaults():
    s = main_scope()
    assert s.runtime_kind == "outreach"
    assert s.mailing_only is True
    assert s.campaign_name == "Основной"

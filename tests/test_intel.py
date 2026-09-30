# -*- coding: utf-8 -*-
from app.ai.intel.prepare import prepare_posts
from app.ai.intel.schema import PersonRaw
from app.ai.intel.triage import triage_local


def test_prepare_keeps_full_text_no_trim():
    long = ("Looking for clients this week, need chatter for accounts, rates open. " * 3).strip()
    got = prepare_posts([long, "ok", "lol", long], max_posts=50, max_total_chars=20000)
    assert long in got
    assert all(g not in {"ok", "lol"} for g in got)
    # не обрезали
    assert got[0] == long


def test_prepare_drops_only_noise_and_dupes():
    posts = [
        "Need a chatter for 3 accounts, % negotiable",
        "ok",
        "Need a chatter for 3 accounts, % negotiable",
        "Buying traffic for my offer tomorrow",
    ]
    got = prepare_posts(posts)
    assert len(got) == 2


def test_empty_still_triaged():
    raw = PersonRaw(user_id=1, posts=["hi", "ok"])
    # pipeline skips <2 substantive; triage_local may still classify
    v = triage_local(raw)
    assert v is not None


def test_verdict_guards_coder_and_employee():
    from app.ai.intel.qualify_quality import _verdict_from_llm_item

    coder = _verdict_from_llm_item(
        1,
        {"role": "coder", "score": 90, "bucket": "premium", "reason": "dev"},
        premium_threshold=70,
    )
    assert coder.bucket == "coders"
    assert coder.score <= 45

    emp = _verdict_from_llm_item(
        2,
        {"role": "employee", "score": 85, "bucket": "premium", "reason": "works"},
        premium_threshold=70,
    )
    assert emp.bucket == "other"

    op = _verdict_from_llm_item(
        3,
        {"role": "operator", "score": 80, "bucket": "premium", "reason": "hires"},
        premium_threshold=70,
    )
    assert op.bucket == "premium"
    assert op.score == 80

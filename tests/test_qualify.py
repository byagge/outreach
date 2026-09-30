# -*- coding: utf-8 -*-
"""Tests for lead profile helpers (LLM is mocked / not required)."""

from __future__ import annotations

from app.ai.qualify import (
    BUCKET_CODERS,
    BUCKET_OTHER,
    LeadProfile,
    heuristic_qualify,
    language_ok,
    matches_language,
)


def test_full_message_in_blob():
    long = ("We scale our content studio with a team of 15 managers. " * 5).strip()
    p = LeadProfile(user_id=8, messages=[long])
    blob = p.blob()
    assert long in blob
    assert "posts (full text" in blob


def test_language_ru_filter():
    ru_text = "Привет, у нас студия и команда менеджеров работает уже давно"
    en_text = "Hello we run a content studio with a professional team of managers"
    assert matches_language(ru_text, "ru")
    assert not matches_language(en_text, "ru")
    assert matches_language(en_text, "en")
    ru = LeadProfile(user_id=4, messages=[ru_text])
    en = LeadProfile(user_id=5, messages=[en_text])
    assert language_ok(ru, "ru")
    assert not language_ok(en, "ru")
    assert language_ok(en, "en")


def test_fallback_coder_only_on_explicit_code():
    p = LeadProfile(
        user_id=1,
        messages=["Check my github pull request and npm install steps"],
    )
    q = heuristic_qualify(p)
    assert q is not None
    assert q.bucket == BUCKET_CODERS
    assert q.source == "fallback"


def test_fallback_without_keywords_is_other():
    """Без LLM не угадываем buyer по словам agency — только other."""
    p = LeadProfile(
        user_id=2,
        messages=["Looking for clients in my niche, rates open this week"],
    )
    q = heuristic_qualify(p)
    assert q is not None
    assert q.bucket == BUCKET_OTHER
    assert q.source == "fallback"

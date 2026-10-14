from __future__ import annotations

from pathlib import Path

import pytest

from app.analytics import build_report
from app.store import Store
from app.ui.charts import CHART_KINDS, build_charts, try_chart
from tests.test_replies import _seed


@pytest.fixture
async def store(tmp_path: Path):
    db = Store(tmp_path / "charts.db")
    await db.init()
    return db


@pytest.mark.asyncio
async def test_build_charts_png_magic(store: Store):
    await _seed(store)
    report = await build_report(store, days=30)
    charts = build_charts(report, "30 дн")
    assert set(charts) == set(CHART_KINDS)
    for kind, png in charts.items():
        assert png[:8] == b"\x89PNG\r\n\x1a\n", kind
        assert len(png) > 500, kind


@pytest.mark.asyncio
async def test_empty_report_still_draws(store: Store):
    report = await build_report(store, days=7)
    png = try_chart("dashboard", report, "7 дн")
    assert png and png[:4] == b"\x89PNG"
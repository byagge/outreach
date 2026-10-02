from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery

from app.analytics import build_report
from app.bot.keyboards import MenuCB, stats_kb
from app.bot.render import safe_edit
from app.context import ctx
from app.ui import stats_screens as ui
from app.utils.report import build_report_xlsx

router = Router()

DIGEST_HOURS = [-1, 9, 12, 18, 21]


async def _digest_hour() -> int:
    raw = await ctx.store.get_setting("daily_report_hour", "-1")
    try:
        return int(raw)
    except ValueError:
        return -1


async def _show(query: CallbackQuery, view: str, idx: int) -> None:
    idx = max(0, min(idx, len(ui.PERIODS) - 1))
    label = ui.period_label(idx)
    report = await build_report(ctx.store, days=ui.period_days(idx))
    if view == "st":
        text = ui.overview_html(report, label)
    elif view == "st_txt":
        text = ui.breakdown_html("Офферы", report["dims"]["text"], label, "mega")
    elif view == "st_acc":
        text = ui.breakdown_html("Аккаунты", report["dims"]["account"], label, "user")
    elif view == "st_cmp":
        text = ui.compare_html(report, label, "campaign")
    elif view == "st_tm":
        text = ui.time_html(report, label)
    else:
        text = ui.errors_html(report, label)
    await safe_edit(query, text, stats_kb(view, idx, await _digest_hour()))


@router.callback_query(
    MenuCB.filter(F.a.in_({"st", "st_txt", "st_acc", "st_cmp", "st_tm", "st_err"}))
)
async def cb_stats(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    await _show(query, callback_data.a, callback_data.i)


@router.callback_query(MenuCB.filter(F.a == "st_xl"))
async def cb_stats_xlsx(query: CallbackQuery, callback_data: MenuCB) -> None:
    idx = max(0, min(callback_data.i, len(ui.PERIODS) - 1))
    await query.answer("Собираю отчёт…")
    data, _ = await build_report_xlsx(ctx.store, days=ui.period_days(idx))
    name = f"outreach_report_{ui.period_label(idx).replace(' ', '_')}.xlsx"
    await query.message.answer_document(
        BufferedInputFile(data, filename=name),
        caption=f"Отчёт · {ui.period_label(idx)}",
    )


@router.callback_query(MenuCB.filter(F.a == "st_dg"))
async def cb_stats_digest(query: CallbackQuery, callback_data: MenuCB) -> None:
    cur = await _digest_hour()
    nxt = DIGEST_HOURS[(DIGEST_HOURS.index(cur) + 1) % len(DIGEST_HOURS)] if cur in DIGEST_HOURS else 9
    await ctx.store.set_setting("daily_report_hour", str(nxt))
    await query.answer("Дайджест выключен" if nxt < 0 else f"Ежедневный отчёт в {nxt:02d}:00")
    await _show(query, "st", callback_data.i)

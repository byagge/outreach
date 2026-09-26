from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    DisabledButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.models import Account, Campaign, ContactBase, Proxy, TextVariant
from app.ui.emoji import icon_id

BTN_PANEL = "Панель"
BTN_CANCEL = "Отмена"
BTN_HOME = "В меню"


class MenuCB(CallbackData, prefix="m"):
    a: str
    i: int = 0
    p: int = 0


def _kbtn(text: str, icon: str) -> KeyboardButton:
    return KeyboardButton(text=text, icon_custom_emoji_id=icon_id(icon))


def panel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[_kbtn(BTN_PANEL, "cube")]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Панель…",
    )


def input_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[_kbtn(BTN_CANCEL, "block")]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Ввод или Отмена",
    )


def ib(text: str, a: str, i: int = 0, p: int = 0, *, icon: str = "cube") -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=MenuCB(a=a, i=i, p=p).pack(),
        icon_custom_emoji_id=icon_id(icon),
    )


def _cb(text: str, data: MenuCB, icon: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=data.pack(),
        icon_custom_emoji_id=icon_id(icon),
    )


def _off(text: str, icon: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        icon_custom_emoji_id=icon_id(icon),
        disabled=DisabledButton(),
    )


def home_row() -> list[InlineKeyboardButton]:
    return [ib(BTN_HOME, "home", icon="home")]


def nav_row(action: str, page: int, total_pages: int) -> list[InlineKeyboardButton]:
    prev = ib("Назад", action, p=page - 1, icon="down") if page > 0 else _off("Назад", "block")
    nxt = (
        ib("Вперёд", action, p=page + 1, icon="up")
        if page + 1 < total_pages
        else _off("Вперёд", "block")
    )
    return [prev, ib(f"{page + 1}/{total_pages}", action, p=page, icon="stack"), nxt]


def main_menu(running: bool = False) -> InlineKeyboardMarkup:
    start = ib("Стоп", "run_stop", icon="down") if running else ib("Старт", "run_go", icon="up")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [start, ib("Базы", "bases", icon="users")],
            [ib("Офферы", "texts", icon="mega"), ib("Аккаунты", "accounts", icon="user")],
            [ib("Прокси", "proxies", icon="shield"), ib("Настройки", "settings", icon="hammer")],
            [ib("Сбор базы", "collect", icon="search"), ib("Кампании", "camps", icon="folder")],
            [ib("История", "history", icon="chart"), ib("Инфо", "info", icon="info")],
        ]
    )


def accounts_kb(accounts: list[Account], page: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[ib("Добавить session", "acc_add", icon="inbox")]]
    chunk = accounts[page * 8 : page * 8 + 8]
    for acc in chunk:
        icon = {"running": "up", "paused": "clock", "error": "warn", "done": "check"}.get(
            acc.status, "user"
        )
        rows.append([ib(acc.label, "acc", acc.id, icon=icon)])
    total_pages = max(1, (len(accounts) + 7) // 8)
    if total_pages > 1:
        rows.append(nav_row("accounts", page, total_pages))
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_kb(acc: Account) -> InlineKeyboardMarkup:
    asg = (
        ib("Снять с рассылки", "acc_asg", acc.id, icon="block")
        if acc.assigned
        else ib("Назначить", "acc_asg", acc.id, icon="check")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [asg],
            [
                ib("Рабочие часы", "acc_wh", acc.id, icon="clock"),
                ib("Интервал", "acc_dly", acc.id, icon="term"),
            ],
            [ib("Не отправлять", "acc_blk", acc.id, icon="block")],
            [ib("Telethon session", "acc_tl", acc.id, icon="lock")],
            [
                ib("Переименовать", "acc_ren", acc.id, icon="hammer"),
                ib("Удалить", "acc_del", acc.id, icon="warn"),
            ],
            [ib("Аккаунты", "accounts", icon="user")],
            home_row(),
        ]
    )


def confirm_kb(yes: MenuCB, no: MenuCB, yes_text: str = "Запустить") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_cb(yes_text, yes, "check"), _cb(BTN_CANCEL, no, "block")],
            home_row(),
        ]
    )


def proxies_kb(proxies: list[Proxy], page: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [ib("Добавить прокси", "px_add", icon="inbox")],
        [ib("Перераздать по аккаунтам", "px_rebal", icon="robot")],
    ]
    chunk = proxies[page * 8 : page * 8 + 8]
    for p in chunk:
        icon = "check" if p.status == "ok" else "warn"
        rows.append([ib(f"{p.scheme} {p.host}:{p.port}", "px", p.id, icon=icon)])
    total_pages = max(1, (len(proxies) + 7) // 8)
    if total_pages > 1:
        rows.append(nav_row("proxies", page, total_pages))
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_kb(
    proxy: Proxy,
    accounts: list[Account] | None = None,
    bound_ids: set[int] | None = None,
) -> InlineKeyboardMarkup:
    bound_ids = bound_ids or set()
    rows: list[list[InlineKeyboardButton]] = [
        [ib("Проверить", "px_chk", proxy.id, icon="search")],
    ]
    for acc in (accounts or [])[:8]:
        bound = acc.id in bound_ids
        rows.append(
            [
                ib(
                    f"{'✓' if bound else '·'} {acc.label[:20]}",
                    "px_bind",
                    proxy.id,
                    p=acc.id,
                    icon="check" if bound else "user",
                )
            ]
        )
    rows.extend(
        [
            [ib("Удалить", "px_del", proxy.id, icon="warn")],
            [ib("Прокси", "proxies", icon="shield")],
            home_row(),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contacts_kb(n: int, page: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [ib("Загрузить базу", "ct_add", icon="inbox")],
        [
            ib("Докинуть ещё", "ct_add", icon="up"),
            ib("Ошибки в pending", "ct_retry", icon="clock"),
        ],
        [ib("Очистить базу", "ct_clear", icon="warn")],
    ]
    total_pages = max(1, (max(n, 1) + 7) // 8)
    if total_pages > 1:
        rows.append(nav_row("contacts", page, total_pages))
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def texts_kb(items: list[TextVariant], page: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[ib("Добавить вариант", "tx_add", icon="inbox")]]
    chunk = items[page * 8 : page * 8 + 8]
    for item in chunk:
        title = (item.title or f"вариант #{item.id}")[:28]
        icon = "mega" if item.enabled else "block"
        rows.append([ib(title, "tx", item.id, icon=icon)])
    total_pages = max(1, (len(items) + 7) // 8)
    if total_pages > 1:
        rows.append(nav_row("texts", page, total_pages))
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def text_kb(item: TextVariant) -> InlineKeyboardMarkup:
    toggle = (
        ib("Выключить", "tx_on", item.id, icon="block")
        if item.enabled
        else ib("Включить", "tx_on", item.id, icon="check")
    )
    rows: list[list[InlineKeyboardButton]] = [
        [toggle],
        [
            ib("Изменить текст", "tx_edit", item.id, icon="hammer"),
            ib("Название", "tx_ren", item.id, icon="bookmark"),
        ],
    ]
    if item.photo_path:
        rows.append([ib("Убрать фото", "tx_nophoto", item.id, icon="block")])
    rows.extend(
        [
            [ib("Удалить", "tx_del", item.id, icon="warn")],
            [ib("Тексты", "texts", icon="mega")],
            home_row(),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def run_kb(accounts: list[Account], running: bool) -> InlineKeyboardMarkup:
    start = (
        ib("Стоп", "run_stop", icon="down")
        if running
        else ib("Запустить", "run_go", icon="up")
    )
    rows: list[list[InlineKeyboardButton]] = [[start]]
    for acc in accounts[:12]:
        icon = "check" if acc.assigned else "block"
        rows.append([ib(acc.label, "run_asg", acc.id, icon=icon)])
    rows.append([ib("Настройки", "settings", icon="hammer")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bases_kb(bases: list[ContactBase], page: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[ib("Новая база", "base_add", icon="inbox")]]
    chunk = bases[page * 8 : page * 8 + 8]
    for base in chunk:
        if base.isolated:
            icon = "folder"
            prefix = "⊕ "
        else:
            icon = "check" if base.enabled else "block"
            prefix = ""
        rows.append([ib(f"{prefix}{base.name[:26]}", "base", base.id, icon=icon)])
    total_pages = max(1, (len(bases) + 7) // 8)
    if total_pages > 1:
        rows.append(nav_row("bases", page, total_pages))
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def base_kb(base: ContactBase, total: int, page: int = 0) -> InlineKeyboardMarkup:
    toggle = ib("Выключить базу", "base_on", base.id, icon="block") if base.enabled else ib(
        "Включить базу", "base_on", base.id, icon="check"
    )
    rows = [
        [toggle],
        [ib("Загрузить", "base_imp", base.id, icon="inbox"), ib("Экспорт", "base_exp", base.id, icon="up")],
    ]
    if base.isolated:
        rows.append([ib("Назначить в кампанию", "asg_camp", base.id, icon="check")])
    else:
        rows.append([ib("Итоговая из этой базы", "col_final", base.id, icon="check")])
    rows.append([ib("Удалить базу", "base_del", base.id, icon="warn")])
    total_pages = max(1, (max(total, 1) + 7) // 8)
    if total_pages > 1:
        prev = (
            ib("Назад", "base", base.id, p=page - 1, icon="down")
            if page > 0
            else _off("Назад", "block")
        )
        nxt = (
            ib("Вперёд", "base", base.id, p=page + 1, icon="up")
            if page + 1 < total_pages
            else _off("Вперёд", "block")
        )
        rows.append([prev, ib(f"{page + 1}/{total_pages}", "base", base.id, p=page, icon="stack"), nxt])
    rows.extend([[ib("Все базы", "bases", icon="users")], home_row()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def collect_kb(accounts: list[Account] | None = None, running: bool = False) -> InlineKeyboardMarkup:
    n = len([a for a in (accounts or []) if a.has_telethon])
    rows: list[list[InlineKeyboardButton]] = []
    if running:
        rows.append([ib("Стоп сбора (сохранить)", "col_stop", icon="down")])
    rows.extend(
        [
            [ib("Все участники чата", "col_mode", 0, icon="users")],
            [ib("Только писавшие", "col_mode", 1, icon="search")],
            [ib("Кому писали (ЛС)", "col_dm", 0, icon="mega")],
            [ib("Кто отвечал (ЛС)", "col_dm", 1, icon="term")],
            [ib("Отдельно", "col_sep", icon="folder")],
            [ib("Итоговая база для рассылки", "col_final", icon="check")],
            [ib("История сбора / скачать", "col_hist", icon="chart")],
            [ib(f"Настройки сбора · акк. {n}", "col_set", icon="hammer")],
            home_row(),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def collect_separate_kb() -> InlineKeyboardMarkup:
    """Тот же сбор, но база не попадает в основную очередь."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("Все участники чата", "col_mode", 0, icon="users")],
            [ib("Только писавшие", "col_mode", 1, icon="search")],
            [ib("Кому писали (ЛС)", "col_dm", 0, icon="mega")],
            [ib("Кто отвечал (ЛС)", "col_dm", 1, icon="term")],
            [ib("Назад к сбору", "collect", icon="down")],
            home_row(),
        ]
    )


def collect_done_kb(base_id: int, *, separate: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [ib("Экспорт txt/csv/xlsx", "col_exp", base_id, icon="up")],
    ]
    if separate:
        rows.append([ib("Назначить в кампанию", "asg_camp", base_id, icon="check")])
    rows.append([ib("Открыть базу", "base", base_id, icon="users")])
    rows.append([ib("К сбору", "collect", icon="search")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def assign_campaign_kb(campaigns: list[Campaign], base_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for c in campaigns:
        icon = "crown" if c.is_main else "folder"
        rows.append([ib(c.name[:28], "asg_do", base_id, p=c.id, icon=icon)])
    rows.append([ib("Назад", "col_exp", base_id, icon="down")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaigns_kb(campaigns: list[Campaign], page: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[ib("Новая кампания", "camp_add", icon="inbox")]]
    chunk = campaigns[page * 8 : page * 8 + 8]
    for c in chunk:
        from app.jobs.runtime import runtime

        if c.is_main:
            running = runtime.is_running("outreach", 0)
            icon = "up" if running else "crown"
        else:
            running = runtime.is_running("campaign", c.id)
            icon = "up" if running else "folder"
        rows.append([ib(c.name[:28], "camp", c.id, icon=icon)])
    total_pages = max(1, (len(campaigns) + 7) // 8)
    if total_pages > 1:
        rows.append(nav_row("camps", page, total_pages))
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_kb(camp: Campaign, running: bool) -> InlineKeyboardMarkup:
    if camp.is_main:
        start = (
            ib("Стоп основной", "run_stop", icon="down")
            if running
            else ib("Старт основной", "run_go", icon="up")
        )
        rows: list[list[InlineKeyboardButton]] = [
            [start],
            [ib("К рассылке", "run", icon="robot")],
            [ib("Все кампании", "camps", icon="folder")],
            home_row(),
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    start = (
        ib("Стоп", "camp_stop", camp.id, icon="down")
        if running
        else ib("Запустить", "camp_go", camp.id, icon="up")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [start],
            [
                ib("Базы", "camp_bases", camp.id, icon="users"),
                ib("Аккаунты", "camp_accs", camp.id, icon="user"),
            ],
            [ib("Офферы", "camp_txs", camp.id, icon="mega")],
            [
                ib("Переименовать", "camp_ren", camp.id, icon="hammer"),
                ib("Удалить", "camp_del", camp.id, icon="warn"),
            ],
            [ib("Все кампании", "camps", icon="folder")],
            home_row(),
        ]
    )


def campaign_pick_bases_kb(
    bases: list[ContactBase], selected: set[int], campaign_id: int, page: int = 0
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            ib("Все", "camp_ball", campaign_id, icon="check"),
            ib("Снять", "camp_bclr", campaign_id, icon="block"),
        ]
    ]
    chunk = bases[page * 8 : page * 8 + 8]
    for base in chunk:
        on = base.id in selected
        mark = "✓ " if on else "· "
        tag = "⊕ " if base.isolated else ""
        rows.append(
            [
                ib(
                    f"{mark}{tag}{base.name[:24]}",
                    "camp_tb",
                    campaign_id,
                    p=base.id,
                    icon="check" if on else "block",
                )
            ]
        )
    total_pages = max(1, (len(bases) + 7) // 8)
    if total_pages > 1:
        prev = (
            ib("Назад", "camp_bases", campaign_id, p=page - 1, icon="down")
            if page > 0
            else _off("Назад", "block")
        )
        nxt = (
            ib("Вперёд", "camp_bases", campaign_id, p=page + 1, icon="up")
            if page + 1 < total_pages
            else _off("Вперёд", "block")
        )
        rows.append(
            [prev, ib(f"{page + 1}/{total_pages}", "camp_bases", campaign_id, p=page, icon="stack"), nxt]
        )
    rows.append([ib("К кампании", "camp", campaign_id, icon="folder")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_pick_accounts_kb(
    accounts: list[Account], selected: set[int], campaign_id: int, page: int = 0
) -> InlineKeyboardMarkup:
    live = [a for a in accounts if a.has_telethon]
    rows: list[list[InlineKeyboardButton]] = [
        [
            ib("Все", "camp_aall", campaign_id, icon="check"),
            ib("Снять", "camp_aclr", campaign_id, icon="block"),
        ]
    ]
    chunk = live[page * 8 : page * 8 + 8]
    for acc in chunk:
        on = acc.id in selected
        mark = "✓ " if on else "· "
        rows.append(
            [
                ib(
                    f"{mark}{acc.label[:24]}",
                    "camp_ta",
                    campaign_id,
                    p=acc.id,
                    icon="check" if on else "block",
                )
            ]
        )
    total_pages = max(1, (len(live) + 7) // 8)
    if total_pages > 1:
        prev = (
            ib("Назад", "camp_accs", campaign_id, p=page - 1, icon="down")
            if page > 0
            else _off("Назад", "block")
        )
        nxt = (
            ib("Вперёд", "camp_accs", campaign_id, p=page + 1, icon="up")
            if page + 1 < total_pages
            else _off("Вперёд", "block")
        )
        rows.append(
            [prev, ib(f"{page + 1}/{total_pages}", "camp_accs", campaign_id, p=page, icon="stack"), nxt]
        )
    rows.append([ib("К кампании", "camp", campaign_id, icon="folder")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_pick_texts_kb(
    owned: list[TextVariant],
    shared: list[TextVariant],
    selected_shared: set[int],
    campaign_id: int,
    page: int = 0,
    *,
    mode: str = "owned",  # owned | share
) -> InlineKeyboardMarkup:
    """Офферы кампании: свои (owned) + прикрепление общих (share)."""
    rows: list[list[InlineKeyboardButton]] = []
    if mode == "share":
        rows.append(
            [
                ib("Все общие", "camp_tall", campaign_id, icon="check"),
                ib("Снять общие", "camp_tclr", campaign_id, icon="block"),
            ]
        )
        chunk = shared[page * 8 : page * 8 + 8]
        for item in chunk:
            on = item.id in selected_shared
            mark = "✓ " if on else "· "
            title = (item.title or f"#{item.id}")[:24]
            rows.append(
                [
                    ib(
                        f"{mark}{title}",
                        "camp_tt",
                        campaign_id,
                        p=item.id,
                        icon="check" if on else "block",
                    )
                ]
            )
        total_pages = max(1, (len(shared) + 7) // 8)
        if total_pages > 1:
            prev = (
                ib("Назад", "camp_tshare", campaign_id, p=page - 1, icon="down")
                if page > 0
                else _off("Назад", "block")
            )
            nxt = (
                ib("Вперёд", "camp_tshare", campaign_id, p=page + 1, icon="up")
                if page + 1 < total_pages
                else _off("Вперёд", "block")
            )
            rows.append(
                [
                    prev,
                    ib(f"{page + 1}/{total_pages}", "camp_tshare", campaign_id, p=page, icon="stack"),
                    nxt,
                ]
            )
        rows.append([ib("К офферам кампании", "camp_txs", campaign_id, icon="mega")])
        rows.append(home_row())
        return InlineKeyboardMarkup(inline_keyboard=rows)

    rows.append([ib("Добавить оффер", "camp_tx_add", campaign_id, icon="inbox")])
    chunk = owned[page * 8 : page * 8 + 8]
    for item in chunk:
        title = (item.title or f"#{item.id}")[:26]
        icon = "mega" if item.enabled else "block"
        rows.append([ib(f"⊕ {title}", "camp_tx", item.id, p=campaign_id, icon=icon)])
    total_pages = max(1, (len(owned) + 7) // 8)
    if total_pages > 1:
        prev = (
            ib("Назад", "camp_txs", campaign_id, p=page - 1, icon="down")
            if page > 0
            else _off("Назад", "block")
        )
        nxt = (
            ib("Вперёд", "camp_txs", campaign_id, p=page + 1, icon="up")
            if page + 1 < total_pages
            else _off("Вперёд", "block")
        )
        rows.append(
            [prev, ib(f"{page + 1}/{total_pages}", "camp_txs", campaign_id, p=page, icon="stack"), nxt]
        )
    rows.append([ib("Прикрепить из общих", "camp_tshare", campaign_id, icon="stack")])
    rows.append([ib("К кампании", "camp", campaign_id, icon="folder")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_text_kb(item: TextVariant, campaign_id: int) -> InlineKeyboardMarkup:
    toggle = (
        ib("Выключить", "camp_tx_on", item.id, p=campaign_id, icon="block")
        if item.enabled
        else ib("Включить", "camp_tx_on", item.id, p=campaign_id, icon="check")
    )
    rows: list[list[InlineKeyboardButton]] = [
        [toggle],
        [
            ib("Изменить текст", "camp_tx_edit", item.id, p=campaign_id, icon="hammer"),
            ib("Название", "camp_tx_ren", item.id, p=campaign_id, icon="bookmark"),
        ],
    ]
    if item.photo_path:
        rows.append(
            [ib("Убрать фото", "camp_tx_nophoto", item.id, p=campaign_id, icon="block")]
        )
    rows.extend(
        [
            [ib("Удалить", "camp_tx_del", item.id, p=campaign_id, icon="warn")],
            [ib("К офферам", "camp_txs", campaign_id, icon="mega")],
            home_row(),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def collect_running_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("Стоп — сохранить базу", "col_stop", icon="down")],
            home_row(),
        ]
    )


def collect_history_kb(runs, page: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for run in runs:
        src = "API" if run.source == "api" else "бот"
        title = (run.base_name or run.title or run.mode or run.kind)[:22]
        stop = "⏹" if run.stopped else ""
        rows.append(
            [
                ib(
                    f"#{run.id} {src} {title} ·{run.added}{stop}",
                    "col_run",
                    run.id,
                    icon="folder",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(ib("Назад", "col_hist", p=page - 1, icon="down"))
    if len(runs) >= 10:
        nav.append(ib("Ещё", "col_hist", p=page + 1, icon="up"))
    if nav:
        rows.append(nav)
    rows.append([ib("К сбору", "collect", icon="search")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def collect_run_kb(run) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if run.base_id:
        rows.append([ib("Скачать txt/csv/xlsx", "col_dl", run.id, icon="up")])
        rows.append([ib("Открыть базу", "base", run.base_id, icon="users")])
    rows.append([ib("К истории", "col_hist", icon="chart")])
    rows.append([ib("К сбору", "collect", icon="search")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def collect_accounts_kb(accounts: list[Account], mode_i: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    live = [a for a in accounts if a.has_telethon]
    for acc in live[:12]:
        rows.append([ib(acc.label[:28], "col_acc", acc.id, p=mode_i, icon="user")])
    if live:
        rows.append([ib("Любой доступный", "col_acc", 0, p=mode_i, icon="robot")])
    rows.append([ib("Назад", "collect", icon="down")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def collect_chat_accounts_kb(accounts: list[Account], mode_i: int) -> InlineKeyboardMarkup:
    """Выбор аккаунта для сбора из чата (приватный id работает только у участника)."""
    rows: list[list[InlineKeyboardButton]] = []
    live = [a for a in accounts if a.has_telethon]
    for acc in live[:12]:
        rows.append([ib(acc.label[:28], "col_chat_acc", acc.id, p=mode_i, icon="user")])
    if live:
        rows.append([ib("Все по очереди", "col_chat_acc", 0, p=mode_i, icon="robot")])
    rows.append([ib("Назад", "collect", icon="down")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def banwords_kb(
    words: list[str] | None = None,
    page: int = 0,
    banned_total: int = 0,
) -> InlineKeyboardMarkup:
    words = words or []
    per = 15
    total = len(words)
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    chunk = words[page * per : page * per + per]
    rows: list[list[InlineKeyboardButton]] = [
        [ib("Добавить банворды", "bw_add", icon="inbox")],
        [
            ib(f"Скачать слова ({total})", "bw_all", icon="up"),
            ib(f"Банбаза ({banned_total})", "bb_view", icon="block"),
        ],
    ]
    for i, word in enumerate(chunk):
        abs_i = page * per + i
        rows.append([ib(f"✕ {word[:28]}", "bw_del", abs_i, p=page, icon="block")])
    if pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(ib("«", "bw_page", p=page - 1, icon="down"))
        nav.append(ib(f"{page + 1}/{pages}", "bw_page", p=page, icon="stack"))
        if page + 1 < pages:
            nav.append(ib("»", "bw_page", p=page + 1, icon="up"))
        rows.append(nav)
    rows.append([ib("Назад к сбору", "collect", icon="search")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def banbase_kb(items, total: int, page: int = 0, per: int = 10) -> InlineKeyboardMarkup:
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    rows: list[list[InlineKeyboardButton]] = [
        [ib("Очистить всю банбазу", "bb_clr", icon="warn")],
    ]
    for item in items:
        label = (item.pretty or item.value)[:24]
        rows.append([ib(f"✕ #{item.id} {label}", "bb_del", item.id, p=page, icon="block")])
    if pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(ib("«", "bb_page", p=page - 1, icon="down"))
        nav.append(ib(f"{page + 1}/{pages}", "bb_page", p=page, icon="stack"))
        if page + 1 < pages:
            nav.append(ib("»", "bb_page", p=page + 1, icon="up"))
        rows.append(nav)
    rows.append([ib("К банвордам", "col_set", icon="hammer")])
    rows.append([ib("К сбору", "collect", icon="search")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("Интервал (аккаунт)", "s_delay", icon="clock")],
            [ib("Между аккаунтами", "s_between", icon="term")],
            [
                ib("Печатает", "s_type", icon="term"),
                ib("Офферы", "s_var", icon="stack"),
            ],
            [ib("Ротация прокси", "s_prot", icon="shield")],
            [ib("Режим 24/7", "s_cont", icon="robot")],
            home_row(),
        ]
    )


def history_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("Обновить", "history", icon="search")],
            home_row(),
        ]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[ib(BTN_CANCEL, "cancel", icon="block")], home_row()]
    )

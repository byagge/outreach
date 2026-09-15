from aiogram import Dispatcher

from app.bot.handlers import (
    accounts_router,
    banwords_router,
    bases_router,
    collect_router,
    contacts_router,
    history_router,
    menu_router,
    proxies_router,
    run_router,
    settings_router,
    texts_router,
)


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(menu_router)
    dp.include_router(accounts_router)
    dp.include_router(proxies_router)
    dp.include_router(bases_router)
    dp.include_router(contacts_router)
    dp.include_router(collect_router)
    dp.include_router(banwords_router)
    dp.include_router(texts_router)
    dp.include_router(run_router)
    dp.include_router(settings_router)
    dp.include_router(history_router)

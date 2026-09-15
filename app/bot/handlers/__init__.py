from app.bot.handlers.accounts import router as accounts_router
from app.bot.handlers.banwords import router as banwords_router
from app.bot.handlers.bases import router as bases_router
from app.bot.handlers.collect import router as collect_router
from app.bot.handlers.contacts import router as contacts_router
from app.bot.handlers.history import router as history_router
from app.bot.handlers.menu import router as menu_router
from app.bot.handlers.proxies import router as proxies_router
from app.bot.handlers.run import router as run_router
from app.bot.handlers.settings import router as settings_router
from app.bot.handlers.texts import router as texts_router

__all__ = [
    "accounts_router",
    "banwords_router",
    "bases_router",
    "collect_router",
    "contacts_router",
    "history_router",
    "menu_router",
    "proxies_router",
    "run_router",
    "settings_router",
    "texts_router",
]

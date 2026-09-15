from aiogram.fsm.state import State, StatesGroup


class AddAccount(StatesGroup):
    session = State()
    label = State()


class AccountFile(StatesGroup):
    telethon = State()
    rename = State()


class AddProxies(StatesGroup):
    blob = State()


class AddContacts(StatesGroup):
    file = State()


class AddText(StatesGroup):
    message = State()


class EditSettings(StatesGroup):
    delay = State()
    between_delay = State()
    proxy_every = State()


class AddBase(StatesGroup):
    name = State()
    file = State()


class AccountSettings(StatesGroup):
    work_hours = State()
    delay = State()
    blocklist = State()


class CollectChat(StatesGroup):
    chat = State()


class Banwords(StatesGroup):
    add = State()

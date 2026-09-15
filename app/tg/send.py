from __future__ import annotations

import asyncio
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.contacts import DeleteContactsRequest, ImportContactsRequest
from telethon.tl.types import InputPhoneContact, User

from app.models import Contact, TextVariant
from app.utils.entities import entities_loads, to_telethon_entities


async def resolve_peer(client: TelegramClient, contact: Contact):
    if contact.kind == "username":
        name = contact.value.lstrip("@")
        return await client.get_entity(name)
    if contact.kind == "user_id":
        return await client.get_entity(int(contact.value))
    if contact.kind == "phone":
        phone = contact.value if contact.value.startswith("+") else f"+{contact.value}"
        first = (contact.display or contact.extra or "User")[:40] or "User"
        result = await client(
            ImportContactsRequest(
                [
                    InputPhoneContact(
                        client_id=0,
                        phone=phone,
                        first_name=first,
                        last_name="",
                    )
                ]
            )
        )
        users = list(result.users or [])
        if not users:
            raise RuntimeError("Номер не найден в Telegram")
        user = users[0]
        try:
            await client(DeleteContactsRequest(id=[user]))
        except Exception:
            pass
        return user
    raise RuntimeError(f"Неизвестный тип контакта: {contact.kind}")


async def send_human(
    client: TelegramClient,
    contact: Contact,
    variant: TextVariant,
    *,
    typing_seconds: float,
    pre_pause: float,
) -> None:
    entity = await resolve_peer(client, contact)
    if isinstance(entity, User) and getattr(entity, "bot", False):
        raise RuntimeError("Это бот — пропускаю")
    if isinstance(entity, User) and getattr(entity, "deleted", False):
        raise RuntimeError("Аккаунт удалён")

    if pre_pause > 0:
        await asyncio.sleep(pre_pause)

    photo = (variant.photo_path or "").strip()

    async with client.action(entity, "typing"):
        await asyncio.sleep(max(0.4, typing_seconds))

    entities = to_telethon_entities(entities_loads(variant.entities_json))
    text = variant.text or ""
    if photo and Path(photo).exists():
        await client.send_file(
            entity,
            photo,
            caption=text or None,
            formatting_entities=entities or None,
        )
        return
    if not text.strip():
        raise RuntimeError("Пустой оффер — пропускаю")
    await client.send_message(
        entity,
        text,
        formatting_entities=entities or None,
        link_preview=False,
    )

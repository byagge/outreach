"""Хранилище входящих ответов и наших ответов на них (mixin для Store)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.models import Reply, ReplyAnswer


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_REPLY_SELECT = (
    "SELECT r.*, COALESCE(a.label,'') AS account_label, "
    "COALESCE(NULLIF(c.display,''), c.value, '') AS contact_pretty, "
    "COALESCE(NULLIF(t.title,''), SUBSTR(t.text,1,40), '') AS text_title "
    "FROM replies r "
    "LEFT JOIN accounts a ON a.id=r.account_id "
    "LEFT JOIN contacts c ON c.id=r.contact_id "
    "LEFT JOIN texts t ON t.id=r.text_id "
)


def _reply(row: aiosqlite.Row) -> Reply:
    keys = row.keys()

    def g(name: str, default: Any = "") -> Any:
        return row[name] if name in keys else default

    return Reply(
        id=row["id"],
        account_id=row["account_id"],
        contact_id=row["contact_id"],
        send_id=row["send_id"],
        text_id=row["text_id"],
        peer_id=int(row["peer_id"]),
        tg_msg_id=int(row["tg_msg_id"]),
        text=row["text"] or "",
        media=row["media"] or "",
        from_name=row["from_name"] or "",
        from_username=row["from_username"] or "",
        has_link=int(row["has_link"] or 0),
        valid=int(row["valid"] or 0),
        status=row["status"] or "new",
        notified=int(row["notified"] or 0),
        campaign_id=row["campaign_id"],
        campaign_name=row["campaign_name"] or "",
        msg_date=row["msg_date"] or "",
        created_at=row["created_at"] or "",
        answered_at=row["answered_at"] or "",
        account_label=g("account_label") or "",
        contact_pretty=g("contact_pretty") or "",
        text_title=g("text_title") or "",
    )


def _answer(row: aiosqlite.Row) -> ReplyAnswer:
    return ReplyAnswer(
        id=row["id"],
        reply_id=row["reply_id"],
        account_id=row["account_id"],
        peer_id=int(row["peer_id"]),
        text=row["text"] or "",
        tg_msg_id=row["tg_msg_id"],
        source=row["source"] or "bot",
        created_at=row["created_at"] or "",
    )


class RepliesMixin:
    """Требует self._connect() из Store."""

    async def replies_tracking_since(self) -> str:
        async with self._connect() as db:  # type: ignore[attr-defined]
            cur = await db.execute("SELECT value FROM settings WHERE key='replies_tracking_since'")
            row = await cur.fetchone()
            return row[0] if row else ""

    async def reply_contact_index(self, account_id: int) -> list[dict[str, Any]]:
        """Контакты, которым аккаунт успешно писал: по ним ищем ответы."""
        async with self._connect() as db:  # type: ignore[attr-defined]
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT s.id AS send_id, s.contact_id, s.peer_id, s.message_id, "
                "s.created_at AS sent_at, s.text_id, s.campaign_id, s.campaign_name, "
                "c.kind, c.value, c.display, c.extra "
                "FROM sends s JOIN contacts c ON c.id=s.contact_id "
                "WHERE s.account_id=? AND s.status='sent' "
                "AND s.id=(SELECT MIN(s2.id) FROM sends s2 "
                "          WHERE s2.contact_id=s.contact_id AND s2.status='sent')",
                (account_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def link_send_peer(self, account_id: int, contact_id: int, peer_id: int) -> None:
        async with self._connect() as db:  # type: ignore[attr-defined]
            await db.execute(
                "UPDATE sends SET peer_id=? WHERE account_id=? AND contact_id=? AND peer_id IS NULL",
                (peer_id, account_id, contact_id),
            )
            await db.commit()

    async def add_reply(
        self,
        *,
        account_id: int,
        peer_id: int,
        tg_msg_id: int,
        contact_id: int | None,
        send_id: int | None,
        text_id: int | None,
        campaign_id: int | None,
        campaign_name: str,
        text: str,
        media: str,
        from_name: str,
        from_username: str,
        has_link: bool,
        msg_date: str,
        notified: bool = False,
    ) -> Reply | None:
        """Сохранить входящее. None — такое сообщение уже было (дедуп)."""
        async with self._connect() as db:  # type: ignore[attr-defined]
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "INSERT OR IGNORE INTO replies(account_id, contact_id, send_id, text_id, "
                "campaign_id, campaign_name, peer_id, tg_msg_id, from_name, from_username, "
                "text, media, has_link, valid, status, notified, msg_date, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    contact_id,
                    send_id,
                    text_id,
                    campaign_id,
                    campaign_name or "",
                    peer_id,
                    tg_msg_id,
                    from_name or "",
                    from_username or "",
                    text or "",
                    media or "",
                    int(has_link),
                    0 if has_link else 1,
                    "new" if not has_link else "redirect",
                    int(notified or has_link),
                    msg_date,
                    _utcnow(),
                ),
            )
            await db.commit()
            if int(cur.rowcount or 0) == 0:
                return None
            cur = await db.execute(_REPLY_SELECT + "WHERE r.id=?", (cur.lastrowid,))
            row = await cur.fetchone()
        return _reply(row) if row else None

    async def get_reply(self, reply_id: int) -> Reply | None:
        async with self._connect() as db:  # type: ignore[attr-defined]
            db.row_factory = aiosqlite.Row
            cur = await db.execute(_REPLY_SELECT + "WHERE r.id=?", (reply_id,))
            row = await cur.fetchone()
        return _reply(row) if row else None

    async def list_replies(
        self,
        *,
        status: str | None = None,
        valid: bool | None = True,
        account_id: int | None = None,
        campaign_id: int | None = None,
        text_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
        notified: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Reply]:
        where, args = self._reply_filters(
            status, valid, account_id, campaign_id, text_id, since, until, notified
        )
        async with self._connect() as db:  # type: ignore[attr-defined]
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                _REPLY_SELECT + where + " ORDER BY r.msg_date DESC, r.id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            )
            rows = await cur.fetchall()
        return [_reply(r) for r in rows]

    async def count_replies(
        self,
        *,
        status: str | None = None,
        valid: bool | None = True,
        account_id: int | None = None,
        campaign_id: int | None = None,
        text_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> int:
        where, args = self._reply_filters(
            status, valid, account_id, campaign_id, text_id, since, until
        )
        async with self._connect() as db:  # type: ignore[attr-defined]
            cur = await db.execute("SELECT COUNT(*) FROM replies r " + where, args)
            row = await cur.fetchone()
        return int(row[0] if row else 0)

    @staticmethod
    def _reply_filters(
        status, valid, account_id, campaign_id, text_id, since, until, notified=None
    ) -> tuple[str, list[Any]]:
        conds: list[str] = []
        args: list[Any] = []
        if notified is not None:
            conds.append("r.notified=?")
            args.append(1 if notified else 0)
        if valid is not None:
            conds.append("r.valid=?")
            args.append(1 if valid else 0)
        if status:
            conds.append("r.status=?")
            args.append(status)
        if account_id is not None:
            conds.append("r.account_id=?")
            args.append(account_id)
        if campaign_id is not None:
            conds.append("r.campaign_id=?")
            args.append(campaign_id)
        if text_id is not None:
            conds.append("r.text_id=?")
            args.append(text_id)
        if since:
            conds.append("r.msg_date>=?")
            args.append(since)
        if until:
            conds.append("r.msg_date<?")
            args.append(until)
        return ("WHERE " + " AND ".join(conds) if conds else ""), args

    async def pending_notifications(self, limit: int = 50) -> list[Reply]:
        """Валидные ответы, о которых ещё не сообщили (старые вперёд)."""
        items = await self.list_replies(valid=True, notified=False, status="new", limit=limit)
        return list(reversed(items))

    async def mark_reply_notified(self, reply_id: int) -> None:
        async with self._connect() as db:  # type: ignore[attr-defined]
            await db.execute("UPDATE replies SET notified=1 WHERE id=?", (reply_id,))
            await db.commit()

    async def set_reply_status(self, reply_id: int, status: str) -> Reply | None:
        """ignored — «отработано без ответа»; new — вернуть в очередь."""
        async with self._connect() as db:  # type: ignore[attr-defined]
            await db.execute("UPDATE replies SET status=? WHERE id=? AND valid=1", (status, reply_id))
            await db.commit()
        return await self.get_reply(reply_id)

    async def add_answer(
        self,
        reply: Reply,
        text: str,
        *,
        tg_msg_id: int | None,
        source: str = "bot",
    ) -> ReplyAnswer:
        now = _utcnow()
        async with self._connect() as db:  # type: ignore[attr-defined]
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "INSERT INTO reply_answers(reply_id, account_id, peer_id, text, tg_msg_id, source, "
                "created_at) VALUES(?,?,?,?,?,?,?)",
                (reply.id, reply.account_id, reply.peer_id, text, tg_msg_id, source, now),
            )
            answer_id = cur.lastrowid
            # весь диалог с этим человеком считаем отработанным
            await db.execute(
                "UPDATE replies SET status='answered', answered_at=? "
                "WHERE account_id IS ? AND peer_id=? AND valid=1 AND status IN ('new','ignored')",
                (now, reply.account_id, reply.peer_id),
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM reply_answers WHERE id=?", (answer_id,))
            row = await cur.fetchone()
        return _answer(row)

    async def list_answers(self, reply_id: int) -> list[ReplyAnswer]:
        async with self._connect() as db:  # type: ignore[attr-defined]
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM reply_answers WHERE reply_id=? ORDER BY id", (reply_id,)
            )
            return [_answer(r) for r in await cur.fetchall()]

    async def reply_thread(self, reply: Reply, limit: int = 12) -> list[dict[str, Any]]:
        """Диалог с человеком: его валидные ответы + наши ответы, по времени."""
        async with self._connect() as db:  # type: ignore[attr-defined]
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT msg_date AS at, text, media, 'in' AS dir FROM replies "
                "WHERE account_id IS ? AND peer_id=? AND valid=1",
                (reply.account_id, reply.peer_id),
            )
            items = [dict(r) for r in await cur.fetchall()]
            cur = await db.execute(
                "SELECT created_at AS at, text, '' AS media, 'out' AS dir FROM reply_answers "
                "WHERE account_id IS ? AND peer_id=?",
                (reply.account_id, reply.peer_id),
            )
            items += [dict(r) for r in await cur.fetchall()]
        items.sort(key=lambda x: x["at"])
        return items[-limit:]

    async def unanswered_replies_count(self) -> int:
        return await self.count_replies(status="new", valid=True)

    async def get_contact_row(self, contact_id: int):
        """Contact по id (для резолва получателя при ответе)."""
        from app.store import _contact

        async with self._connect() as db:  # type: ignore[attr-defined]
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM contacts WHERE id=?", (contact_id,))
            row = await cur.fetchone()
        return _contact(row) if row else None

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.ai.contacts import Classified
from app.config import DB_PATH, ensure_dirs
from app.models import (
    Account,
    BanContact,
    BlockEntry,
    Contact,
    ContactBase,
    Counts,
    Job,
    JobLog,
    OutreachSettings,
    Proxy,
    SendRow,
    TextVariant,
)
from app.utils.proxy import ParsedProxy

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    user_id INTEGER,
    telethon_session TEXT NOT NULL DEFAULT '',
    proxy_cursor INTEGER NOT NULL DEFAULT 0,
    assigned INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'idle',
    last_error TEXT NOT NULL DEFAULT '',
    pause_until TEXT NOT NULL DEFAULT '',
    sent_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw TEXT NOT NULL,
    scheme TEXT NOT NULL DEFAULT 'socks5',
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(scheme, host, port, username)
);

CREATE TABLE IF NOT EXISTS account_proxies (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    proxy_id INTEGER NOT NULL REFERENCES proxies(id) ON DELETE CASCADE,
    PRIMARY KEY (account_id, proxy_id)
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    display TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT NOT NULL DEFAULT '',
    sent_at TEXT NOT NULL DEFAULT '',
    account_id INTEGER,
    text_id INTEGER,
    base_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(kind, value)
);

CREATE TABLE IF NOT EXISTS texts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    entities_json TEXT NOT NULL DEFAULT '[]',
    photo_path TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER,
    account_id INTEGER,
    text_id INTEGER,
    proxy_id INTEGER,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    report TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(kind, value)
);

CREATE TABLE IF NOT EXISTS banwords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ban_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    display TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    source_base_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(kind, value)
);
"""

DEFAULT_SETTINGS = {
    "delay_min": "60",
    "delay_max": "120",
    "between_delay_min": "0",
    "between_delay_max": "0",
    "typing": "1",
    "rotate_proxy_every": "1",
    "variant_mode": "random",
    "continuous": "1",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _account(row: aiosqlite.Row) -> Account:
    keys = row.keys()
    delay_min = row["delay_min"] if "delay_min" in keys else None
    delay_max = row["delay_max"] if "delay_max" in keys else None
    return Account(
        id=row["id"],
        label=row["label"],
        phone=row["phone"] or "",
        username=row["username"] or "",
        user_id=row["user_id"],
        telethon_session=row["telethon_session"] or "",
        proxy_cursor=int(row["proxy_cursor"] or 0),
        assigned=int(row["assigned"] or 0),
        status=row["status"] or "idle",
        last_error=row["last_error"] or "",
        pause_until=row["pause_until"] or "",
        sent_count=int(row["sent_count"] or 0),
        work_start=row["work_start"] if "work_start" in keys else "",
        work_end=row["work_end"] if "work_end" in keys else "",
        delay_min=int(delay_min) if delay_min is not None else None,
        delay_max=int(delay_max) if delay_max is not None else None,
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _proxy(row: aiosqlite.Row) -> Proxy:
    return Proxy(
        id=row["id"],
        raw=row["raw"] or "",
        scheme=row["scheme"] or "socks5",
        host=row["host"] or "",
        port=int(row["port"] or 0),
        username=row["username"] or "",
        password=row["password"] or "",
        status=row["status"] or "ok",
        last_error=row["last_error"] or "",
        created_at=row["created_at"] or "",
    )


def _contact(row: aiosqlite.Row) -> Contact:
    keys = row.keys()
    return Contact(
        id=row["id"],
        raw=row["raw"] or "",
        kind=row["kind"] or "unknown",
        value=row["value"] or "",
        display=row["display"] or "",
        extra=row["extra"] or "",
        status=row["status"] or "pending",
        last_error=row["last_error"] or "",
        sent_at=row["sent_at"] or "",
        account_id=row["account_id"],
        text_id=row["text_id"],
        base_id=row["base_id"] if "base_id" in keys else None,
        created_at=row["created_at"] or "",
    )


def _base(row: aiosqlite.Row) -> ContactBase:
    return ContactBase(
        id=row["id"],
        name=row["name"] or "",
        enabled=int(row["enabled"] or 0),
        created_at=row["created_at"] or "",
    )


def _block(row: aiosqlite.Row) -> BlockEntry:
    return BlockEntry(
        id=row["id"],
        kind=row["kind"] or "",
        value=row["value"] or "",
        note=row["note"] or "",
        created_at=row["created_at"] or "",
    )


def _ban_contact(row: aiosqlite.Row) -> BanContact:
    return BanContact(
        id=row["id"],
        kind=row["kind"] or "",
        value=row["value"] or "",
        display=row["display"] or "",
        reason=row["reason"] or "",
        source_base_id=row["source_base_id"],
        created_at=row["created_at"] or "",
    )


def _text(row: aiosqlite.Row) -> TextVariant:
    return TextVariant(
        id=row["id"],
        title=row["title"] or "",
        text=row["text"] or "",
        entities_json=row["entities_json"] or "[]",
        photo_path=row["photo_path"] or "",
        enabled=int(row["enabled"] or 0),
        created_at=row["created_at"] or "",
    )


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or DB_PATH)
        self._claim_lock = asyncio.Lock()

    async def init(self) -> None:
        ensure_dirs()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.execute("PRAGMA foreign_keys = ON")
            await self._migrate(db)
            for key, value in DEFAULT_SETTINGS.items():
                await db.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                    (key, value),
                )
            await db.commit()

    async def _migrate(self, db: aiosqlite.Connection) -> None:
        async def _cols(table: str) -> set[str]:
            cur = await db.execute(f"PRAGMA table_info({table})")
            return {r[1] for r in await cur.fetchall()}

        acc_cols = await _cols("accounts")
        for col, ddl in (
            ("work_start", "ALTER TABLE accounts ADD COLUMN work_start TEXT NOT NULL DEFAULT ''"),
            ("work_end", "ALTER TABLE accounts ADD COLUMN work_end TEXT NOT NULL DEFAULT ''"),
            ("delay_min", "ALTER TABLE accounts ADD COLUMN delay_min INTEGER"),
            ("delay_max", "ALTER TABLE accounts ADD COLUMN delay_max INTEGER"),
        ):
            if col not in acc_cols:
                await db.execute(ddl)

        ct_cols = await _cols("contacts")
        if "base_id" not in ct_cols:
            await db.execute("ALTER TABLE contacts ADD COLUMN base_id INTEGER")

        cur = await db.execute("SELECT COUNT(*) FROM contact_bases")
        row = await cur.fetchone()
        if not row or int(row[0] or 0) == 0:
            now = _now()
            await db.execute(
                "INSERT INTO contact_bases(name, enabled, created_at) VALUES(?,?,?)",
                ("Основная", 1, now),
            )
            cur = await db.execute("SELECT id FROM contact_bases ORDER BY id LIMIT 1")
            base_row = await cur.fetchone()
            if base_row:
                await db.execute(
                    "UPDATE contacts SET base_id=? WHERE base_id IS NULL",
                    (base_row[0],),
                )

    @asynccontextmanager
    async def _connect(self):
        db = await aiosqlite.connect(self.path)
        try:
            await db.execute("PRAGMA foreign_keys = ON")
            yield db
        finally:
            await db.close()

    async def get_setting(self, key: str, default: str = "") -> str:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = await cur.fetchone()
            return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await db.commit()

    async def outreach_settings(self) -> OutreachSettings:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT key, value FROM settings")
            rows = {r["key"]: r["value"] for r in await cur.fetchall()}

        def _i(key: str, default: int) -> int:
            try:
                return int(rows.get(key, default))
            except (TypeError, ValueError):
                return default

        return OutreachSettings(
            delay_min=_i("delay_min", 60),
            delay_max=_i("delay_max", 120),
            between_delay_min=_i("between_delay_min", 0),
            between_delay_max=_i("between_delay_max", 0),
            typing=str(rows.get("typing", "1")) not in {"0", "false", "off"},
            rotate_proxy_every=max(1, _i("rotate_proxy_every", 1)),
            variant_mode=rows.get("variant_mode", "random") or "random",
            continuous=str(rows.get("continuous", "1")) not in {"0", "false", "off"},
        )

    async def update_settings(self, **kwargs: Any) -> OutreachSettings:
        allowed = {
            "delay_min",
            "delay_max",
            "between_delay_min",
            "between_delay_max",
            "typing",
            "rotate_proxy_every",
            "variant_mode",
            "continuous",
        }
        for key, value in kwargs.items():
            if key not in allowed:
                continue
            stored = value
            if isinstance(value, bool):
                stored = "1" if value else "0"
            await self.set_setting(key, str(stored))
        return await self.outreach_settings()

    async def counts(self) -> Counts:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row

            async def _n(sql: str, *args: Any) -> int:
                cur = await db.execute(sql, args)
                row = await cur.fetchone()
                return int(row[0] if row else 0)

            pending_sql = (
                "SELECT COUNT(*) FROM contacts c "
                "LEFT JOIN contact_bases b ON b.id=c.base_id "
                "WHERE c.status='pending' AND (c.base_id IS NULL OR b.enabled=1) "
                "AND NOT EXISTS (SELECT 1 FROM blocklist bl WHERE bl.kind=c.kind AND bl.value=c.value) "
                "AND NOT EXISTS (SELECT 1 FROM ban_contacts bc WHERE bc.kind=c.kind AND bc.value=c.value)"
            )
            return Counts(
                accounts=await _n("SELECT COUNT(*) FROM accounts"),
                assigned=await _n("SELECT COUNT(*) FROM accounts WHERE assigned=1"),
                proxies=await _n("SELECT COUNT(*) FROM proxies"),
                contacts=await _n("SELECT COUNT(*) FROM contacts"),
                pending=await _n(pending_sql),
                sent=await _n("SELECT COUNT(*) FROM contacts WHERE status='sent'"),
                errors=await _n("SELECT COUNT(*) FROM contacts WHERE status='error'"),
                skipped=await _n("SELECT COUNT(*) FROM contacts WHERE status='skip'"),
                texts=await _n(
                    "SELECT COUNT(*) FROM texts WHERE enabled=1 AND "
                    "(TRIM(text) != '' OR TRIM(photo_path) != '')"
                ),
                bases=await _n("SELECT COUNT(*) FROM contact_bases"),
                bases_enabled=await _n("SELECT COUNT(*) FROM contact_bases WHERE enabled=1"),
                blocklist=await _n("SELECT COUNT(*) FROM blocklist"),
                banwords=await _n("SELECT COUNT(*) FROM banwords"),
                ban_contacts=await _n("SELECT COUNT(*) FROM ban_contacts"),
            )

    async def list_accounts(self) -> list[Account]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM accounts ORDER BY id")
            return [_account(r) for r in await cur.fetchall()]

    async def get_account(self, account_id: int) -> Account | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM accounts WHERE id=?", (account_id,))
            row = await cur.fetchone()
            return _account(row) if row else None

    async def add_account(self, label: str) -> Account:
        now = _now()
        async with self._connect() as db:
            cur = await db.execute(
                "INSERT INTO accounts(label, created_at, updated_at) VALUES(?, ?, ?)",
                (label, now, now),
            )
            await db.commit()
            pk = cur.lastrowid
        account = await self.get_account(int(pk))
        assert account is not None
        await self.assign_unbound_proxies()
        return await self.get_account(account.id) or account

    async def update_account(self, account_id: int, **fields: Any) -> Account | None:
        if not fields:
            return await self.get_account(account_id)
        nullable = {"delay_min", "delay_max"}
        cleaned = {k: v for k, v in fields.items() if v is not None or k in nullable}
        fields = cleaned
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [account_id]
        async with self._connect() as db:
            await db.execute(f"UPDATE accounts SET {cols} WHERE id=?", values)
            await db.commit()
        return await self.get_account(account_id)

    async def delete_account(self, account_id: int) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM account_proxies WHERE account_id=?", (account_id,))
            await db.execute("DELETE FROM accounts WHERE id=?", (account_id,))
            await db.commit()
        await self.assign_unbound_proxies()

    async def toggle_assigned(self, account_id: int) -> Account | None:
        acc = await self.get_account(account_id)
        if not acc:
            return None
        return await self.update_account(account_id, assigned=0 if acc.assigned else 1)

    async def pause_account(self, account_id: int, seconds: int, error: str = "") -> None:
        until = (datetime.now(timezone.utc) + timedelta(seconds=max(1, seconds))).isoformat(
            timespec="seconds"
        )
        await self.update_account(account_id, pause_until=until, last_error=error, status="paused")

    async def bump_sent(self, account_id: int) -> None:
        async with self._connect() as db:
            await db.execute(
                "UPDATE accounts SET sent_count=sent_count+1, updated_at=? WHERE id=?",
                (_now(), account_id),
            )
            await db.commit()

    async def list_proxies(self) -> list[Proxy]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM proxies ORDER BY id")
            return [_proxy(r) for r in await cur.fetchall()]

    async def get_proxy(self, proxy_id: int) -> Proxy | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM proxies WHERE id=?", (proxy_id,))
            row = await cur.fetchone()
            return _proxy(row) if row else None

    async def add_proxies(self, items: list[ParsedProxy]) -> tuple[int, int]:
        added = 0
        skipped = 0
        now = _now()
        async with self._connect() as db:
            for item in items:
                try:
                    await db.execute(
                        "INSERT INTO proxies(raw, scheme, host, port, username, password, created_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            item.raw,
                            item.scheme,
                            item.host,
                            item.port,
                            item.username,
                            item.password,
                            now,
                        ),
                    )
                    added += 1
                except aiosqlite.IntegrityError:
                    skipped += 1
            await db.commit()
        if added:
            await self.assign_unbound_proxies()
        return added, skipped

    async def delete_proxy(self, proxy_id: int) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM account_proxies WHERE proxy_id=?", (proxy_id,))
            await db.execute("DELETE FROM proxies WHERE id=?", (proxy_id,))
            await db.commit()
        await self.assign_unbound_proxies()

    async def mark_proxy(self, proxy_id: int, status: str, error: str = "") -> None:
        async with self._connect() as db:
            await db.execute(
                "UPDATE proxies SET status=?, last_error=? WHERE id=?",
                (status, error, proxy_id),
            )
            await db.commit()

    async def proxies_for_account(self, account_id: int) -> list[Proxy]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT p.* FROM proxies p "
                "JOIN account_proxies ap ON ap.proxy_id=p.id "
                "WHERE ap.account_id=? ORDER BY p.id",
                (account_id,),
            )
            return [_proxy(r) for r in await cur.fetchall()]

    async def bind_proxy(self, account_id: int, proxy_id: int, bind: bool) -> None:
        async with self._connect() as db:
            if bind:
                await db.execute(
                    "INSERT OR IGNORE INTO account_proxies(account_id, proxy_id) VALUES(?,?)",
                    (account_id, proxy_id),
                )
            else:
                await db.execute(
                    "DELETE FROM account_proxies WHERE account_id=? AND proxy_id=?",
                    (account_id, proxy_id),
                )
            await db.commit()

    async def rebalance_proxies(self) -> None:
        """Full redistribute — only for explicit UI action."""
        accounts = await self.list_accounts()
        proxies = await self.list_proxies()
        if not accounts or not proxies:
            return
        async with self._connect() as db:
            await db.execute("DELETE FROM account_proxies")
            for i, proxy in enumerate(proxies):
                acc = accounts[i % len(accounts)]
                await db.execute(
                    "INSERT OR IGNORE INTO account_proxies(account_id, proxy_id) VALUES(?,?)",
                    (acc.id, proxy.id),
                )
            await db.commit()

    async def assign_unbound_proxies(self) -> None:
        """Attach proxies that have no account yet — keep existing binds."""
        accounts = await self.list_accounts()
        if not accounts:
            return
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT p.id FROM proxies p "
                "LEFT JOIN account_proxies ap ON ap.proxy_id=p.id "
                "WHERE ap.proxy_id IS NULL ORDER BY p.id"
            )
            unbound = [int(r["id"]) for r in await cur.fetchall()]
            if not unbound:
                return
            for i, proxy_id in enumerate(unbound):
                acc = accounts[i % len(accounts)]
                await db.execute(
                    "INSERT OR IGNORE INTO account_proxies(account_id, proxy_id) VALUES(?,?)",
                    (acc.id, proxy_id),
                )
            await db.commit()

    async def next_proxy(self, account_id: int) -> Proxy | None:
        acc = await self.get_account(account_id)
        if not acc:
            return None
        proxies = await self.proxies_for_account(account_id)
        if not proxies:
            proxies = await self.list_proxies()
        if not proxies:
            return None
        idx = acc.proxy_cursor % len(proxies)
        chosen = proxies[idx]
        await self.update_account(account_id, proxy_cursor=acc.proxy_cursor + 1)
        return chosen

    async def peek_proxy(self, account_id: int) -> Proxy | None:
        """Return a proxy without advancing the rotation cursor."""
        acc = await self.get_account(account_id)
        if not acc:
            return None
        proxies = await self.proxies_for_account(account_id)
        if not proxies:
            proxies = await self.list_proxies()
        if not proxies:
            return None
        return proxies[acc.proxy_cursor % len(proxies)]

    async def list_contacts(
        self, status: str | None = None, page: int = 0, per_page: int = 8
    ) -> list[Contact]:
        sql = "SELECT * FROM contacts WHERE 1=1"
        args: list[Any] = []
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args.extend([per_page, page * per_page])
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, args)
            return [_contact(r) for r in await cur.fetchall()]

    async def contact_kind_counts(self) -> dict[str, int]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT kind, COUNT(*) AS n FROM contacts GROUP BY kind"
            )
            return {r["kind"]: int(r["n"]) for r in await cur.fetchall()}

    async def add_contacts(
        self, items: list[Classified], base_id: int | None = None
    ) -> tuple[int, int]:
        added = 0
        skipped = 0
        now = _now()
        if base_id is None:
            base_id = await self.default_base_id()
        async with self._connect() as db:
            for item in items:
                cur = await db.execute(
                    "SELECT 1 FROM ban_contacts WHERE kind=? AND value=? LIMIT 1",
                    (item.kind, item.value),
                )
                if await cur.fetchone():
                    skipped += 1
                    continue
                cur = await db.execute(
                    "SELECT 1 FROM blocklist WHERE kind=? AND value=? LIMIT 1",
                    (item.kind, item.value),
                )
                if await cur.fetchone():
                    skipped += 1
                    continue
                try:
                    await db.execute(
                        "INSERT INTO contacts(raw, kind, value, display, extra, base_id, created_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            item.raw or item.value,
                            item.kind,
                            item.value,
                            item.display or item.value,
                            item.extra or "",
                            base_id,
                            now,
                        ),
                    )
                    added += 1
                except aiosqlite.IntegrityError:
                    skipped += 1
            await db.commit()
        return added, skipped

    async def claim_contact(self) -> Contact | None:
        async with self._claim_lock:
            async with self._connect() as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT c.* FROM contacts c "
                    "LEFT JOIN contact_bases b ON b.id=c.base_id "
                    "WHERE c.status='pending' "
                    "AND (c.base_id IS NULL OR b.enabled=1) "
                    "AND NOT EXISTS (SELECT 1 FROM blocklist bl WHERE bl.kind=c.kind AND bl.value=c.value) "
                    "AND NOT EXISTS (SELECT 1 FROM ban_contacts bc WHERE bc.kind=c.kind AND bc.value=c.value) "
                    "ORDER BY c.id LIMIT 1"
                )
                row = await cur.fetchone()
                if not row:
                    return None
                upd = await db.execute(
                    "UPDATE contacts SET status='sending' WHERE id=? AND status='pending'",
                    (row["id"],),
                )
                if int(upd.rowcount or 0) == 0:
                    await db.commit()
                    return None
                await db.commit()
                cur = await db.execute("SELECT * FROM contacts WHERE id=?", (row["id"],))
                fresh = await cur.fetchone()
        return _contact(fresh) if fresh else None

    async def finish_contact(
        self,
        contact_id: int,
        status: str,
        *,
        account_id: int | None = None,
        text_id: int | None = None,
        error: str = "",
    ) -> None:
        sent_at = _now() if status == "sent" else ""
        async with self._connect() as db:
            await db.execute(
                "UPDATE contacts SET status=?, last_error=?, sent_at=?, account_id=?, text_id=? "
                "WHERE id=?",
                (status, error, sent_at, account_id, text_id, contact_id),
            )
            await db.commit()

    async def release_contact(self, contact_id: int) -> None:
        async with self._connect() as db:
            await db.execute(
                "UPDATE contacts SET status='pending', last_error='' "
                "WHERE id=? AND status='sending'",
                (contact_id,),
            )
            await db.commit()

    async def release_stuck_sending(self) -> int:
        async with self._connect() as db:
            cur = await db.execute(
                "UPDATE contacts SET status='pending' WHERE status='sending'"
            )
            await db.commit()
            return int(cur.rowcount or 0)

    async def clear_contacts(self, only_pending: bool = False) -> int:
        async with self._connect() as db:
            if only_pending:
                cur = await db.execute(
                    "DELETE FROM contacts WHERE status IN ('pending','error','skip')"
                )
            else:
                cur = await db.execute("DELETE FROM contacts")
            await db.commit()
            return int(cur.rowcount or 0)

    async def reset_errors_to_pending(self) -> int:
        async with self._connect() as db:
            cur = await db.execute(
                "UPDATE contacts SET status='pending', last_error='' "
                "WHERE status IN ('error','skip')"
            )
            await db.commit()
            return int(cur.rowcount or 0)

    async def list_texts(self, enabled_only: bool = False) -> list[TextVariant]:
        sql = "SELECT * FROM texts"
        args: list[Any] = []
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id"
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, args)
            return [_text(r) for r in await cur.fetchall()]

    async def get_text(self, text_id: int) -> TextVariant | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM texts WHERE id=?", (text_id,))
            row = await cur.fetchone()
            return _text(row) if row else None

    async def add_text(
        self,
        text: str,
        entities: list[dict[str, Any]],
        photo_path: str = "",
        title: str = "",
    ) -> TextVariant:
        async with self._connect() as db:
            cur = await db.execute(
                "INSERT INTO texts(title, text, entities_json, photo_path, created_at) "
                "VALUES(?,?,?,?,?)",
                (
                    title,
                    text,
                    json.dumps(entities, ensure_ascii=False),
                    photo_path,
                    _now(),
                ),
            )
            await db.commit()
            pk = cur.lastrowid
        item = await self.get_text(int(pk))
        assert item is not None
        return item

    async def update_text(self, text_id: int, **fields: Any) -> TextVariant | None:
        allowed = {"title", "text", "entities_json", "photo_path", "enabled"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return await self.get_text(text_id)
        cols = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [text_id]
        async with self._connect() as db:
            await db.execute(f"UPDATE texts SET {cols} WHERE id=?", values)
            await db.commit()
        return await self.get_text(text_id)

    async def delete_text(self, text_id: int) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM texts WHERE id=?", (text_id,))
            await db.commit()

    async def add_send(
        self,
        *,
        contact_id: int | None,
        account_id: int | None,
        text_id: int | None,
        proxy_id: int | None,
        status: str,
        detail: str = "",
    ) -> None:
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO sends(contact_id, account_id, text_id, proxy_id, status, detail, created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (contact_id, account_id, text_id, proxy_id, status, detail, _now()),
            )
            await db.commit()

    async def recent_sends(self, limit: int = 20, offset: int = 0) -> list[SendRow]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT s.*, "
                "COALESCE(c.display, c.value, '') AS contact_pretty, "
                "COALESCE(a.label,'') AS account_label "
                "FROM sends s "
                "LEFT JOIN contacts c ON c.id=s.contact_id "
                "LEFT JOIN accounts a ON a.id=s.account_id "
                "ORDER BY s.id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cur.fetchall()
        return [
            SendRow(
                id=r["id"],
                contact_id=r["contact_id"],
                account_id=r["account_id"],
                text_id=r["text_id"],
                proxy_id=r["proxy_id"],
                status=r["status"],
                detail=r["detail"] or "",
                created_at=r["created_at"] or "",
                contact_pretty=r["contact_pretty"] or "",
                account_label=r["account_label"] or "",
            )
            for r in rows
        ]

    async def create_job(self, kind: str, account_id: int | None) -> Job:
        async with self._connect() as db:
            cur = await db.execute(
                "INSERT INTO jobs(account_id, kind, status, started_at) VALUES(?,?,?,?)",
                (account_id, kind, "running", _now()),
            )
            await db.commit()
            pk = cur.lastrowid
        job = await self.get_job(int(pk))
        assert job is not None
        return job

    async def get_job(self, job_id: int) -> Job | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT j.*, COALESCE(a.label,'') AS account_label "
                "FROM jobs j LEFT JOIN accounts a ON a.id=j.account_id WHERE j.id=?",
                (job_id,),
            )
            row = await cur.fetchone()
        if not row:
            return None
        return Job(
            id=row["id"],
            account_id=row["account_id"],
            kind=row["kind"],
            status=row["status"],
            started_at=row["started_at"] or "",
            finished_at=row["finished_at"] or "",
            report=row["report"] or "",
            account_label=row["account_label"] or "",
        )

    async def finish_job(self, job_id: int, status: str, report: str = "") -> None:
        async with self._connect() as db:
            await db.execute(
                "UPDATE jobs SET status=?, finished_at=?, report=? WHERE id=?",
                (status, _now(), report, job_id),
            )
            await db.commit()

    async def add_log(self, job_id: int, message: str, level: str = "info") -> None:
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO job_logs(job_id, created_at, level, message) VALUES(?,?,?,?)",
                (job_id, _now(), level, message),
            )
            await db.commit()

    async def job_logs(self, job_id: int, limit: int = 40) -> list[JobLog]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM job_logs WHERE job_id=? ORDER BY id DESC LIMIT ?",
                (job_id, limit),
            )
            rows = await cur.fetchall()
        return [
            JobLog(
                id=r["id"],
                job_id=r["job_id"],
                created_at=r["created_at"],
                level=r["level"],
                message=r["message"],
            )
            for r in rows
        ]

    async def recent_jobs(self, limit: int = 20) -> list[Job]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT j.*, COALESCE(a.label,'') AS account_label "
                "FROM jobs j LEFT JOIN accounts a ON a.id=j.account_id "
                "ORDER BY j.id DESC LIMIT ?",
                (limit,),
            )
            rows = await cur.fetchall()
        return [
            Job(
                id=r["id"],
                account_id=r["account_id"],
                kind=r["kind"],
                status=r["status"],
                started_at=r["started_at"] or "",
                finished_at=r["finished_at"] or "",
                report=r["report"] or "",
                account_label=r["account_label"] or "",
            )
            for r in rows
        ]

    async def default_base_id(self) -> int:
        bases = await self.list_bases()
        if bases:
            return bases[0].id
        now = _now()
        async with self._connect() as db:
            cur = await db.execute(
                "INSERT INTO contact_bases(name, enabled, created_at) VALUES(?,?,?)",
                ("Основная", 1, now),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def list_bases(self) -> list[ContactBase]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM contact_bases ORDER BY id")
            return [_base(r) for r in await cur.fetchall()]

    async def get_base(self, base_id: int) -> ContactBase | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM contact_bases WHERE id=?", (base_id,))
            row = await cur.fetchone()
            return _base(row) if row else None

    async def add_base(self, name: str) -> ContactBase:
        now = _now()
        async with self._connect() as db:
            cur = await db.execute(
                "INSERT INTO contact_bases(name, enabled, created_at) VALUES(?,?,?)",
                (name.strip(), 1, now),
            )
            await db.commit()
            pk = int(cur.lastrowid)
        base = await self.get_base(pk)
        assert base is not None
        return base

    async def toggle_base(self, base_id: int) -> ContactBase | None:
        base = await self.get_base(base_id)
        if not base:
            return None
        async with self._connect() as db:
            await db.execute(
                "UPDATE contact_bases SET enabled=? WHERE id=?",
                (0 if base.enabled else 1, base_id),
            )
            await db.commit()
        return await self.get_base(base_id)

    async def rename_base(self, base_id: int, name: str) -> ContactBase | None:
        async with self._connect() as db:
            await db.execute(
                "UPDATE contact_bases SET name=? WHERE id=?",
                (name.strip()[:60], base_id),
            )
            await db.commit()
        return await self.get_base(base_id)

    async def delete_base(self, base_id: int) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM contacts WHERE base_id=?", (base_id,))
            await db.execute("DELETE FROM contact_bases WHERE id=?", (base_id,))
            await db.commit()

    async def base_stats(self, base_id: int) -> dict[str, int]:
        async with self._connect() as db:
            async def _n(sql: str) -> int:
                cur = await db.execute(sql, (base_id,))
                row = await cur.fetchone()
                return int(row[0] if row else 0)

            return {
                "total": await _n("SELECT COUNT(*) FROM contacts WHERE base_id=?"),
                "pending": await _n(
                    "SELECT COUNT(*) FROM contacts WHERE base_id=? AND status='pending'"
                ),
                "sent": await _n("SELECT COUNT(*) FROM contacts WHERE base_id=? AND status='sent'"),
            }

    async def list_contacts_for_base(
        self, base_id: int, status: str | None = None, page: int = 0, per_page: int = 8
    ) -> list[Contact]:
        sql = "SELECT * FROM contacts WHERE base_id=?"
        args: list[Any] = [base_id]
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args.extend([per_page, page * per_page])
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, args)
            return [_contact(r) for r in await cur.fetchall()]

    async def export_contacts(self, base_id: int | None = None) -> list[Contact]:
        sql = "SELECT * FROM contacts WHERE 1=1"
        args: list[Any] = []
        if base_id is not None:
            sql += " AND base_id=?"
            args.append(base_id)
        sql += " ORDER BY id"
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, args)
            return [_contact(r) for r in await cur.fetchall()]

    async def list_blocklist(self, page: int = 0, per_page: int = 20) -> list[BlockEntry]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM blocklist ORDER BY id DESC LIMIT ? OFFSET ?",
                (per_page, page * per_page),
            )
            return [_block(r) for r in await cur.fetchall()]

    async def add_blocklist(self, items: list[Classified], note: str = "") -> tuple[int, int]:
        added = 0
        skipped = 0
        now = _now()
        async with self._connect() as db:
            for item in items:
                if item.kind == "unknown":
                    skipped += 1
                    continue
                try:
                    await db.execute(
                        "INSERT INTO blocklist(kind, value, note, created_at) VALUES(?,?,?,?)",
                        (item.kind, item.value, note, now),
                    )
                    added += 1
                    await db.execute(
                        "UPDATE contacts SET status='skip', last_error='blocklist' "
                        "WHERE kind=? AND value=? AND status='pending'",
                        (item.kind, item.value),
                    )
                except aiosqlite.IntegrityError:
                    skipped += 1
            await db.commit()
        return added, skipped

    async def remove_block(self, block_id: int) -> None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT kind, value FROM blocklist WHERE id=?", (block_id,))
            row = await cur.fetchone()
            if row:
                await db.execute(
                    "UPDATE contacts SET status='pending', last_error='' "
                    "WHERE kind=? AND value=? AND status='skip' AND last_error='blocklist'",
                    (row["kind"], row["value"]),
                )
            await db.execute("DELETE FROM blocklist WHERE id=?", (block_id,))
            await db.commit()

    async def list_banwords(self) -> list[str]:
        async with self._connect() as db:
            cur = await db.execute("SELECT word FROM banwords ORDER BY word")
            return [r[0] for r in await cur.fetchall()]

    async def add_banwords(self, words: list[str]) -> tuple[int, int]:
        added = 0
        skipped = 0
        now = _now()
        async with self._connect() as db:
            for word in words:
                w = (word or "").strip()
                if not w:
                    continue
                try:
                    await db.execute(
                        "INSERT INTO banwords(word, created_at) VALUES(?,?)",
                        (w, now),
                    )
                    added += 1
                except aiosqlite.IntegrityError:
                    skipped += 1
            await db.commit()
        return added, skipped

    async def remove_banword(self, word: str) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM banwords WHERE word=?", (word,))
            await db.commit()

    async def add_ban_contact(
        self,
        kind: str,
        value: str,
        *,
        display: str = "",
        reason: str = "",
        source_base_id: int | None = None,
    ) -> bool:
        now = _now()
        async with self._connect() as db:
            try:
                await db.execute(
                    "INSERT INTO ban_contacts(kind, value, display, reason, source_base_id, created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (kind, value, display or value, reason, source_base_id, now),
                )
                await db.execute(
                    "DELETE FROM contacts WHERE kind=? AND value=? AND status='pending'",
                    (kind, value),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def list_ban_contacts(self, page: int = 0, per_page: int = 20) -> list[BanContact]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM ban_contacts ORDER BY id DESC LIMIT ? OFFSET ?",
                (per_page, page * per_page),
            )
            return [_ban_contact(r) for r in await cur.fetchall()]

    async def accounts_for_proxy(self, proxy_id: int) -> list[Account]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT a.* FROM accounts a "
                "JOIN account_proxies ap ON ap.account_id=a.id "
                "WHERE ap.proxy_id=? ORDER BY a.id",
                (proxy_id,),
            )
            return [_account(r) for r in await cur.fetchall()]

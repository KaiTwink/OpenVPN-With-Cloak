from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    server_host TEXT NOT NULL,
    protocol TEXT NOT NULL,
    port INTEGER NOT NULL,
    subnet TEXT NOT NULL,
    netmask TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS remotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    remote_host TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_name TEXT NOT NULL UNIQUE,
    cert_cn TEXT NOT NULL UNIQUE,
    created_date TEXT NOT NULL,
    expiration_date TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    traffic_used INTEGER NOT NULL DEFAULT 0,
    profile_path TEXT,
    last_connected_at TEXT,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS telegram_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    bot_token TEXT DEFAULT '',
    admin_ids TEXT DEFAULT '',
    notify_chat_id TEXT DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id TEXT PRIMARY KEY,
    can_manage INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT DEFAULT ''
);
"""


def db_path() -> Path:
    return Path(load_config()["db_path"])


@contextmanager
def get_conn(path: str | None = None) -> Iterator[sqlite3.Connection]:
    db = Path(path) if path else db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO telegram_settings(id) VALUES (1)")


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with get_conn() as conn:
        conn.execute(sql, tuple(params))


def fetchone(sql: str, params: Iterable[Any] = ()):
    with get_conn() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def fetchall(sql: str, params: Iterable[Any] = ()):
    with get_conn() as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def audit(actor: str, action: str, details: str = "") -> None:
    execute("INSERT INTO audit_log(actor, action, details) VALUES (?, ?, ?)", (actor, action, details))

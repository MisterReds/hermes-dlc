"""Shared storage for the DLC.

The agent library must be shared by ALL profiles: Kanban workers run as separate profiles
(`hermes -p <assignee>`), each with its own HERMES_HOME. That is why the data lives in the
Hermes root (`~/.hermes/dlc/`), not in `plugin_data_dir()`, which follows the active profile.
Override: the DLC_HOME env var.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    slug        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    specialty   TEXT NOT NULL,
    domains     TEXT NOT NULL DEFAULT '[]',
    tier        TEXT NOT NULL DEFAULT 'specialist',
    profile     TEXT NOT NULL,
    model       TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    version     INTEGER NOT NULL DEFAULT 1,
    parent_slug TEXT,
    embedding   BLOB,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_slug  TEXT NOT NULL,
    task_id     TEXT,
    board       TEXT,
    outcome     TEXT NOT NULL,
    complexity  TEXT,
    score       REAL,
    notes       TEXT,
    retro_done  INTEGER NOT NULL DEFAULT 0,
    at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(agent_slug, task_id, outcome)
);
CREATE TABLE IF NOT EXISTS lessons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_slug  TEXT NOT NULL,
    lesson      TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'do',
    source_task TEXT,
    applied     INTEGER NOT NULL DEFAULT 0,
    at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    collection  TEXT NOT NULL,
    source      TEXT NOT NULL,
    ord         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embedding   BLOB NOT NULL,
    model       TEXT NOT NULL,
    at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_coll ON chunks(collection);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_slug);
"""

_lock = threading.Lock()


def dlc_home() -> Path:
    env = os.environ.get("DLC_HOME")
    if env:
        root = Path(env).expanduser()
    else:
        try:
            from hermes_constants import get_default_hermes_root
            root = get_default_hermes_root() / "dlc"
        except Exception:  # running outside Hermes (tests, scripts)
            root = Path.home() / ".hermes" / "dlc"
    root.mkdir(parents=True, exist_ok=True)
    return root


def hermes_root() -> Path:
    try:
        from hermes_constants import get_default_hermes_root
        return get_default_hermes_root()
    except Exception:
        return Path(os.environ.get("HERMES_ROOT", Path.home() / ".hermes")).expanduser()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(dlc_home() / "dlc.db", timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    with _lock:
        conn.executescript(_SCHEMA)
    return conn

"""SQLite connection, schema and demo data."""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta

from models import (
    EVENT_DRAFT,
    EVENT_PUBLISHED,
    ROLE_ADMIN,
    ROLE_CHECKER,
    ROLE_ORGANIZER,
    ROLE_PARTICIPANT,
    now_text,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organizer_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    city TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    deadline TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    title TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity >= 0)
);
CREATE TABLE IF NOT EXISTS ticket_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    name TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity >= 0)
);
CREATE TABLE IF NOT EXISTS session_checkers (
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (session_id, user_id)
);
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ticket_type_id INTEGER NOT NULL REFERENCES ticket_types(id),
    state TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    checked_in_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_registration
    ON registrations(user_id, session_id)
    WHERE state IN ('已报名', '已签到');
CREATE TABLE IF NOT EXISTS waitlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ticket_type_id INTEGER NOT NULL REFERENCES ticket_types(id),
    state TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_waiting_entry
    ON waitlist(user_id, session_id)
    WHERE state = '排队中';
CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_id INTEGER NOT NULL UNIQUE REFERENCES registrations(id),
    code TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_id INTEGER NOT NULL REFERENCES registrations(id),
    checker_id INTEGER NOT NULL REFERENCES users(id),
    result TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    result TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    registration_id INTEGER,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def connect(path):
    """Open a connection with foreign keys and dict-like rows enabled."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.isolation_level = None
    return conn


def hash_password(password, salt=None):
    """Return a salted SHA-256 hash for a password."""
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    ).hex()
    return digest, salt


def add_user(conn, account, display_name, password, role):
    """Insert one user and return its id."""
    digest, salt = hash_password(password)
    cur = conn.execute(
        "INSERT INTO users (account, display_name, password_hash, salt, role)"
        " VALUES (?, ?, ?, ?, ?)",
        (account, display_name, digest, salt, role),
    )
    return cur.lastrowid


def log_action(conn, user_id, action, target_type, target_id, result):
    """Append one operation log row."""
    conn.execute(
        "INSERT INTO operation_logs"
        " (user_id, action, target_type, target_id, result, occurred_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, action, target_type, target_id, result, now_text()),
    )


def init_db(conn, with_demo=True):
    """Create tables and optionally insert demo data."""
    conn.executescript(SCHEMA)
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0 and with_demo:
        seed_demo(conn)


def seed_demo(conn):
    """Insert demo accounts and two events."""
    admin_id = add_user(conn, "admin1", "平台管理员", "123456", ROLE_ADMIN)
    organizer_id = add_user(conn, "organizer1", "城南文化", "123456", ROLE_ORGANIZER)
    checker_id = add_user(conn, "checker1", "检票员小李", "123456", ROLE_CHECKER)
    participant_id = add_user(conn, "participant1", "王小满", "123456", ROLE_PARTICIPANT)
    add_user(conn, "participant2", "陈青", "123456", ROLE_PARTICIPANT)

    start = datetime.now() + timedelta(days=5)
    end = start + timedelta(hours=3)
    cur = conn.execute(
        "INSERT INTO events (organizer_id, title, city, category, description,"
        " deadline, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            organizer_id,
            "城市音乐节",
            "南京",
            "音乐",
            "露天舞台与独立乐队演出",
            (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
            EVENT_PUBLISHED,
            now_text(),
        ),
    )
    event_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO sessions (event_id, title, start_time, end_time, capacity)"
        " VALUES (?, ?, ?, ?, ?)",
        (event_id, "周六夜场", start.strftime("%Y-%m-%d %H:%M:%S"),
         end.strftime("%Y-%m-%d %H:%M:%S"), 2),
    )
    session_id = cur.lastrowid
    conn.execute(
        "INSERT INTO ticket_types (session_id, name, capacity) VALUES (?, ?, ?)",
        (session_id, "普通票", 2),
    )
    conn.execute(
        "INSERT INTO session_checkers (session_id, user_id) VALUES (?, ?)",
        (session_id, checker_id),
    )
    conn.execute(
        "INSERT INTO events (organizer_id, title, city, category, description,"
        " deadline, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            organizer_id,
            "校园戏剧周",
            "南京",
            "戏剧",
            "学生社团联合演出",
            (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"),
            EVENT_DRAFT,
            now_text(),
        ),
    )
    conn.execute(
        "INSERT INTO notifications"
        " (user_id, registration_id, kind, status, retry_count, created_at)"
        " VALUES (?, NULL, '报名成功', '失败', 0, ?)",
        (participant_id, now_text()),
    )
    conn.execute(
        "INSERT INTO operation_logs"
        " (user_id, action, target_type, target_id, result, occurred_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (admin_id, "初始化演示数据", "system", None, "成功", now_text()),
    )

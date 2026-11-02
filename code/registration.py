"""Registration, waitlist and cancellation use cases."""

import secrets
import uuid

import notifications
from db import log_action
from events import (
    get_session,
    get_ticket,
    session_occupied,
    ticket_occupied,
)
from models import (
    ACTIVE_STATES,
    CANCELLED,
    CHECKED_IN,
    EVENT_PUBLISHED,
    REGISTERED,
    ROLE_PARTICIPANT,
    WAIT_EXPIRED,
    WAIT_PROMOTED,
    WAIT_WAITING,
    ServiceError,
    deadline_open,
    now_text,
)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_code(conn):
    """Generate a credential code that is not used yet."""
    for _ in range(10):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        exists = conn.execute(
            "SELECT 1 FROM credentials WHERE code = ?", (code,)
        ).fetchone()
        if exists is None:
            return code
    raise ServiceError("凭证生成失败，请重试")


def _code_for(conn, registration_id):
    """Return the credential code of a registration."""
    row = conn.execute(
        "SELECT code FROM credentials WHERE registration_id = ?", (registration_id,)
    ).fetchone()
    return row["code"] if row else ""


def _insert_registration(conn, user_id, session_id, ticket_type_id, request_id):
    """Insert a registration and its credential inside a transaction."""
    cur = conn.execute(
        "INSERT INTO registrations"
        " (request_id, user_id, session_id, ticket_type_id, state, registered_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, user_id, session_id, ticket_type_id, REGISTERED, now_text()),
    )
    registration_id = cur.lastrowid
    code = _new_code(conn)
    conn.execute(
        "INSERT INTO credentials (registration_id, code, issued_at) VALUES (?, ?, ?)",
        (registration_id, code, now_text()),
    )
    return registration_id, code


def register(conn, user, session_id, ticket_type_id, request_id=None):
    """Register a participant for one ticket; repeated requests are idempotent."""
    if user["role"] != ROLE_PARTICIPANT:
        raise ServiceError("只有参与者可以报名")
    session = get_session(conn, session_id)
    ticket = get_ticket(conn, ticket_type_id)
    if ticket["session_id"] != session_id:
        raise ServiceError("票种不属于该场次")
    if request_id:
        old = conn.execute(
            "SELECT * FROM registrations WHERE request_id = ?", (request_id,)
        ).fetchone()
        if old is not None:
            if old["user_id"] != user["id"]:
                raise ServiceError("请求编号已被其他用户使用")
            return old, _code_for(conn, old["id"]), "重复请求，返回首次结果"
    if session["event_state"] != EVENT_PUBLISHED:
        raise ServiceError("活动未发布或已取消")
    if not deadline_open(session["deadline"]):
        raise ServiceError("报名已截止")
    if session["end_time"] < now_text():
        raise ServiceError("场次已结束")
    request_id = request_id or f"reg-{user['id']}-{uuid.uuid4().hex}"
    conn.execute("BEGIN IMMEDIATE")
    try:
        fresh = get_session(conn, session_id)
        if fresh["event_state"] != EVENT_PUBLISHED:
            raise ServiceError("活动状态已变化，报名失败")
        duplicate = conn.execute(
            "SELECT 1 FROM registrations WHERE user_id = ? AND session_id = ?"
            " AND state IN (?, ?)",
            (user["id"], session_id, *ACTIVE_STATES),
        ).fetchone()
        if duplicate:
            raise ServiceError("同一场次只能有一条有效报名")
        ticket = get_ticket(conn, ticket_type_id)
        if (session_occupied(conn, session_id) >= fresh["capacity"]
                or ticket_occupied(conn, ticket_type_id) >= ticket["capacity"]):
            raise ServiceError("名额已满，请选择候补")
        registration_id, code = _insert_registration(
            conn, user["id"], session_id, ticket_type_id, request_id
        )
        log_action(conn, user["id"], "报名", "registration", registration_id, "成功")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    notifications.create(conn, user["id"], registration_id, "报名成功")
    row = conn.execute(
        "SELECT * FROM registrations WHERE id = ?", (registration_id,)
    ).fetchone()
    return row, code, "报名成功"


def join_waitlist(conn, user, session_id, ticket_type_id):
    """Put a participant into the waitlist when the session is full."""
    if user["role"] != ROLE_PARTICIPANT:
        raise ServiceError("只有参与者可以登记候补")
    session = get_session(conn, session_id)
    ticket = get_ticket(conn, ticket_type_id)
    if ticket["session_id"] != session_id:
        raise ServiceError("票种不属于该场次")
    if session["event_state"] != EVENT_PUBLISHED:
        raise ServiceError("活动未发布或已取消")
    if not deadline_open(session["deadline"]):
        raise ServiceError("报名已截止，不能登记候补")
    conn.execute("BEGIN IMMEDIATE")
    try:
        active = conn.execute(
            "SELECT 1 FROM registrations WHERE user_id = ? AND session_id = ?"
            " AND state IN (?, ?)",
            (user["id"], session_id, *ACTIVE_STATES),
        ).fetchone()
        if active:
            raise ServiceError("已有有效报名，无需候补")
        waiting = conn.execute(
            "SELECT * FROM waitlist WHERE user_id = ? AND session_id = ? AND state = ?",
            (user["id"], session_id, WAIT_WAITING),
        ).fetchone()
        if waiting:
            position = conn.execute(
                "SELECT COUNT(*) FROM waitlist WHERE session_id = ? AND state = ?"
                " AND id <= ?",
                (session_id, WAIT_WAITING, waiting["id"]),
            ).fetchone()[0]
            conn.execute("COMMIT")
            return waiting["id"], position, "已在候补队列中"
        if (session_occupied(conn, session_id) < session["capacity"]
                and ticket_occupied(conn, ticket_type_id) < ticket["capacity"]):
            raise ServiceError("仍有名额，请直接报名")
        cur = conn.execute(
            "INSERT INTO waitlist"
            " (user_id, session_id, ticket_type_id, state, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user["id"], session_id, ticket_type_id, WAIT_WAITING, now_text()),
        )
        waitlist_id = cur.lastrowid
        position = conn.execute(
            "SELECT COUNT(*) FROM waitlist WHERE session_id = ? AND state = ?",
            (session_id, WAIT_WAITING),
        ).fetchone()[0]
        log_action(conn, user["id"], "登记候补", "waitlist", waitlist_id, "成功")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    notifications.create(conn, user["id"], None, "候补登记成功")
    return waitlist_id, position, "候补登记成功"


def _promote(conn, session_id, ticket_type_id):
    """Promote the first waiting entry if a seat is free; caller owns the txn."""
    entry = conn.execute(
        "SELECT * FROM waitlist WHERE session_id = ? AND ticket_type_id = ?"
        " AND state = ? ORDER BY id LIMIT 1",
        (session_id, ticket_type_id, WAIT_WAITING),
    ).fetchone()
    if entry is None:
        return None
    session = get_session(conn, session_id)
    ticket = get_ticket(conn, ticket_type_id)
    if (session_occupied(conn, session_id) >= session["capacity"]
            or ticket_occupied(conn, ticket_type_id) >= ticket["capacity"]):
        return None
    duplicate = conn.execute(
        "SELECT 1 FROM registrations WHERE user_id = ? AND session_id = ?"
        " AND state IN (?, ?)",
        (entry["user_id"], session_id, *ACTIVE_STATES),
    ).fetchone()
    if duplicate:
        conn.execute(
            "UPDATE waitlist SET state = ? WHERE id = ?", (WAIT_EXPIRED, entry["id"])
        )
        return None
    registration_id, code = _insert_registration(
        conn, entry["user_id"], session_id, ticket_type_id,
        f"promote-{entry['id']}"
    )
    conn.execute(
        "UPDATE waitlist SET state = ? WHERE id = ?", (WAIT_PROMOTED, entry["id"])
    )
    log_action(conn, None, "自动递补", "registration", registration_id, "成功")
    return {
        "user_id": entry["user_id"],
        "registration_id": registration_id,
        "code": code,
    }


def cancel_registration(conn, user, registration_id):
    """Cancel an own registration and promote the first waitlist entry."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT r.*, s.event_id, s.end_time, e.state AS event_state, e.deadline"
            " FROM registrations r"
            " JOIN sessions s ON s.id = r.session_id"
            " JOIN events e ON e.id = s.event_id"
            " WHERE r.id = ?",
            (registration_id,),
        ).fetchone()
        if row is None:
            raise ServiceError("报名记录不存在")
        if row["user_id"] != user["id"]:
            raise ServiceError("只能取消本人的报名")
        if row["state"] != REGISTERED:
            raise ServiceError("只有已报名的记录可以取消")
        if row["event_state"] != EVENT_PUBLISHED:
            raise ServiceError("活动当前状态不允许取消")
        conn.execute(
            "UPDATE registrations SET state = ? WHERE id = ?",
            (CANCELLED, registration_id),
        )
        log_action(conn, user["id"], "取消报名", "registration", registration_id, "成功")
        promoted = None
        if deadline_open(row["deadline"]):
            promoted = _promote(conn, row["session_id"], row["ticket_type_id"])
        else:
            conn.execute(
                "UPDATE waitlist SET state = ? WHERE session_id = ? AND state = ?",
                (WAIT_EXPIRED, row["session_id"], WAIT_WAITING),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    notifications.create(conn, user["id"], registration_id, "取消报名成功")
    if promoted:
        notifications.create(
            conn, promoted["user_id"], promoted["registration_id"], "候补递补成功"
        )
    return promoted


def my_registrations(conn, user):
    """Return the current user's registrations with event details."""
    return conn.execute(
        "SELECT r.*, e.title, s.title AS session_title, s.start_time,"
        " t.name AS ticket_name, c.code"
        " FROM registrations r"
        " JOIN sessions s ON s.id = r.session_id"
        " JOIN events e ON e.id = s.event_id"
        " JOIN ticket_types t ON t.id = r.ticket_type_id"
        " LEFT JOIN credentials c ON c.registration_id = r.id"
        " WHERE r.user_id = ? ORDER BY r.id DESC",
        (user["id"],),
    ).fetchall()


def state_counts(conn, session_id):
    """Count registrations per state for one session."""
    rows = conn.execute(
        "SELECT state, COUNT(*) AS total FROM registrations"
        " WHERE session_id = ? GROUP BY state",
        (session_id,),
    ).fetchall()
    return {row["state"]: row["total"] for row in rows}


def checked_in_count(conn, session_id):
    """Count checked-in registrations for one session."""
    row = conn.execute(
        "SELECT COUNT(*) FROM registrations WHERE session_id = ? AND state = ?",
        (session_id, CHECKED_IN),
    ).fetchone()
    return row[0]

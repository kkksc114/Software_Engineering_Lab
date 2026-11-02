"""Event, session and ticket use cases."""

from db import log_action
from models import (
    ABSENT,
    ACTIVE_STATES,
    EVENT_CANCELLED,
    EVENT_CANCELLED_REG,
    EVENT_DRAFT,
    EVENT_FINISHED,
    EVENT_PENDING,
    EVENT_PUBLISHED,
    EVENT_REJECTED,
    REGISTERED,
    ROLE_ADMIN,
    ROLE_ORGANIZER,
    WAIT_EXPIRED,
    WAIT_WAITING,
    ServiceError,
    deadline_open,
    now_text,
)

EDITABLE_STATES = (EVENT_DRAFT, EVENT_REJECTED)


def session_occupied(conn, session_id):
    """Count registrations that still occupy a seat in a session."""
    row = conn.execute(
        "SELECT COUNT(*) FROM registrations"
        " WHERE session_id = ? AND state IN (?, ?)",
        (session_id, *ACTIVE_STATES),
    ).fetchone()
    return row[0]


def ticket_occupied(conn, ticket_type_id):
    """Count registrations that still occupy one ticket type."""
    row = conn.execute(
        "SELECT COUNT(*) FROM registrations"
        " WHERE ticket_type_id = ? AND state IN (?, ?)",
        (ticket_type_id, *ACTIVE_STATES),
    ).fetchone()
    return row[0]


def get_event(conn, event_id):
    """Return one event row or raise."""
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise ServiceError("活动不存在")
    return row


def get_session(conn, session_id):
    """Return a session row joined with its event."""
    row = conn.execute(
        "SELECT s.*, e.organizer_id, e.state AS event_state, e.deadline,"
        " e.title AS event_title"
        " FROM sessions s JOIN events e ON e.id = s.event_id WHERE s.id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ServiceError("场次不存在")
    return row


def get_ticket(conn, ticket_type_id):
    """Return a ticket type row joined with session and event."""
    row = conn.execute(
        "SELECT t.*, s.event_id, s.capacity AS session_capacity,"
        " e.organizer_id, e.state AS event_state, e.deadline"
        " FROM ticket_types t"
        " JOIN sessions s ON s.id = t.session_id"
        " JOIN events e ON e.id = s.event_id"
        " WHERE t.id = ?",
        (ticket_type_id,),
    ).fetchone()
    if row is None:
        raise ServiceError("票种不存在")
    return row


def list_sessions(conn, event_id):
    """Return all sessions of an event."""
    return conn.execute(
        "SELECT * FROM sessions WHERE event_id = ? ORDER BY start_time",
        (event_id,),
    ).fetchall()


def list_tickets(conn, session_id):
    """Return all ticket types of a session."""
    return conn.execute(
        "SELECT * FROM ticket_types WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()


def search_events(conn, keyword="", city="", category=""):
    """Search published events by optional keyword, city and category."""
    sql = "SELECT * FROM events WHERE state = ?"
    args = [EVENT_PUBLISHED]
    if keyword:
        sql += " AND (title LIKE ? OR description LIKE ?)"
        args.extend([f"%{keyword}%", f"%{keyword}%"])
    if city:
        sql += " AND city = ?"
        args.append(city)
    if category:
        sql += " AND category = ?"
        args.append(category)
    sql += " ORDER BY deadline"
    return conn.execute(sql, args).fetchall()


def create_event(conn, organizer, title, city, category, deadline,
                 session_title, start_time, end_time, capacity):
    """Create a draft event with one session and one ticket type."""
    if organizer["role"] != ROLE_ORGANIZER:
        raise ServiceError("只有组织者可以创建活动")
    if capacity <= 0:
        raise ServiceError("名额必须大于 0")
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "INSERT INTO events (organizer_id, title, city, category,"
            " description, deadline, state, created_at)"
            " VALUES (?, ?, ?, '', ?, ?, ?, ?)",
            (organizer["id"], title, city, category, deadline,
             EVENT_DRAFT, now_text()),
        )
        event_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO sessions (event_id, title, start_time, end_time, capacity)"
            " VALUES (?, ?, ?, ?, ?)",
            (event_id, session_title, start_time, end_time, capacity),
        )
        session_id = cur.lastrowid
        conn.execute(
            "INSERT INTO ticket_types (session_id, name, capacity) VALUES (?, '普通票', ?)",
            (session_id, capacity),
        )
        log_action(conn, organizer["id"], "创建活动", "event", event_id, "成功")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return event_id


def _check_owner(event, actor):
    """Raise unless the actor owns the event or is an administrator."""
    if actor["role"] == ROLE_ADMIN:
        return
    if actor["role"] != ROLE_ORGANIZER or event["organizer_id"] != actor["id"]:
        raise ServiceError("只能管理自己创建的活动")


def add_session(conn, actor, event_id, title, start_time, end_time, capacity):
    """Add a session and a default ticket to an editable event."""
    event = get_event(conn, event_id)
    _check_owner(event, actor)
    if event["state"] not in EDITABLE_STATES:
        raise ServiceError("已发布活动不能新增场次，请先取消后重建")
    if capacity <= 0:
        raise ServiceError("名额必须大于 0")
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "INSERT INTO sessions (event_id, title, start_time, end_time, capacity)"
            " VALUES (?, ?, ?, ?, ?)",
            (event_id, title, start_time, end_time, capacity),
        )
        session_id = cur.lastrowid
        conn.execute(
            "INSERT INTO ticket_types (session_id, name, capacity) VALUES (?, '普通票', ?)",
            (session_id, capacity),
        )
        log_action(conn, actor["id"], "新增场次", "session", session_id, "成功")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def add_ticket(conn, actor, session_id, name, capacity):
    """Add a ticket type to an editable session."""
    session = get_session(conn, session_id)
    event = get_event(conn, session["event_id"])
    _check_owner(event, actor)
    if event["state"] not in EDITABLE_STATES:
        raise ServiceError("已发布活动不能新增票种")
    if capacity <= 0:
        raise ServiceError("名额必须大于 0")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO ticket_types (session_id, name, capacity) VALUES (?, ?, ?)",
            (session_id, name, capacity),
        )
        total = conn.execute(
            "SELECT SUM(capacity) FROM ticket_types WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        conn.execute("UPDATE sessions SET capacity = ? WHERE id = ?", (total, session_id))
        log_action(conn, actor["id"], "新增票种", "session", session_id, "成功")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def adjust_ticket_capacity(conn, actor, ticket_type_id, capacity):
    """Change one ticket capacity without dropping below occupied seats."""
    ticket = get_ticket(conn, ticket_type_id)
    event = get_event(conn, ticket["event_id"])
    _check_owner(event, actor)
    if event["state"] in (EVENT_CANCELLED, EVENT_FINISHED):
        raise ServiceError("活动已结束或被取消")
    if capacity < ticket_occupied(conn, ticket_type_id):
        raise ServiceError("容量不能低于当前占用数")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE ticket_types SET capacity = ? WHERE id = ?",
            (capacity, ticket_type_id),
        )
        total = conn.execute(
            "SELECT SUM(capacity) FROM ticket_types WHERE session_id = ?",
            (ticket["session_id"],),
        ).fetchone()[0]
        if total < session_occupied(conn, ticket["session_id"]):
            raise ServiceError("场次容量不能低于当前占用数")
        conn.execute(
            "UPDATE sessions SET capacity = ? WHERE id = ?",
            (total, ticket["session_id"]),
        )
        log_action(conn, actor["id"], "调整名额", "ticket_type", ticket_type_id, "成功")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def submit_review(conn, actor, event_id):
    """Submit a draft or rejected event for review."""
    event = get_event(conn, event_id)
    _check_owner(event, actor)
    if event["state"] not in (EVENT_DRAFT, EVENT_REJECTED):
        raise ServiceError("只有草稿或审核驳回的活动可以提交审核")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE events SET state = ? WHERE id = ?", (EVENT_PENDING, event_id))
        log_action(conn, actor["id"], "提交审核", "event", event_id, "成功")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def review_event(conn, admin, event_id, approve):
    """Approve or reject a pending event."""
    if admin["role"] != ROLE_ADMIN:
        raise ServiceError("只有平台管理员可以审核活动")
    event = get_event(conn, event_id)
    if event["state"] != EVENT_PENDING:
        raise ServiceError("该活动当前不在待审核状态")
    new_state = EVENT_PUBLISHED if approve else EVENT_REJECTED
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE events SET state = ? WHERE id = ?", (new_state, event_id))
        result = "通过" if approve else "驳回"
        log_action(conn, admin["id"], "审核活动", "event", event_id, result)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def cancel_event(conn, actor, event_id):
    """Cancel an event and close its registrations and waitlist."""
    event = get_event(conn, event_id)
    _check_owner(event, actor)
    if event["state"] in (EVENT_CANCELLED, EVENT_FINISHED):
        raise ServiceError("活动已取消或已结束")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE events SET state = ? WHERE id = ?", (EVENT_CANCELLED, event_id)
        )
        conn.execute(
            "UPDATE registrations SET state = ?"
            " WHERE session_id IN (SELECT id FROM sessions WHERE event_id = ?)"
            " AND state = ?",
            (EVENT_CANCELLED_REG, event_id, REGISTERED),
        )
        conn.execute(
            "UPDATE waitlist SET state = ?"
            " WHERE session_id IN (SELECT id FROM sessions WHERE event_id = ?)"
            " AND state = ?",
            (WAIT_EXPIRED, event_id, WAIT_WAITING),
        )
        log_action(conn, actor["id"], "取消活动", "event", event_id, "成功")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def expire_waitlists(conn):
    """Expire waiting entries whose event registration deadline has passed."""
    rows = conn.execute(
        "SELECT DISTINCT e.id FROM waitlist w"
        " JOIN sessions s ON s.id = w.session_id"
        " JOIN events e ON e.id = s.event_id"
        " WHERE w.state = ? AND e.state = ?",
        (WAIT_WAITING, EVENT_PUBLISHED),
    ).fetchall()
    for row in rows:
        event = get_event(conn, row["id"])
        if deadline_open(event["deadline"]):
            continue
        conn.execute(
            "UPDATE waitlist SET state = ?"
            " WHERE state = ? AND session_id IN"
            " (SELECT id FROM sessions WHERE event_id = ?)",
            (WAIT_EXPIRED, WAIT_WAITING, event["id"]),
        )
        log_action(conn, None, "候补截止失效", "event", event["id"], "成功")


def finish_due_sessions(conn):
    """Mark ended sessions absent and finish events whose sessions all ended."""
    rows = conn.execute(
        "SELECT s.id, s.event_id FROM sessions s"
        " JOIN events e ON e.id = s.event_id"
        " WHERE s.end_time < ? AND e.state = ?",
        (now_text(), EVENT_PUBLISHED),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE registrations SET state = ? WHERE session_id = ? AND state = ?",
            (ABSENT, row["id"], REGISTERED),
        )
        log_action(conn, None, "标记缺席", "session", row["id"], "成功")
        remaining = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE event_id = ? AND end_time >= ?",
            (row["event_id"], now_text()),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute(
                "UPDATE events SET state = ? WHERE id = ?",
                (EVENT_FINISHED, row["event_id"]),
            )
            log_action(conn, None, "活动结束", "event", row["event_id"], "成功")

"""Check-in use cases for authorized checkers."""

from db import log_action
from models import (
    CHECKED_IN,
    EVENT_CANCELLED,
    EVENT_FINISHED,
    EVENT_PUBLISHED,
    REGISTERED,
    ROLE_CHECKER,
    ServiceError,
    now_text,
)


def my_sessions(conn, checker):
    """Return sessions assigned to the current checker."""
    return conn.execute(
        "SELECT s.*, e.title AS event_title, e.state AS event_state"
        " FROM session_checkers sc"
        " JOIN sessions s ON s.id = sc.session_id"
        " JOIN events e ON e.id = s.event_id"
        " WHERE sc.user_id = ? ORDER BY s.start_time",
        (checker["id"],),
    ).fetchall()


def check_in(conn, checker, code):
    """Verify a credential and change the registration to checked in."""
    if checker["role"] != ROLE_CHECKER:
        raise ServiceError("只有检票人员可以核验凭证")
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT c.registration_id, r.state, r.session_id,"
            " s.event_id, s.end_time, e.state AS event_state"
            " FROM credentials c"
            " JOIN registrations r ON r.id = c.registration_id"
            " JOIN sessions s ON s.id = r.session_id"
            " JOIN events e ON e.id = s.event_id"
            " WHERE c.code = ?",
            (code,),
        ).fetchone()
        if row is None:
            log_action(conn, checker["id"], "核验凭证", "credential", None, "凭证无效")
            conn.execute("COMMIT")
            raise ServiceError("凭证无效")
        assigned = conn.execute(
            "SELECT 1 FROM session_checkers WHERE session_id = ? AND user_id = ?",
            (row["session_id"], checker["id"]),
        ).fetchone()
        if assigned is None:
            log_action(conn, checker["id"], "核验凭证", "credential", None, "无场次权限")
            conn.execute("COMMIT")
            raise ServiceError("无权核验该场次")
        if row["event_state"] in (EVENT_CANCELLED, EVENT_FINISHED):
            log_action(conn, checker["id"], "核验凭证", "credential", None, "活动不可签到")
            conn.execute("COMMIT")
            raise ServiceError("活动已取消或已结束")
        if row["event_state"] != EVENT_PUBLISHED:
            log_action(conn, checker["id"], "核验凭证", "credential", None, "活动未发布")
            conn.execute("COMMIT")
            raise ServiceError("活动当前不可签到")
        if row["state"] == CHECKED_IN:
            conn.execute(
                "INSERT INTO checkins (registration_id, checker_id, result, checked_at)"
                " VALUES (?, ?, '重复签到', ?)",
                (row["registration_id"], checker["id"], now_text()),
            )
            log_action(conn, checker["id"], "核验凭证", "registration",
                       row["registration_id"], "重复签到")
            conn.execute("COMMIT")
            return "该凭证已签到"
        if row["state"] != REGISTERED:
            log_action(conn, checker["id"], "核验凭证", "registration",
                       row["registration_id"], "状态不允许签到")
            conn.execute("COMMIT")
            raise ServiceError("当前报名状态不能签到")
        conn.execute(
            "UPDATE registrations SET state = ?, checked_in_at = ? WHERE id = ?",
            (CHECKED_IN, now_text(), row["registration_id"]),
        )
        conn.execute(
            "INSERT INTO checkins (registration_id, checker_id, result, checked_at)"
            " VALUES (?, ?, '成功', ?)",
            (row["registration_id"], checker["id"], now_text()),
        )
        log_action(conn, checker["id"], "核验凭证", "registration",
                   row["registration_id"], "成功")
        conn.execute("COMMIT")
    except ServiceError:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return "签到成功"

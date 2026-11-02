"""Statistics, CSV export, platform summary and audit log queries."""

import csv
import os

import events
import notifications
from db import log_action
from models import (
    ABSENT,
    ACTIVE_STATES,
    CHECKED_IN,
    ROLE_ADMIN,
    ROLE_ORGANIZER,
    WAIT_WAITING,
    ServiceError,
)


def _check_view(event, actor):
    """Allow the owner, an administrator; otherwise raise."""
    if actor["role"] == ROLE_ADMIN:
        return
    if actor["role"] != ROLE_ORGANIZER or event["organizer_id"] != actor["id"]:
        raise ServiceError("只能查看自己活动的数据")


def event_registrations(conn, actor, event_id, state=None):
    """Return registration rows of an event with optional state filter."""
    event = events.get_event(conn, event_id)
    _check_view(event, actor)
    sql = (
        "SELECT r.id, u.account, u.display_name, s.title AS session_title,"
        " t.name AS ticket_name, r.state, r.registered_at, r.checked_in_at,"
        " c.code"
        " FROM registrations r"
        " JOIN users u ON u.id = r.user_id"
        " JOIN sessions s ON s.id = r.session_id"
        " JOIN ticket_types t ON t.id = r.ticket_type_id"
        " LEFT JOIN credentials c ON c.registration_id = r.id"
        " WHERE s.event_id = ?"
    )
    args = [event_id]
    if state:
        sql += " AND r.state = ?"
        args.append(state)
    sql += " ORDER BY s.start_time, r.id"
    return conn.execute(sql, args).fetchall()


def event_stats(conn, actor, event_id):
    """Return capacity, registration, waitlist and attendance rows."""
    event = events.get_event(conn, event_id)
    _check_view(event, actor)
    rows = []
    for session in events.list_sessions(conn, event_id):
        for ticket in events.list_tickets(conn, session["id"]):
            active = conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE ticket_type_id = ?"
                " AND state IN (?, ?)",
                (ticket["id"], *ACTIVE_STATES),
            ).fetchone()[0]
            waiting = conn.execute(
                "SELECT COUNT(*) FROM waitlist WHERE ticket_type_id = ? AND state = ?",
                (ticket["id"], WAIT_WAITING),
            ).fetchone()[0]
            checked = conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE ticket_type_id = ?"
                " AND state = ?",
                (ticket["id"], CHECKED_IN),
            ).fetchone()[0]
            absent = conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE ticket_type_id = ?"
                " AND state = ?",
                (ticket["id"], ABSENT),
            ).fetchone()[0]
            denominator = checked + absent
            rate = f"{checked / denominator:.0%}" if denominator else "暂无数据"
            rows.append(
                {
                    "session": session["title"],
                    "ticket": ticket["name"],
                    "capacity": ticket["capacity"],
                    "registered": active,
                    "waiting": waiting,
                    "remaining": ticket["capacity"] - active,
                    "checked": checked,
                    "absent": absent,
                    "rate": rate,
                }
            )
    return rows


def export_csv(conn, actor, event_id, path):
    """Export filtered registrations to CSV; failed writes are logged."""
    rows = event_registrations(conn, actor, event_id)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["报名编号", "账号", "姓名", "场次", "票种", "状态",
                 "凭证码", "报名时间", "签到时间"]
            )
            for row in rows:
                writer.writerow(
                    [row["id"], row["account"], row["display_name"],
                     row["session_title"], row["ticket_name"], row["state"],
                     row["code"] or "", row["registered_at"],
                     row["checked_in_at"] or ""]
                )
        os.replace(temp_path, path)
    except OSError as exc:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        log_action(conn, actor["id"], "导出名单", "event", event_id, "失败")
        raise ServiceError(f"导出失败：{exc}") from exc
    log_action(conn, actor["id"], "导出名单", "event", event_id, "成功")
    return len(rows)


def platform_summary(conn, actor):
    """Return counts that the platform administrator can inspect."""
    if actor["role"] != ROLE_ADMIN:
        raise ServiceError("只有平台管理员可以查看平台汇总")
    events_by_state = conn.execute(
        "SELECT state, COUNT(*) AS total FROM events GROUP BY state"
    ).fetchall()
    registrations_by_state = conn.execute(
        "SELECT state, COUNT(*) AS total FROM registrations GROUP BY state"
    ).fetchall()
    users_by_role = conn.execute(
        "SELECT role, COUNT(*) AS total FROM users GROUP BY role"
    ).fetchall()
    checkins = conn.execute("SELECT COUNT(*) FROM checkins WHERE result = '成功'").fetchone()[0]
    return events_by_state, registrations_by_state, users_by_role, checkins


def query_logs(conn, actor, action="", limit=30):
    """Return recent operation logs, optionally filtered by action."""
    if actor["role"] != ROLE_ADMIN:
        raise ServiceError("只有平台管理员可以查询日志")
    sql = (
        "SELECT l.*, u.account FROM operation_logs l"
        " LEFT JOIN users u ON u.id = l.user_id"
        " WHERE 1 = 1"
    )
    args = []
    if action:
        sql += " AND l.action LIKE ?"
        args.append(f"%{action}%")
    sql += " ORDER BY l.id DESC LIMIT ?"
    args.append(limit)
    return conn.execute(sql, args).fetchall()


def failed_notifications(conn, actor):
    """Return failed notifications for the administrator."""
    if actor["role"] != ROLE_ADMIN:
        raise ServiceError("只有平台管理员可以查看通知")
    return conn.execute(
        "SELECT * FROM notifications WHERE status = ?", (notifications.FAILED,)
    ).fetchall()

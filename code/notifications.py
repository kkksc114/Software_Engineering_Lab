"""Notification records and manual retry."""

from db import log_action
from models import now_text

SENT = "已发送"
FAILED = "失败"


def create(conn, user_id, registration_id, kind, fail=False):
    """Store one notification after the business transaction has committed."""
    status = FAILED if fail else SENT
    conn.execute(
        "INSERT INTO notifications"
        " (user_id, registration_id, kind, status, retry_count, created_at)"
        " VALUES (?, ?, ?, ?, 0, ?)",
        (user_id, registration_id, kind, status, now_text()),
    )
    return status


def retry_failed(conn, actor):
    """Mark failed notifications as sent and return how many were retried."""
    rows = conn.execute(
        "SELECT id FROM notifications WHERE status = ?", (FAILED,)
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE notifications SET status = ?, retry_count = retry_count + 1"
            " WHERE id = ?",
            (SENT, row["id"]),
        )
    log_action(conn, actor["id"], "补发通知", "notification", None,
               f"成功 {len(rows)} 条")
    return len(rows)

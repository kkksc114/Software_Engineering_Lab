"""Unit tests for the core ticketing rules."""

# pylint: disable=missing-function-docstring

import os
import tempfile
import threading
import unittest

import auth
import checkin
import db
import events
import notifications
import registration
import reports
from models import (
    ABSENT,
    CHECKED_IN,
    EVENT_CANCELLED_REG,
    EVENT_FINISHED,
    REGISTERED,
    ROLE_CHECKER,
    ROLE_PARTICIPANT,
    WAIT_PROMOTED,
    ServiceError,
)


class ServiceTestCase(unittest.TestCase):
    """Base class that creates a fresh database for every test."""

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.conn = db.connect(self.path)
        db.init_db(self.conn)
        self.participant = auth.login(self.conn, "participant1", "123456")
        self.participant2 = auth.login(self.conn, "participant2", "123456")
        self.organizer = auth.login(self.conn, "organizer1", "123456")
        self.checker = auth.login(self.conn, "checker1", "123456")
        self.admin = auth.login(self.conn, "admin1", "123456")

    def tearDown(self):
        self.conn.close()
        os.unlink(self.path)

    def add_participant(self, account):
        """Create one more participant and return its row."""
        user_id = db.add_user(self.conn, account, account, "123456", ROLE_PARTICIPANT)
        return self.conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    def code_of(self, registration_id):
        """Return the credential code of a registration."""
        row = self.conn.execute(
            "SELECT code FROM credentials WHERE registration_id = ?",
            (registration_id,),
        ).fetchone()
        return row["code"]

    def state_of(self, registration_id):
        """Return the current state of a registration."""
        row = self.conn.execute(
            "SELECT state FROM registrations WHERE id = ?", (registration_id,)
        ).fetchone()
        return row["state"]

    def register(self, user, request_id=None):
        """Register for session 1, ticket 1."""
        row, _, _ = registration.register(self.conn, user, 1, 1, request_id)
        return row["id"]


class RegistrationTests(ServiceTestCase):
    """Capacity, waitlist and idempotency rules."""

    def test_capacity_and_waitlist_promotion(self):
        first = self.register(self.participant, "r1")
        self.register(self.participant2, "r2")
        third = self.add_participant("participant3")
        with self.assertRaises(ServiceError):
            self.register(third, "r3")
        _, position, _ = registration.join_waitlist(self.conn, third, 1, 1)
        self.assertEqual(position, 1)
        registration.cancel_registration(self.conn, self.participant, first)
        promoted = self.conn.execute(
            "SELECT * FROM registrations WHERE user_id = ?", (third["id"],)
        ).fetchone()
        self.assertEqual(promoted["state"], REGISTERED)
        entry = self.conn.execute(
            "SELECT state FROM waitlist WHERE user_id = ?", (third["id"],)
        ).fetchone()
        self.assertEqual(entry["state"], WAIT_PROMOTED)
        self.assertEqual(events.session_occupied(self.conn, 1), 2)

    def test_idempotent_request_returns_first_result(self):
        first = self.register(self.participant, "same-request")
        again = self.register(self.participant, "same-request")
        self.assertEqual(first, again)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM registrations WHERE request_id = 'same-request'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_deadline_and_duplicate_registration(self):
        self.conn.execute(
            "UPDATE events SET deadline = '2000-01-01 00:00:00' WHERE id = 1"
        )
        with self.assertRaises(ServiceError):
            self.register(self.participant, "late")
        self.conn.execute(
            "UPDATE events SET deadline = '2099-01-01 00:00:00' WHERE id = 1"
        )
        self.register(self.participant, "ok")
        with self.assertRaises(ServiceError):
            self.register(self.participant, "another")

    def test_cancel_twice_is_rejected(self):
        registration_id = self.register(self.participant, "cancel-once")
        registration.cancel_registration(self.conn, self.participant, registration_id)
        with self.assertRaises(ServiceError):
            registration.cancel_registration(
                self.conn, self.participant, registration_id
            )


class CheckInTests(ServiceTestCase):
    """Check-in permissions and duplicate handling."""

    def test_check_in_is_unique(self):
        registration_id = self.register(self.participant, "checkin")
        code = self.code_of(registration_id)
        self.assertEqual(checkin.check_in(self.conn, self.checker, code), "签到成功")
        self.assertEqual(checkin.check_in(self.conn, self.checker, code), "该凭证已签到")
        self.assertEqual(self.state_of(registration_id), CHECKED_IN)
        total = self.conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
        self.assertEqual(total, 2)

    def test_checker_without_session_permission_is_rejected(self):
        registration_id = self.register(self.participant, "checkin")
        code = self.code_of(registration_id)
        other_id = db.add_user(self.conn, "checker2", "检票员小周", "123456", ROLE_CHECKER)
        other = self.conn.execute(
            "SELECT * FROM users WHERE id = ?", (other_id,)
        ).fetchone()
        with self.assertRaises(ServiceError):
            checkin.check_in(self.conn, other, code)
        self.assertEqual(self.state_of(registration_id), REGISTERED)


class EventLifecycleTests(ServiceTestCase):
    """Cancellation, absence and permission rules."""

    def test_cancel_event_keeps_checked_in_history(self):
        first = self.register(self.participant, "e1")
        second = self.register(self.participant2, "e2")
        checkin.check_in(self.conn, self.checker, self.code_of(first))
        events.cancel_event(self.conn, self.organizer, 1)
        self.assertEqual(self.state_of(first), CHECKED_IN)
        self.assertEqual(self.state_of(second), EVENT_CANCELLED_REG)

    def test_finished_session_marks_absent(self):
        registration_id = self.register(self.participant, "absent")
        self.conn.execute(
            "UPDATE sessions SET end_time = '2000-01-01 00:00:00' WHERE id = 1"
        )
        events.finish_due_sessions(self.conn)
        self.assertEqual(self.state_of(registration_id), ABSENT)
        state = self.conn.execute("SELECT state FROM events WHERE id = 1").fetchone()[0]
        self.assertEqual(state, EVENT_FINISHED)

    def test_role_permissions(self):
        with self.assertRaises(ServiceError):
            events.create_event(
                self.conn, self.participant, "越权", "南京", "音乐",
                "2099-01-01 00:00:00", "场次", "2099-02-01 00:00:00",
                "2099-02-01 02:00:00", 10,
            )
        with self.assertRaises(ServiceError):
            events.review_event(self.conn, self.organizer, 1, True)
        with self.assertRaises(ServiceError):
            reports.event_stats(self.conn, self.participant, 1)


class ReportingTests(ServiceTestCase):
    """CSV export, audit queries and notification retry."""

    def test_export_and_audit_log(self):
        self.register(self.participant, "export")
        path = self.path + ".csv"
        count = reports.export_csv(self.conn, self.organizer, 1, path)
        self.assertEqual(count, 1)
        with open(path, encoding="utf-8-sig") as handle:
            lines = handle.read().splitlines()
        self.assertIn("凭证码", lines[0])
        os.unlink(path)
        logs = reports.query_logs(self.conn, self.admin, "导出名单")
        self.assertEqual(logs[0]["result"], "成功")

    def test_retry_failed_notification(self):
        before = reports.failed_notifications(self.conn, self.admin)
        self.assertGreaterEqual(len(before), 1)
        notifications.retry_failed(self.conn, self.admin)
        after = reports.failed_notifications(self.conn, self.admin)
        self.assertEqual(len(after), 0)


class ConcurrencyTests(ServiceTestCase):
    """Only one request may win the last seat."""

    def test_last_seat_is_not_oversold(self):
        events.adjust_ticket_capacity(self.conn, self.organizer, 1, 1)
        barrier = threading.Barrier(2)
        results = []

        def worker(account):
            conn = db.connect(self.path)
            try:
                user = auth.login(conn, account, "123456")
                barrier.wait()
                registration.register(conn, user, 1, 1, f"race-{account}")
                results.append("ok")
            except Exception as exc:  # pylint: disable=broad-except
                results.append(str(exc))
            finally:
                conn.close()

        threads = [
            threading.Thread(target=worker, args=(account,))
            for account in ("participant1", "participant2")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(events.session_occupied(self.conn, 1), 1)


if __name__ == "__main__":
    unittest.main()

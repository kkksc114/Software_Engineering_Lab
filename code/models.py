"""Shared constants, exceptions and small helpers."""

from datetime import datetime

ROLE_PARTICIPANT = "参与者"
ROLE_ORGANIZER = "组织者"
ROLE_CHECKER = "检票人员"
ROLE_ADMIN = "平台管理员"

EVENT_DRAFT = "草稿"
EVENT_PENDING = "待审核"
EVENT_REJECTED = "审核驳回"
EVENT_PUBLISHED = "已发布"
EVENT_CANCELLED = "已取消"
EVENT_FINISHED = "已结束"

REGISTERED = "已报名"
WAITLISTED = "候补中"
CANCELLED = "已取消"
CHECKED_IN = "已签到"
ABSENT = "缺席"
EVENT_CANCELLED_REG = "活动取消"
WAITLIST_EXPIRED = "候补失效"

WAIT_WAITING = "排队中"
WAIT_PROMOTED = "已递补"
WAIT_EXPIRED = "已失效"

ACTIVE_STATES = (REGISTERED, CHECKED_IN)


class ServiceError(Exception):
    """Raised when a business rule rejects an operation."""


def now_text():
    """Return the current local time as a sortable string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_time(text):
    """Parse a timestamp written by now_text."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def deadline_open(deadline):
    """Return True when the registration deadline has not passed."""
    return datetime.now() < parse_time(deadline)

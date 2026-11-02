"""Login and role checks."""

from db import hash_password
from models import ServiceError


def login(conn, account, password):
    """Return the user row when the account and password match."""
    row = conn.execute(
        "SELECT * FROM users WHERE account = ? AND active = 1", (account,)
    ).fetchone()
    if row is None:
        raise ServiceError("账号或密码错误")
    digest, _ = hash_password(password, row["salt"])
    if digest != row["password_hash"]:
        raise ServiceError("账号或密码错误")
    return row


def require_role(user, *roles):
    """Raise when the user does not hold one of the allowed roles."""
    if user["role"] not in roles:
        raise ServiceError("当前角色无权执行该操作")

"""Command line entry point for the ticketing system."""

import os
import sys
from datetime import datetime

import auth
import checkin
import db
import events
import registration
from models import (
    EVENT_REJECTED,
    ROLE_ADMIN,
    ROLE_CHECKER,
    ROLE_ORGANIZER,
    ROLE_PARTICIPANT,
    ServiceError,
)

DB_PATH = os.environ.get(
    "TICKET_DB", os.path.join(os.path.dirname(__file__), "..", "data", "ticket.db")
)


def ask(prompt):
    """Read one non-empty line from the terminal."""
    value = input(prompt).strip()
    return value


def ask_int(prompt):
    """Read an integer with a friendly retry loop."""
    while True:
        value = ask(prompt)
        try:
            return int(value)
        except ValueError:
            print("请输入整数")


def ask_time(prompt):
    """Read a timestamp in YYYY-MM-DD HH:MM format."""
    while True:
        value = ask(prompt)
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M").strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            print("格式应为 YYYY-MM-DD HH:MM")


def show_event(conn, event):
    """Print one event with sessions, tickets and remaining seats."""
    print(f"\n[{event['id']}] {event['title']}  {event['city']} / {event['category']}")
    print(f"状态：{event['state']}  报名截止：{event['deadline']}")
    for session in events.list_sessions(conn, event["id"]):
        occupied = events.session_occupied(conn, session["id"])
        print(f"  场次 {session['id']}：{session['title']}  "
              f"{session['start_time']} - {session['end_time']}  "
              f"容量 {session['capacity']} 已占 {occupied}")
        for ticket in events.list_tickets(conn, session["id"]):
            used = events.ticket_occupied(conn, ticket["id"])
            print(f"    票种 {ticket['id']}：{ticket['name']}  "
                  f"容量 {ticket['capacity']} 已占 {used}")


def browse_events(conn):
    """Search published events."""
    keyword = ask("关键词（可空）：")
    city = ask("城市（可空）：")
    category = ask("类别（可空）：")
    rows = events.search_events(conn, keyword, city, category)
    if not rows:
        print("没有符合条件的活动")
        return
    for event in rows:
        print(f"[{event['id']}] {event['title']}  {event['city']}  "
              f"{event['category']}  截止 {event['deadline']}")


def view_event(conn):
    """Show the detail of one event."""
    event_id = ask_int("活动编号：")
    show_event(conn, events.get_event(conn, event_id))


def my_events(conn, user):
    """List events created by the current organizer."""
    rows = conn.execute(
        "SELECT * FROM events WHERE organizer_id = ? ORDER BY id DESC", (user["id"],)
    ).fetchall()
    if not rows:
        print("还没有创建活动")
        return
    for event in rows:
        print(f"[{event['id']}] {event['title']}  状态：{event['state']}")


def create_event(conn, user):
    """Interactive wizard for a new event."""
    title = ask("活动名称：")
    city = ask("城市：")
    category = ask("类别：")
    deadline = ask_time("报名截止（YYYY-MM-DD HH:MM）：")
    session_title = ask("场次名称：")
    start = ask_time("场次开始（YYYY-MM-DD HH:MM）：")
    end = ask_time("场次结束（YYYY-MM-DD HH:MM）：")
    capacity = ask_int("名额：")
    event_id = events.create_event(
        conn, user, title, city, category, deadline,
        session_title, start, end, capacity
    )
    print("活动已创建，编号", event_id, "，当前为草稿")


def submit_review(conn, user):
    """Submit one of the organizer's events for review."""
    my_events(conn, user)
    event_id = ask_int("要提交审核的活动编号：")
    events.submit_review(conn, user, event_id)
    print("已提交审核")


def add_session(conn, user):
    """Add a session to an editable event."""
    my_events(conn, user)
    event_id = ask_int("活动编号：")
    title = ask("场次名称：")
    start = ask_time("开始（YYYY-MM-DD HH:MM）：")
    end = ask_time("结束（YYYY-MM-DD HH:MM）：")
    capacity = ask_int("名额：")
    events.add_session(conn, user, event_id, title, start, end, capacity)
    print("场次已添加")


def add_ticket(conn, user):
    """Add a ticket type to a session."""
    session_id = ask_int("场次编号：")
    name = ask("票种名称：")
    capacity = ask_int("名额：")
    events.add_ticket(conn, user, session_id, name, capacity)
    print("票种已添加")


def adjust_capacity(conn, user):
    """Change a ticket capacity."""
    ticket_id = ask_int("票种编号：")
    capacity = ask_int("新容量：")
    events.adjust_ticket_capacity(conn, user, ticket_id, capacity)
    print("容量已调整")


def cancel_event(conn, user):
    """Cancel an event."""
    event_id = ask_int("要取消的活动编号：")
    events.cancel_event(conn, user, event_id)
    print("活动已取消")


def pending_events(conn):
    """List events waiting for review."""
    rows = conn.execute(
        "SELECT * FROM events WHERE state = '待审核' ORDER BY id"
    ).fetchall()
    if not rows:
        print("没有待审核活动")
        return
    for event in rows:
        print(f"[{event['id']}] {event['title']}  组织者 {event['organizer_id']}")


def review_event(conn, user):
    """Approve or reject a pending event."""
    pending_events(conn)
    event_id = ask_int("活动编号：")
    choice = ask("1 通过  2 驳回：")
    events.review_event(conn, user, event_id, choice == "1")
    print("审核完成")


def do_register(conn, user):
    """Register for a session and ticket."""
    event_id = ask_int("活动编号：")
    show_event(conn, events.get_event(conn, event_id))
    session_id = ask_int("场次编号：")
    ticket_id = ask_int("票种编号：")
    request_id = ask("请求编号（可空，用于重复提交测试）：") or None
    _, code, message = registration.register(
        conn, user, session_id, ticket_id, request_id
    )
    print(message, "凭证码：", code)


def do_waitlist(conn, user):
    """Join the waitlist of a full session."""
    event_id = ask_int("活动编号：")
    show_event(conn, events.get_event(conn, event_id))
    session_id = ask_int("场次编号：")
    ticket_id = ask_int("票种编号：")
    _, position, message = registration.join_waitlist(
        conn, user, session_id, ticket_id
    )
    print(message, "当前候补位置：", position)


def show_my_registrations(conn, user):
    """Print the current user's registrations."""
    rows = registration.my_registrations(conn, user)
    if not rows:
        print("还没有报名记录")
        return
    for row in rows:
        print(f"[{row['id']}] {row['title']} / {row['session_title']}"
              f" / {row['ticket_name']}  状态：{row['state']}"
              f"  凭证：{row['code'] or '-'}")


def do_cancel(conn, user):
    """Cancel one own registration."""
    show_my_registrations(conn, user)
    registration_id = ask_int("要取消的报名编号：")
    promoted = registration.cancel_registration(conn, user, registration_id)
    print("已取消")
    if promoted:
        print(f"候补用户 {promoted['user_id']} 已自动递补，"
              f"凭证码 {promoted['code']}")


def participant_menu(conn, user):
    """Participant menu."""
    while True:
        print("\n1 查询活动  2 活动详情  3 报名  4 登记候补"
              "  5 取消报名  6 我的报名  0 退出")
        choice = ask("请选择：")
        try:
            if choice == "1":
                browse_events(conn)
            elif choice == "2":
                view_event(conn)
            elif choice == "3":
                do_register(conn, user)
            elif choice == "4":
                do_waitlist(conn, user)
            elif choice == "5":
                do_cancel(conn, user)
            elif choice == "6":
                show_my_registrations(conn, user)
            elif choice == "0":
                return
        except ServiceError as exc:
            print("操作失败：", exc)


def organizer_menu(conn, user):
    """Organizer menu."""
    while True:
        print("\n1 我的活动  2 创建活动  3 提交审核  4 新增场次  5 新增票种"
              "  6 调整名额  7 取消活动  0 退出")
        choice = ask("请选择：")
        try:
            if choice == "1":
                my_events(conn, user)
            elif choice == "2":
                create_event(conn, user)
            elif choice == "3":
                submit_review(conn, user)
            elif choice == "4":
                add_session(conn, user)
            elif choice == "5":
                add_ticket(conn, user)
            elif choice == "6":
                adjust_capacity(conn, user)
            elif choice == "7":
                cancel_event(conn, user)
            elif choice == "0":
                return
        except ServiceError as exc:
            print("操作失败：", exc)


def show_checker_sessions(conn, user):
    """Print sessions assigned to the checker."""
    rows = checkin.my_sessions(conn, user)
    if not rows:
        print("没有分配检票场次")
        return
    for row in rows:
        print(f"场次 {row['id']}：{row['event_title']} / {row['title']}"
              f"  {row['start_time']}  状态：{row['event_state']}")


def do_checkin(conn, user):
    """Verify a credential code."""
    code = ask("凭证码：")
    print(checkin.check_in(conn, user, code))


def checker_menu(conn, user):
    """Checker menu."""
    while True:
        print("\n1 我的场次  2 核验凭证  0 退出")
        choice = ask("请选择：")
        try:
            if choice == "1":
                show_checker_sessions(conn, user)
            elif choice == "2":
                do_checkin(conn, user)
            elif choice == "0":
                return
        except ServiceError as exc:
            print("操作失败：", exc)


def admin_menu(conn, user):
    """Administrator menu."""
    while True:
        print("\n1 待审核活动  2 审核活动  3 取消活动  0 退出")
        choice = ask("请选择：")
        try:
            if choice == "1":
                pending_events(conn)
            elif choice == "2":
                review_event(conn, user)
            elif choice == "3":
                cancel_event(conn, user)
            elif choice == "0":
                return
        except ServiceError as exc:
            print("操作失败：", exc)


MENUS = {
    ROLE_PARTICIPANT: participant_menu,
    ROLE_ORGANIZER: organizer_menu,
    ROLE_CHECKER: checker_menu,
    ROLE_ADMIN: admin_menu,
}


def login_loop(conn):
    """Ask for credentials until the user quits."""
    while True:
        print("\n活动票务与报名系统")
        print("演示账号：participant1 / organizer1 / checker1 / admin1，密码均为 123456")
        account = ask("账号（直接回车退出）：")
        if not account:
            return False
        password = ask("密码：")
        try:
            user = auth.login(conn, account, password)
        except ServiceError as exc:
            print("登录失败：", exc)
            continue
        print(f"欢迎，{user['display_name']}（{user['role']}）")
        MENUS[user["role"]](conn, user)
        return True


def main():
    """Initialize the database and start the login loop."""
    db_file = os.path.abspath(DB_PATH)
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    conn = db.connect(db_file)
    db.init_db(conn)
    events.expire_waitlists(conn)
    events.finish_due_sessions(conn)
    try:
        login_loop(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

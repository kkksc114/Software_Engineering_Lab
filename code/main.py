"""Activity ticketing and registration prototype.

AI first draft: everything is kept in memory and only the happy path works.
"""

import random
import string

ACCOUNTS = {
    "participant1": ("123456", "参与者"),
    "organizer1": ("123456", "组织者"),
    "checker1": ("123456", "检票人员"),
    "admin1": ("123456", "平台管理员"),
}

EVENTS = []
REGISTRATIONS = []


def make_code():
    """Return a random six-character credential code."""
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def login():
    """Ask for an account and return the matching user tuple."""
    account = input("账号：").strip()
    password = input("密码：").strip()
    if account not in ACCOUNTS or ACCOUNTS[account][0] != password:
        print("账号或密码错误")
        return None
    return account, ACCOUNTS[account][1]


def find_event(event_id):
    """Find an event by id."""
    for event in EVENTS:
        if event["id"] == event_id:
            return event
    return None


def create_event(account):
    """Create a published event with one session and one ticket type."""
    title = input("活动名称：").strip()
    city = input("城市：").strip()
    capacity = int(input("名额：").strip())
    event = {
        "id": len(EVENTS) + 1,
        "title": title,
        "city": city,
        "organizer": account,
        "state": "已发布",
        "sessions": [
            {
                "id": len(EVENTS) * 10 + 1,
                "title": "默认场次",
                "capacity": capacity,
                "tickets": [{"id": 1, "name": "普通票", "capacity": capacity}],
            }
        ],
    }
    EVENTS.append(event)
    print("活动已创建，编号", event["id"])


def show_events():
    """Print all published events."""
    for event in EVENTS:
        if event["state"] == "已发布":
            print(f"[{event['id']}] {event['title']}  {event['city']}")


def count_registered(session_id):
    """Count registrations that still occupy a seat."""
    total = 0
    for item in REGISTRATIONS:
        if item["session_id"] == session_id and item["state"] == "已报名":
            total += 1
    return total


def register(account):
    """Register the current user for a session."""
    show_events()
    event_id = int(input("活动编号：").strip())
    event = find_event(event_id)
    if event is None:
        print("活动不存在")
        return
    session = event["sessions"][0]
    if count_registered(session["id"]) >= session["capacity"]:
        print("名额已满")
        return
    for item in REGISTRATIONS:
        if item["user"] == account and item["session_id"] == session["id"]:
            print("已经报名过该场次")
            return
    code = make_code()
    REGISTRATIONS.append(
        {
            "user": account,
            "event_id": event_id,
            "session_id": session["id"],
            "state": "已报名",
            "code": code,
        }
    )
    print("报名成功，凭证码：", code)


def my_registrations(account):
    """Print the current user's registrations."""
    for item in REGISTRATIONS:
        if item["user"] == account:
            event = find_event(item["event_id"])
            print(f"{event['title']}  {item['state']}  凭证 {item['code']}")


def cancel(account):
    """Cancel one of the current user's registrations."""
    my_registrations(account)
    code = input("要取消的凭证码：").strip()
    for item in REGISTRATIONS:
        if item["code"] == code and item["user"] == account:
            item["state"] = "已取消"
            print("已取消")
            return
    print("没有找到该报名")


def check_in():
    """Check in a registration by credential code."""
    code = input("凭证码：").strip()
    for item in REGISTRATIONS:
        if item["code"] == code:
            if item["state"] == "已签到":
                print("已签到")
            else:
                item["state"] = "已签到"
                print("签到成功")
            return
    print("凭证无效")


def participant_menu(account):
    """Menu for participants."""
    while True:
        print("\n1 查看活动  2 报名  3 我的报名  4 取消报名  0 退出")
        choice = input("请选择：").strip()
        if choice == "1":
            show_events()
        elif choice == "2":
            register(account)
        elif choice == "3":
            my_registrations(account)
        elif choice == "4":
            cancel(account)
        elif choice == "0":
            return


def organizer_menu(account):
    """Menu for organizers."""
    while True:
        print("\n1 创建活动  2 查看活动  0 退出")
        choice = input("请选择：").strip()
        if choice == "1":
            create_event(account)
        elif choice == "2":
            show_events()
        elif choice == "0":
            return


def checker_menu():
    """Menu for checkers."""
    while True:
        print("\n1 核验凭证  0 退出")
        choice = input("请选择：").strip()
        if choice == "1":
            check_in()
        elif choice == "0":
            return


def admin_menu():
    """Menu for platform administrators."""
    while True:
        print("\n1 查看活动  0 退出")
        choice = input("请选择：").strip()
        if choice == "1":
            show_events()
        elif choice == "0":
            return


def main():
    """Run the command line prototype."""
    print("活动票务与报名系统（AI 初稿）")
    user = login()
    if user is None:
        return
    account, role = user
    if role == "参与者":
        participant_menu(account)
    elif role == "组织者":
        organizer_menu(account)
    elif role == "检票人员":
        checker_menu()
    else:
        admin_menu()


if __name__ == "__main__":
    main()

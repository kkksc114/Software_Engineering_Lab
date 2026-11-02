# 活动票务与报名系统（实验三实现）

纯 Python 标准库 + SQLite + 命令行界面，不需要安装第三方依赖。

## 运行

```bash
cd code
python3 main.py
```

演示账号（密码均为 `123456`）：

| 账号 | 角色 |
| --- | --- |
| participant1 / participant2 | 参与者 |
| organizer1 | 组织者 |
| checker1 | 检票人员 |
| admin1 | 平台管理员 |

首次运行会在仓库根目录生成 `data/ticket.db` 并写入演示活动。

## 已实现功能

- 四类角色登录与数据范围校验
- 活动的草稿、提交审核、通过、驳回、发布、取消与结束
- 场次、票种与容量维护，容量不得低于已占用数
- 报名、重复报名拦截、请求幂等、报名截止校验
- 满额候补、按队列自动递补、截止后候补失效
- 凭证码、检票核验、重复签到提示、场次结束标记缺席
- 活动取消后的记录处理与关键操作日志
- 条件查询、容量与签到率统计、CSV 名单导出
- 通知失败记录与管理端补发

## 测试

```bash
cd code
python3 -m unittest discover -s tests -v
```

## 代码规范

```bash
python3 -m pylint main.py db.py models.py auth.py events.py \
    registration.py checkin.py notifications.py reports.py
```

## 目录

- `main.py`：命令行界面与菜单
- `db.py`：SQLite 连接、表结构与演示数据
- `models.py`：角色、状态常量和公共异常
- `auth.py`：登录与角色校验
- `events.py`：活动、场次、票种与生命周期
- `registration.py`：报名、候补、递补与取消
- `checkin.py`：检票核验
- `reports.py`：统计、CSV、平台汇总与日志
- `notifications.py`：通知记录与补发
- `tests/`：核心规则单元测试

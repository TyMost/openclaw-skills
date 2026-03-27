#!/usr/bin/env python3
"""Feishu Task v2 API CLI - manage tasks, members, reminders, tasklists."""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta

BASE_URL = "https://open.feishu.cn/open-apis"
TOKEN_FILE = os.path.expanduser("~/.openclaw/credentials/feishu-user-token.json")
APP_ID = "YOUR_APP_ID"
APP_SECRET = "YOUR_APP_SECRET"

# ─── Time parsing ───────────────────────────────────────────────────────────

def parse_time(text):
    """Parse natural language time to (timestamp_ms, is_all_day) or None."""
    if not text:
        return None
    text = text.strip()

    # Raw milliseconds
    if re.match(r"^\d{13}$", text):
        return int(text), False

    # ISO-like: 2024-03-20 15:00 or 2024-03-20
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{1,2}):(\d{2}))?$", text)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        if m[4]:
            h, mi = int(m[4]), int(m[5])
            dt = datetime(y, mo, d, h, mi)
            return int(dt.timestamp() * 1000), False
        else:
            dt = datetime(y, mo, d)
            # all-day: use UTC midnight timestamp
            return int(dt.timestamp() * 1000), True

    now = datetime.now()
    weekday_names = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
    weekday_en = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

    text_lower = text.lower()

    # Extract time if present (e.g., "明天14:00" -> date="明天", time="14:00")
    time_match = re.search(r"(\d{1,2})[:：](\d{2})", text)
    hour, minute = None, None
    if time_match:
        hour, minute = int(time_match[1]), int(time_match[2])
        is_all_day = False
        text_base = re.sub(r"\s*\d{1,2}[:：]\d{2}", "", text).strip()
    else:
        is_all_day = True
        text_base = text

    target_date = None

    # "今天", "明天", "后天"
    if text_base == "今天":
        target_date = now
    elif text_base == "明天":
        target_date = now + timedelta(days=1)
    elif text_base == "后天":
        target_date = now + timedelta(days=2)
    # "N天后"
    m = re.match(r"(\d+)\s*天后?", text_base)
    if m:
        target_date = now + timedelta(days=int(m[1]))
    # "N小时后"
    m = re.match(r"(\d+)\s*小时后?", text_base)
    if m:
        target_date = now + timedelta(hours=int(m[1]))
        is_all_day = False
    # "N分钟后"
    m = re.match(r"(\d+)\s*分钟?", text_base)
    if m:
        target_date = now + timedelta(minutes=int(m[1]))
        is_all_day = False
    # "下周一/二/..."
    m = re.match(r"下周([一二三四五六日])", text_base)
    if m:
        day_want = weekday_names.get(m[1], 0)
        days_ahead = (day_want - now.weekday() + 7) % 7 or 7
        target_date = now + timedelta(days=days_ahead)
    # "下周一 14:00" style (time already extracted)
    m = re.match(r"下?周([一二三四五六日])", text_base)
    if m and not target_date:
        day_want = weekday_names.get(m[1], 0)
        days_ahead = (day_want - now.weekday() + 7) % 7 or 7
        target_date = now + timedelta(days=days_ahead)

    if target_date:
        if is_all_day:
            dt = datetime(target_date.year, target_date.month, target_date.day)
            return int(dt.timestamp() * 1000), True
        else:
            dt = target_date.replace(hour=hour or 9, minute=minute or 0, second=0)
            return int(dt.timestamp() * 1000), False

    return None


# ─── Token management ───────────────────────────────────────────────────────

def load_token():
    with open(TOKEN_FILE) as f:
        return json.load(f)


def save_token(data):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_access_token():
    data = load_token()
    if time.time() - data.get("created_at", 0) < data.get("expires_in", 0) - 300:
        return data["access_token"]
    # Step 1: Get app_access_token (required for refreshing user token)
    app_url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
    app_body = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
    app_req = urllib.request.Request(app_url, data=app_body, headers={"Content-Type": "application/json"})
    try:
        app_resp = urllib.request.urlopen(app_req, timeout=10)
        app_result = json.loads(app_resp.read())
        if app_result.get("code") != 0:
            print(f"App token failed: {app_result}", file=sys.stderr)
            return get_tenant_token()
        app_token = app_result["app_access_token"]
    except Exception as e:
        print(f"App token error: {e}", file=sys.stderr)
        return get_tenant_token()
    # Step 2: Refresh user token with app_access_token
    url = "https://open.feishu.cn/open-apis/authen/v1/oidc/refresh_access_token"
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": data["refresh_token"],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {app_token}"})
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        if result.get("code") != 0:
            print(f"Refresh failed: {result}", file=sys.stderr)
            return get_tenant_token()
        new_data = result["data"]
        data["access_token"] = new_data["access_token"]
        data["refresh_token"] = new_data.get("refresh_token", data["refresh_token"])
        data["expires_in"] = new_data.get("expires_in", 7200)
        data["created_at"] = int(time.time())
        data["token_type"] = "Bearer"
        save_token(data)
        return data["access_token"]
    except Exception as e:
        print(f"Token refresh error: {e}", file=sys.stderr)
        return get_tenant_token()


def get_tenant_token():
    """Fallback: get tenant_access_token."""
    url = f"https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    body = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    return result["tenant_access_token"]


# ─── HTTP helpers ───────────────────────────────────────────────────────────

def api(method, path, body=None, params=None):
    token = get_access_token()
    url = f"{BASE_URL}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
        if qs:
            url += f"?{qs}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        result = json.loads(e.read())
    return result


def format_time(ts_str, is_all_day=False):
    if not ts_str or ts_str == "0":
        return ""
    ts = int(ts_str)
    if is_all_day:
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d (全天)")
    return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")


def format_task(task):
    """Pretty-print a task."""
    lines = []
    name = task.get("summary", "?")
    guid = task.get("guid", "")
    status = task.get("status", "")
    completed = task.get("completed_at", "0") != "0"

    icon = "✅" if completed else "⬜"
    if task.get("is_milestone"):
        icon = "🏁"
    lines.append(f"{icon} {name}  [{guid[:8]}]")

    if task.get("description"):
        lines.append(f"   📝 {task['description']}")
    if task.get("extra"):
        lines.append(f"   🏷️  extra: {task['extra']}")

    due = task.get("due")
    start = task.get("start")
    if start:
        lines.append(f"   🕐 开始: {format_time(start.get('timestamp', '0'), start.get('is_all_day'))}")
    if due:
        lines.append(f"   ⏰ 截止: {format_time(due.get('timestamp', '0'), due.get('is_all_day'))}")

    members = task.get("members", [])
    if members:
        roles = []
        for m in members:
            roles.append(f"{m['id'][:12]}({m['role']})")
        lines.append(f"   👥 {', '.join(roles)}")

    tasklists = task.get("tasklists", [])
    if tasklists:
        tl_names = [t.get("name", t.get("guid", "?")[:8]) for t in tasklists]
        lines.append(f"   📋 分组: {', '.join(tl_names)}")

    if task.get("parent_task_guid"):
        lines.append(f"   🔗 父任务: {task['parent_task_guid'][:8]}")
    if task.get("repeat_rule"):
        lines.append(f"   🔁 重复: {task['repeat_rule']}")
    if task.get("url"):
        lines.append(f"   🔗 {task['url']}")

    return "\n".join(lines)


# ─── Actions ────────────────────────────────────────────────────────────────

def cmd_create(args):
    task = {"summary": args.summary}
    if args.desc:
        task["description"] = args.desc
    if args.milestone:
        task["is_milestone"] = True
    if args.repeat:
        task["repeat_rule"] = args.repeat
    if args.parent:
        task["parent_task_guid"] = args.parent

    if args.start:
        t = parse_time(args.start)
        if t:
            task["start"] = {"timestamp": str(t[0]), "is_all_day": t[1]}

    if args.due:
        t = parse_time(args.due)
        if t:
            task["due"] = {"timestamp": str(t[0]), "is_all_day": t[1]}

    if args.priority is not None:
        task["extra"] = json.dumps({"priority": int(args.priority)})

    # Members
    members = []
    if args.assignee:
        members.append({"id": args.assignee, "type": "user", "role": "assignee"})
    if args.follower:
        members.append({"id": args.follower, "type": "user", "role": "follower"})
    if members:
        task["members"] = members

    # Reminders (only works if due is set)
    if args.reminder and args.due:
        task["reminders"] = [{"relative_fire_minute": int(args.reminder)}]

    # Tasklists
    if args.tasklist:
        task["tasklists"] = [{"tasklist_guid": args.tasklist}]

    body = {}
    body.update(task)
    if args.idempotent:
        body["client_token"] = args.idempotent

    result = api("POST", "/task/v2/tasks", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    task_data = result["data"]["task"]
    print(format_task(task_data))
    return task_data


def cmd_get(args):
    result = api("GET", f"/task/v2/tasks/{args.guid}")
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(format_task(result["data"]["task"]))
    # Also print raw JSON for full details
    if args.raw:
        print("\n--- Raw JSON ---")
        print(json.dumps(result["data"]["task"], indent=2, ensure_ascii=False))


def cmd_list(args):
    params = {"page_size": str(args.page_size or 50)}
    result = api("GET", "/task/v2/tasks", params=params)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    items = result["data"].get("items", [])
    if not items:
        print("No tasks found.")
    for t in items:
        print(format_task(t))
        print()


def cmd_update(args):
    update_fields = []
    task = {}
    if args.summary:
        task["summary"] = args.summary
        update_fields.append("summary")
    if args.desc is not None:
        task["description"] = args.desc if args.desc else ""
        update_fields.append("description")
    if args.due:
        t = parse_time(args.due)
        if t:
            task["due"] = {"timestamp": str(t[0]), "is_all_day": t[1]}
            update_fields.append("due")
    elif args.clear_due:
        task["due"] = {"timestamp": "0"}
        update_fields.append("due")
    if args.start:
        t = parse_time(args.start)
        if t:
            task["start"] = {"timestamp": str(t[0]), "is_all_day": t[1]}
            update_fields.append("start")
    elif args.due:
        # If only due is set and start exists, align is_all_day
        pass
    # Ensure start and due have same is_all_day
    if "start" in task and "due" in task:
        task["start"]["is_all_day"] = task["due"]["is_all_day"]
        task["due"]["is_all_day"] = task["start"]["is_all_day"]
    if args.priority is not None:
        task["extra"] = json.dumps({"priority": int(args.priority)})
        update_fields.append("extra")
    if args.milestone:
        task["is_milestone"] = True
        update_fields.append("is_milestone")
    if args.no_milestone:
        task["is_milestone"] = False
        update_fields.append("is_milestone")
    if args.repeat is not None:
        task["repeat_rule"] = args.repeat if args.repeat else ""
        update_fields.append("repeat_rule")

    if not update_fields:
        print("Nothing to update. Use --summary, --desc, --due, etc.", file=sys.stderr)
        sys.exit(1)

    body = {"task": task, "update_fields": update_fields}
    result = api("PATCH", f"/task/v2/tasks/{args.guid}", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(format_task(result["data"]["task"]))


def cmd_delete(args):
    result = api("DELETE", f"/task/v2/tasks/{args.guid}")
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"Task {args.guid[:8]} deleted.")


def cmd_done(args):
    ts = str(int(time.time() * 1000))
    body = {"task": {"completed_at": ts}, "update_fields": ["completed_at"]}
    result = api("PATCH", f"/task/v2/tasks/{args.guid}", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Task completed: {result['data']['task']['summary']}")


def cmd_undo(args):
    body = {"task": {"completed_at": "0"}, "update_fields": ["completed_at"]}
    result = api("PATCH", f"/task/v2/tasks/{args.guid}", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"↩️ Task restored: {result['data']['task']['summary']}")


def cmd_add_member(args):
    role = args.role or "assignee"
    body = {"members": [{"id": args.user, "type": "user", "role": role}]}
    result = api("POST", f"/task/v2/tasks/{args.guid}/add_members", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"Added {args.user[:12]} as {role} to task {args.guid[:8]}")


def cmd_remove_member(args):
    body = {"members": [{"id": args.user, "type": "user"}]}
    result = api("POST", f"/task/v2/tasks/{args.guid}/remove_members", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"Removed {args.user[:12]} from task {args.guid[:8]}")


def cmd_add_reminder(args):
    body = {"reminders": [{"relative_fire_minute": int(args.mins)}]}
    result = api("POST", f"/task/v2/tasks/{args.guid}/add_reminders", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"⏰ Reminder set: {args.mins} minutes before due")


def cmd_remove_reminder(args):
    # Remove all reminders by passing empty list or specific ones
    # Try removing all: first get task to find reminder IDs
    result = api("GET", f"/task/v2/tasks/{args.guid}")
    task = result.get("data", {}).get("task", {})
    reminders = task.get("reminders", [])
    if not reminders:
        print("No reminders to remove.")
        return
    # Use remove_reminders endpoint
    body = {"reminders": [{"id": r["id"]} for r in reminders]}
    result = api("POST", f"/task/v2/tasks/{args.guid}/remove_reminders", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print("Reminders removed.")


def cmd_add_dependency(args):
    body = {"dependency_guids": [args.dep]}
    result = api("POST", f"/task/v2/tasks/{args.guid}/dependencies/add", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"🔗 Dependency added: {args.dep[:8]} -> {args.guid[:8]}")


def cmd_remove_dependency(args):
    body = {"dependency_guids": [args.dep]}
    result = api("POST", f"/task/v2/tasks/{args.guid}/dependencies/remove", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"Dependency removed.")


def cmd_list_tasklist(args):
    result = api("GET", "/task/v2/tasklists")
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    items = result["data"].get("items", [])
    if not items:
        print("No tasklists found.")
    for t in items:
        print(f"📋 {t.get('name', '?')}  [{t.get('guid', '?')[:8]}]")
        print(f"   owner: {t.get('owner', {}).get('id', '?')[:12]}")
        print()


def cmd_create_tasklist(args):
    body = {"name": args.name}
    result = api("POST", "/task/v2/tasklists", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    tl = result["data"]["tasklist"]
    print(f"📋 Tasklist created: {tl.get('name')} [{tl.get('guid', '')[:8]}]")


def cmd_delete_tasklist(args):
    result = api("DELETE", f"/task/v2/tasklists/{args.guid}")
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"Tasklist {args.guid[:8]} deleted.")


def cmd_add_to_tasklist(args):
    body = {"tasklist_guids": [args.tasklist]}
    result = api("POST", f"/task/v2/tasks/{args.task}/add_tasklists", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"Task added to tasklist {args.tasklist[:8]}")


def cmd_remove_from_tasklist(args):
    body = {"tasklist_guids": [args.tasklist]}
    result = api("POST", f"/task/v2/tasks/{args.task}/remove_tasklists", body)
    if result.get("code") != 0:
        print(f"Error: {result.get('msg', result)}", file=sys.stderr)
        sys.exit(1)
    print(f"Task removed from tasklist.")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Feishu Task v2 CLI")
    sub = parser.add_subparsers(dest="action")

    # create
    p = sub.add_parser("create", help="Create a task")
    p.add_argument("--summary", "-s", required=True)
    p.add_argument("--desc", "-d")
    p.add_argument("--assignee")
    p.add_argument("--follower")
    p.add_argument("--start")
    p.add_argument("--due")
    p.add_argument("--reminder", type=int, help="Minutes before due")
    p.add_argument("--priority", type=int, choices=[0, 1, 2, 3])
    p.add_argument("--parent", help="Parent task GUID for subtask")
    p.add_argument("--milestone", action="store_true")
    p.add_argument("--repeat")
    p.add_argument("--tasklist")
    p.add_argument("--idempotent")

    # get
    p = sub.add_parser("get", help="Get task details")
    p.add_argument("guid")
    p.add_argument("--raw", action="store_true")

    # list
    p = sub.add_parser("list", help="List tasks")
    p.add_argument("--page-size", type=int)

    # update
    p = sub.add_parser("update", help="Update task")
    p.add_argument("guid")
    p.add_argument("--summary")
    p.add_argument("--desc")
    p.add_argument("--due")
    p.add_argument("--start")
    p.add_argument("--priority", type=int, choices=[0, 1, 2, 3])
    p.add_argument("--milestone", action="store_true")
    p.add_argument("--no-milestone", action="store_true")
    p.add_argument("--clear-due", action="store_true")
    p.add_argument("--repeat")

    # delete
    p = sub.add_parser("delete", help="Delete task")
    p.add_argument("guid")

    # done
    p = sub.add_parser("done", help="Mark complete")
    p.add_argument("guid")

    # undo
    p = sub.add_parser("undo", help="Restore incomplete")
    p.add_argument("guid")

    # add-member
    p = sub.add_parser("add-member", help="Add member")
    p.add_argument("guid")
    p.add_argument("--user", required=True)
    p.add_argument("--role", choices=["assignee", "follower"])

    # remove-member
    p = sub.add_parser("remove-member", help="Remove member")
    p.add_argument("guid")
    p.add_argument("--user", required=True)

    # add-reminder
    p = sub.add_parser("add-reminder", help="Add reminder")
    p.add_argument("guid")
    p.add_argument("--mins", type=int, required=True)

    # remove-reminder
    p = sub.add_parser("remove-reminder", help="Remove reminders")
    p.add_argument("guid")

    # add-dependency
    p = sub.add_parser("add-dependency", help="Add dependency")
    p.add_argument("guid")
    p.add_argument("--dep", required=True)

    # remove-dependency
    p = sub.add_parser("remove-dependency", help="Remove dependency")
    p.add_argument("guid")
    p.add_argument("--dep", required=True)

    # list-tasklist
    sub.add_parser("list-tasklist", help="List tasklists")

    # create-tasklist
    p = sub.add_parser("create-tasklist", help="Create tasklist")
    p.add_argument("--name", required=True)

    # delete-tasklist
    p = sub.add_parser("delete-tasklist", help="Delete tasklist")
    p.add_argument("guid")

    # add-to-tasklist
    p = sub.add_parser("add-to-tasklist", help="Add task to tasklist")
    p.add_argument("--task", required=True)
    p.add_argument("--tasklist", required=True)

    # remove-from-tasklist
    p = sub.add_parser("remove-from-tasklist", help="Remove task from tasklist")
    p.add_argument("--task", required=True)
    p.add_argument("--tasklist", required=True)

    args = parser.parse_args()
    if not args.action:
        parser.print_help()
        sys.exit(1)

    actions = {
        "create": cmd_create,
        "get": cmd_get,
        "list": cmd_list,
        "update": cmd_update,
        "delete": cmd_delete,
        "done": cmd_done,
        "undo": cmd_undo,
        "add-member": cmd_add_member,
        "remove-member": cmd_remove_member,
        "add-reminder": cmd_add_reminder,
        "remove-reminder": cmd_remove_reminder,
        "add-dependency": cmd_add_dependency,
        "remove-dependency": cmd_remove_dependency,
        "list-tasklist": cmd_list_tasklist,
        "create-tasklist": cmd_create_tasklist,
        "delete-tasklist": cmd_delete_tasklist,
        "add-to-tasklist": cmd_add_to_tasklist,
        "remove-from-tasklist": cmd_remove_from_tasklist,
    }
    actions[args.action](args)


if __name__ == "__main__":
    main()

# Feishu Task v2 API Skill

Manage Feishu (Lark) tasks via the v2 API. Supports creating, updating, deleting tasks, managing members, reminders, tasklists, subtasks, and more.

## When to Use

Activate when the user asks to:
- Create / update / delete tasks (创建/更新/删除任务)
- List tasks or view task details
- Set task priority, assign members, add reminders
- Manage tasklists (任务分组)
- Create subtasks
- Mark tasks complete or undo completion

## Prerequisites

- Feishu app credentials saved in `/root/.openclaw/credentials/feishu-user-token.json`
- The script auto-manages user_access_token refresh

## API Scripts

All operations are in `scripts/api.py`. Run via:

```bash
python3 ~/.openclaw/workspace/skills/feishu-task/scripts/api.py <action> [args...]
```

### Actions

| Action | Description | Key Arguments |
|--------|-------------|---------------|
| `create` | Create a task | `--summary`, `--desc`, `--assignee <open_id>`, `--follower <open_id>`, `--start <time>`, `--due <time>`, `--reminder <mins>`, `--priority <0-3>`, `--parent <guid>`, `--milestone`, `--repeat <rrule>`, `--tasklist <guid>` |
| `list` | List all tasks (user as assignee) | `--page-size N` |
| `get` | Get task details | `<guid>` |
| `update` | Update task fields | `<guid>`, `--summary`, `--desc`, `--due <time>`, `--start <time>`, `--priority <0-3>`, `--milestone`, `--no-milestone` |
| `delete` | Delete a task | `<guid>` |
| `done` | Mark task complete | `<guid>` |
| `undo` | Restore task to incomplete | `<guid>` |
| `add-member` | Add assignee/follower | `<guid>`, `--user <open_id>`, `--role assignee\|follower` |
| `remove-member` | Remove member | `<guid>`, `--user <open_id>` |
| `add-reminder` | Add reminder (requires due) | `<guid>`, `--mins <minutes_before_due>` |
| `remove-reminder` | Remove reminder | `<guid>` |
| `add-dependency` | Add task dependency | `<guid>`, `--dep <dependency_guid>` |
| `remove-dependency` | Remove dependency | `<guid>`, `--dep <dependency_guid>` |
| `list-tasklist` | List all tasklists | |
| `create-tasklist` | Create a tasklist | `--name <name>` |
| `delete-tasklist` | Delete a tasklist | `<guid>` |
| `add-to-tasklist` | Add task to tasklist | `--task <guid>`, `--tasklist <guid>` |
| `remove-from-tasklist` | Remove task from tasklist | `--task <guid>`, `--tasklist <guid>` |

### Time Format

All `--start`, `--due`, `--time` arguments support natural language in Chinese:

- `今天14:00`, `明天18:30`, `后天`, `3天后`, `下周一`
- `2024-03-20 15:00`, `2024-03-20` (all-day)
- Raw epoch milliseconds also accepted

### Priority Levels

| Value | Meaning |
|-------|---------|
| 0 | None / No priority |
| 1 | Low (低) |
| 2 | Medium (中) — default |
| 3 | High (高) |

Priority is stored in the `extra` JSON field. Not a native Feishu field — visual effect may vary.

### Repeat Rules (RRULE subset)

- `FREQ=DAILY;INTERVAL=1` — daily
- `FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,TU,WE,TH,FR` — weekdays
- `FREQ=WEEKLY;INTERVAL=2` — biweekly
- `FREQ=MONTHLY;INTERVAL=1` — monthly

Note: Recurring tasks require a `due` time.

## Token Management

The script automatically:
1. Reads `user_access_token` from `/root/.openclaw/credentials/feishu-user-token.json`
2. Checks expiration and refreshes if needed via `refresh_token`
3. Saves updated token back to the file

App credentials: `cli_a914ad0747b8dcc6` / stored in env or defaults.

## Key API Endpoints

| Operation | Method | Endpoint |
|-----------|--------|----------|
| Create task | POST | `/task/v2/tasks` |
| Get task | GET | `/task/v2/tasks/{guid}` |
| Update task | PATCH | `/task/v2/tasks/{guid}` |
| Delete task | DELETE | `/task/v2/tasks/{guid}` |
| List tasks | GET | `/task/v2/tasks` |
| Add members | POST | `/task/v2/tasks/{guid}/add_members` |
| Remove members | POST | `/task/v2/tasks/{guid}/remove_members` |
| Add reminders | POST | `/task/v2/tasks/{guid}/add_reminders` |
| Remove reminders | POST | `/task/v2/tasks/{guid}/remove_reminders` |
| Create tasklist | POST | `/task/v2/tasklists` |
| List tasklists | GET | `/task/v2/tasklists` |
| Delete tasklist | DELETE | `/task/v2/tasklists/{guid}` |
| Add to tasklist | POST | `/task/v2/tasks/{guid}/add_tasklists` |
| Remove from tasklist | POST | `/task/v2/tasks/{guid}/remove_tasklists` |
| Add dependency | POST | `/task/v2/tasks/{guid}/dependencies/add` |
| Remove dependency | POST | `/task/v2/tasks/{guid}/dependencies/remove` |

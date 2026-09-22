# matrix-jira-bot

A Matrix bot that lets you manage Jira issues by typing commands in a chat room
— one room per Jira board, or one shared room for everything. It can also
watch Jira and announce status changes back into the room. Fully
config-driven: no Matrix room IDs, user mappings, or credentials are
hardcoded anywhere in the code.

```
/ticket @honarkar Fix the login page timeout
  -> ✅ Created CK-130 for @honarkar — https://jira.example.org/browse/CK-130

/comment CK-130 Reproduced on staging, looking into it now
  -> ✅ Commented on CK-130 — https://jira.example.org/browse/CK-130

/assign CK-130 @arya
  -> ✅ Assigned CK-130 to @arya — https://jira.example.org/browse/CK-130

/status CK-130 Done
  -> ✅ CK-130 moved to Done — https://jira.example.org/browse/CK-130
```

## How it works

- Each Matrix room you configure can optionally map to one default Jira
  project. `/comment`, `/assign`, and `/status` never need this — the issue
  key (e.g. `CK-130`) already says which project they act on. Only `/ticket`
  (which creates a new issue) needs to know a project, so a room without a
  default project just requires it explicitly: `/ticket CK @user <summary>`
  instead of `/ticket @user <summary>`. This is what lets you either run one
  room per board, or one shared room covering every board at once.
- The bot stays connected to Matrix (long-polling `/sync`) and watches only the
  rooms listed in your config.
- A message starting with any of the configured `command_prefixes` (default `["/"]`) is
  parsed as a command; everything else is ignored.
- `@user` in a command is resolved against the `users:` list in your config —
  either by matching the typed alias, or by matching a real Matrix mention if
  your client sends one (`m.mentions`).
- After running a command, the bot replies in-thread with a confirmation or an
  error, so the room always shows what happened.
- Reply to any message with `/ticket`, and that message's text is folded into
  the new issue's description -- useful for turning a bug report or request
  already in the room into a ticket without retyping it.
- The bot ignores its own messages and anything sent before it started, so it
  can't trigger itself or replay old history on restart.
- Optionally, the bot can also poll Jira and announce status changes back
  into a room (`watch_projects` + `status_poll_interval_seconds` -- see
  below). This is a workaround for deployments that can't receive real Jira
  webhooks (e.g. a firewall blocking inbound connections from Jira); if yours
  can, a webhook receiver is the better fit for that direction and this bot
  doesn't need to do it.

## Requirements

- Python 3.10+
- A Matrix account for the bot with a long-lived access token
- A Jira Server/Data Center instance and a Personal Access Token
  (`Authorization: Bearer <token>`)
- **Unencrypted rooms.** This bot does not implement Matrix end-to-end
  encryption. Create the rooms it will watch without enabling encryption
  (most clients ask at room-creation time; it cannot be turned off afterwards).

## Setup

1. Copy the example config and fill in your values:
   ```bash
   cp config.example.yaml config.yaml
   ```

2. Get a Matrix access token for the bot account. One way: log in via curl —
   ```bash
   curl -X POST https://your-homeserver/_matrix/client/v3/login \
     -H "Content-Type: application/json" \
     -d '{"type":"m.login.password","user":"bot","password":"..."}'
   ```
   Copy the `access_token` from the response into `matrix.access_token`.

3. Get a Jira Personal Access Token: Jira → Profile → Personal Access Tokens →
   Create token. Put it in `jira.token`.

4. For each Jira board/project you want, create (or reuse) a Matrix room, invite
   the bot, and add an entry under `matrix.rooms:` with that room's ID and the
   matching Jira project key.

5. Under `users:`, add one entry per person who should be assignable via
   `/ticket` or `/assign`: their chosen alias, their Matrix user ID, and their
   Jira username.

6. Install dependencies and run:
   ```bash
   pip install -r requirements.txt
   python -m matrix_jira_bot config.yaml
   ```

   Or with Docker:
   ```bash
   docker build -t matrix-jira-bot .
   docker run -v $(pwd)/config.yaml:/config/config.yaml:ro matrix-jira-bot
   ```

## Configuration reference

See [`config.example.yaml`](config.example.yaml) for the full annotated example.

| Key | Description |
|---|---|
| `matrix.homeserver` | Your Matrix homeserver base URL |
| `matrix.user_id` | The bot's full Matrix user ID |
| `matrix.access_token` | The bot's long-lived access token |
| `matrix.device_id` | Optional; leave blank to let the server assign one |
| `matrix.rooms[].room_id` | Matrix room ID |
| `matrix.rooms[].project_key` | Optional default project for `/ticket` in that room. Omit for a room shared across multiple boards, where every `/ticket` names its project explicitly |
| `matrix.rooms[].watch_projects` | Optional list of project keys whose Jira status changes get announced in that room (see status polling, below). Independent of `project_key` |
| `matrix.rooms[].name` | Free-text label, logging only |
| `jira.url` | Your Jira base URL |
| `jira.token` | A Jira Personal Access Token |
| `jira.default_issue_type` | Issue type used by `/ticket` (e.g. `Task`) |
| `command_prefixes` | List of prefixes that mark a message as a command, e.g. `["/", "!"]` (default `["/"]`) |
| `status_poll_interval_seconds` | How often (seconds) to poll Jira for status changes on any room's `watch_projects` (default `30`). Ignored if no room sets `watch_projects` |
| `users[].alias` | Short name used in commands, e.g. `honarkar` for `@honarkar` |
| `users[].matrix_id` | That person's full Matrix user ID |
| `users[].jira_username` | That person's Jira username |

## Commands

| Command | Usage | Effect |
|---|---|---|
| `/ticket` | `/ticket [PROJECT] @user <summary>` | Creates an issue assigned to `@user`, in `PROJECT` if given, otherwise the room's default project |
| `/comment` | `/comment <KEY> <text>` | Adds a comment to an existing issue |
| `/assign` | `/assign <KEY> @user` | Reassigns an existing issue |
| `/status` | `/status <KEY> <status name>` | Transitions an issue to a new status, if a valid transition exists |

## Status polling (Jira → Matrix)

Commands only cover Matrix → Jira. To also hear about changes made directly
in Jira (someone moving a card on the board, changing status in the Jira UI,
etc.), set `watch_projects` on a room:

```yaml
rooms:
  - room_id: "!general:example.org"
    watch_projects: ["CK", "CLM"]
    name: "General"
```

Every `status_poll_interval_seconds`, the bot checks the watched projects for
issues updated since its last check, and announces any status transitions it
finds:

```
🔄 [CK] CK-130 moved: In Progress → Done (Arya)
https://jira.example.org/browse/CK-130
```

This is pull-based (the bot asks Jira), so it needs no inbound network access
at all -- unlike a real Jira webhook, which needs Jira to be able to reach the
bot. Use this if that's not possible in your network (e.g. a firewall between
Jira and wherever the bot runs); it's less instant than a webhook (bounded by
the poll interval) but works anywhere the bot can reach Jira outbound.

## Notes / limitations

- `/status` only works if the target status is reachable via a workflow
  transition from the issue's current status; the error message lists what is
  actually available if the one you typed isn't.
- Any message typed in a watched room that starts with the command prefix is
  treated as a command attempt. Plain conversation (no leading `/`) is always
  ignored.

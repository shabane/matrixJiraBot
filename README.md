# matrix-jira-bot

A Matrix bot that lets you manage Jira issues by typing commands in a chat room —
one room per Jira board/project. Fully config-driven: no Matrix room IDs, user
mappings, or credentials are hardcoded anywhere in the code.

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

- Each Matrix room you configure is mapped to exactly one Jira project.
- The bot stays connected to Matrix (long-polling `/sync`) and watches only the
  rooms listed in your config.
- A message starting with any of the configured `command_prefixes` (default `["/"]`) is
  parsed as a command; everything else is ignored.
- `@user` in a command is resolved against the `users:` list in your config —
  either by matching the typed alias, or by matching a real Matrix mention if
  your client sends one (`m.mentions`).
- After running a command, the bot replies in-thread with a confirmation or an
  error, so the room always shows what happened.
- The bot ignores its own messages and anything sent before it started, so it
  can't trigger itself or replay old history on restart.

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
| `matrix.rooms[].project_key` | Jira project key that room maps to |
| `matrix.rooms[].name` | Free-text label, logging only |
| `jira.url` | Your Jira base URL |
| `jira.token` | A Jira Personal Access Token |
| `jira.default_issue_type` | Issue type used by `/ticket` (e.g. `Task`) |
| `command_prefixes` | List of prefixes that mark a message as a command, e.g. `["/", "!"]` (default `["/"]`) |
| `users[].alias` | Short name used in commands, e.g. `honarkar` for `@honarkar` |
| `users[].matrix_id` | That person's full Matrix user ID |
| `users[].jira_username` | That person's Jira username |

## Commands

| Command | Usage | Effect |
|---|---|---|
| `/ticket` | `/ticket @user <summary>` | Creates an issue in the room's project, assigned to `@user` |
| `/comment` | `/comment <KEY> <text>` | Adds a comment to an existing issue |
| `/assign` | `/assign <KEY> @user` | Reassigns an existing issue |
| `/status` | `/status <KEY> <status name>` | Transitions an issue to a new status, if a valid transition exists |

## Notes / limitations

- This is a one-way command bot, not a full Jira↔Matrix sync — it doesn't mirror
  Jira activity back into the room. Pair it with a webhook or poller on the
  Jira side if you also want that direction.
- `/status` only works if the target status is reachable via a workflow
  transition from the issue's current status; the error message lists what is
  actually available if the one you typed isn't.
- Any mention typed in a watched room that starts with the command prefix is
  treated as a command attempt. Plain conversation (no leading `/`) is always
  ignored.

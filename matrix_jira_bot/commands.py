"""Command parsing and execution. All four commands live here:
/ticket, /comment, /assign, /status."""
from __future__ import annotations

import dataclasses
from typing import Optional

from .config import Config, RoomConfig
from .jira_client import JiraClient, JiraError


@dataclasses.dataclass
class CommandResult:
    ok: bool
    message: str  # plain text reply to send back to the room


def _resolve_user(config: Config, token: str, mentioned_matrix_ids: list[str]):
    """Resolve a @alias token, a full Matrix ID, or an actual Matrix mention
    to a configured user."""
    token = token.strip()
    if token.startswith("@") and ":" in token:
        user = config.user_by_matrix_id(token)
        if user:
            return user
    for mid in mentioned_matrix_ids:
        user = config.user_by_matrix_id(mid)
        if user:
            return user
    return config.user_by_alias(token)


def _match_prefix(body: str, prefixes: list[str]) -> Optional[str]:
    """Returns the first configured prefix the message starts with, or None."""
    for prefix in prefixes:
        if body.startswith(prefix):
            return prefix
    return None


def parse_and_run(
    body: str,
    room: RoomConfig,
    config: Config,
    jira: JiraClient,
    sender_display_name: str,
    mentioned_matrix_ids: list[str],
    quoted_text: Optional[str] = None,
) -> Optional[CommandResult]:
    body = body.strip()
    prefix = _match_prefix(body, config.command_prefixes)
    if prefix is None:
        return None

    parts = body[len(prefix):].split(maxsplit=1)
    if not parts:
        return None
    command = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    try:
        if command == "ticket":
            return _cmd_ticket(rest, room, config, jira, sender_display_name, mentioned_matrix_ids, quoted_text)
        if command == "comment":
            return _cmd_comment(rest, jira)
        if command == "assign":
            return _cmd_assign(rest, config, jira, mentioned_matrix_ids)
        if command == "status":
            return _cmd_status(rest, jira)
    except JiraError as e:
        return CommandResult(ok=False, message=f"❌ {e}")

    return CommandResult(
        ok=False,
        message=f"❓ Unknown command '{command}'. Supported: /ticket, /comment, /assign, /status",
    )


def _cmd_ticket(rest: str, room: RoomConfig, config: Config, jira: JiraClient,
                 sender_display_name: str, mentioned_matrix_ids: list[str],
                 quoted_text: Optional[str] = None) -> CommandResult:
    usage = "Usage: /ticket [PROJECT] @user <summary text>"
    parts = rest.split(maxsplit=1)
    if not parts:
        return CommandResult(ok=False, message=usage)

    first, remainder = parts[0], (parts[1] if len(parts) > 1 else "")

    if first.startswith("@"):
        # No project given -- fall back to this room's configured default.
        project_key = room.project_key
        user_token = first
        summary = remainder.strip()
    else:
        # First token isn't a user mention, so treat it as an explicit project
        # key override -- this is what lets one shared room file tickets
        # against multiple boards.
        project_key = first.upper()
        sub = remainder.split(maxsplit=1)
        if len(sub) < 2:
            return CommandResult(ok=False, message=usage)
        user_token, summary = sub[0], sub[1].strip()

    if not project_key:
        return CommandResult(
            ok=False,
            message="❓ This room has no default project. Specify one: /ticket <PROJECT> @user <summary text>",
        )
    if not summary:
        return CommandResult(ok=False, message=usage)

    user = _resolve_user(config, user_token, mentioned_matrix_ids)
    if not user:
        return CommandResult(ok=False, message=f"❓ Unknown user '{user_token}'. Add them under 'users:' in config.yaml.")

    issue = jira.create_issue(
        project_key=project_key,
        summary=summary,
        issuetype=config.jira.default_issue_type,
        assignee=user.jira_username,
        reporter_hint=sender_display_name,
        quoted_text=quoted_text,
    )
    key = issue["key"]
    return CommandResult(ok=True, message=f"✅ Created {key} for @{user.alias} — {jira.issue_url(key)}")


def _cmd_comment(rest: str, jira: JiraClient) -> CommandResult:
    parts = rest.split(maxsplit=1)
    if len(parts) < 2:
        return CommandResult(ok=False, message="Usage: /comment <ISSUE-KEY> <text>")
    key, text = parts[0].upper(), parts[1].strip()
    jira.add_comment(key, text)
    return CommandResult(ok=True, message=f"✅ Commented on {key} — {jira.issue_url(key)}")


def _cmd_assign(rest: str, config: Config, jira: JiraClient, mentioned_matrix_ids: list[str]) -> CommandResult:
    parts = rest.split()
    if len(parts) < 2:
        return CommandResult(ok=False, message="Usage: /assign <ISSUE-KEY> @user")
    key, user_token = parts[0].upper(), parts[1]
    user = _resolve_user(config, user_token, mentioned_matrix_ids)
    if not user:
        return CommandResult(ok=False, message=f"❓ Unknown user '{user_token}'. Add them under 'users:' in config.yaml.")
    jira.assign_issue(key, user.jira_username)
    return CommandResult(ok=True, message=f"✅ Assigned {key} to @{user.alias} — {jira.issue_url(key)}")


def _cmd_status(rest: str, jira: JiraClient) -> CommandResult:
    parts = rest.split(maxsplit=1)
    if len(parts) < 2:
        return CommandResult(ok=False, message="Usage: /status <ISSUE-KEY> <status name>")
    key, status_name = parts[0].upper(), parts[1].strip()
    new_status = jira.transition_issue(key, status_name)
    return CommandResult(ok=True, message=f"✅ {key} moved to {new_status} — {jira.issue_url(key)}")

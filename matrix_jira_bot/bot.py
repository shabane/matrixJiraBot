"""Matrix event loop: listens for messages in the configured rooms and
dispatches them to commands.py. Ignores its own messages and any history
from before it started, to avoid feedback loops and replaying old events."""
from __future__ import annotations

import asyncio
import logging
import time

from nio import AsyncClient, MatrixRoom, RoomMessageText
from nio.responses import RoomGetEventResponse

from .commands import parse_and_run
from .config import Config
from .jira_client import JiraClient

log = logging.getLogger("matrix_jira_bot")


def _strip_reply_fallback(body: str) -> str:
    """Matrix clients prefix a reply's body with a quoted-text fallback
    (lines starting with '>', then a blank line) before the text the user
    actually typed. Strip it so command parsing sees only what was typed."""
    lines = body.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith(">"):
        i += 1
    if i < len(lines) and lines[i] == "":
        i += 1
    return "\n".join(lines[i:])


class Bot:
    def __init__(self, config: Config):
        self.config = config
        self.jira = JiraClient(config.jira.url, config.jira.token)
        self.client = AsyncClient(config.matrix.homeserver, config.matrix.user_id)
        self.client.access_token = config.matrix.access_token
        self.client.user_id = config.matrix.user_id
        if config.matrix.device_id:
            self.client.device_id = config.matrix.device_id
        self.start_ts_ms = int(time.time() * 1000)

    async def on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if event.sender == self.config.matrix.user_id:
            return  # never react to our own messages
        if event.server_timestamp < self.start_ts_ms:
            return  # ignore history from before the bot started

        room_cfg = self.config.room_by_id(room.room_id)
        if room_cfg is None:
            return  # not a room we're configured to act in

        try:
            content = event.source.get("content", {})
            body = _strip_reply_fallback(event.body or "")
            mentions = list(content.get("m.mentions", {}).get("user_ids", []))
            sender_name = room.user_name(event.sender) or event.sender

            quoted_text = None
            reply_to_id = content.get("m.relates_to", {}).get("m.in_reply_to", {}).get("event_id")
            if reply_to_id:
                quoted_text = await self._fetch_quoted_text(room.room_id, reply_to_id)

            # parse_and_run makes synchronous, blocking Jira HTTP calls. Running it in
            # a thread keeps the event loop free to keep processing other rooms/events
            # while it's in flight, instead of stalling the whole bot for up to
            # REQUEST_TIMEOUT_SECONDS on every command.
            result = await asyncio.to_thread(
                parse_and_run,
                body=body,
                room=room_cfg,
                config=self.config,
                jira=self.jira,
                sender_display_name=sender_name,
                mentioned_matrix_ids=mentions,
                quoted_text=quoted_text,
            )
            if result is None:
                return

            log.info("%s ran %r in %s -> ok=%s", event.sender, body, room.room_id, result.ok)
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": result.message,
                    "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
                },
            )
        except Exception:
            # nio's callback dispatcher has no exception handling of its own, so an
            # uncaught error here would otherwise vanish silently. Always log it.
            log.exception("Error handling message %r from %s in %s", event.body, event.sender, room.room_id)

    async def _fetch_quoted_text(self, room_id: str, event_id: str) -> str | None:
        """Fetches the message a command was sent as a reply to, so /ticket can
        fold its text into the new issue's description. Best-effort: any
        failure here shouldn't stop the command itself from running."""
        try:
            resp = await self.client.room_get_event(room_id, event_id)
        except Exception:
            log.exception("Failed to fetch replied-to event %s in %s", event_id, room_id)
            return None
        if not isinstance(resp, RoomGetEventResponse):
            log.warning("Could not fetch replied-to event %s in %s: %s", event_id, room_id, resp)
            return None
        original_body = getattr(resp.event, "body", None)
        if not original_body:
            return None
        original_sender = getattr(resp.event, "sender", "someone")
        return f"{original_sender}: {original_body}"

    async def run(self) -> None:
        self.client.add_event_callback(self.on_message, RoomMessageText)

        whoami = await self.client.whoami()
        if hasattr(whoami, "user_id"):
            log.info("Logged in as %s", whoami.user_id)
        else:
            log.warning("whoami failed: %s -- check matrix.access_token in config.yaml", whoami)

        for room in self.config.matrix.rooms:
            await self.client.join(room.room_id)
            log.info("Watching room %s (%s -> project %s)", room.room_id, room.name or "unnamed", room.project_key)

        # One full-state sync to load initial room state, then incremental syncs only --
        # passing full_state=True to sync_forever would (incorrectly) re-request full
        # state on every poll, not just the first.
        await self.client.sync(timeout=30000, full_state=True)

        log.info("matrix-jira-bot is running.")
        await self.client.sync_forever(timeout=30000)

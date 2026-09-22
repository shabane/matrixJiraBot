"""Matrix event loop: listens for messages in the configured rooms and
dispatches them to commands.py. Ignores its own messages and any history
from before it started, to avoid feedback loops and replaying old events."""
from __future__ import annotations

import logging
import time

from nio import AsyncClient, MatrixRoom, RoomMessageText

from .commands import parse_and_run
from .config import Config
from .jira_client import JiraClient

log = logging.getLogger("matrix_jira_bot")


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

        body = event.body or ""
        mentions = list(event.source.get("content", {}).get("m.mentions", {}).get("user_ids", []))
        sender_name = room.user_name(event.sender) or event.sender

        result = parse_and_run(
            body=body,
            room=room_cfg,
            config=self.config,
            jira=self.jira,
            sender_display_name=sender_name,
            mentioned_matrix_ids=mentions,
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

        log.info("matrix-jira-bot is running.")
        await self.client.sync_forever(timeout=30000, full_state=True)

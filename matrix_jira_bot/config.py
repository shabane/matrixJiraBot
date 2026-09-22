"""Configuration loading for matrix-jira-bot. Everything is driven by config.yaml
so this project can be reused across any Matrix/Jira deployment without code changes."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Optional

import yaml


@dataclasses.dataclass
class RoomConfig:
    room_id: str
    # Optional: the default project /ticket creates issues in when the command
    # doesn't specify one explicitly. Leave unset for a room shared across
    # multiple boards, where every /ticket names its project directly
    # (e.g. "/ticket CK @user ..." instead of "/ticket @user ...").
    project_key: Optional[str] = None
    # Optional: project keys whose status changes get posted to this room.
    # Independent of project_key -- a shared room can watch several projects,
    # and a per-board room's own project isn't watched unless listed here too.
    watch_projects: list[str] = dataclasses.field(default_factory=list)
    name: str = ""


@dataclasses.dataclass
class MatrixConfig:
    homeserver: str
    user_id: str
    access_token: str
    rooms: list[RoomConfig]
    device_id: str = ""


@dataclasses.dataclass
class JiraConfig:
    url: str
    token: str
    default_issue_type: str = "Task"


@dataclasses.dataclass
class UserConfig:
    alias: str
    matrix_id: str
    jira_username: str


@dataclasses.dataclass
class Config:
    matrix: MatrixConfig
    jira: JiraConfig
    users: list[UserConfig]
    command_prefixes: list[str] = dataclasses.field(default_factory=lambda: ["/"])
    # How often (seconds) to poll Jira for status changes on watched projects.
    # Only takes effect if at least one room configures watch_projects.
    status_poll_interval_seconds: int = 30

    def room_by_id(self, room_id: str) -> Optional[RoomConfig]:
        return next((r for r in self.matrix.rooms if r.room_id == room_id), None)

    def watched_projects(self) -> dict[str, list[str]]:
        """Maps each watched project key to the list of room IDs that should
        be notified about its status changes."""
        watched: dict[str, list[str]] = {}
        for room in self.matrix.rooms:
            for project_key in room.watch_projects:
                watched.setdefault(project_key, []).append(room.room_id)
        return watched

    def user_by_alias(self, alias: str) -> Optional[UserConfig]:
        alias = alias.lstrip("@").lower()
        return next((u for u in self.users if u.alias.lower() == alias), None)

    def user_by_matrix_id(self, matrix_id: str) -> Optional[UserConfig]:
        return next((u for u in self.users if u.matrix_id == matrix_id), None)


def load_config(path: str) -> Config:
    p = Path(path)
    if not p.exists():
        sys.exit(
            f"Config file not found: {path}\n"
            f"Copy config.example.yaml to config.yaml and fill in your values."
        )
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    try:
        matrix_raw = dict(raw["matrix"])
        rooms = [RoomConfig(**r) for r in matrix_raw.pop("rooms", [])]
        matrix = MatrixConfig(rooms=rooms, **matrix_raw)
        jira = JiraConfig(**raw["jira"])
        users = [UserConfig(**u) for u in raw.get("users", [])]
        command_prefixes = raw.get("command_prefixes", ["/"])
        status_poll_interval_seconds = raw.get("status_poll_interval_seconds", 30)
    except (KeyError, TypeError) as e:
        sys.exit(f"Invalid config file ({path}): {e}")

    if not matrix.rooms:
        sys.exit("Config error: at least one room must be configured under 'matrix.rooms'.")
    if not command_prefixes:
        sys.exit("Config error: 'command_prefixes' must have at least one entry.")
    if status_poll_interval_seconds <= 0:
        sys.exit("Config error: 'status_poll_interval_seconds' must be positive.")

    return Config(
        matrix=matrix,
        jira=jira,
        users=users,
        command_prefixes=command_prefixes,
        status_poll_interval_seconds=status_poll_interval_seconds,
    )

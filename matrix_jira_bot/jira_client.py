"""Minimal Jira Server/Data Center REST client covering exactly what the bot's
commands need: creating issues, commenting, assigning, and transitioning status."""
from __future__ import annotations

import requests

# Every request must fail fast rather than hang. Without this, a network
# problem reaching Jira would block forever -- and since this client is
# called from inside the bot's single-threaded async event loop, a single
# hung request would silently freeze the entire bot for every room.
REQUEST_TIMEOUT_SECONDS = 10


class JiraError(Exception):
    pass


def _with_default_timeout(request_func):
    """Wraps Session.request so every call gets a timeout unless one is
    explicitly passed, and so connection/timeout failures surface as a
    JiraError the rest of the bot already knows how to turn into a clean
    reply in the room, instead of an unhandled exception."""
    def wrapped(method, url, **kwargs):
        kwargs.setdefault("timeout", REQUEST_TIMEOUT_SECONDS)
        try:
            return request_func(method, url, **kwargs)
        except requests.exceptions.RequestException as e:
            raise JiraError(f"Could not reach Jira ({url}): {e}") from e
    return wrapped


class JiraClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        self.session.request = _with_default_timeout(self.session.request)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def create_issue(self, project_key: str, summary: str, issuetype: str,
                      assignee: str | None, reporter_hint: str | None = None) -> dict:
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issuetype},
        }
        if assignee:
            fields["assignee"] = {"name": assignee}
        if reporter_hint:
            fields["description"] = f"Created via Matrix by {reporter_hint}."
        resp = self.session.post(self._url("/rest/api/2/issue"), json={"fields": fields})
        if not resp.ok:
            raise JiraError(f"Failed to create issue: {resp.status_code} {resp.text}")
        return resp.json()

    def add_comment(self, issue_key: str, body: str) -> dict:
        resp = self.session.post(self._url(f"/rest/api/2/issue/{issue_key}/comment"), json={"body": body})
        if not resp.ok:
            raise JiraError(f"Failed to comment on {issue_key}: {resp.status_code} {resp.text}")
        return resp.json()

    def assign_issue(self, issue_key: str, jira_username: str) -> None:
        resp = self.session.put(
            self._url(f"/rest/api/2/issue/{issue_key}/assignee"), json={"name": jira_username}
        )
        if not resp.ok:
            raise JiraError(f"Failed to assign {issue_key}: {resp.status_code} {resp.text}")

    def get_transitions(self, issue_key: str) -> list[dict]:
        resp = self.session.get(self._url(f"/rest/api/2/issue/{issue_key}/transitions"))
        if not resp.ok:
            raise JiraError(f"Failed to fetch transitions for {issue_key}: {resp.status_code} {resp.text}")
        return resp.json().get("transitions", [])

    def transition_issue(self, issue_key: str, status_name: str) -> str:
        transitions = self.get_transitions(issue_key)
        match = next(
            (t for t in transitions if t.get("to", {}).get("name", "").lower() == status_name.lower()),
            None,
        )
        if not match:
            available = ", ".join(t["to"]["name"] for t in transitions) or "(no transitions available)"
            raise JiraError(f"No transition to '{status_name}' from the current status. Available: {available}")
        resp = self.session.post(
            self._url(f"/rest/api/2/issue/{issue_key}/transitions"),
            json={"transition": {"id": match["id"]}},
        )
        if not resp.ok:
            raise JiraError(f"Failed to transition {issue_key}: {resp.status_code} {resp.text}")
        return match["to"]["name"]

    def issue_url(self, issue_key: str) -> str:
        return f"{self.base_url}/browse/{issue_key}"

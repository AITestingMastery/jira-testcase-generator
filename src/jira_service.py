"""Jira REST client: fetches summary, description and comments for a ticket."""
import re
from typing import Any

import httpx


class JiraError(Exception):
    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.status = status


def adf_to_text(node: Any) -> str:
    """Flatten Atlassian Document Format (API v3) into plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    kind, inner = node.get("type"), "".join(adf_to_text(c) for c in node.get("content", []))
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    if kind == "listItem":
        return "• " + inner.strip() + "\n"
    if kind in ("paragraph", "heading", "codeBlock", "blockquote"):
        return inner + "\n"
    return inner


def split_description(text: str) -> tuple[str, str]:
    """Heuristic split into (user story, acceptance criteria)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "acceptance criteria" in line.lower() and len(line) < 60:
            return "\n".join(lines[:i]).strip(), "\n".join(lines[i + 1:]).strip()
    return text.strip(), ""


class JiraService:
    TICKET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]+-\d+$")

    def __init__(self, base_url: str, username: str, token: str, auth_mode: str = "basic"):
        if not base_url or not token:
            raise JiraError("Jira base URL and API token are required.", 400)
        if auth_mode == "basic" and not username:
            raise JiraError("Username (email) is required for basic auth.", 400)
        self.base = base_url.rstrip("/")
        self.mode = auth_mode
        # Cloud uses v3 (ADF bodies); Server/Data Center PATs use v2 (plain text).
        self.api = "3" if auth_mode == "basic" else "2"
        self.auth = httpx.BasicAuth(username, token) if auth_mode == "basic" else None
        self.headers = {"Accept": "application/json"}
        if auth_mode == "pat":
            self.headers["Authorization"] = f"Bearer {token}"

    def check_connection(self) -> dict:
        """Verify the Jira URL and credentials without exposing secrets."""
        url = f"{self.base}/rest/api/{self.api}/myself"
        try:
            with httpx.Client(timeout=20, auth=self.auth, headers=self.headers) as c:
                r = c.get(url)
        except httpx.HTTPError as e:
            raise JiraError(f"Could not reach Jira at {self.base}: {e}", 502) from e

        if r.status_code == 401:
            raise JiraError("Jira is reachable, but authentication failed. Check JIRA_USERNAME, JIRA_TOKEN, and JIRA_AUTH_MODE.", 401)
        if r.status_code == 403:
            raise JiraError("Jira is reachable, but this account is not allowed to access the user profile endpoint.", 403)
        if r.status_code == 404:
            raise JiraError(f"Jira responded, but {url} was not found. Check JIRA_BASE_URL (use the site root, without /rest/api/...).", 502)
        if r.status_code >= 400:
            raise JiraError(f"Jira connection check failed with HTTP {r.status_code} at {url}.", 502)

        user = r.json()
        return {
            "connected": True,
            "message": "Jira connection and authentication succeeded.",
            "base_url": self.base,
            "api_version": self.api,
            "user": user.get("displayName") or user.get("name") or "Authenticated user",
        }

    def fetch_ticket(self, ticket_id: str) -> dict:
        ticket_id = ticket_id.strip().upper()
        if not self.TICKET_RE.match(ticket_id):
            raise JiraError("Ticket ID must look like PROJ-123.", 400)
        url = f"{self.base}/rest/api/{self.api}/issue/{ticket_id}"
        try:
            with httpx.Client(timeout=20, auth=self.auth, headers=self.headers) as c:
                r = c.get(url, params={"fields": "summary,description,comment"})
        except httpx.HTTPError as e:
            raise JiraError(f"Could not reach Jira at {self.base}: {e}", 502)

        errors = {
            401: f"Jira rejected authentication while fetching {ticket_id}. Check JIRA_USERNAME, JIRA_TOKEN, and JIRA_AUTH_MODE.",
            403: f"Jira authenticated the request, but this account cannot view {ticket_id}. Ask a Jira admin to check Browse Projects permission.",
            404: f"Jira returned 404 for {ticket_id}. Jira often hides issues you cannot view. Check the project key/issue number and confirm this account has Browse Projects access. Requested URL: {url}",
        }
        if r.status_code in errors:
            raise JiraError(errors[r.status_code], r.status_code)
        if r.status_code >= 400:
            raise JiraError(f"Jira returned HTTP {r.status_code}.", 502)

        fields = r.json().get("fields", {})
        description = adf_to_text(fields.get("description")).strip()
        story, criteria = split_description(description)
        comments = [
            {"author": (c.get("author") or {}).get("displayName", "Unknown"),
             "body": adf_to_text(c.get("body")).strip()}
            for c in (fields.get("comment") or {}).get("comments", [])
        ]
        return {"key": ticket_id, "summary": fields.get("summary", ""),
                "description": description, "user_story": story,
                "acceptance_criteria": criteria, "comments": comments}

"""Generate validated test cases from Jira tickets using the OpenAI API."""
import json
import os
import re
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError


class NLPError(Exception):
    pass


class TestCase(BaseModel):
    __test__ = False
    id: str
    title: str
    type: Literal["Happy Path", "Negative", "Edge Case"]
    preconditions: str
    steps: list[str]
    expected_result: str


SYSTEM_PROMPT = """You are an elite Quality Assurance Engineer. Analyze the provided Jira ticket text to extract and generate structured test cases.

Rules:
- Do not invent out-of-scope features.
- Generate happy paths, negative paths, and edge cases when supported by the ticket.
- Return only a JSON object matching the supplied schema, with a test_cases array.
"""

_ITEM = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "title", "type", "preconditions", "steps", "expected_result"],
    "properties": {
        "id": {"type": "string"}, "title": {"type": "string"},
        "type": {"type": "string", "enum": ["Happy Path", "Negative", "Edge Case"]},
        "preconditions": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "expected_result": {"type": "string"},
    },
}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["test_cases"],
          "properties": {"test_cases": {"type": "array", "items": _ITEM}}}


def build_user_prompt(ticket: dict) -> str:
    parts = [f"Ticket: {ticket.get('key', '')}", f"Summary: {ticket.get('summary', '')}"]
    if ticket.get("user_story"):
        parts.append(f"User Story / Description:\n{ticket['user_story']}")
    if ticket.get("acceptance_criteria"):
        parts.append(f"Acceptance Criteria:\n{ticket['acceptance_criteria']}")
    if ticket.get("comments"):
        parts.append("Comments:\n" + "\n".join(
            f"- {comment['author']}: {comment['body']}" for comment in ticket["comments"][:15]
        ))
    return "\n\n".join(parts)


def _call_openai(prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise NLPError("Set OPENAI_API_KEY in the project-root .env to generate test cases.")
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "test_cases", "strict": True, "schema": SCHEMA,
        }},
    }
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions", json=body, timeout=120,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if response.status_code != 200:
        try:
            message = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            message = response.text
        raise NLPError(f"OpenAI error {response.status_code}: {message}")
    return response.json()["choices"][0]["message"]["content"]


def _parse(raw: str) -> list[TestCase]:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("test_cases", [])
        cases = [TestCase(**item) for item in data]
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise NLPError(f"OpenAI returned data that did not match the test case schema: {exc}") from exc
    for index, case in enumerate(cases, 1):
        case.id = f"TC_{index:03d}"
    return cases


def generate_test_cases(ticket: dict) -> list[dict]:
    if not (ticket.get("summary") or ticket.get("description")):
        raise NLPError("The ticket has no summary or description to analyze.")
    try:
        raw = _call_openai(build_user_prompt(ticket))
    except httpx.HTTPError as exc:
        raise NLPError(f"Could not reach OpenAI: {exc}") from exc
    return [case.model_dump() for case in _parse(raw)]

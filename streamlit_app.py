"""Simple Streamlit UI for the Jira test case generator API."""
import atexit
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
import urllib.error
import urllib.request

import streamlit as st


st.set_page_config(page_title="Ticket to test cases", page_icon="🧪", layout="wide")
st.title("Jira ticket to test cases")
st.caption("Fetch a Jira issue or paste its contents, then generate test cases.")

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def api_is_available(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/health", timeout=1):
            return True
    except (urllib.error.URLError, TimeoutError):
        return False


@st.cache_resource(show_spinner=False)
def start_local_backend(base_url: str):
    """Start FastAPI once when the configured local API is not already running."""
    parsed = urlparse(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None
    if api_is_available(base_url):
        return None

    host = parsed.hostname
    port = parsed.port or 8000
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", str(port)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start the API: {exc}") from exc
    atexit.register(process.terminate)

    for _ in range(40):
        if api_is_available(base_url):
            return process
        if process.poll() is not None:
            raise RuntimeError("The API process stopped while starting. Check that the Python requirements are installed.")
        time.sleep(0.25)
    process.terminate()
    raise RuntimeError("The API did not start within 10 seconds.")


def api_request(base_url: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = str(exc)
        raise RuntimeError(detail) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Cannot reach the backend at {base_url}. Is it running?") from exc


def ticket_from_text(content: str) -> dict:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    key_match = re.search(r"[A-Z][A-Z0-9_]+-\d+", content, re.IGNORECASE)
    key = key_match.group(0).upper() if key_match else "PASTED_TICKET"
    summary_line = next((line for line in lines if line.lower().startswith("summary:")), "")
    summary = summary_line.split(":", 1)[1].strip() if summary_line else (lines[0] if lines else "Pasted Jira ticket")
    if key_match:
        summary = summary.replace(key_match.group(0), "", 1).lstrip(" -:|")
    return {
        "key": key, "summary": summary or "Pasted Jira ticket", "description": content,
        "user_story": content, "acceptance_criteria": "", "comments": [],
    }


def generate(ticket: dict) -> None:
    st.session_state.ticket = ticket
    result = api_request(BACKEND_URL, "/api/generate", {"ticket": ticket})
    st.session_state.test_cases = result.get("test_cases", [])


with st.sidebar:
    try:
        start_local_backend(BACKEND_URL)
    except RuntimeError as exc:
        st.error(str(exc))
    if st.button("Check Jira connection", use_container_width=True):
        try:
            result = api_request(BACKEND_URL, "/api/jira/connection")
            st.success(result.get("message", "Jira connection is available."))
        except RuntimeError as exc:
            st.error(str(exc))
    try:
        readiness = api_request(BACKEND_URL, "/api/settings")
        st.markdown("### Project info")
        st.markdown(f"**OpenAI model:** `{readiness.get('openai_model', 'gpt-4o-mini')}`")
        st.caption("Generates happy path, negative, and edge case tests from ticket details.")
        if not readiness.get("jira_configured") or not readiness.get("openai_configured"):
            st.warning("Set Jira and OpenAI credentials in the project-root .env, then restart the app.")
    except RuntimeError:
        st.info("The local API is starting or unavailable. Check that the app dependencies are installed.")


fetch_tab, paste_tab = st.tabs(["Fetch from Jira", "Paste ticket"])
with fetch_tab:
    with st.form("fetch_ticket"):
        ticket_id = st.text_input("Jira issue key", placeholder="PROJ-123")
        fetch_submitted = st.form_submit_button("Fetch and generate test cases", type="primary")
    if fetch_submitted:
        if not ticket_id.strip():
            st.error("Enter a Jira issue key.")
        else:
            try:
                with st.spinner("Fetching ticket and generating test cases…"):
                    ticket = api_request(BACKEND_URL, "/api/ticket", {"ticket_id": ticket_id.strip()})
                    generate(ticket)
                st.success("Test cases generated.")
            except RuntimeError as exc:
                st.error(str(exc))

with paste_tab:
    with st.form("paste_ticket"):
        pasted = st.text_area("Ticket content", height=180,
                              placeholder="Paste the issue key, summary, description, and acceptance criteria")
        paste_submitted = st.form_submit_button("Generate from pasted ticket", type="primary")
    if paste_submitted:
        if not pasted.strip():
            st.error("Paste ticket content first.")
        else:
            try:
                with st.spinner("Generating test cases…"):
                    generate(ticket_from_text(pasted.strip()))
                st.success("Test cases generated.")
            except RuntimeError as exc:
                st.error(str(exc))


ticket = st.session_state.get("ticket")
cases = st.session_state.get("test_cases")
if ticket:
    st.subheader(f"{ticket.get('key', '')}: {ticket.get('summary', '')}")
    with st.expander("Ticket details", expanded=False):
        st.markdown("**User story / description**")
        st.write(ticket.get("user_story") or ticket.get("description") or "No description.")
        st.markdown("**Acceptance criteria**")
        st.write(ticket.get("acceptance_criteria") or "None found.")
        if ticket.get("comments"):
            st.caption(f"{len(ticket['comments'])} Jira comment(s) included.")

if cases is not None:
    st.subheader("Generated test cases")
    if cases:
        table_columns = ["ID", "Title", "Type", "Preconditions", "Steps", "Expected result"]
        header_cells = st.columns([0.65, 1.8, 1.0, 1.7, 3.2, 2.0])
        for cell, label in zip(header_cells, table_columns):
            cell.markdown(f"**{label}**")

        for case in cases:
            with st.container(border=True):
                cells = st.columns([0.65, 1.8, 1.0, 1.7, 3.2, 2.0])
                cells[0].write(case.get("id", ""))
                cells[1].write(case.get("title", ""))
                cells[2].write(case.get("type", ""))
                cells[3].write(case.get("preconditions", ""))
                steps = case.get("steps", [])
                cells[4].markdown("\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1)))
                cells[5].write(case.get("expected_result", ""))

        csv_buffer = io.StringIO()
        columns = ["id", "title", "type", "preconditions", "steps", "expected_result"]
        writer = csv.DictWriter(csv_buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for case in cases:
            row = dict(case)
            row["steps"] = "\n".join(f"{i}. {step}" for i, step in enumerate(case.get("steps", []), 1))
            writer.writerow(row)
        st.download_button("Download CSV", csv_buffer.getvalue().encode("utf-8-sig"),
                           file_name=f"{ticket.get('key', 'ticket')}_test_cases.csv", mime="text/csv")

        with st.expander("Send by email"):
            with st.form("send_email"):
                recipient = st.text_input("Recipient email address")
                email_submitted = st.form_submit_button("Send test cases")
            if email_submitted:
                if not recipient.strip():
                    st.error("Enter a recipient email address.")
                else:
                    try:
                        api_request(BACKEND_URL, "/api/email",
                                    {"recipient": recipient.strip(), "ticket": ticket, "test_cases": cases})
                        st.success(f"Test cases sent to {recipient.strip()}.")
                    except RuntimeError as exc:
                        st.error(str(exc))
    else:
        st.info("No test cases were returned.")

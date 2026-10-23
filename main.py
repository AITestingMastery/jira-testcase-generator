"""FastAPI entry point. Run with: python -m uvicorn main:app --reload --port 8000"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from src.email_service import EmailError, send_test_cases
from src.jira_service import JiraError, JiraService
from src.nlp_service import NLPError, generate_test_cases

load_dotenv(Path(__file__).with_name(".env"))

app = FastAPI(title="Jira to Test Case Generator")


class TicketReq(BaseModel):
    ticket_id: str


class GenerateReq(BaseModel):
    ticket: dict


class EmailReq(BaseModel):
    recipient: str
    ticket: dict
    test_cases: list[dict]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/settings")
def get_settings():
    return {
        "jira_configured": bool(os.getenv("JIRA_BASE_URL") and os.getenv("JIRA_TOKEN")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "email_configured": bool(
            os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM_EMAIL") and os.getenv("SMTP_PASSWORD")
        ),
    }


def jira_service() -> JiraService:
    return JiraService(
        os.getenv("JIRA_BASE_URL", ""),
        os.getenv("JIRA_USERNAME", ""),
        os.getenv("JIRA_TOKEN", ""),
        os.getenv("JIRA_AUTH_MODE", "basic"),
    )


@app.get("/api/jira/connection")
def check_jira_connection():
    """Check Jira URL and credentials; returns diagnostics without secrets."""
    try:
        return jira_service().check_connection()
    except JiraError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.post("/api/ticket")
def get_ticket(req: TicketReq):
    try:
        return jira_service().fetch_ticket(req.ticket_id)
    except JiraError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.post("/api/generate")
def generate(req: GenerateReq):
    try:
        return {"test_cases": generate_test_cases(req.ticket)}
    except NLPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/email")
def email_test_cases(req: EmailReq):
    try:
        send_test_cases(req.recipient, req.ticket, req.test_cases)
        return {"sent": True}
    except EmailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

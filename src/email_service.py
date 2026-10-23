"""Email generated test cases using the backend's configured SMTP account."""
from email.message import EmailMessage
from email.utils import parseaddr
import os
import smtplib
import ssl


class EmailError(Exception):
    pass


def send_test_cases(recipient: str, ticket: dict, cases: list[dict]) -> None:
    address = recipient.strip()
    parsed_name, parsed_address = parseaddr(address)
    if not parsed_address or parsed_address != address or "@" not in parsed_address:
        raise EmailError("Enter a valid recipient email address.")

    host = os.getenv("SMTP_HOST", "")
    sender = os.getenv("SMTP_FROM_EMAIL", "")
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not sender or not password:
        raise EmailError("Configure SMTP_HOST, SMTP_FROM_EMAIL, and SMTP_PASSWORD in the project-root .env to send email.")

    key = ticket.get("key", "Jira ticket")
    summary = ticket.get("summary", "")
    lines = [f"Test cases for {key}: {summary}", ""]
    for case in cases:
        lines.extend([
            f"{case['id']}: {case['title']} ({case['type']})",
            f"Preconditions: {case['preconditions']}",
            "Steps:",
            *[f"  {index}. {step}" for index, step in enumerate(case["steps"], 1)],
            f"Expected result: {case['expected_result']}",
            "",
        ])

    message = EmailMessage()
    message["Subject"] = f"[{key}] Generated test cases"
    message["From"] = sender
    message["To"] = address
    message.set_content("\n".join(lines))

    port = int(os.getenv("SMTP_PORT", "587"))
    security = os.getenv("SMTP_SECURITY", "starttls").lower()
    timeout = 20
    try:
        if security == "ssl":
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        with client as smtp:
            smtp.ehlo()
            if security == "starttls":
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.login(sender, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        raise EmailError(f"Could not send email: {exc}") from exc

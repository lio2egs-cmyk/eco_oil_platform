# -*- coding: utf-8 -*-
"""
Shared office-notification mailer. Same two-channel layering as the magic-link
sender in auth.py (kept separate on purpose — do not touch that flow):

1. Resend HTTPS API when RESEND_API_KEY is set — production (Railway blocks
   outbound SMTP ports entirely).
2. SMTP (smtp.gmail.com STARTTLS) when MAIL_* are set — local dev.

Failures are logged and swallowed by the caller's choice — a notification must
never fail the business action that triggered it.
"""
import os
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import current_app

OFFICE_EMAIL = "office@eco-oil.co.il"


def send_office_email(subject: str, html: str, text: str = None, to: str = None) -> bool:
    """Send an internal notification email. Returns True on confirmed send."""
    to = to or OFFICE_EMAIL
    from_addr = os.environ.get("MAIL_FROM_ADDRESS", os.environ.get("MAIL_USERNAME", ""))
    from_name = os.environ.get("MAIL_FROM_NAME", "")

    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key and from_addr:
        sender = formataddr((from_name, from_addr)) if from_name else from_addr
        try:
            import requests
            payload = {"from": sender, "to": [to], "subject": subject, "html": html}
            if text:
                payload["text"] = text
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": "Bearer " + resend_key},
                json=payload, timeout=20,
            )
            if r.status_code < 300:
                return True
            current_app.logger.error("office email (Resend) failed %s: %s | subject: %s",
                                     r.status_code, r.text[:200], subject)
        except Exception as exc:
            current_app.logger.error("office email (Resend) error: %s | subject: %s", exc, subject)
        return False

    smtp_host = os.environ.get("MAIL_HOST")
    smtp_user = os.environ.get("MAIL_USERNAME")
    smtp_pass = os.environ.get("MAIL_PASSWORD")
    if not (smtp_host and smtp_user and smtp_pass and from_addr):
        current_app.logger.warning("office email — no mail channel configured | subject: %s", subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr)) if from_name else from_addr
    msg["To"] = to
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP(smtp_host, int(os.environ.get("MAIL_PORT", "587")), timeout=20) as server:
            server.ehlo(); server.starttls(); server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception as exc:
        current_app.logger.error("office email (SMTP) failed: %s | subject: %s", exc, subject)
        return False

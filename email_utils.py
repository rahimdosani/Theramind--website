# email_utils.py — SMTP ONLY (NO RESEND)
import os
import smtplib
import logging
from email.message import EmailMessage

logger = logging.getLogger("theramind.email")

# --------------------------------------------------
# SMTP Config (REQUIRED)
# --------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_FROM = os.getenv(
    "EMAIL_FROM",
    "Theramind <theramind12@gmail.com>"
)

# Validate config early
if not all([SMTP_HOST, SMTP_USER, SMTP_PASS]):
    raise RuntimeError("SMTP is not fully configured")

# --------------------------------------------------
# Core email sender (STRICT)
# --------------------------------------------------
def send_email(to_email: str, subject: str, body: str) -> None:
    """
    Sends an email via SMTP or raises RuntimeError.
    No silent fallbacks. No third-party providers.
    """
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

    except Exception:
        logger.exception("SMTP email failed")
        raise RuntimeError("Email delivery failed")

# --------------------------------------------------
# OTP email
# --------------------------------------------------
def send_otp_email(to_email: str, otp: str) -> None:
    body = f"""
Your Theramind verification code is:

{otp}

This code will expire in 10 minutes.

If you did not request this, you can safely ignore this email.

— Theramind
""".strip()

    send_email(
        to_email=to_email,
        subject="Your Theramind verification code",
        body=body,
    )

# email_utils.py
import os
import smtplib
import logging
from email.message import EmailMessage

logger = logging.getLogger("theramind.email")

# --------------------------------------------------
# Config
# --------------------------------------------------
EMAIL_FROM = os.getenv("EMAIL_FROM", "Theramind <no-reply@theramind.app>")

# ---- Resend ----
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
USE_RESEND = False
resend = None

if RESEND_API_KEY:
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        USE_RESEND = True
        logger.info("Resend email enabled")
    except Exception:
        logger.exception("Resend import failed")

# ---- SMTP ----
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

USE_SMTP = all([SMTP_HOST, SMTP_USER, SMTP_PASS])

# --------------------------------------------------
# Core email sender (STRICT)
# --------------------------------------------------
def send_email(to_email: str, subject: str, body: str) -> None:
    """
    Sends an email or raises RuntimeError.
    NO silent fallbacks in production.
    """

    # ---- Resend ----
    if USE_RESEND:
        try:
            resend.Emails.send({
                "from": EMAIL_FROM,
                "to": to_email,
                "subject": subject,
                "text": body,
            })
            return
        except Exception:
            logger.exception("Resend failed")

    # ---- SMTP ----
    if USE_SMTP:
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

            return
        except Exception:
            logger.exception("SMTP failed")

    # ---- HARD FAIL ----
    raise RuntimeError("No email provider available")

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

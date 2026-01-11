# email_utils.py
import os
import resend

# ======================================================
# CONFIG
# ======================================================

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Theramind <onboarding@resend.dev>")

if not RESEND_API_KEY:
    raise RuntimeError("RESEND_API_KEY is not set")

resend.api_key = RESEND_API_KEY


# ======================================================
# GENERIC EMAIL SENDER (future-proof)
# ======================================================

def send_email(to_email: str, subject: str, text: str):
    """
    Sends a plain-text email using Resend.
    Works reliably on mobile + desktop.
    """

    resend.Emails.send({
        "from": EMAIL_FROM,
        "to": to_email,
        "subject": subject,
        "text": text
    })


# ======================================================
# OTP EMAIL (LOGIN / SIGNUP / VERIFY)
# ======================================================

def send_otp_email(to_email: str, otp: str, purpose: str = "verify"):
    """
    Sends a 6-digit OTP.
    Guaranteed delivery on:
    - Gmail mobile
    - Gmail desktop
    - Outlook
    - Yahoo
    """

    subject = "Your Theramind verification code"

    text = f"""
Your Theramind verification code is:

{otp}

This code will expire in 10 minutes.

If you did not request this, you can safely ignore this email.

— Theramind
""".strip()

    send_email(
        to_email=to_email,
        subject=subject,
        text=text
    )

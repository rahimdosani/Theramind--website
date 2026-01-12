import os
import resend

# ======================================================
# CONFIG (RENDER SAFE)
# ======================================================

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Theramind <onboarding@resend.dev>")

if not RESEND_API_KEY:
    raise RuntimeError("RESEND_API_KEY is not set")

resend.api_key = RESEND_API_KEY


# ======================================================
# GENERIC EMAIL SENDER
# ======================================================

def send_email(to_email: str, subject: str, text: str):
    """
    Sends a plain-text email using Resend.
    Works on:
    - Render
    - Mobile
    - Desktop
    - Gmail / Outlook / Yahoo
    """

    try:
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": to_email,
            "subject": subject,
            "text": text
        })
    except Exception as e:
        # CRITICAL: bubble error so signup route can handle it
        raise RuntimeError(f"Email send failed: {e}")


# ======================================================
# OTP EMAIL (SIGNUP / LOGIN / VERIFY)
# ======================================================

def send_otp_email(to_email: str, otp: str, purpose: str = "verify"):
    """
    Sends a 6-digit OTP email.
    """

    subject = "Your Theramind verification code"

    text = f"""
Hi,

Your Theramind verification code is:

{otp}

This code will expire in 10 minutes.

If you did not request this, you can safely ignore this email.

— Theramind Team
""".strip()

    send_email(
        to_email=to_email,
        subject=subject,
        text=text
    )

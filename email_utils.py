# email_utils.py
import os
import smtplib
from email.message import EmailMessage

# =========================
# SMTP CONFIG
# =========================
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Theramind <no-reply@localhost>")


# =========================
# BASE EMAIL SENDER
# =========================
def send_email(to_email, subject, body, html=None):
    """
    Generic email sender.
    - Uses SMTP if configured
    - Prints to console in dev mode
    """
    if not SMTP_HOST:
        print("=== EMAIL (DEV MODE) ===")
        print("To:", to_email)
        print("Subject:", subject)
        print("Body:\n", body)
        print("=======================")
        return True

    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    if html:
        msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        print("Failed to send email:", e)
        return False


# =========================
# OTP EMAIL (LOGIN / VERIFY)
# =========================
def send_otp_email(to_email, otp, purpose="login"):
    """
    Sends a 6-digit OTP for:
    - Login
    - Email verification
    """

    subject = "Your Theramind verification code"

    body = f"""
Hi,

Your Theramind verification code is:

{otp}

This code will expire in 10 minutes.

If you did not request this, you can safely ignore this email.

— Theramind Team
"""

    html = f"""
<html>
  <body style="font-family:Arial,Helvetica,sans-serif;background:#f9fafb;padding:20px;">
    <div style="max-width:520px;margin:auto;background:white;padding:24px;border-radius:10px;">
      <h2 style="color:#1f2937;">Theramind Verification Code</h2>
      <p>Your verification code is:</p>

      <div style="
        font-size:26px;
        font-weight:bold;
        letter-spacing:6px;
        margin:16px 0;
        color:#111827;
      ">
        {otp}
      </div>

      <p>This code will expire in <b>10 minutes</b>.</p>

      <p style="color:#6b7280;font-size:14px;">
        If you did not request this, please ignore this email.
      </p>

      <hr style="margin:24px 0;" />

      <p style="font-size:12px;color:#9ca3af;">
        Theramind • Mental Wellness Platform
      </p>
    </div>
  </body>
</html>
"""

    return send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        html=html
    )

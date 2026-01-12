# email_utils.py
import os
import smtplib
from email.message import EmailMessage

# --------------------------------------------------
# Optional Resend support (SAFE)
# --------------------------------------------------
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Theramind <no-reply@theramind.app>")

USE_RESEND = False
resend = None

if RESEND_API_KEY:
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        USE_RESEND = True
        print("✅ Resend email enabled")
    except Exception as e:
        print("⚠️ Resend import failed, falling back to SMTP:", e)

# --------------------------------------------------
# SMTP fallback (REQUIRED on Render if no Resend)
# --------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

USE_SMTP = all([SMTP_HOST, SMTP_USER, SMTP_PASS])

# --------------------------------------------------
# Core email sender (NEVER CRASHES)
# --------------------------------------------------
def send_email(to_email, subject, body):
    # ---- Try Resend first ----
    if USE_RESEND:
        try:
            resend.Emails.send({
                "from": EMAIL_FROM,
                "to": to_email,
                "subject": subject,
                "text": body
            })
            return True
        except Exception as e:
            print("❌ Resend failed:", e)

    # ---- Fallback to SMTP ----
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

            return True
        except Exception as e:
            print("❌ SMTP failed:", e)

    # ---- Dev / last-resort fallback ----
    print("📧 EMAIL (DEV MODE)")
    print("To:", to_email)
    print("Subject:", subject)
    print(body)
    print("────────────────────")

    return False


# --------------------------------------------------
# OTP email
# --------------------------------------------------
def send_otp_email(to_email, otp, purpose="verify"):
    body = f"""
Your Theramind verification code is:

{otp}

This code will expire in 10 minutes.

If you did not request this, you can safely ignore this email.

— Theramind
""".strip()

    ok = send_email(
        to_email=to_email,
        subject="Your Theramind verification code",
        body=body
    )

    if not ok:
        raise RuntimeError("Email delivery failed")

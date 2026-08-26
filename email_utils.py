import os
import base64
import json
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


EMAIL_FROM = "Theramind <theramind12@gmail.com>"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _get_gmail_service():
    token_b64 = os.getenv("GMAIL_TOKEN_BASE64")

    if not token_b64:
        raise RuntimeError("GMAIL_TOKEN_BASE64 not set")

    try:
        token_json = base64.b64decode(token_b64).decode("utf-8")
        token_data = json.loads(token_json)

        creds = Credentials.from_authorized_user_info(
            token_data,
            SCOPES
        )

        # Access tokens expire periodically.
        # If expired, refresh using the long-lived refresh token.
        if creds.expired:
            if not creds.refresh_token:
                raise RuntimeError(
                    "Gmail access token expired and no refresh token is available"
                )

            creds.refresh(Request())

        return build(
            "gmail",
            "v1",
            credentials=creds
        )

    except Exception as e:
        raise RuntimeError(
            f"Unable to authenticate with Gmail: {e}"
        ) from e


def send_email(to_email: str, subject: str, body: str):
    service = _get_gmail_service()

    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    encoded = base64.urlsafe_b64encode(
        msg.as_bytes()
    ).decode("utf-8")

    service.users().messages().send(
        userId="me",
        body={"raw": encoded}
    ).execute()


def send_otp_email(to_email: str, otp: str):
    body = f"""
Your Theramind verification code is:

{otp}

This code will expire in 10 minutes.

— Theramind
""".strip()

    send_email(
        to_email=to_email,
        subject="Your Theramind verification code",
        body=body,
    )
# email_utils.py
import base64
import pickle
import os
from email.message import EmailMessage
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

EMAIL_FROM = "Theramind <theramind12@gmail.com>"
TOKEN_PATH = "gmail_token.pickle"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def _get_gmail_service():
    if not os.path.exists(TOKEN_PATH):
        raise RuntimeError("Gmail token not found")

    with open(TOKEN_PATH, "rb") as f:
        creds = pickle.load(f)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("gmail", "v1", credentials=creds)

def send_email(to_email: str, subject: str, body: str):
    service = _get_gmail_service()

    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()

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

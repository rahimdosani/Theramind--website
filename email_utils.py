import os

import requests
from dotenv import load_dotenv

load_dotenv()

MAILJET_API_KEY = os.getenv("MAILJET_API_KEY")
MAILJET_SECRET_KEY = os.getenv("MAILJET_SECRET_KEY")
MAILJET_SENDER_EMAIL = os.getenv("MAILJET_SENDER_EMAIL")
MAILJET_SENDER_NAME = os.getenv("MAILJET_SENDER_NAME", "Theramind")


def send_email(to_email: str, subject: str, body: str):
    if not MAILJET_API_KEY or not MAILJET_SECRET_KEY:
        raise RuntimeError("Mailjet API credentials are not configured")

    if not MAILJET_SENDER_EMAIL:
        raise RuntimeError("MAILJET_SENDER_EMAIL is not configured")

    payload = {
        "Messages": [
            {
                "From": {
                    "Email": MAILJET_SENDER_EMAIL,
                    "Name": MAILJET_SENDER_NAME
                },
                "To": [
                    {
                        "Email": to_email
                    }
                ],
                "Subject": subject,
                "TextPart": body
            }
        ]
    }

    response = requests.post(
        "https://api.mailjet.com/v3.1/send",
        auth=(MAILJET_API_KEY, MAILJET_SECRET_KEY),
        json=payload,
        timeout=15
    )

    if not response.ok:
        raise RuntimeError(
            f"Mailjet email failed: {response.status_code} - {response.text}"
        )


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
        body=body
    )
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

flow = InstalledAppFlow.from_client_secrets_file(
    "gmail_credentials.json",
    SCOPES
)

creds = flow.run_local_server(port=0)

# ✅ SAVE AS JSON (NOT PICKLE)
with open("token.json", "w") as f:
    f.write(creds.to_json())

print("Gmail token generated successfully (token.json)")

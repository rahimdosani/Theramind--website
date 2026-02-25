import json
import base64
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

flow = InstalledAppFlow.from_client_secrets_file(
    "gmail_credentials.json",
    SCOPES
)

creds = flow.run_local_server(port=0)

token_json = creds.to_json()

token_b64 = base64.b64encode(token_json.encode()).decode()

print("\n\n=== COPY THIS BASE64 TOKEN ===\n")
print(token_b64)

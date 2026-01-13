from google_auth_oauthlib.flow import InstalledAppFlow
import pickle

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

flow = InstalledAppFlow.from_client_secrets_file(
    "gmail_credentials.json",
    SCOPES
)

creds = flow.run_local_server(port=0)

with open("gmail_token.pickle", "wb") as f:
    pickle.dump(creds, f)

print("Gmail token generated successfully")

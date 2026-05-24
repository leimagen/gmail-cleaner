import os
import base64
import json
from email.mime.text import MIMEText
from typing import Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv()

# Required for local HTTP development — oauthlib blocks OAuth over non-HTTPS by default
# Set OAUTHLIB_INSECURE_TRANSPORT=0 in .env to enforce HTTPS (production)
if os.getenv("OAUTHLIB_INSECURE_TRANSPORT", "1") != "0":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials/credentials.json")
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/oauth/callback")

# Store pending flows by state so the same object (with PKCE verifier) is reused at exchange
_pending_flows: dict[str, Flow] = {}


def get_oauth_flow() -> Flow:
    flow = Flow.from_client_secrets_file(CREDENTIALS_FILE, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    return flow


def get_auth_url() -> tuple[str, str]:
    flow = get_oauth_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _pending_flows[state] = flow  # preserve flow so code_verifier survives to exchange
    return auth_url, state


def exchange_code(code: str, state: str) -> dict:
    flow = _pending_flows.pop(state, None) or get_oauth_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }


def load_credentials(token_file: str) -> Optional[Credentials]:
    if not os.path.exists(token_file):
        return None
    with open(token_file) as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(token_file, creds)
    return creds


def save_credentials(token_file: str, creds: Credentials):
    os.makedirs(os.path.dirname(token_file), exist_ok=True)
    with open(token_file, "w") as f:
        json.dump({
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or []),
        }, f)


def get_service(token_file: str):
    creds = load_credentials(token_file)
    if not creds:
        raise ValueError(f"No valid credentials at {token_file}")
    return build("gmail", "v1", credentials=creds)


def get_user_email(token_file: str) -> str:
    service = get_service(token_file)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def fetch_messages(token_file: str, max_results: int = 500, page_token: str = None) -> dict:
    service = get_service(token_file)
    params = {"userId": "me", "maxResults": min(max_results, 500)}
    if page_token:
        params["pageToken"] = page_token
    return service.users().messages().list(**params).execute()


def get_message_detail(token_file: str, message_id: str) -> dict:
    service = get_service(token_file)
    return service.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["From", "Subject", "Date", "List-Unsubscribe", "List-Unsubscribe-Post",
                         "Received-SPF", "DKIM-Signature", "Authentication-Results"]
    ).execute()


def create_filter(token_file: str, sender: str, action: str = "trash") -> dict:
    service = get_service(token_file)
    filter_body = {
        "criteria": {"from": sender},
        "action": {"addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]} if action == "trash"
                  else {"addLabelIds": ["SPAM"]}
    }
    return service.users().settings().filters().create(userId="me", body=filter_body).execute()


def send_email(token_file: str, to: str, subject: str, body: str = "") -> dict:
    service = get_service(token_file)
    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return service.users().messages().send(userId="me", body={"raw": raw}).execute()


def trash_messages_from_sender(token_file: str, sender: str) -> int:
    service = get_service(token_file)
    result = service.users().messages().list(
        userId="me", q=f"from:{sender}", maxResults=500
    ).execute()
    messages = result.get("messages", [])
    for msg in messages:
        try:
            service.users().messages().trash(userId="me", id=msg["id"]).execute()
        except HttpError:
            pass
    return len(messages)


def credentials_exist(token_file: str) -> bool:
    return os.path.exists(token_file)

# Gmail Cleaner

A local web app that finds spam, phishing and newsletters in Gmail, unsubscribes from them or blocks them, and checks
your address against known data breaches. Everything runs on your own machine.

One-day prototype, built in May 2026. Case study: https://dev.luitiescobar.com/work/gmail-cleaner/

## Features

- **Several Gmail accounts**, added through a guided OAuth wizard.
- **Inbox scan** of up to 500 messages. Each sender gets a risk score from its headers, authentication results
  (SPF, DKIM, DMARC), phishing keywords and a list of bulk-mail domains.
- **Unsubscribe** through the standard `List-Unsubscribe` header. It never unsubscribes from a message scored as
  phishing, because in phishing that link is the trap.
- **Block a sender**: creates a Gmail filter that sends their future mail to the trash and clears what's already there.
- **Data breach check** against Have I Been Pwned, with Claude Haiku explaining each breach and the steps to take.
- **History** of every action, and a small **Chrome extension** with a badge and a popup.

The spam scoring is a set of readable rules. AI is only used for the breach advice.

## Setup

### 1. Google Cloud

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com) and enable the **Gmail API**.
2. Create an **OAuth 2.0 Client ID** of type **Web application** with the redirect URI
   `http://localhost:8000/oauth/callback`.
3. Download the JSON, rename it to `credentials.json` and put it in `credentials/` (git-ignored).

### 2. Install and configure

```bash
pip install -r requirements.txt
cp .env.example .env
```

Optionally add `HIBP_API_KEY` (breach check) and `ANTHROPIC_API_KEY` (breach advice) to `.env`.

### 3. Run

```bash
uvicorn backend.main:app --reload
```

Open http://localhost:8000 and the onboarding wizard takes it from there.

## Chrome extension

1. Open `chrome://extensions/` and turn on **Developer mode**.
2. Click **Load unpacked** and select the `chrome-extension/` folder.
3. The first time you open the popup, confirm the server URL (default `http://localhost:8000`).

The badge shows the number of open issues. The popup can start a scan or open the dashboard. It needs the local app
running.

## Structure

```
backend/
  main.py           FastAPI app and routes
  database.py       SQLAlchemy models (SQLite in data/)
  accounts.py       multi-account management
  gmail_client.py   OAuth2 + Gmail API wrapper
  spam_analyzer.py  spam and phishing scoring
  unsubscriber.py   List-Unsubscribe handling
  blocker.py        Gmail filters
  breach_checker.py Have I Been Pwned
  breach_advice.py  breach explanations with Claude
frontend/           Jinja2 templates, CSS and JS
chrome-extension/   Manifest V3
```

## Privacy

- Data is stored locally in `data/` (SQLite). OAuth credentials and tokens live in `credentials/`. Both are git-ignored.
- The app only talks to the Gmail API, Have I Been Pwned and, if you add a key, the Anthropic API.

## Author

Luiti Escobar · https://dev.luitiescobar.com

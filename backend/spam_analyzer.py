import re
from datetime import datetime
from email.utils import parseaddr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .database import ScannedEmail, Account, ActionLog
from . import gmail_client

PHISHING_KEYWORDS = [
    "verify your account", "confirm your identity", "suspended", "unusual activity",
    "click here to unlock", "update your payment", "account will be closed",
    "you have won", "claim your prize", "urgent action required",
    "wire transfer", "bitcoin", "crypto payment", "inheritance",
]

SPAM_DOMAINS = {
    "mailchimp.com", "sendgrid.net", "constantcontact.com", "klaviyo.com",
    "mailgun.org", "amazonses.com", "sparkpostmail.com",
}


def _parse_headers(msg: dict) -> dict:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return headers


def _extract_sender(from_header: str) -> tuple[str, str]:
    name, addr = parseaddr(from_header)
    addr = addr.lower().strip()
    domain = addr.split("@")[-1] if "@" in addr else addr
    return addr, domain


def _check_auth_results(headers: dict) -> str:
    auth = headers.get("authentication-results", "").lower()
    spf = headers.get("received-spf", "").lower()
    if "spf=fail" in auth or "spf=fail" in spf or "dkim=fail" in auth:
        return "high"
    if "spf=softfail" in auth or "dmarc=fail" in auth:
        return "medium"
    return "low"


def _check_phishing_keywords(subject: str) -> bool:
    subject_lower = subject.lower()
    return any(kw in subject_lower for kw in PHISHING_KEYWORDS)


def _parse_unsubscribe(header_value: str) -> tuple[str | None, str | None]:
    mailto = None
    url = None
    parts = [p.strip().strip("<>") for p in header_value.split(",")]
    for part in parts:
        if part.startswith("mailto:"):
            mailto = part[7:]
        elif part.startswith("http"):
            url = part
    return mailto, url


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


async def scan_account_emails(db: AsyncSession, account: Account, max_results: int = 500) -> int:
    token_file = account.token_file
    existing_ids_res = await db.execute(
        select(ScannedEmail.message_id).where(ScannedEmail.account_id == account.id)
    )
    existing_ids = set(existing_ids_res.scalars().all())

    fetched = 0
    page_token = None
    new_emails = []

    while fetched < max_results:
        batch_size = min(100, max_results - fetched)
        try:
            result = gmail_client.fetch_messages(token_file, batch_size, page_token)
        except Exception:
            break

        messages = result.get("messages", [])
        if not messages:
            break

        for msg_stub in messages:
            msg_id = msg_stub["id"]
            if msg_id in existing_ids:
                continue
            try:
                msg = gmail_client.get_message_detail(token_file, msg_id)
            except Exception:
                continue

            headers = _parse_headers(msg)
            from_header = headers.get("from", "")
            sender, domain = _extract_sender(from_header)
            subject = headers.get("subject", "")
            date = _parse_date(headers.get("date"))

            risk = _check_auth_results(headers)
            if _check_phishing_keywords(subject):
                risk = "phishing" if risk == "high" else "high"

            unsub_header = headers.get("list-unsubscribe", "")
            has_unsub = bool(unsub_header)
            unsub_mailto, unsub_url = _parse_unsubscribe(unsub_header) if has_unsub else (None, None)

            # Bulk mailer domains lower phishing risk (they're spam, not phishing)
            if domain in SPAM_DOMAINS and risk == "phishing":
                risk = "high"

            new_emails.append(ScannedEmail(
                account_id=account.id,
                message_id=msg_id,
                sender=sender,
                sender_domain=domain,
                subject=subject[:500] if subject else None,
                date=date,
                risk_level=risk,
                has_unsubscribe=1 if has_unsub else 0,
                unsubscribe_mailto=unsub_mailto,
                unsubscribe_url=unsub_url,
                action_taken="none",
            ))

        fetched += len(messages)
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    if new_emails:
        db.add_all(new_emails)
        db.add(ActionLog(
            account_id=account.id,
            action_type="scan",
            target=f"{len(new_emails)} emails",
            result="completed",
        ))
        await db.commit()

    return len(new_emails)

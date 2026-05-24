import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from .database import ScannedEmail, ActionLog, Account
from . import gmail_client


async def do_unsubscribe(db: AsyncSession, account: Account, sender: str) -> dict:
    result = await db.execute(
        select(ScannedEmail).where(
            ScannedEmail.account_id == account.id,
            ScannedEmail.sender == sender,
            ScannedEmail.has_unsubscribe == 1,
            ScannedEmail.action_taken == "none",
        ).limit(1)
    )
    email = result.scalar_one_or_none()
    if not email:
        return {"ok": False, "reason": "No unsubscribe info found for this sender"}

    # Never unsubscribe from phishing — it confirms the email is active
    if email.risk_level == "phishing":
        return {"ok": False, "reason": "Phishing sender — unsubscribe blocked for safety. Use block instead."}

    success = False
    method_used = None

    if email.unsubscribe_url:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.post(email.unsubscribe_url)
                if resp.status_code < 400:
                    success = True
                    method_used = f"HTTP POST to {email.unsubscribe_url}"
                else:
                    resp2 = await client.get(email.unsubscribe_url)
                    success = resp2.status_code < 400
                    method_used = f"HTTP GET to {email.unsubscribe_url}"
        except Exception as e:
            pass

    if not success and email.unsubscribe_mailto:
        try:
            gmail_client.send_email(
                account.token_file,
                to=email.unsubscribe_mailto,
                subject="Unsubscribe",
                body="Please unsubscribe me from this mailing list.",
            )
            success = True
            method_used = f"Email to {email.unsubscribe_mailto}"
        except Exception:
            pass

    if success:
        await db.execute(
            update(ScannedEmail)
            .where(ScannedEmail.account_id == account.id, ScannedEmail.sender == sender)
            .values(action_taken="unsubscribed")
        )
        db.add(ActionLog(
            account_id=account.id,
            action_type="unsubscribe",
            target=sender,
            result=f"Success via {method_used}",
        ))
        await db.commit()
        return {"ok": True, "method": method_used}

    return {"ok": False, "reason": "All unsubscribe methods failed"}

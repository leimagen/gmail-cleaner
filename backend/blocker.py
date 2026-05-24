from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from .database import ScannedEmail, FilterCreated, ActionLog, Account
from . import gmail_client


async def block_sender(
    db: AsyncSession,
    account: Account,
    sender: str,
    delete_existing: bool = False,
) -> dict:
    try:
        filter_result = gmail_client.create_filter(account.token_file, sender, action="trash")
        gmail_filter_id = filter_result.get("id")
    except Exception as e:
        return {"ok": False, "reason": str(e)}

    domain = sender.split("@")[-1] if "@" in sender else sender
    filter_type = "block_sender" if "@" in sender else "block_domain"

    db.add(FilterCreated(
        account_id=account.id,
        sender=sender,
        filter_type=filter_type,
        gmail_filter_id=gmail_filter_id,
    ))

    await db.execute(
        update(ScannedEmail)
        .where(ScannedEmail.account_id == account.id, ScannedEmail.sender == sender)
        .values(action_taken="blocked")
    )

    deleted_count = 0
    if delete_existing:
        try:
            deleted_count = gmail_client.trash_messages_from_sender(account.token_file, sender)
        except Exception:
            pass

    db.add(ActionLog(
        account_id=account.id,
        action_type="block",
        target=sender,
        result=f"Filter created (id={gmail_filter_id}); {deleted_count} emails trashed",
    ))
    await db.commit()

    return {
        "ok": True,
        "filter_id": gmail_filter_id,
        "emails_trashed": deleted_count,
    }

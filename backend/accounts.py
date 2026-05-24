import os
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .database import Account


TOKEN_DIR = os.getenv("GOOGLE_TOKEN_DIR", "credentials")


async def list_accounts(db: AsyncSession) -> list[Account]:
    result = await db.execute(select(Account).order_by(Account.created_at))
    return result.scalars().all()


async def get_account(db: AsyncSession, account_id: int) -> Account | None:
    result = await db.execute(select(Account).where(Account.id == account_id))
    return result.scalar_one_or_none()


async def get_account_by_email(db: AsyncSession, email: str) -> Account | None:
    result = await db.execute(select(Account).where(Account.email == email))
    return result.scalar_one_or_none()


async def create_account(db: AsyncSession, email: str, display_name: str | None = None) -> Account:
    token_file = os.path.join(TOKEN_DIR, f"token_{email.replace('@', '_at_')}.json")
    account = Account(email=email, display_name=display_name or email, token_file=token_file)
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def update_last_scan(db: AsyncSession, account_id: int):
    account = await get_account(db, account_id)
    if account:
        account.last_scan_at = datetime.utcnow()
        await db.commit()


async def delete_account(db: AsyncSession, account_id: int) -> bool:
    account = await get_account(db, account_id)
    if not account:
        return False
    if account.token_file and os.path.exists(account.token_file):
        os.remove(account.token_file)
    await db.delete(account)
    await db.commit()
    return True


async def count_accounts(db: AsyncSession) -> int:
    result = await db.execute(select(Account))
    return len(result.scalars().all())

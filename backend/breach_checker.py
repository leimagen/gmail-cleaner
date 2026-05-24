import os
import json
from datetime import datetime, timedelta
import httpx
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from .database import Breach

HIBP_API_KEY = os.getenv("HIBP_API_KEY", "")
CACHE_TTL_HOURS = 24


async def get_cached_breaches(db: AsyncSession, account_id: int) -> list[Breach]:
    result = await db.execute(
        select(Breach).where(Breach.account_id == account_id).order_by(Breach.breach_date.desc())
    )
    return result.scalars().all()


async def check_breaches(db: AsyncSession, account_id: int, email: str) -> list[Breach]:
    # Clear old cache
    cutoff = datetime.utcnow() - timedelta(hours=CACHE_TTL_HOURS)
    await db.execute(
        delete(Breach).where(Breach.account_id == account_id, Breach.checked_at < cutoff)
    )
    await db.commit()

    # Check if fresh cache exists
    existing = await get_cached_breaches(db, account_id)
    if existing:
        return existing

    headers = {
        "User-Agent": "GmailCleaner/1.0",
        "hibp-api-key": HIBP_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                headers=headers,
                params={"truncateResponse": "false"},
            )
    except Exception:
        return []

    if resp.status_code == 404:
        # No breaches found — store a sentinel so we don't re-check immediately
        return []
    if resp.status_code == 401:
        # API key required
        return []
    if resp.status_code != 200:
        return []

    data = resp.json()
    new_breaches = []
    for b in data:
        new_breaches.append(Breach(
            account_id=account_id,
            breach_name=b.get("Name", ""),
            breach_title=b.get("Title", ""),
            breach_date=b.get("BreachDate", ""),
            data_types=json.dumps(b.get("DataClasses", [])),
            description=b.get("Description", "")[:1000] if b.get("Description") else None,
            checked_at=datetime.utcnow(),
        ))

    if new_breaches:
        db.add_all(new_breaches)
        await db.commit()

    return new_breaches

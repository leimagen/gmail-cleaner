import asyncio
import os
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv

load_dotenv()

from .database import init_db, get_db
from .accounts import (
    list_accounts, get_account, get_account_by_email,
    create_account, delete_account, count_accounts, update_last_scan
)
from . import gmail_client
from .spam_analyzer import scan_account_emails
from .breach_checker import check_breaches, get_cached_breaches
from .breach_advice import get_breach_advice
from .unsubscriber import do_unsubscribe
from .blocker import block_sender

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Gmail Cleaner", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tightened per-env via CORS_ORIGINS in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))
templates.env.cache = None  # Python 3.14 compat: LRUCache unhashable dict key bug
templates.env.filters["from_json"] = json.loads

_oauth_states: dict[str, str] = {}  # state -> pending email (temp in-memory)


# ── Helpers ──────────────────────────────────────────────────────────────────

def has_credentials_file() -> bool:
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials/credentials.json")
    return os.path.exists(creds_file)


async def get_active_account_id(request: Request) -> Optional[int]:
    val = request.cookies.get("active_account_id")
    return int(val) if val and val.isdigit() else None


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, db: AsyncSession = Depends(get_db)):
    n = await count_accounts(db)
    if n == 0:
        return RedirectResponse("/setup")
    accounts = await list_accounts(db)
    active_id = await get_active_account_id(request) or accounts[0].id
    active = await get_account(db, active_id) or accounts[0]
    breaches = await get_cached_breaches(db, active.id)
    from sqlalchemy import select, func
    from .database import ScannedEmail, FilterCreated
    spam_count_res = await db.execute(
        select(func.count()).where(ScannedEmail.account_id == active.id,
                                   ScannedEmail.action_taken == "none",
                                   ScannedEmail.risk_level.in_(["high", "phishing"]))
    )
    spam_count = spam_count_res.scalar() or 0
    blocked_res = await db.execute(
        select(func.count()).where(FilterCreated.account_id == active.id)
    )
    blocked_count = blocked_res.scalar() or 0
    resp = templates.TemplateResponse(request, "index.html", {
        "accounts": accounts,
        "active": active,
        "breach_count": len(breaches),
        "spam_count": spam_count,
        "blocked_count": blocked_count,
        "has_credentials": has_credentials_file(),
    })
    resp.set_cookie("active_account_id", str(active.id))
    return resp


@app.get("/setup", response_class=HTMLResponse)
async def setup(request: Request):
    return templates.TemplateResponse(request, "setup.html", {
        "has_credentials": has_credentials_file(),
    })


@app.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, db: AsyncSession = Depends(get_db)):
    accounts = await list_accounts(db)
    active_id = await get_active_account_id(request)
    return templates.TemplateResponse(request, "accounts.html", {
        "accounts": accounts,
        "active_id": active_id,
        "has_credentials": has_credentials_file(),
    })


@app.get("/accounts/add", response_class=HTMLResponse)
async def account_add(request: Request, step: int = 1):
    if not has_credentials_file():
        return RedirectResponse("/setup")
    return templates.TemplateResponse(request, "account_add.html", {
        "step": step,
        "has_credentials": has_credentials_file(),
    })


@app.get("/accounts/{account_id}/switch")
async def switch_account(account_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    resp = RedirectResponse("/")
    resp.set_cookie("active_account_id", str(account_id))
    return resp


@app.delete("/accounts/{account_id}")
async def remove_account(account_id: int, db: AsyncSession = Depends(get_db)):
    ok = await delete_account(db, account_id)
    if not ok:
        raise HTTPException(404, "Account not found")
    return {"ok": True}


# ── OAuth ─────────────────────────────────────────────────────────────────────

@app.get("/oauth/start")
async def oauth_start(request: Request):
    if not has_credentials_file():
        return RedirectResponse("/setup?error=no_credentials")
    auth_url, state = gmail_client.get_auth_url()
    _oauth_states[state] = "pending"
    resp = RedirectResponse(auth_url)
    resp.set_cookie("oauth_state", state, httponly=True)
    return resp


@app.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if error:
        return RedirectResponse(f"/accounts/add?step=1&error={error}")

    stored_state = request.cookies.get("oauth_state")
    if not state or state != stored_state or state not in _oauth_states:
        return RedirectResponse("/accounts/add?step=1&error=invalid_state")

    try:
        token_data = gmail_client.exchange_code(code, state)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return RedirectResponse(f"/accounts/add?step=1&error=exchange_failed")

    # Determine token file path using a temp token to get email
    temp_token_path = "credentials/_temp_token.json"
    os.makedirs("credentials", exist_ok=True)
    with open(temp_token_path, "w") as f:
        json.dump(token_data, f)

    try:
        email = gmail_client.get_user_email(temp_token_path)
    except Exception:
        os.remove(temp_token_path)
        return RedirectResponse("/accounts/add?step=1&error=profile_failed")

    # Check if account already exists
    existing = await get_account_by_email(db, email)
    if existing:
        # Update token
        token_file = existing.token_file
    else:
        account = await create_account(db, email)
        token_file = account.token_file

    os.makedirs(os.path.dirname(token_file), exist_ok=True)
    with open(token_file, "w") as f:
        json.dump(token_data, f)
    if os.path.exists(temp_token_path):
        os.remove(temp_token_path)

    del _oauth_states[state]

    account = await get_account_by_email(db, email)
    resp = RedirectResponse(f"/accounts/add?step=3&account_id={account.id}&email={email}")
    resp.set_cookie("active_account_id", str(account.id))
    resp.delete_cookie("oauth_state")
    return resp


# ── Scan ──────────────────────────────────────────────────────────────────────

@app.post("/api/scan/{account_id}")
async def trigger_scan(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    if not gmail_client.credentials_exist(account.token_file):
        raise HTTPException(400, "Account not authenticated")
    count = await scan_account_emails(db, account)
    await update_last_scan(db, account_id)
    return {"scanned": count}


# ── Emails ────────────────────────────────────────────────────────────────────

@app.get("/emails/{account_id}", response_class=HTMLResponse)
async def emails_page(request: Request, account_id: int, db: AsyncSession = Depends(get_db)):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    accounts = await list_accounts(db)
    from sqlalchemy import select
    from .database import ScannedEmail
    result = await db.execute(
        select(ScannedEmail)
        .where(ScannedEmail.account_id == account_id, ScannedEmail.action_taken == "none")
        .order_by(ScannedEmail.risk_level.desc(), ScannedEmail.date.desc())
        .limit(200)
    )
    email_rows = result.scalars().all()
    # Group by sender
    grouped: dict[str, dict] = {}
    for e in email_rows:
        if e.sender not in grouped:
            grouped[e.sender] = {
                "sender": e.sender,
                "domain": e.sender_domain,
                "risk_level": e.risk_level,
                "count": 0,
                "has_unsubscribe": bool(e.has_unsubscribe),
                "unsubscribe_url": e.unsubscribe_url,
                "unsubscribe_mailto": e.unsubscribe_mailto,
                "latest_subject": e.subject,
                "latest_id": e.id,
            }
        grouped[e.sender]["count"] += 1
    return templates.TemplateResponse(request, "emails.html", {
        "accounts": accounts,
        "active": account,
        "senders": list(grouped.values()),
    })


@app.post("/api/emails/bulk-unsubscribe")
async def bulk_unsubscribe_route(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    account = await get_account(db, body.get("account_id"))
    if not account:
        raise HTTPException(404)
    ok = failed = 0
    for sender in body.get("senders", []):
        result = await do_unsubscribe(db, account, sender)
        if result.get("ok"):
            ok += 1
        else:
            failed += 1
    return {"ok": ok, "failed": failed}


@app.post("/api/emails/bulk-block")
async def bulk_block_route(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    account = await get_account(db, body.get("account_id"))
    if not account:
        raise HTTPException(404)
    delete_existing = body.get("delete_existing", False)
    ok = failed = emails_trashed = 0
    for sender in body.get("senders", []):
        result = await block_sender(db, account, sender, delete_existing)
        if result.get("ok"):
            ok += 1
            emails_trashed += result.get("emails_trashed", 0)
        else:
            failed += 1
    return {"ok": ok, "failed": failed, "emails_trashed": emails_trashed}


@app.post("/api/emails/unsubscribe")
async def unsubscribe_sender(
    account_id: int = Form(...),
    sender: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    result = await do_unsubscribe(db, account, sender)
    return result


@app.post("/api/emails/block")
async def block_sender_route(
    account_id: int = Form(...),
    sender: str = Form(...),
    delete_existing: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    result = await block_sender(db, account, sender, delete_existing)
    return result


@app.post("/api/emails/ignore")
async def ignore_sender(
    account_id: int = Form(...),
    sender: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import update
    from .database import ScannedEmail
    await db.execute(
        update(ScannedEmail)
        .where(ScannedEmail.account_id == account_id, ScannedEmail.sender == sender)
        .values(action_taken="ignored")
    )
    await db.commit()
    return {"ok": True}


@app.post("/api/emails/bulk-ignore")
async def bulk_ignore_route(request: Request, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import update
    from .database import ScannedEmail
    body = await request.json()
    account_id = body.get("account_id")
    for sender in body.get("senders", []):
        await db.execute(
            update(ScannedEmail)
            .where(ScannedEmail.account_id == account_id, ScannedEmail.sender == sender)
            .values(action_taken="ignored")
        )
    await db.commit()
    return {"ok": len(body.get("senders", []))}


# ── Breaches ──────────────────────────────────────────────────────────────────

@app.get("/breaches/{account_id}", response_class=HTMLResponse)
async def breaches_page(request: Request, account_id: int, db: AsyncSession = Depends(get_db)):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    accounts = await list_accounts(db)
    breaches = await get_cached_breaches(db, account_id)
    return templates.TemplateResponse(request, "breaches.html", {
        "accounts": accounts,
        "active": account,
        "breaches": breaches,
    })


@app.post("/api/breaches/check")
async def check_breaches_route(account_id: int = Form(...), db: AsyncSession = Depends(get_db)):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    breaches = await check_breaches(db, account.id, account.email)
    return {"breaches": len(breaches)}


# ── API: Breach remediation ───────────────────────────────────────────────────

@app.post("/api/breaches/mark-reviewed")
async def mark_breach_reviewed(breach_id: int = Form(...), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from .database import Breach
    result = await db.execute(select(Breach).where(Breach.id == breach_id))
    breach = result.scalar_one_or_none()
    if not breach:
        raise HTTPException(404)
    breach.reviewed = not breach.reviewed
    await db.commit()
    return {"ok": True, "reviewed": breach.reviewed}


@app.post("/api/breaches/advice")
async def breach_advice_route(breach_id: int = Form(...), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from .database import Breach
    result = await db.execute(select(Breach).where(Breach.id == breach_id))
    breach = result.scalar_one_or_none()
    if not breach:
        raise HTTPException(404)
    data_types = json.loads(breach.data_types) if breach.data_types else []
    advice = await get_breach_advice(
        breach_title=breach.breach_title or breach.breach_name,
        data_types=data_types,
        description=breach.description or "",
    )
    return {"advice": advice}


# ── API: Summary (for Chrome extension) ───────────────────────────────────────

@app.get("/api/summary/{account_id}")
async def api_summary(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    breaches = await get_cached_breaches(db, account_id)
    from sqlalchemy import select, func
    from .database import ScannedEmail, FilterCreated
    spam_res = await db.execute(
        select(func.count()).where(
            ScannedEmail.account_id == account_id,
            ScannedEmail.action_taken == "none",
            ScannedEmail.risk_level.in_(["high", "phishing"])
        )
    )
    blocked_res = await db.execute(
        select(func.count()).where(FilterCreated.account_id == account_id)
    )
    unreviewed = sum(1 for b in breaches if not b.reviewed)
    overall = "error" if unreviewed > 0 else "ok"
    return {
        "email": account.email,
        "breaches": len(breaches),
        "breaches_unreviewed": unreviewed,
        "senders_blocked": blocked_res.scalar() or 0,
        "spam_unread": spam_res.scalar() or 0,
        "last_scan": account.last_scan_at.isoformat() if account.last_scan_at else None,
        "overall_status": overall,
    }


@app.get("/api/accounts")
async def api_accounts(db: AsyncSession = Depends(get_db)):
    accounts = await list_accounts(db)
    return [{"id": a.id, "email": a.email, "display_name": a.display_name} for a in accounts]


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/history/{account_id}", response_class=HTMLResponse)
async def history_page(request: Request, account_id: int, db: AsyncSession = Depends(get_db)):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(404)
    accounts = await list_accounts(db)
    from sqlalchemy import select
    from .database import ActionLog
    result = await db.execute(
        select(ActionLog)
        .where(ActionLog.account_id == account_id)
        .order_by(ActionLog.timestamp.desc())
        .limit(100)
    )
    logs = result.scalars().all()
    return templates.TemplateResponse(request, "history.html", {
        "accounts": accounts,
        "active": account,
        "logs": logs,
    })

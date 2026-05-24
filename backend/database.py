import os
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Enum as SAEnum, text
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, relationship
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/gmail_cleaner.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    token_file = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_scan_at = Column(DateTime, nullable=True)

    emails = relationship("ScannedEmail", back_populates="account", cascade="all, delete-orphan")
    breaches = relationship("Breach", back_populates="account", cascade="all, delete-orphan")
    filters = relationship("FilterCreated", back_populates="account", cascade="all, delete-orphan")
    actions = relationship("ActionLog", back_populates="account", cascade="all, delete-orphan")


class ScannedEmail(Base):
    __tablename__ = "scanned_emails"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    message_id = Column(String, nullable=False, index=True)
    sender = Column(String, nullable=False)
    sender_domain = Column(String, nullable=False)
    subject = Column(Text, nullable=True)
    date = Column(DateTime, nullable=True)
    risk_level = Column(SAEnum("low", "medium", "high", "phishing", name="risk_level"), default="low")
    has_unsubscribe = Column(Integer, default=0)  # bool
    unsubscribe_mailto = Column(Text, nullable=True)
    unsubscribe_url = Column(Text, nullable=True)
    action_taken = Column(SAEnum("none", "unsubscribed", "blocked", "deleted", "ignored", name="email_action"), default="none")
    scanned_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="emails")


class FilterCreated(Base):
    __tablename__ = "filters_created"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    sender = Column(String, nullable=False)
    filter_type = Column(SAEnum("block_sender", "block_domain", name="filter_type"))
    gmail_filter_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="filters")


class Breach(Base):
    __tablename__ = "breaches"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    breach_name = Column(String, nullable=False)
    breach_title = Column(String, nullable=True)
    breach_date = Column(String, nullable=True)
    data_types = Column(Text, nullable=True)  # JSON array as string
    description = Column(Text, nullable=True)
    reviewed = Column(Boolean, nullable=False, default=False, server_default="0")
    checked_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="breaches")


class ActionLog(Base):
    __tablename__ = "action_log"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    action_type = Column(String, nullable=False)
    target = Column(String, nullable=True)
    result = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="actions")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add `reviewed` column to existing DBs that predate it
        try:
            await conn.execute(text("ALTER TABLE breaches ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0"))
        except Exception:
            pass  # column already exists


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

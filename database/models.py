from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, String, Float, DateTime, Integer,
    Boolean, Text, func, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import (
    AsyncSession, AsyncEngine,
    async_sessionmaker, create_async_engine
)
from bot.config import settings


class Base(DeclarativeBase):
    pass


class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = (
        Index("ix_deals_stage", "stage"),
        Index("ix_deals_responsible", "responsible_id"),
        Index("ix_deals_date_modify", "date_modify"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    stage: Mapped[str] = mapped_column(String(128))
    stage_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    opportunity: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="RUB")
    responsible_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    responsible_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    date_create: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    date_modify: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    date_closed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_won: Mapped[bool] = mapped_column(Boolean, default=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, default=False)
    has_tasks: Mapped[bool] = mapped_column(Boolean, default=False)
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    stage_entered_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deals_fetched: Mapped[int] = mapped_column(Integer, default=0)
    deals_updated: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ReportLog(Base):
    __tablename__ = "report_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    report_type: Mapped[str] = mapped_column(String(64))
    chat_id: Mapped[str] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# Engine & session factory (initialized in main.py)
engine: Optional[AsyncEngine] = None
async_session_factory: Optional[async_sessionmaker] = None


def get_engine() -> AsyncEngine:
    global engine
    if engine is None:
        engine = create_async_engine(
            settings.db_url,
            echo=False,
            pool_pre_ping=True,
        )
    return engine


def get_session_factory() -> async_sessionmaker:
    global async_session_factory
    if async_session_factory is None:
        async_session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return async_session_factory


async def init_db() -> None:
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    factory = get_session_factory()
    async with factory() as session:
        yield session

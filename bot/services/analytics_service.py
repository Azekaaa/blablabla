import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from database.models import Deal, get_session_factory

logger = logging.getLogger(__name__)


@dataclass
class ManagerStats:
    name: str
    deal_count: int = 0
    total_amount: float = 0.0
    won_count: int = 0
    problem_count: int = 0

    @property
    def avg_amount(self) -> float:
        return self.total_amount / self.deal_count if self.deal_count > 0 else 0.0


@dataclass
class StageStats:
    stage_name: str
    count: int = 0
    total_amount: float = 0.0


@dataclass
class CRMAnalytics:
    # Основная статистика
    total_active_deals: int = 0
    total_active_amount: float = 0.0
    currency: str = "RUB"

    # Сегодня
    new_deals_today: int = 0
    closed_deals_today: int = 0
    won_deals_today: int = 0
    lost_deals_today: int = 0

    # Проблемные сделки
    inactive_deals: list[dict] = field(default_factory=list)
    deals_without_tasks: list[dict] = field(default_factory=list)
    stuck_stage_deals: list[dict] = field(default_factory=list)

    # По менеджерам
    manager_stats: list[ManagerStats] = field(default_factory=list)

    # По стадиям
    stage_stats: list[StageStats] = field(default_factory=list)

    # Метаданные
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_problem_deals(self) -> int:
        problem_ids = set()
        for d in self.inactive_deals:
            problem_ids.add(d["id"])
        for d in self.deals_without_tasks:
            problem_ids.add(d["id"])
        for d in self.stuck_stage_deals:
            problem_ids.add(d["id"])
        return len(problem_ids)


class AnalyticsService:
    def __init__(self) -> None:
        self.inactive_threshold = settings.inactive_days_threshold
        self.stuck_threshold = settings.stuck_stage_days_threshold

    async def get_analytics(self) -> CRMAnalytics:
        session_factory = get_session_factory()
        async with session_factory() as session:
            analytics = CRMAnalytics()

            await self._fill_active_deals(session, analytics)
            await self._fill_today_stats(session, analytics)
            await self._fill_problem_deals(session, analytics)
            await self._fill_manager_stats(session, analytics)
            await self._fill_stage_stats(session, analytics)

            return analytics

    async def _fill_active_deals(self, session: AsyncSession, analytics: CRMAnalytics) -> None:
        result = await session.execute(
            select(
                func.count(Deal.id).label("cnt"),
                func.coalesce(func.sum(Deal.opportunity), 0).label("total"),
                func.max(Deal.currency).label("currency"),
            ).where(
                and_(Deal.is_won == False, Deal.is_lost == False)
            )
        )
        row = result.one()
        analytics.total_active_deals = row.cnt or 0
        analytics.total_active_amount = float(row.total or 0)
        analytics.currency = row.currency or "RUB"

    async def _fill_today_stats(self, session: AsyncSession, analytics: CRMAnalytics) -> None:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # New deals today
        result = await session.execute(
            select(func.count(Deal.id)).where(Deal.date_create >= today_start)
        )
        analytics.new_deals_today = result.scalar() or 0

        # Closed deals today (won + lost)
        result = await session.execute(
            select(func.count(Deal.id)).where(
                and_(
                    Deal.date_modify >= today_start,
                    (Deal.is_won == True) | (Deal.is_lost == True),
                )
            )
        )
        analytics.closed_deals_today = result.scalar() or 0

        # Won today
        result = await session.execute(
            select(func.count(Deal.id)).where(
                and_(Deal.date_modify >= today_start, Deal.is_won == True)
            )
        )
        analytics.won_deals_today = result.scalar() or 0

        # Lost today
        result = await session.execute(
            select(func.count(Deal.id)).where(
                and_(Deal.date_modify >= today_start, Deal.is_lost == True)
            )
        )
        analytics.lost_deals_today = result.scalar() or 0

    async def _fill_problem_deals(self, session: AsyncSession, analytics: CRMAnalytics) -> None:
        inactive_threshold = datetime.now(timezone.utc) - timedelta(days=self.inactive_threshold)
        stuck_threshold = datetime.now(timezone.utc) - timedelta(days=self.stuck_threshold)

        # Inactive deals (no activity for N days)
        result = await session.execute(
            select(Deal).where(
                and_(
                    Deal.is_won == False,
                    Deal.is_lost == False,
                    Deal.date_modify <= inactive_threshold,
                )
            ).order_by(Deal.date_modify.asc()).limit(10)
        )
        analytics.inactive_deals = [
            self._deal_to_dict(d, inactive_threshold)
            for d in result.scalars().all()
        ]

        # Deals without tasks
        result = await session.execute(
            select(Deal).where(
                and_(
                    Deal.is_won == False,
                    Deal.is_lost == False,
                    Deal.has_tasks == False,
                )
            ).order_by(Deal.date_create.desc()).limit(10)
        )
        analytics.deals_without_tasks = [
            self._deal_to_dict(d)
            for d in result.scalars().all()
        ]

        # Stuck in same stage for N+ days
        result = await session.execute(
            select(Deal).where(
                and_(
                    Deal.is_won == False,
                    Deal.is_lost == False,
                    Deal.stage_entered_date <= stuck_threshold,
                    Deal.stage_entered_date.isnot(None),
                )
            ).order_by(Deal.stage_entered_date.asc()).limit(10)
        )
        analytics.stuck_stage_deals = [
            self._deal_to_dict(d, stuck_threshold)
            for d in result.scalars().all()
        ]

    async def _fill_manager_stats(self, session: AsyncSession, analytics: CRMAnalytics) -> None:
        result = await session.execute(
            select(
                Deal.responsible_name,
                func.count(Deal.id).label("deal_count"),
                func.coalesce(func.sum(Deal.opportunity), 0).label("total_amount"),
                func.sum(case((Deal.is_won == True, 1), else_=0)).label("won_count"),
            ).where(
                and_(Deal.is_won == False, Deal.is_lost == False)
            ).group_by(Deal.responsible_name).order_by(
                func.coalesce(func.sum(Deal.opportunity), 0).desc()
            )
        )

        manager_list: list[ManagerStats] = []
        for row in result.all():
            ms = ManagerStats(
                name=row.responsible_name or "Неизвестно",
                deal_count=row.deal_count,
                total_amount=float(row.total_amount or 0),
                won_count=int(row.won_count or 0),
            )
            manager_list.append(ms)

        # Count problem deals per manager
        if manager_list:
            manager_names = {ms.name for ms in manager_list}
            problem_ids_by_manager: dict[str, int] = {}

            inactive_threshold = datetime.now(timezone.utc) - timedelta(days=self.inactive_threshold)
            result = await session.execute(
                select(Deal.responsible_name, func.count(Deal.id)).where(
                    and_(
                        Deal.is_won == False,
                        Deal.is_lost == False,
                        Deal.date_modify <= inactive_threshold,
                    )
                ).group_by(Deal.responsible_name)
            )
            for row in result.all():
                if row[0]:
                    problem_ids_by_manager[row[0]] = int(row[1])

            for ms in manager_list:
                ms.problem_count = problem_ids_by_manager.get(ms.name, 0)

        analytics.manager_stats = manager_list

    async def _fill_stage_stats(self, session: AsyncSession, analytics: CRMAnalytics) -> None:
        result = await session.execute(
            select(
                Deal.stage_name,
                func.count(Deal.id).label("count"),
                func.coalesce(func.sum(Deal.opportunity), 0).label("total"),
            ).where(
                and_(Deal.is_won == False, Deal.is_lost == False)
            ).group_by(Deal.stage_name).order_by(
                func.count(Deal.id).desc()
            )
        )

        analytics.stage_stats = [
            StageStats(
                stage_name=row.stage_name or "Неизвестно",
                count=row.count,
                total_amount=float(row.total or 0),
            )
            for row in result.all()
        ]

    @staticmethod
    def _deal_to_dict(deal: Deal, threshold: Optional[datetime] = None) -> dict:
        days_inactive = None
        if deal.date_modify and threshold:
            days_inactive = (datetime.now(timezone.utc) - deal.date_modify).days

        days_in_stage = None
        if deal.stage_entered_date:
            days_in_stage = (datetime.now(timezone.utc) - deal.stage_entered_date).days

        return {
            "id": deal.id,
            "title": deal.title,
            "stage": deal.stage_name or deal.stage,
            "amount": deal.opportunity,
            "currency": deal.currency,
            "responsible": deal.responsible_name or "Неизвестно",
            "days_inactive": days_inactive,
            "days_in_stage": days_in_stage,
            "date_modify": deal.date_modify,
        }

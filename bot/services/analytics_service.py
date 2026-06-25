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
@dataclass
class ManagerStats:
    name: str
    deal_count: int = 0
    total_amount: float = 0.0
    won_count: int = 0
    lost_count: int = 0
    problem_count: int = 0

    @property
    def conversion_rate(self) -> float:
        total_closed = self.won_count + self.lost_count
        return (self.won_count / total_closed * 100) if total_closed > 0 else 0.0


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

    # Вчера
    new_deals_yesterday: int = 0
    won_deals_yesterday: int = 0
    lost_deals_yesterday: int = 0

    # Проблемные сделки
    inactive_deals: list[dict] = field(default_factory=list)
    deals_without_tasks: list[dict] = field(default_factory=list)
    trial_lessons_day: dict[str, int] = field(default_factory=dict)
    trial_lessons_week: dict[str, int] = field(default_factory=dict)
    trial_lessons_month: dict[str, int] = field(default_factory=dict)

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
            await self._fill_trial_lesson_stats(session, analytics)
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
        # Вчера
        yesterday_start = today_start - timedelta(days=1)
        
        result = await session.execute(
            select(func.count(Deal.id)).where(
                and_(
                    Deal.date_create >= yesterday_start,
                    Deal.date_create < today_start,
                )
            )
        )
        analytics.new_deals_yesterday = result.scalar() or 0

        result = await session.execute(
            select(func.count(Deal.id)).where(
                and_(
                    Deal.date_modify >= yesterday_start,
                    Deal.date_modify < today_start,
                    Deal.is_won == True,
                )
            )
        )
        analytics.won_deals_yesterday = result.scalar() or 0

        result = await session.execute(
            select(func.count(Deal.id)).where(
                and_(
                    Deal.date_modify >= yesterday_start,
                    Deal.date_modify < today_start,
                    Deal.is_lost == True,
                )
            )
        )
        analytics.lost_deals_yesterday = result.scalar() or 0

    async def _fill_problem_deals(self, session: AsyncSession, analytics: CRMAnalytics) -> None:
        # Проблемная сделка: date_modify - date_create >= 1 день (не менялась с момента создания)
        all_active = await session.execute(
            select(Deal).where(
                and_(
                    Deal.is_won == False,
                    Deal.is_lost == False,
                    Deal.date_create.isnot(None),
                    Deal.date_modify.isnot(None),
                )
            )
        )

        problem_deals = []
        for deal in all_active.scalars().all():
            delta = deal.date_modify - deal.date_create
            if delta >= timedelta(days=1):
                problem_deals.append(deal)

        problem_deals.sort(key=lambda d: d.date_create or datetime.now(timezone.utc))
        analytics.inactive_deals = [self._deal_to_dict(d) for d in problem_deals[:10]]

        # Без задач (логика не меняется)
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

    async def _fill_trial_lesson_stats(self, session: AsyncSession, analytics: CRMAnalytics) -> None:
        """Подсчёт записей на пробное занятие по менеджерам: день/неделя/месяц."""
        TRIAL_STAGE = "C2:UC_I4N9EL"  # Запись на ПрУрок/Резерв

        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        month_start = day_start.replace(day=1)

        async def count_by_manager(since: datetime) -> dict[str, int]:
            result = await session.execute(
                select(Deal.responsible_name, func.count(Deal.id)).where(
                    and_(
                        Deal.stage == TRIAL_STAGE,
                        Deal.stage_entered_date >= since,
                    )
                ).group_by(Deal.responsible_name)
            )
            return {row[0] or "Неизвестно": row[1] for row in result.all()}

        analytics.trial_lessons_day = await count_by_manager(day_start)
        analytics.trial_lessons_week = await count_by_manager(week_start)
        analytics.trial_lessons_month = await count_by_manager(month_start)

    async def _fill_manager_stats(self, session: AsyncSession, analytics: CRMAnalytics) -> None:
        # Активные сделки
        result = await session.execute(
            select(
                Deal.responsible_name,
                func.count(Deal.id).label("deal_count"),
                func.coalesce(func.sum(Deal.opportunity), 0).label("total_amount"),
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
            )
            manager_list.append(ms)

        # Won/Lost для конверсии
        won_lost_result = await session.execute(
            select(
                Deal.responsible_name,
                func.sum(case((Deal.is_won == True, 1), else_=0)).label("won_count"),
                func.sum(case((Deal.is_lost == True, 1), else_=0)).label("lost_count"),
            ).where(
                (Deal.is_won == True) | (Deal.is_lost == True)
            ).group_by(Deal.responsible_name)
        )
        won_lost_map = {
            row.responsible_name: (int(row.won_count or 0), int(row.lost_count or 0))
            for row in won_lost_result.all()
        }

        for ms in manager_list:
            won, lost = won_lost_map.get(ms.name, (0, 0))
            ms.won_count = won
            ms.lost_count = lost

        # Проблемные сделки по менеджерам
        inactive_threshold = datetime.now(timezone.utc) - timedelta(days=self.inactive_threshold)
        prob_result = await session.execute(
            select(Deal.responsible_name, func.count(Deal.id)).where(
                and_(
                    Deal.is_won == False,
                    Deal.is_lost == False,
                    Deal.date_modify <= inactive_threshold,
                )
            ).group_by(Deal.responsible_name)
        )
        problem_map = {row[0]: int(row[1]) for row in prob_result.all() if row[0]}
        for ms in manager_list:
            ms.problem_count = problem_map.get(ms.name, 0)

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

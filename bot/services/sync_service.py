import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bot.bitrix.client import BitrixClient, parse_deal
from bot.config import settings
from database.models import Deal, SyncLog, get_session_factory

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self) -> None:
        self.client = BitrixClient()

    async def sync_deals(self) -> dict:
        """Full sync: fetch all active deals, upsert to DB."""
        session_factory = get_session_factory()
        sync_log_id: Optional[int] = None

        async with session_factory() as session:
            # Create sync log entry
            sync_log = SyncLog(started_at=datetime.now(timezone.utc))
            session.add(sync_log)
            await session.flush()
            sync_log_id = sync_log.id
            await session.commit()

        try:
            # Fetch stage names
            stage_names = await self.client.get_stage_names()

            # Fetch all active deals
            raw_deals = await self.client.get_all_deals()
            
            # Также фетчим закрытые сделки для конверсии
            raw_closed = await self.client.get_closed_deals_month()
            raw_deals_all = raw_deals + raw_closed

            # Collect unique responsible IDs
            responsible_ids = {
                str(d.get("ASSIGNED_BY_ID", ""))
                for d in raw_deals
                if d.get("ASSIGNED_BY_ID")
            }

            # Fetch user names in bulk
            user_names = await self.client.get_users_batch(responsible_ids)

            # Parse deals
            parsed_deals = [parse_deal(rd, stage_names, user_names) for rd in raw_deals]

            # Skip task fetching for large datasets to avoid timeout
            deal_task_counts: dict[int, int] = {}

            # Upsert to database
            updated_count = await self._upsert_deals(parsed_deals, deal_task_counts)

            # Update sync log
            async with session_factory() as session:
                await session.execute(
                    update(SyncLog)
                    .where(SyncLog.id == sync_log_id)
                    .values(
                        finished_at=datetime.now(timezone.utc),
                        deals_fetched=len(parsed_deals),
                        deals_updated=updated_count,
                        success=True,
                    )
                )
                await session.commit()

            logger.info(
                "Sync completed: %d fetched, %d updated",
                len(parsed_deals), updated_count
            )
            return {"success": True, "fetched": len(parsed_deals), "updated": updated_count}

        except Exception as e:
            logger.error("Sync failed: %s", e, exc_info=True)
            async with session_factory() as session:
                await session.execute(
                    update(SyncLog)
                    .where(SyncLog.id == sync_log_id)
                    .values(
                        finished_at=datetime.now(timezone.utc),
                        success=False,
                        error_message=str(e)[:1000],
                    )
                )
                await session.commit()
            raise

    async def _fetch_task_counts(self, deals: list[dict]) -> dict[int, int]:
        """Fetch task counts for all deals."""
        task_counts: dict[int, int] = {}

        # Batch requests to not overwhelm the API
        for i, deal in enumerate(deals):
            if i % 20 == 0 and i > 0:
                import asyncio
                await asyncio.sleep(0.5)  # Rate limiting

            deal_id = str(deal["id"])
            try:
                tasks = await self.client.get_deal_tasks(deal_id)
                task_counts[deal["id"]] = len(tasks)
            except Exception as e:
                logger.debug("Could not fetch tasks for deal %s: %s", deal_id, e)
                task_counts[deal["id"]] = 0

        return task_counts

    async def _upsert_deals(self, deals: list[dict], task_counts: dict[int, int]) -> int:
        """Upsert deals to database. Returns count of upserted records."""
        if not deals:
            return 0

        session_factory = get_session_factory()
        now = datetime.now(timezone.utc)
        batch_size = 100
        total_saved = 0

        # Get existing deals map
        async with session_factory() as session:
            existing_ids = {d["id"] for d in deals}
            existing_deals_result = await session.execute(
                select(Deal.id, Deal.stage, Deal.stage_entered_date).where(
                    Deal.id.in_(existing_ids)
                )
            )
            existing_map = {
                row.id: {"stage": row.stage, "stage_entered_date": row.stage_entered_date}
                for row in existing_deals_result
            }

        # Save in batches
        for i in range(0, len(deals), batch_size):
            batch = deals[i:i + batch_size]
            async with session_factory() as session:
                for deal_data in batch:
                    deal_id = deal_data["id"]
                    existing = existing_map.get(deal_id)

                    if existing is None:
                        stage_entered_date = deal_data.get("date_create") or now
                    elif existing["stage"] != deal_data["stage"]:
                        stage_entered_date = now
                    else:
                        stage_entered_date = existing["stage_entered_date"] or now

                    task_count = task_counts.get(deal_id, 0)

                    deal_obj = await session.get(Deal, deal_id)
                    if deal_obj is None:
                        deal_obj = Deal(id=deal_id)
                        session.add(deal_obj)

                    deal_obj.title = deal_data["title"]
                    deal_obj.stage = deal_data["stage"]
                    deal_obj.stage_name = deal_data["stage_name"]
                    deal_obj.opportunity = deal_data["opportunity"]
                    deal_obj.currency = deal_data["currency"]
                    deal_obj.responsible_id = deal_data["responsible_id"]
                    deal_obj.responsible_name = deal_data["responsible_name"]
                    deal_obj.date_create = deal_data["date_create"]
                    deal_obj.date_modify = deal_data["date_modify"]
                    deal_obj.date_closed = deal_data["date_closed"]
                    deal_obj.is_won = deal_data["is_won"]
                    deal_obj.is_lost = deal_data["is_lost"]
                    deal_obj.has_tasks = task_count > 0
                    deal_obj.task_count = task_count
                    deal_obj.stage_entered_date = stage_entered_date
                    deal_obj.synced_at = now

                await session.commit()
                total_saved += len(batch)
                logger.info("Saved batch %d/%d (%d deals)", i // batch_size + 1, (len(deals) - 1) // batch_size + 1, total_saved)

        return total_saved

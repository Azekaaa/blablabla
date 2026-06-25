import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional
import httpx
from bot.config import settings

logger = logging.getLogger(__name__)

# Bitrix24 stage name mapping (common defaults, may differ per portal)
STAGE_NAMES: dict[str, str] = {
    "NEW": "Новые и повторные",
    "WON": "Успешная сделка",
    "LOSE": "Сделка неуспешна",
    "C2:NEW": "Новые и повторные",
    "C2:WON": "Успешная сделка",
    "C2:LOSE": "Сделка неуспешна",
    "UC_8YJMS2": "1-й недозвон",
    "UC_XHKP7Q": "2-й недозвон",
    "UC_MF2W1N": "3-й недозвон / нет ответа",
    "UC_9RVI1J": "Думает/ В работе",
    "UC_XIG545": "Отложил покупку",
    "UC_MO0EB8": "Выставлен счет для оплаты",
    "UC_KGTQZP": "Резерв/Тренер",
    "C2:UC_ERC66U": "Перезвонить",
    "C2:UC_M1W40P": "Дожим на покупку",
    "C2:UC_81LJT2": "Лагерь",
    "C2:UC_I4N9EL": "Запись на ПрУрок/Резерв",
    "C2:UC_IHNJ7D": "Посетил пробное занятие",
    "C2:UC_LO2T5Y": "Запись Обучающегося в МК",
    "C2:UC_PQLEBD": "Пробный урок+Аренда+Теннис",
    "C2:UC_PTA1XG": "Тестовая",
    "C2:UC_U3KILD": "Резерв",
}


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Bitrix returns ISO 8601 with timezone offset like 2024-01-15T10:30:00+03:00
        dt = datetime.fromisoformat(value)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


class BitrixClient:
    def __init__(self) -> None:
        self.webhook = settings.bitrix_webhook
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Make a single REST API call with retry logic."""
        client = await self._get_client()
        url = f"{self.webhook}{method}"
        params = params or {}

        for attempt in range(3):
            try:
                response = await client.post(url, json=params)
                response.raise_for_status()
                data = response.json()

                if "error" in data:
                    error_desc = data.get("error_description", data.get("error"))
                    raise RuntimeError(f"Bitrix24 API error: {error_desc}")

                return data.get("result")
            except httpx.TimeoutException as e:
                logger.warning("Bitrix24 timeout (attempt %d/3): %s", attempt + 1, e)
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as e:
                logger.error("Bitrix24 HTTP error %s: %s", e.response.status_code, e)
                raise

    async def get_all_deals(self) -> list[dict[str, Any]]:
        """Fetch ALL active deals using pagination (max 50 per request)."""
        all_deals: list[dict[str, Any]] = []
        start = 0

        select_fields = [
            "ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "CURRENCY_ID",
            "ASSIGNED_BY_ID", "DATE_CREATE", "DATE_MODIFY",
            "CLOSEDATE", "CLOSED", "PROBABILITY",
        ]

        while True:
            result = await self._call("crm.deal.list", {
                "filter": {"CLOSED": "N"},
                "select": select_fields,
                "order": {"DATE_MODIFY": "DESC"},
                "start": start,
            })

            logger.info("crm.deal.list response type=%s, value=%s", type(result).__name__, str(result)[:200])

            if not result:
                break

            deals = result if isinstance(result, list) else []
            all_deals.extend(deals)

            if len(deals) < 50:
                break
            start += 50

        logger.info("Fetched %d active deals from Bitrix24", len(all_deals))
        return all_deals

    async def get_closed_deals_month(self) -> list[dict[str, Any]]:
        """Fetch deals closed in last 30 days."""
        from datetime import timedelta
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)

        all_closed: list[dict[str, Any]] = []
        start = 0
        while True:
            result = await self._call("crm.deal.list", {
                "filter": {
                    "CLOSED": "Y",
                    ">=DATE_MODIFY": month_ago.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                "select": [
                    "ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "CURRENCY_ID",
                    "ASSIGNED_BY_ID", "DATE_CREATE", "DATE_MODIFY", "CLOSED",
                ],
                "start": start,
            })
            if not result:
                break
            deals = result if isinstance(result, list) else []
            all_closed.extend(deals)
            if len(deals) < 50:
                break
            start += 50
        logger.info("Fetched %d closed deals (last 30 days)", len(all_closed))
        return all_closed

    async def get_new_deals_today(self) -> list[dict[str, Any]]:
        """Fetch deals created today."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self._call("crm.deal.list", {
            "filter": {
                ">=DATE_CREATE": today_start.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            "select": [
                "ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "CURRENCY_ID",
                "ASSIGNED_BY_ID", "DATE_CREATE",
            ],
            "start": 0,
        })
        return result or []

    async def get_deal_tasks(self, deal_id: str) -> list[dict[str, Any]]:
        """Fetch tasks linked to a specific deal."""
        result = await self._call("tasks.task.list", {
            "filter": {
                "UF_CRM_TASK": f"D_{deal_id}",
            },
            "select": ["ID", "TITLE", "STATUS", "DEADLINE"],
        })
        if isinstance(result, dict):
            return result.get("tasks", [])
        return result or []

    async def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        """Fetch user info by ID."""
        try:
            result = await self._call("user.get", {"ID": user_id})
            if result and isinstance(result, list) and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.warning("Could not fetch user %s: %s", user_id, e)
        return None

    async def get_users_batch(self, user_ids: set[str]) -> dict[str, str]:
        """Fetch multiple users, return {user_id: full_name}."""
        result: dict[str, str] = {}
        unique_ids = list(user_ids)

        for i in range(0, len(unique_ids), 50):
            batch = unique_ids[i:i + 50]
            try:
                users = await self._call("user.get", {"ID": batch})
                if users:
                    for u in users:
                        uid = str(u.get("ID", ""))
                        name = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
                        result[uid] = name or f"User#{uid}"
            except Exception as e:
                logger.warning("Batch user fetch failed (continuing without names): %s", e)
                # Fill with ID-based names so sync continues
                for uid in batch:
                    result[str(uid)] = f"Менеджер #{uid}"

        return result

    async def get_stage_names(self) -> dict[str, str]:
        """Fetch custom stage names for deals pipeline."""
        stage_map: dict[str, str] = dict(STAGE_NAMES)

        # Method 1: crm.status.list — universal method for all Bitrix24
        try:
            result = await self._call("crm.status.list", {
                "filter": {"ENTITY_ID": "DEAL_STAGE"}
            })
            if result:
                items = result if isinstance(result, list) else result.get("items", [])
                for stage in items:
                    sid = stage.get("STATUS_ID") or stage.get("ID", "")
                    name = stage.get("NAME", sid)
                    if sid:
                        stage_map[sid] = name
                logger.info("Loaded %d stage names via crm.status.list", len(stage_map))
                return stage_map
        except Exception as e:
            logger.warning("crm.status.list failed: %s", e)

        # Method 2: crm.dealcategory stages
        try:
            categories = await self._call("crm.dealcategory.list", {}) or []
            for cat in categories:
                cat_id = cat.get("ID")
                if cat_id:
                    try:
                        cat_stages = await self._call(
                            "crm.dealcategory.stage.list", {"id": cat_id}
                        )
                        if cat_stages:
                            for stage in cat_stages:
                                sid = stage.get("STATUS_ID", "")
                                if sid:
                                    stage_map[sid] = stage.get("NAME", sid)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("crm.dealcategory.list failed: %s", e)

        return stage_map


def parse_deal(raw: dict[str, Any], stage_names: dict[str, str], user_names: dict[str, str]) -> dict[str, Any]:
    """Parse raw Bitrix24 deal dict into a clean domain object."""
    stage_id = raw.get("STAGE_ID", "")
    responsible_id = str(raw.get("ASSIGNED_BY_ID", ""))

    return {
        "id": int(raw["ID"]),
        "title": raw.get("TITLE", "Без названия"),
        "stage": stage_id,
        "stage_name": stage_names.get(stage_id, stage_id),
        "opportunity": float(raw.get("OPPORTUNITY") or 0),
        "currency": raw.get("CURRENCY_ID", "RUB"),
        "responsible_id": responsible_id,
        "responsible_name": user_names.get(responsible_id, f"User#{responsible_id}"),
        "date_create": _parse_dt(raw.get("DATE_CREATE")),
        "date_modify": _parse_dt(raw.get("DATE_MODIFY")),
        "date_closed": _parse_dt(raw.get("CLOSEDATE")),
        "is_won": stage_id.endswith(":WON") or stage_id == "WON",
        "is_lost": stage_id.endswith(":LOSE") or stage_id.endswith(":APOLOGY") or stage_id in ("LOSE", "APOLOGY"),
    }
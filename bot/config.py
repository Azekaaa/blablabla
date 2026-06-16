from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram
    bot_token: str
    chat_id: str

    # Bitrix24
    bitrix_webhook: str

    # Database
    db_url: str = "sqlite+aiosqlite:///./crm_bot.db"

    # Scheduler
    report_time_morning: str = "09:00"
    report_time_evening: str = "18:00"

    # Analysis thresholds
    inactive_days_threshold: int = 3
    stuck_stage_days_threshold: int = 7

    # Logging
    log_level: str = "INFO"

    @field_validator("bitrix_webhook")
    @classmethod
    def validate_webhook(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("BITRIX_WEBHOOK must start with https://")
        if not v.endswith("/"):
            v += "/"
        return v

    @property
    def morning_hour(self) -> int:
        return int(self.report_time_morning.split(":")[0])

    @property
    def morning_minute(self) -> int:
        return int(self.report_time_morning.split(":")[1])

    @property
    def evening_hour(self) -> int:
        return int(self.report_time_evening.split(":")[0])

    @property
    def evening_minute(self) -> int:
        return int(self.report_time_evening.split(":")[1])


settings = Settings()

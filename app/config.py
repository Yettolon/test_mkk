from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str
    rabbitmq_url: str
    api_key: str = Field(min_length=1)

    outbox_poll_interval: float = Field(gt=0)
    outbox_batch_size: int = Field(ge=1, le=500)
    webhook_timeout: float = Field(gt=0)
    consumer_attempts: int = Field(ge=1, le=10)


@lru_cache
def get_settings() -> Settings:
    """Возвращает объект настроек приложения"""
    return Settings()


settings = get_settings()

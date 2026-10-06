from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.enums import Currency, PaymentStatus
from pydantic import BaseModel, Field, HttpUrl, field_validator


class PaymentCreate(BaseModel):
    """Схема для создания платежа"""

    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Currency
    description: str = Field(max_length=2000)
    metadata: dict[str, Any]
    webhook_url: HttpUrl

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"))


class PaymentAccepted(BaseModel):
    """Схема для ответа при успешном создании платежа"""

    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentDetails(BaseModel):
    """Схема для получения деталей платежа"""

    payment_id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None


class PaymentEvent(BaseModel):
    """Событие платежа для публикации в брокер сообщений"""

    payment_id: UUID


class WebhookPayload(BaseModel):
    """Платёжные данные для отправки на webhook"""

    payment_id: UUID
    status: PaymentStatus
    processed_at: datetime

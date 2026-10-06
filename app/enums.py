from enum import StrEnum


class Currency(StrEnum):
    """Валюта платежа"""

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    """Статусы платежей"""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OutboxEventType(StrEnum):
    """Типы событий outbox"""

    PAYMENT_CREATED = "payment.created"

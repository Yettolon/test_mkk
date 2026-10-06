from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import Currency, PaymentCreate


def test_payment_create_normalizes_amount() -> None:
    payload = PaymentCreate(
        amount="10.5",
        currency=Currency.USD,
        description="test",
        metadata={"order_id": 123},
        webhook_url="https://example.com/hook",
    )
    assert payload.amount == Decimal("10.50")


def test_payment_create_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError):
        PaymentCreate(
            amount="-1",
            currency=Currency.USD,
            description="test",
            metadata={},
            webhook_url="https://example.com/hook",
        )


def test_payment_create_rejects_unsupported_currency() -> None:
    with pytest.raises(ValidationError):
        PaymentCreate(
            amount="10.00",
            currency="GBP",
            description="test",
            metadata={},
            webhook_url="https://example.com/hook",
        )


def test_payment_create_rejects_too_many_decimal_places() -> None:
    with pytest.raises(ValidationError):
        PaymentCreate(
            amount="10.001",
            currency=Currency.USD,
            description="test",
            metadata={},
            webhook_url="https://example.com/hook",
        )


def test_payment_create_rejects_invalid_webhook_url() -> None:
    with pytest.raises(ValidationError):
        PaymentCreate(
            amount="10.00",
            currency=Currency.USD,
            description="test",
            metadata={},
            webhook_url="not-a-url",
        )

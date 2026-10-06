from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OutboxEventType, PaymentStatus
from app.models import OutboxEvent, Payment
from app.schemas import PaymentAccepted, PaymentCreate, PaymentDetails


def to_accepted(payment: Payment) -> PaymentAccepted:
    """Преобразует объект Payment в PaymentAccepted."""
    return PaymentAccepted(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


def to_details(payment: Payment) -> PaymentDetails:
    """Преобразует объект Payment в PaymentDetails."""
    return PaymentDetails(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata_,
        status=payment.status,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )


async def get_payment_by_idempotency_key(
    session: AsyncSession, idempotency_key: str
) -> Payment | None:
    """Получение платежа по ключу идемпотентности."""
    result = await session.execute(
        select(Payment).where(Payment.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


async def create_payment(
    session: AsyncSession,
    payload: PaymentCreate,
    idempotency_key: str,
) -> Payment:
    """Создание платежа."""
    existing = await get_payment_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing

    payment = Payment(
        amount=payload.amount,
        currency=payload.currency.value,
        description=payload.description,
        metadata_=payload.metadata,
        status=PaymentStatus.PENDING,
        idempotency_key=idempotency_key,
        webhook_url=str(payload.webhook_url),
    )
    session.add(payment)

    try:
        await session.flush()
        session.add(
            OutboxEvent(
                aggregate_id=payment.id,
                event_type=OutboxEventType.PAYMENT_CREATED,
                payload={"payment_id": str(payment.id)},
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_payment_by_idempotency_key(session, idempotency_key)
        if existing is None:
            raise
        return existing

    await session.refresh(payment)
    return payment


async def get_payment(session: AsyncSession, payment_id: UUID) -> Payment | None:
    """Получение платежа по айди."""
    return await session.get(Payment, payment_id)

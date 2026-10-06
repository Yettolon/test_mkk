import asyncio
import logging
import random
from datetime import UTC, datetime

from app.enums import PaymentStatus
import httpx
from faststream import AckPolicy, FastStream
from faststream.rabbit import Channel, RabbitBroker
from sqlalchemy import select

from app.config import settings
from app.database import SessionFactory
from app.messaging import ensure_topology, payments_exchange, payments_queue
from app.models import Payment
from app.schemas import PaymentEvent, WebhookPayload

logger = logging.getLogger(__name__)


broker = RabbitBroker(
    settings.rabbitmq_url,
    default_channel=Channel(prefetch_count=1),
)
app = FastStream(broker)


@app.after_startup
async def declare_topology() -> None:
    """Объявление обменников и очередей"""
    await ensure_topology(broker)


async def process_payment_event(event: PaymentEvent) -> None:
    """Обрабатывание события платежа"""
    async with SessionFactory() as session:
        async with session.begin():
            result = await session.execute(
                select(Payment).where(Payment.id == event.payment_id).with_for_update()
            )
            payment = result.scalar_one_or_none()
            if payment is None:
                raise RuntimeError(f"Платёж {event.payment_id} не найден")

            if payment.status == PaymentStatus.PENDING:
                await asyncio.sleep(random.uniform(2, 5))
                payment.status = (
                    PaymentStatus.SUCCEEDED
                    if random.random() < 0.9
                    else PaymentStatus.FAILED
                )
                payment.processed_at = datetime.now(UTC)

            if payment.processed_at is None:
                raise RuntimeError(
                    f"У платежа {payment.id} отсутствует метка processed_at"
                )

            webhook_payload = WebhookPayload(
                payment_id=payment.id,
                status=payment.status,
                processed_at=payment.processed_at,
            )
            webhook_url = payment.webhook_url

    async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
        response = await client.post(
            webhook_url,
            json=webhook_payload.model_dump(mode="json"),
            headers={"Idempotency-Key": str(event.payment_id)},
        )
        response.raise_for_status()


@broker.subscriber(
    payments_queue,
    payments_exchange,
    ack_policy=AckPolicy.REJECT_ON_ERROR,
)
async def handle_payment(message: dict) -> None:
    """Обрабатывает событие платежа, публикуемое в брокер сообщений."""
    event_id = (
        str(message.get("payment_id", "<invalid>"))
        if isinstance(message, dict)
        else "<invalid>"
    )

    for attempt in range(1, settings.consumer_attempts + 1):
        try:
            event = PaymentEvent.model_validate(message)
            await process_payment_event(event)
            logger.info(
                "Платёж %s обработан и webhook успешно доставлен", event.payment_id
            )
            return
        except Exception as exc:
            if attempt >= settings.consumer_attempts:
                logger.exception(
                    "Событие платежа %s не удалось обработать после %s попыток; RabbitMQ отправит его в dead-letter",
                    event_id,
                    attempt,
                )
                raise

            delay = 2 ** (attempt - 1)
            logger.warning(
                "Событие платежа %s, попытка %s/%s не удалась: %s. Повтор через %sс",
                event_id,
                attempt,
                settings.consumer_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

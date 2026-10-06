import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

from faststream.rabbit import RabbitBroker
from sqlalchemy import select

from app.config import settings
from app.database import SessionFactory
from app.messaging import PAYMENTS_ROUTING_KEY, payments_exchange
from app.models import OutboxEvent

logger = logging.getLogger(__name__)


async def _next_ids() -> list[UUID]:
    """Возвращает список идентификаторов событий outbox, которые еще не были опубликованы."""
    async with SessionFactory() as session:
        result = await session.execute(
            select(OutboxEvent.id)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at)
            .limit(settings.outbox_batch_size)
        )
        return list(result.scalars().all())


async def _publish_one(broker: RabbitBroker, event_id: UUID) -> bool:
    """Публикует одно событие outbox в брокер сообщений и помечает его как опубликованное."""
    async with SessionFactory() as session:
        async with session.begin():
            result = await session.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.id == event_id,
                    OutboxEvent.published_at.is_(None),
                )
                .with_for_update(skip_locked=True)
            )
            event = result.scalar_one_or_none()
            if event is None:
                return False

            await broker.publish(
                event.payload,
                exchange=payments_exchange,
                routing_key=PAYMENTS_ROUTING_KEY,
                persist=True,
                message_id=str(event.id),
                correlation_id=str(event.aggregate_id),
            )
            event.published_at = datetime.now(UTC)
            return True


async def run_outbox_relay(broker: RabbitBroker, stop_event: asyncio.Event) -> None:
    """Запускает процесс релая событий из таблицы outbox в брокер сообщений."""
    logger.info("Релай-процесс outbox запущен")
    while not stop_event.is_set():
        published_any = False
        try:
            for event_id in await _next_ids():
                try:
                    published_any = (
                        await _publish_one(broker, event_id) or published_any
                    )
                except Exception:
                    logger.exception(
                        "Не удалось опубликовать событие outbox %s", event_id
                    )
                    break
        except Exception:
            logger.exception("Ошибка опроса outbox")

        if not published_any:
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=settings.outbox_poll_interval
                )
            except TimeoutError:
                pass

    logger.info("Релай-процесс outbox остановлен")


async def stop_task(task: asyncio.Task[None]) -> None:
    """Останавливает задачу."""
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

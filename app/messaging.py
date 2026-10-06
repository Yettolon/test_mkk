from faststream.rabbit import (
    Channel,
    ExchangeType,
    QueueType,
    RabbitBroker,
    RabbitExchange,
    RabbitQueue,
)

from app.config import settings


PAYMENTS_QUEUE_NAME = "payments.new"
PAYMENTS_EXCHANGE_NAME = "payments.exchange"
PAYMENTS_ROUTING_KEY = "payments.new"
DLX_NAME = "payments.dlx"
DLQ_NAME = "payments.dlq"
DLQ_ROUTING_KEY = "payments.failed"

payments_exchange = RabbitExchange(
    PAYMENTS_EXCHANGE_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)

payments_dlx = RabbitExchange(
    DLX_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)

payments_dlq = RabbitQueue(
    DLQ_NAME,
    durable=True,
    routing_key=DLQ_ROUTING_KEY,
)

payments_queue = RabbitQueue(
    PAYMENTS_QUEUE_NAME,
    queue_type=QueueType.QUORUM,
    durable=True,
    routing_key=PAYMENTS_ROUTING_KEY,
    arguments={
        "x-dead-letter-exchange": DLX_NAME,
        "x-dead-letter-routing-key": DLQ_ROUTING_KEY,
    },
)


def make_broker() -> RabbitBroker:
    """Создает объект брокера"""
    return RabbitBroker(
        settings.rabbitmq_url,
        default_channel=Channel(publisher_confirms=True, on_return_raises=True),
    )


async def ensure_topology(broker: RabbitBroker) -> None:
    """Объявляет обменники, основную очередь и DLQ без потребления."""
    main_exchange = await broker.declare_exchange(payments_exchange)
    main_queue = await broker.declare_queue(payments_queue)
    await main_queue.bind(main_exchange, routing_key=PAYMENTS_ROUTING_KEY)

    dead_exchange = await broker.declare_exchange(payments_dlx)
    dead_queue = await broker.declare_queue(payments_dlq)
    await dead_queue.bind(dead_exchange, routing_key=DLQ_ROUTING_KEY)

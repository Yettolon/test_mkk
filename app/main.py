import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.messaging import ensure_topology, make_broker
from app.outbox import run_outbox_relay, stop_task
from app.payment_service import create_payment, get_payment, to_accepted, to_details
from app.schemas import PaymentAccepted, PaymentCreate, PaymentDetails
from app.security import require_api_key

publisher_broker = make_broker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Контекстный менеджер для управления временем жизни приложения FastAPI"""
    await publisher_broker.connect()
    await ensure_topology(publisher_broker)

    stop_event = asyncio.Event()
    relay_task = asyncio.create_task(run_outbox_relay(publisher_broker, stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await stop_task(relay_task)
        await publisher_broker.stop()


app = FastAPI(
    lifespan=lifespan,
)


@app.post(
    "/api/v1/payments",
    response_model=PaymentAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
async def post_payment(
    payload: PaymentCreate,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=255
    ),
) -> PaymentAccepted:
    """
    Обрабатывает POST-запрос на создание платежа

    Curryncies: USD, EUR, RUB
    """
    payment = await create_payment(session, payload, idempotency_key)
    return to_accepted(payment)


@app.get(
    "/api/v1/payments/{payment_id}",
    response_model=PaymentDetails,
    dependencies=[Depends(require_api_key)],
)
async def read_payment(
    payment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> PaymentDetails:
    """Обрабатывает GET-запрос на получение информации о платеже"""
    payment = await get_payment(session, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Платеж не найден")
    return to_details(payment)

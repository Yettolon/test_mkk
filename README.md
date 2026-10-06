# Тестовое задание: Асинхронный сервис процессинга платежей

## Описание

Микросервис для асинхронной обработки платежей.

Сервис принимает запрос на создание платежа и задачи для очереди, сохраняет его в PostgreSQL, передаёт событие в RabbitMQ, эмулирует обработку через платёжный шлюз и отправляет результат на указанный webhook URL.

### Основные возможности

* `POST /api/v1/payments` → `202 Accepted`
* `GET /api/v1/payments/{payment_id}`
* обязательный `Idempotency-Key`
* статический `X-API-Key`
* PostgreSQL + SQLAlchemy 2.0 Async
* Transactional Outbox
* RabbitMQ + FastStream
* retry с exponential backoff
* Dead Letter Queue
* webhook-уведомления
* Docker Compose
* Alembic migrations

---


## API

### Создание платежа

```http
POST /api/v1/payments
```

Обязательные заголовки:

```http
X-API-Key: dev-secret
Idempotency-Key: order-10001
```

Пример:

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -H 'Idempotency-Key: order-10001' \
  -d '{
    "amount": "1250.50",
    "currency": "USD",
    "description": "Order #10001",
    "metadata": {
      "order_id": 10001
    },
    "webhook_url": "https://example.com/payment-webhook"
  }'
```

Ответ:

```json
{
  "payment_id": "b3f60ec4-7678-4970-b1cf-a868f9958b60",
  "status": "pending",
  "created_at": "2026-10-05T12:00:00Z"
}
```

Повторная отправка запроса с тем же `Idempotency-Key` возвращает существующий платёж и не создаёт новый.

---

### Получение платежа

```http
GET /api/v1/payments/{payment_id}
```

Пример:

```bash
curl http://localhost:8000/api/v1/payments/<PAYMENT_ID> \
  -H 'X-API-Key: dev-secret'
```

---

## Webhook

После обработки платежа consumer отправляет `POST` на указанный `webhook_url`.

Пример payload:

```json
{
  "payment_id": "b3f60ec4-7678-4970-b1cf-a868f9958b60",
  "status": "succeeded",
  "processed_at": "2026-10-05T12:00:04Z"
}
```

HTTP status `2xx` считается успешной доставкой.

Ошибка соединения или HTTP `4xx/5xx` приводит к повторной попытке отправки.

Для защиты принимающей стороны от повторной доставки используется заголовок:

```http
Idempotency-Key: <payment_id>
```

---

## Локальный webhook

Для проверки webhook без использования внешнего сервиса можно запустить простой локальный HTTP-сервер.

Создай отдельный терминал на хост-машине и выполни:

```bash
python - <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode()

        print("Webhook received:")
        print(body)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


HTTPServer(("0.0.0.0", 9000), WebhookHandler).serve_forever()
PY
```

После запуска сервер будет слушать:

```text
http://localhost:9000
```

Так как API и consumer работают внутри Docker, для обращения из контейнера к webhook на хост-машине используется:

```text
http://host.docker.internal:9000
```

### Создание платежа с локальным webhook

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -H 'Idempotency-Key: order-10001' \
  -d '{
    "amount": "1250.50",
    "currency": "USD",
    "description": "Order #10001",
    "metadata": {
      "order_id": 10001
    },
    "webhook_url": "http://host.docker.internal:9000"
  }'
```

После успешной обработки платежа в терминале с webhook-сервером появится:

```text
Webhook received:
{"payment_id":"...","status":"succeeded","processed_at":"..."}
```

Это позволяет полностью проверить цепочку:

```text
POST /payments
      ↓
PostgreSQL
      ↓
Outbox
      ↓
RabbitMQ
      ↓
Consumer
      ↓
Payment processing
      ↓
Local Webhook
```

Для проверки webhook через интернет также можно использовать любой временный webhook receiver, например `webhook.site`.

---

## Retry и Dead Letter Queue

Обработка сообщения выполняется максимум **3 раза**.

Используется exponential backoff:

1. первая попытка — сразу;
2. после ошибки — ожидание `1` секунды;
3. вторая повторная попытка;
4. после ошибки — ожидание `2` секунд;
5. третья попытка;
6. если третья попытка завершилась ошибкой — сообщение отклоняется.

После окончательного `reject` RabbitMQ направляет сообщение через Dead Letter Exchange в:

```text
payments.dlq
```

Сообщения из DLQ автоматически не потребляются.

---

## Идемпотентность consumer

Transactional Outbox обеспечивает **at-least-once delivery**.

Например, возможна ситуация:

```text
1. Outbox relay публикует сообщение в RabbitMQ
2. RabbitMQ подтверждает публикацию
3. API/relay падает до установки published_at
4. После восстановления событие публикуется повторно
```

Поэтому consumer должен корректно обрабатывать повторную доставку.

Перед эмуляцией платёжной операции consumer проверяет текущий статус платежа.

Если платёж уже находится в состоянии:

```text
succeeded
```

или

```text
failed
```

повторная эмуляция платежного шлюза не выполняется.

При этом webhook может быть отправлен повторно, поскольку его доставка также работает по модели retry.

---

## Transactional Outbox

`POST /api/v1/payments` не публикует сообщение в RabbitMQ напрямую.

В рамках одной PostgreSQL-транзакции создаются:

1. запись в `payments` со статусом `pending`;
2. запись в `outbox` с событием `payment.created`.

После успешного commit отдельный relay читает неопубликованные события:

```sql
FOR UPDATE SKIP LOCKED
```

и публикует их в RabbitMQ.

Используется:

* exchange: `payments.exchange`
* routing key: `payments.new`
* queue: `payments.new`

После успешной публикации с publisher confirm у outbox-записи устанавливается:

```text
published_at
```

Таким образом, сбой между созданием платежа и публикацией сообщения не приводит к потере события.

---

## RabbitMQ

Используется `direct exchange`:

```text
payments.exchange
```

Основная очередь:

```text
payments.new
```

Dead Letter Queue:

```text
payments.dlq
```

Поток сообщений:

```text
payments.exchange
        │
        │ payments.new
        ▼
 payments.new
        │
        │ consumer
        ▼
   processing
        │
        │ final failure
        ▼
 payments.dlq
```
<img width="1112" height="162" alt="image" src="https://github.com/user-attachments/assets/d984fa80-6dc5-42fd-803d-3357ab6d684f" />

---

## Аутентификация

Все API endpoints защищены статическим API key:

```http
X-API-Key: dev-secret
```

Значение настраивается через переменные окружения.

---

## Запуск

### Клонирование репозитория
```bash
git clone git@github.com:Yettolon/test_mkk.git
cd test_mkk
```

### Docker Compose

```bash
docker compose up --build
```

После запуска:

* API: `http://localhost:8000`
* Swagger: `http://localhost:8000/docs`
* RabbitMQ Management UI: `http://localhost:15672`

RabbitMQ credentials для development-окружения:

```text
login: payments
password: payments
```

API key:

```text
dev-secret
```

Конфигурация также доступна в `.env.example`.

---

## Тестирование

Для запуска тестов локально:

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## Структура проекта

```text
app/
  main.py              # FastAPI endpoints + outbox relay lifecycle
  worker.py            # FastStream consumer
  payment_service.py   # payment use-cases / idempotency
  outbox.py             # transactional outbox relay
  messaging.py          # RabbitMQ topology
  models.py             # SQLAlchemy models
  schemas.py            # Pydantic v2 schemas
  database.py           # async DB setup
  security.py           # X-API-Key

alembic/
  versions/
    0001_initial.py

Dockerfile
docker-compose.yml
.env.example
requirements.txt
requirements-dev.txt
```

---

## Технологический стек

* Python
* FastAPI
* Pydantic v2
* SQLAlchemy 2.0 Async
* PostgreSQL
* RabbitMQ
* FastStream
* Alembic
* Docker
* Docker Compose

---

## Реализованные требования

| Требование            | Реализация                               |
| --------------------- | ---------------------------------------- |
| Создание платежа      | `POST /api/v1/payments`                  |
| Получение платежа     | `GET /api/v1/payments/{payment_id}`      |
| Idempotency           | `Idempotency-Key` + unique constraint    |
| Асинхронная обработка | RabbitMQ + FastStream                    |
| Outbox                | `payments` + `outbox` в одной транзакции |
| Retry                 | 3 попытки + exponential backoff          |
| DLQ                   | `payments.dlq`                           |
| Webhook               | HTTP POST после обработки                |
| API authentication    | `X-API-Key`                              |
| Database migrations   | Alembic                                  |
| Containerization      | Docker Compose                           |
| Local webhook         | HTTP server на `:9000`                   |

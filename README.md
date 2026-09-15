# Outreach

Telegram-бот + HTTP API для 24/7 outreach-рассылки.

## Документы

- **[API.md](API.md)** — полное описание всех эндпоинтов
- **[DEPLOY.md](DEPLOY.md)** — установка на Ubuntu + домен `outreachapi.arix.vu`

## Быстрый старт (локально)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # заполнить BOT_TOKEN, ADMIN_IDS, API_KEY

python main.py              # бот
python api_main.py          # API на API_HOST:API_PORT (по умолчанию 127.0.0.1:8091)
```

Swagger: `http://127.0.0.1:8091/docs`

## Prod

- Бот: `outreach-bot.service`
- API: `outreach-api.service` → Caddy → `https://outreachapi.arix.vu`

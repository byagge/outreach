# Deploy Outreach на Ubuntu (рядом с другими проектами)

Этот гайд рассчитан на сервер, где уже крутятся другие сервисы.
Outreach ставится в **отдельный каталог** `/opt/outreach`, на **отдельный порт** `8091`,
с доменом **`https://outreachapi.arix.vu`**. Бот и API — два systemd unit'а.

## 0. Что получится

| Компонент | Как | Порт / URL |
|-----------|-----|------------|
| Telegram-бот | `outreach-bot.service` | polling (наружу порт не нужен) |
| HTTP API | `outreach-api.service` | `127.0.0.1:8091` |
| Публичный домен | Caddy | `https://outreachapi.arix.vu` |

Данные (БД, session-файлы) лежат только в `/opt/outreach/data/` — не пересекаются с другими проектами.

---

## 1. DNS

У DNS-провайдера для `arix.vu`:

```
A    outreachapi.arix.vu    →  IP_ВАШЕГО_СЕРВЕРА
```

Подождите, пока запись резолвится (`dig outreachapi.arix.vu`).

---

## 2. Клон с GitHub (не мешая другим репо)

```bash
sudo mkdir -p /opt/outreach
sudo chown $USER:$USER /opt/outreach
cd /opt
git clone https://github.com/ВАШ_ОРГ/outreach.git outreach
cd /opt/outreach
```

Если репо уже есть локально — просто `git pull` в `/opt/outreach`.

---

## 3. Python venv (свой, не системный)

```bash
cd /opt/outreach
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

---

## 4. `.env`

```bash
cp .env.example .env
nano .env
```

Обязательно заполните:

```env
BOT_TOKEN=...
ADMIN_IDS=...
API_ID=...
API_HASH=...
TIMEZONE=Asia/Bishkek

API_KEY=сгенерируйте_длинный_секрет
API_HOST=127.0.0.1
API_PORT=8091
API_PUBLIC_URL=https://outreachapi.arix.vu
```

Секрет:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Права:

```bash
chmod 600 /opt/outreach/.env
sudo mkdir -p /opt/outreach/data
sudo chown -R www-data:www-data /opt/outreach/data
# чтобы systemd (www-data) мог читать код и .env:
sudo chown -R www-data:www-data /opt/outreach
# или оставьте владельцем себя, но data + .env доступны www-data
```

Рекомендуемый простой вариант прав:

```bash
sudo chown -R www-data:www-data /opt/outreach
```

---

## 5. Проверка локально (до systemd)

```bash
cd /opt/outreach
sudo -u www-data /opt/outreach/.venv/bin/python -c "from app.store import Store; import asyncio; asyncio.run(Store().init()); print('db ok')"
sudo -u www-data /opt/outreach/.venv/bin/python api_main.py
# в другом терминале:
curl -s https://127.0.0.1:8091/v1/health || curl -s http://127.0.0.1:8091/v1/health
```

Остановите Ctrl+C.

---

## 6. systemd

```bash
sudo cp /opt/outreach/deploy/systemd/outreach-bot.service /etc/systemd/system/
sudo cp /opt/outreach/deploy/systemd/outreach-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now outreach-api outreach-bot
sudo systemctl status outreach-api outreach-bot --no-pager
```

Логи:

```bash
journalctl -u outreach-api -f
journalctl -u outreach-bot -f
```

---

## 7. Caddy (домен)

Добавьте блок из `deploy/Caddyfile.snippet` в ваш основной Caddyfile
(**не заменяйте** существующие сайты — только допишите):

```caddy
outreachapi.arix.vu {
	encode gzip
	reverse_proxy 127.0.0.1:8091
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Проверка:

```bash
curl -s https://outreachapi.arix.vu/v1/health
curl -s -H "X-API-Key: ВАШ_КЛЮЧ" https://outreachapi.arix.vu/v1/stats
```

Swagger UI: `https://outreachapi.arix.vu/docs`

---

## 8. Обновление с GitHub

```bash
cd /opt/outreach
sudo -u www-data git pull   # или от своего юзера + chown
sudo -u www-data /opt/outreach/.venv/bin/pip install -r requirements.txt
sudo systemctl restart outreach-api outreach-bot
```

`data/` и `.env` в git **не** попадают (см. `.gitignore`).

---

## 9. Почему не мешает другим проектам

- Каталог только `/opt/outreach`
- Порт только `8091` (localhost)
- Отдельные unit'ы `outreach-bot` / `outreach-api`
- Отдельный venv `.venv`
- Отдельная SQLite `data/outreach.db`
- В Caddy только host `outreachapi.arix.vu`

Не используйте тот же `BOT_TOKEN`, что у другого бота на сервере.

---

## 10. Быстрый smoke

```bash
KEY=ваш_api_key
BASE=https://outreachapi.arix.vu

curl -s $BASE/v1/health
curl -s -H "X-API-Key: $KEY" $BASE/v1/stats
curl -s -H "X-API-Key: $KEY" $BASE/v1/settings
curl -s -H "X-API-Key: $KEY" -X POST $BASE/v1/run/status
```

Полный список эндпоинтов — в [`API.md`](API.md).

# Outreach API — полная документация

**Base URL (prod):** `https://outreachapi.arix.vu`  
**Prefix:** `/v1`  
**Auth:** заголовок `X-API-Key: <API_KEY из .env>`  
**Интерактивно:** `/docs` (Swagger), `/redoc`  
**OpenAPI JSON:** `/openapi.json`

Все эндпоинты кроме `GET /`, `GET /v1/health` требуют `X-API-Key`.

Ответы обычно вида:

```json
{ "ok": true, "...": "..." }
```

Ошибки:

| HTTP | Когда |
|------|--------|
| 401 | Нет / неверный API key |
| 400 | Невалидные данные |
| 404 | Объект не найден |
| 409 | Конфликт (уже запущено / дубликат) |
| 502 | Ошибка Telegram/Telethon при сборе |
| 503 | API_KEY не задан или store не готов |

---

## Оглавление

1. [System](#1-system)
2. [Settings](#2-settings)
3. [Accounts](#3-accounts)
4. [Proxies](#4-proxies)
5. [Bases](#5-bases)
6. [Contacts](#6-contacts)
7. [Texts / Offers](#7-texts--offers)
8. [Blocklist / Banwords / Ban-base](#8-blocklist--banwords--ban-base)
9. [Collect](#9-collect)
10. [Run (рассылка)](#10-run-рассылка)
11. [History](#11-history)
12. [Примеры curl](#12-примеры-curl)

---

## 1. System

### `GET /`

Корень сервиса. Без ключа.

**Ответ:** `service`, `docs`, `public_url`, `api_prefix`.

---

### `GET /v1/health`

Проверка живости API. Без ключа.

**Ответ:**

```json
{
  "ok": true,
  "service": "outreach-api",
  "public_url": "https://outreachapi.arix.vu"
}
```

---

### `GET /v1/stats`

Счётчики системы + статус рассылки.

**Ответ:**

| Поле | Описание |
|------|----------|
| `counts.accounts` | Всего аккаунтов |
| `counts.assigned` | Назначенных на рассылку |
| `counts.proxies` | Прокси |
| `counts.contacts` | Все контакты |
| `counts.pending` | Готовы к отправке (с учётом баз/blocklist/ban) |
| `counts.sent` / `errors` / `skipped` | Статусы |
| `counts.texts` | Включённые офферы с текстом или фото |
| `counts.bases` / `bases_enabled` | Базы |
| `counts.blocklist` / `banwords` / `ban_contacts` | Фильтры |
| `outreach_running` | `true`, если job рассылки жив |
| `running_jobs` | Ключи runtime |

---

### `GET /v1/info`

Версия, timezone, текущие settings, флаг running.

---

## 2. Settings

### `GET /v1/settings`

Глобальные настройки рассылки.

**Поля `settings`:**

| Поле | Тип | По умолчанию | Смысл |
|------|-----|--------------|--------|
| `delay_min` / `delay_max` | int | 60 / 120 | Пауза внутри одного аккаунта (сек) |
| `between_delay_min` / `between_delay_max` | int | 0 / 0 | Пауза между разными аккаунтами (`0` = нет) |
| `typing` | bool | true | Эффект «печатает…» |
| `rotate_proxy_every` | int | 1 | Смена прокси каждые N сообщений |
| `variant_mode` | string | `random` | `random` или `rotate` для офферов |
| `continuous` | bool | true | 24/7: ждать новые контакты |

---

### `PATCH /v1/settings`

Частичное обновление. Тело — любые поля из таблицы выше.

```json
{ "delay_min": 60, "delay_max": 120, "continuous": true, "variant_mode": "random" }
```

**Ответ:** актуальные `settings`.

---

### `GET /v1/settings/raw/{key}`

Сырое значение из таблицы `settings` по ключу.

---

### `PUT /v1/settings/raw/{key}`

Записать произвольный ключ (низкоуровнево).

```json
{ "value": "90" }
```

---

## 3. Accounts

### `GET /v1/accounts`

Список всех аккаунтов.

**Элемент:** `id`, `label`, `phone`, `username`, `user_id`, `telethon_session`, `assigned`, `status`, `last_error`, `pause_until`, `sent_count`, `work_start`, `work_end`, `delay_min`, `delay_max`, `has_telethon`, `display`, timestamps.

---

### `POST /v1/accounts`

Создать аккаунт (без session).

```json
{ "label": "acc1" }
```

---

### `GET /v1/accounts/{account_id}`

Аккаунт + его привязанные прокси.

---

### `PATCH /v1/accounts/{account_id}`

Обновить поля. Можно: `label`, `assigned` (0/1), `work_start`, `work_end` (`HH:MM`), `delay_min`, `delay_max` (`null` = глобальные), `status`, `last_error`, `phone`, `username`, `user_id`.

```json
{ "work_start": "09:00", "work_end": "21:00", "delay_min": 90, "delay_max": 150 }
```

Пустые `work_start`+`work_end` → 24/7.

---

### `DELETE /v1/accounts/{account_id}`

Удалить аккаунт (файл session на диске не трогается автоматически).

---

### `POST /v1/accounts/{account_id}/toggle-assigned`

Вкл/выкл участия в рассылке.

---

### `POST /v1/accounts/{account_id}/pause`

Пауза аккаунта.

```json
{ "seconds": 600, "error": "manual pause" }
```

---

### `POST /v1/accounts/{account_id}/session`

Загрузка Telethon `.session` (multipart).

- form-field: `file` (`.session`)
- Pyrogram отклоняется с 400

**Ответ:** обновлённый `account`, `detail`, `kind`.

---

### `GET /v1/accounts/{account_id}/proxies`

Прокси, привязанные к аккаунту.

---

### `GET /v1/accounts/{account_id}/peek-proxy`

Текущий прокси **без** сдвига ротации (для сбора базы).

---

### `POST /v1/accounts/{account_id}/next-proxy`

Взять следующий прокси и сдвинуть cursor (как в рассылке).

---

## 4. Proxies

### `GET /v1/proxies`

Список всех прокси.

---

### `POST /v1/proxies`

Добавить текстом (тип определяется автоматически: http/https/socks5/…).

```json
{
  "text": "1.2.3.4:1080\nsocks5://user:pass@5.6.7.8:1080\nhttp://9.9.9.9:8080"
}
```

**Ответ:** `added`, `skipped`, `total`.

---

### `POST /v1/proxies/upload`

Загрузить файл (txt/csv/xlsx/json). Multipart `file`.

---

### `GET /v1/proxies/{proxy_id}`

Прокси + список аккаунтов, к которым привязан.

---

### `DELETE /v1/proxies/{proxy_id}`

Удалить прокси.

---

### `POST /v1/proxies/{proxy_id}/check`

Проверка валидности (соединение к Telegram через прокси).

**Ответ:** `valid` (bool), `detail`, обновлённый `proxy`.

---

### `POST /v1/proxies/{proxy_id}/bind`

Привязать / отвязать к аккаунту.

```json
{ "account_id": 1, "bind": true }
```

---

### `POST /v1/proxies/rebalance`

Полная перераздача прокси по аккаунтам (сбрасывает ручные привязки).

---

### `POST /v1/proxies/assign-unbound`

Назначить только «свободные» прокси — **не** трогает уже привязанные.

---

## 5. Bases

Базы контактов (листы). Выключенная база не участвует в рассылке.

### `GET /v1/bases`

Список баз + `stats` (`total`, `pending`, `sent`) по каждой.

---

### `POST /v1/bases`

```json
{ "name": "Лидген март" }
```

---

### `GET /v1/bases/{base_id}`

База, stats, preview контактов (до 20).

---

### `PATCH /v1/bases/{base_id}`

Переименовать.

```json
{ "name": "Новое имя" }
```

---

### `POST /v1/bases/{base_id}/toggle`

Вкл/выкл базу.

---

### `DELETE /v1/bases/{base_id}`

Удалить базу **и все её контакты**.

---

### `GET /v1/bases/{base_id}/contacts`

Контакты базы.

**Query:** `status`, `page`, `per_page` (1–500).

---

### `POST /v1/bases/{base_id}/contacts`

Добавить контакты текстом в базу.

```json
{ "text": "@user1\n+79991234567\n123456789" }
```

Дубликаты (тот же `kind+value` глобально) → `skipped`. Один человек = одно сообщение в системе.

---

### `POST /v1/bases/{base_id}/import`

Импорт файла. Multipart `file`.

**Query:** `multi_sheet=true` (по умолчанию) — для xlsx каждый лист → отдельная база; первый лист пишется в `{base_id}`.

Форматы: txt, csv, xlsx, md, sql, json.

---

### `GET /v1/bases/{base_id}/export`

Скачать базу.

**Query:** `fmt=txt|csv|xlsx`

Возвращает файл (`Content-Disposition`).

---

## 6. Contacts

Глобальные операции по контактам (независимо от UI баз).

### `GET /v1/contacts`

**Query:** `status`, `page`, `per_page`.

---

### `GET /v1/contacts/kinds`

Счётчики по типам (`username` / `phone` / `user_id`).

---

### `POST /v1/contacts`

Добавить текстом.

```json
{ "text": "@a\n@b", "base_id": 1 }
```

Если `base_id` не указан — в базу по умолчанию.

---

### `POST /v1/contacts/claim`

Атомарно взять следующий `pending` контакт (как делает воркер). Статус → `sending`.

---

### `POST /v1/contacts/{contact_id}/finish`

Завершить обработку.

```json
{ "status": "sent", "account_id": 1, "text_id": 2, "error": "" }
```

`status`: `sent` | `error` | `skip` | `pending`.

---

### `POST /v1/contacts/{contact_id}/release`

Вернуть из `sending` в `pending` (если зависло).

---

### `POST /v1/contacts/release-stuck`

Все `sending` → `pending`.

---

### `POST /v1/contacts/reset-errors`

`error` и `skip` → `pending`. **Не** трогает `sending`.

---

### `DELETE /v1/contacts`

Очистить.

**Query:** `only_pending=false` — если `true`, удаляет только pending/error/skip.

---

## 7. Texts / Offers

### `GET /v1/texts`

**Query:** `enabled_only=false`.

---

### `GET /v1/texts/{text_id}`

Один оффер.

---

### `POST /v1/texts`

```json
{
  "title": "оффер A",
  "text": "Привет! …",
  "entities": [],
  "photo_path": "",
  "enabled": 1
}
```

Нужен непустой `text` **или** `photo_path`.

---

### `POST /v1/texts/upload`

Multipart: `text`, `title`, опционально `file` (фото).

---

### `PATCH /v1/texts/{text_id}`

Обновить: `text`, `title`, `entities_json`, `photo_path`, `enabled`.

---

### `POST /v1/texts/{text_id}/toggle`

Вкл/выкл оффер.

---

### `DELETE /v1/texts/{text_id}`

Удалить.

---

## 8. Blocklist / Banwords / Ban-base

### `GET /v1/blocklist`

**Query:** `page`, `per_page`.

Контакты, которым **нельзя** писать (не отправлять).

---

### `POST /v1/blocklist`

```json
{ "text": "@spam\n+7999", "note": "from api" }
```

Pending-контакты с совпадением помечаются `skip`.

---

### `DELETE /v1/blocklist/{block_id}`

Удалить запись; контакты со статусом skip/`blocklist` возвращаются в `pending`.

---

### `GET /v1/banwords`

Список банвордов модуля сбора.

---

### `POST /v1/banwords`

```json
{ "words": ["казино", "ставки", "viagra"] }
```

---

### `DELETE /v1/banwords/{word}`

Удалить слово (path-параметр, URL-encode при кириллице).

---

### `GET /v1/ban-contacts`

Банбаза (кого отсеяли банворды при сборе).

---

### `POST /v1/ban-contacts`

```json
{
  "kind": "username",
  "value": "baduser",
  "display": "@baduser",
  "reason": "banword: казино",
  "source_base_id": 3
}
```

---

## 9. Collect

Сбор базы для рассылки. Результат → **новая база** в `/v1/bases` (можно сразу `run/start`).

### `POST /v1/collect/chat`

Сбор из чата/группы.

```json
{
  "chat": "https://t.me/somechat",
  "mode": "all",
  "account_id": null,
  "base_name": null
}
```

| Поле | Описание |
|------|----------|
| `chat` | Ссылка, `@username`, invite или id `-100…` (аккаунт должен быть в чате) |
| `mode` | `all` — все участники; `writers` — только писавшие |
| `account_id` | `null` = перебор; для приватных укажите аккаунт-участник |
| `base_name` | Имя базы; иначе авто |

Банворды применяются автоматически. Совпадения → банбаза, не в рабочую.

**Ответ:** `base`, `added`, `banned`, `stopped`, `account_id`, `notes`.

---

### `POST /v1/collect/dm`

Сбор из ЛС-истории аккаунта → **отдельная** база.

```json
{
  "mode": "messaged",
  "account_id": 1,
  "dialog_limit": 500,
  "base_name": null
}
```

| `mode` | Смысл |
|--------|--------|
| `messaged` | Кому писали (есть исходящее) |
| `replied` | Кто отвечал (есть входящее) |

---

### `POST /v1/collect/mailing-base`

Итоговая база для рассылки: pending из включённых баз (или одной `source_base_id`), без дублей, без банбазы / blocklist / «кому писали» / `sent`.

```json
{
  "name": "Итоговая рассылка",
  "source_base_id": null
}
```

**Ответ:** `base`, `stats` (`added`, `excluded_ban`, `excluded_block`, `excluded_messaged`, …), `run`.

---

### `GET /v1/collect/history`

Журнал сборов (бот + API). Query: `limit`, `offset`.

**Ответ:** `items[]` — `id`, `source` (`bot`|`api`), `kind`, `mode`, `target`, `title`, `base_id`, `added`, `banned`, `stopped`, `created_at`, …

### `GET /v1/collect/history/{run_id}`

Одна запись журнала.

### `GET /v1/collect/history/{run_id}/export?fmt=txt|csv|xlsx`

Скачать контакты базы этого сбора.

---

## 10. Run (рассылка)

### `GET /v1/run/status`

`running`, `counts`, `continuous`, `running_keys`.

---

### `POST /v1/run/start`

Запуск рассылки 24/7 (или до опустошения очереди, если `continuous=false`).

Условия:

- есть assigned аккаунты с session;
- есть офферы;
- есть pending **или** включён `continuous`.

**409** если уже запущено.

---

### `POST /v1/run/stop`

Запрос остановки. Воркеры завершаются gracefully.

---

## 11. History

### `GET /v1/history/sends`

Последние отправки.

**Query:** `limit`, `offset`.

Поля: `contact_pretty`, `account_label`, `status` (`sent`/`skip`/`error`/`wait`), `detail`, …

---

### `GET /v1/history/jobs`

Последние jobs (`outreach`, …).

---

### `GET /v1/history/jobs/{job_id}`

Job + логи (до 100).

---

### `GET /v1/history/jobs/{job_id}/logs`

Только логи. **Query:** `limit`.

---

## 12. Примеры curl

```bash
export BASE=https://outreachapi.arix.vu
export KEY=your-api-key
H=(-H "X-API-Key: $KEY" -H "Content-Type: application/json")

# health
curl -s $BASE/v1/health

# stats
curl -s "${H[@]}" $BASE/v1/stats

# настройки
curl -s "${H[@]}" $BASE/v1/settings
curl -s "${H[@]}" -X PATCH $BASE/v1/settings \
  -d '{"delay_min":60,"delay_max":120,"between_delay_min":0,"continuous":true}'

# аккаунт + session
curl -s "${H[@]}" -X POST $BASE/v1/accounts -d '{"label":"work1"}'
curl -s -H "X-API-Key: $KEY" -F "file=@./work1.session" \
  $BASE/v1/accounts/1/session

# прокси
curl -s "${H[@]}" -X POST $BASE/v1/proxies \
  -d '{"text":"1.2.3.4:1080\n5.6.7.8:1080:user:pass"}'
curl -s "${H[@]}" -X POST $BASE/v1/proxies/1/check

# база + импорт
curl -s "${H[@]}" -X POST $BASE/v1/bases -d '{"name":"март"}'
curl -s -H "X-API-Key: $KEY" -F "file=@./leads.txt" $BASE/v1/bases/1/import
curl -s "${H[@]}" "$BASE/v1/bases/1/export?fmt=csv" -o leads.csv

# оффер
curl -s "${H[@]}" -X POST $BASE/v1/texts \
  -d '{"title":"A","text":"Привет! Есть предложение…"}'

# банворды
curl -s "${H[@]}" -X POST $BASE/v1/banwords \
  -d '{"words":["казино","ставки"]}'

# сбор
curl -s "${H[@]}" -X POST $BASE/v1/collect/chat \
  -d '{"chat":"@somechat","mode":"writers"}'

# старт / стоп
curl -s "${H[@]}" -X POST $BASE/v1/run/start
curl -s "${H[@]}" $BASE/v1/run/status
curl -s "${H[@]}" -X POST $BASE/v1/run/stop
```

---

## Совместимость с ботом

Бот (`main.py`) и API (`api_main.py`) используют **одну и ту же** SQLite `data/outreach.db`.

- Управлять можно и из Telegram, и через API.
- Рассылку лучше стартовать **либо** из бота, **либо** из API (один runtime на процесс).  
  Если оба процесса запущены отдельно — у каждого свой in-memory `runtime`: стартуйте рассылку в том процессе, которым управляете, либо держите run только в одном из них.

Рекомендация для prod: бот для оператора в Telegram, API для интеграций/панели; рассылку запускайте из одного места.

---

## Версия

`2.1.0` — полный CRUD по всем модулям системы + collect + run + history.

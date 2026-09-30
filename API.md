# Outreach API — полная документация

**Base URL (prod):** `https://outreachapi.arix.vu`  
**Prefix:** `/v1`  
**Version:** `2.2.0`  
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
8. [Campaigns](#8-campaigns)
9. [Blocklist / Banwords / Ban-base](#9-blocklist--banwords--ban-base)
10. [Collect](#10-collect)
11. [Run (основная рассылка)](#11-run-основная-рассылка)
12. [History](#12-history)
13. [Примеры curl](#13-примеры-curl)

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

Базы контактов.  
`enabled=1` + `isolated=0` — участвуют в **основной** рассылке.  
`isolated=1` — отдельная база (сбор «Отдельно»): не в основной очереди, пока не назначена в «Основной» или кампанию.

### `GET /v1/bases`

Список баз + `stats` (`total`, `pending`, `sent`) + флаги `enabled`, `isolated`.

---

### `POST /v1/bases`

```json
{ "name": "Лидген март", "isolated": 0, "enabled": 1 }
```

| Поле | По умолчанию | Смысл |
|------|--------------|--------|
| `isolated` | `0` | `1` = отдельная (не в основной очереди) |
| `enabled` | `1` | для isolated по умолчанию создаётся `enabled=0` |

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

### `PATCH /v1/bases/{base_id}/flags`

```json
{ "isolated": 0, "enabled": 1 }
```

Любое из полей опционально.

---

### `POST /v1/bases/{base_id}/assign`

Назначить базу в кампанию (как кнопка «Назначить» в боте).

```json
{ "campaign_id": 1 }
```

- Если кампания **Основной** (`is_main=1`): `isolated→0`, `enabled→1` (попадает в основную очередь).
- Иначе: база привязывается к кампании, остаётся `isolated=1`.

**Ответ:** `detail` (строка), `base`.

---

### `POST /v1/bases/{base_id}/toggle`

Вкл/выкл базу (`enabled`). Для isolated сама по себе не открывает основную очередь.

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

Атомарно взять следующий `pending` контакт (как воркер). Статус → `sending`.

**Query:**

| Параметр | По умолчанию | Смысл |
|----------|--------------|--------|
| `mailing_only` | `true` | Только enabled + не-isolated базы (основная очередь) |
| `base_ids` | — | `1,2,3` — claim только из этих баз (кампания) |

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

**Query:**

| Параметр | По умолчанию | Смысл |
|----------|--------------|--------|
| `enabled_only` | `false` | Только включённые |
| `shared_only` | `true` | Только общие (основная рассылка) |
| `campaign_id` | — | Офферы конкретной кампании |

---

### `GET /v1/texts/{text_id}`

Один оффер.

---

### `POST /v1/texts`

```json
{
  "title": "оффер A",
  "text": "Привет! {e:5278611606756942667} …",
  "entities": [],
  "photo_path": "",
  "enabled": 1,
  "expand_emoji_markers": true
}
```

Нужен непустой `text` **или** `photo_path`.

#### Premium emoji

Два способа передать custom emoji по ID:

**1. Маркер в тексте** (удобнее):

```json
{ "text": "Привет {e:5278611606756942667} мир" }
```

Также: `{{emoji:ID}}`, `{ce:ID}`, `{custom_emoji:ID}`.  
Маркер заменяется на 😀, а в `entities` пишется `custom_emoji` с UTF-16 offset/length.  
Отключить: `"expand_emoji_markers": false`.

**2. Явный entity:**

```json
{
  "text": "Привет 😀 мир",
  "entities": [
    {
      "type": "custom_emoji",
      "offset": 7,
      "length": 2,
      "custom_emoji_id": "5278611606756942667"
    }
  ]
}
```

`offset`/`length` — в UTF-16 code units (как в Telegram). Алиасы типа: `premium_emoji`, `emoji`, `ce`; id также: `document_id`, `emoji_id`, `id`.

Аккаунт-отправитель должен иметь Premium (или доступ к этому emoji), иначе Telegram не отрисует.

---

### `POST /v1/texts/upload`

Multipart: `text`, `title`, опционально `file` (фото). В `text` тоже работают маркеры `{e:ID}`.

---

### `PATCH /v1/texts/{text_id}`

Обновить оффер (edit).

```json
{
  "title": "оффер A v2",
  "text": "Новый текст с {e:5278611606756942667}",
  "entities": [],
  "photo_path": "",
  "enabled": 1,
  "expand_emoji_markers": true
}
```

Поля опциональны. Можно передать `entities` (массив) **или** `entities_json` (строка).  
При изменении `text` / `entities` маркеры `{e:ID}` раскрываются так же, как в `POST`.
---

### `POST /v1/texts/{text_id}/upload`

Заменить фото оффера. Multipart `file`.

---

### `POST /v1/texts/{text_id}/toggle`

Вкл/выкл оффер.

---

### `DELETE /v1/texts/{text_id}`

Удалить.

---

## 8. Campaigns

Отдельные рассылки со своими базами, аккаунтами и офферами.  
**Основной** (`is_main=1`) — глобальная очередь; старт через `/v1/run/*`.  
Остальные — через `/v1/campaigns/{id}/start|stop`.

### `GET /v1/campaigns`

Список. У каждой: `running`, `pending`; у не-main ещё `bases_n`, `accounts_n`, `texts_n`.

---

### `POST /v1/campaigns`

```json
{ "name": "Ретаргет апрель" }
```

---

### `GET /v1/campaigns/{campaign_id}`

Детали: кампания, `running`, `pending`, `base_ids`, `account_ids`, `text_ids`, объекты `bases` / `accounts` / `texts`.

То же: `GET /v1/campaigns/{id}/status`.

---

### `PATCH /v1/campaigns/{campaign_id}`

Переименовать (не для Основного).

```json
{ "name": "Новое имя" }
```

---

### `DELETE /v1/campaigns/{campaign_id}`

Удалить (не Основной; сначала stop). Базы/офферы не удаляются.

---

### `PUT /v1/campaigns/{id}/bases`

Заменить набор баз целиком.

```json
{ "ids": [3, 5, 8] }
```

---

### `PUT /v1/campaigns/{id}/accounts`

```json
{ "ids": [1, 2] }
```

---

### `PUT /v1/campaigns/{id}/texts`

```json
{ "ids": [4, 7] }
```

Привязать id офферов (свои кампании + общие). Свои офферы кампании лучше создавать через `POST` ниже.

---

### `POST /v1/campaigns/{id}/texts`

Создать **отдельный** оффер кампании (`campaign_id` проставляется). В основную рассылку и `GET /v1/texts` (по умолчанию) **не попадает**.

```json
{ "title": "камп A", "text": "Текст только для кампании {e:5278611606756942667}", "entities": [], "enabled": 1 }
```

Те же правила premium emoji, что у `POST /v1/texts`.

---

### `GET /v1/campaigns/{id}/texts`

`owned` — свои офферы кампании; `shared_linked` — прикреплённые общие; `text_ids` — все id в ротации.

---

### `POST /v1/campaigns/{id}/bases/{base_id}/toggle`

### `POST /v1/campaigns/{id}/accounts/{account_id}/toggle`

### `POST /v1/campaigns/{id}/texts/{text_id}/toggle`

Переключить один элемент. **Ответ:** `selected` (bool) + актуальный список id.

---

### `POST /v1/campaigns/{id}/start`

Запуск отдельной кампании.

Условия: ≥1 база, ≥1 аккаунт с session, ≥1 оффер; pending > 0 или `continuous=true`.

**409** если уже запущена. Для Основного → используйте `/v1/run/start`.

В логах/sends: `campaign_name`, префикс `[Имя]`.

---

### `POST /v1/campaigns/{id}/stop`

Остановка кампании.

---

## 9. Blocklist / Banwords / Ban-base

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

## 10. Collect

Сбор базы. Результат → новая запись в `/v1/bases`.

Флаг **`isolated: true`** — как кнопка «Отдельно» в боте: база не в основной очереди; назначьте через `POST /v1/bases/{id}/assign`.

### `POST /v1/collect/chat`

```json
{
  "chat": "https://t.me/somechat",
  "mode": "all",
  "account_id": null,
  "base_name": null,
  "isolated": false
}
```

| Поле | Описание |
|------|----------|
| `chat` | Ссылка, `@username`, invite или id `-100…` |
| `mode` | `all` / `writers` |
| `account_id` | `null` = перебор; для приватных — участник |
| `base_name` | Имя базы; иначе авто |
| `isolated` | `true` = отдельная база |

**Ответ:** `base`, `added`, `banned`, `stopped`, `isolated`, `account_id`, `run`, `notes`.

---

### `POST /v1/collect/dm`

```json
{
  "mode": "messaged",
  "account_id": 1,
  "dialog_limit": 500,
  "base_name": null,
  "isolated": true
}
```

| `mode` | Смысл |
|--------|--------|
| `messaged` | Кому писали |
| `replied` | Кто отвечал |

---

### `POST /v1/collect/premium`

**Quality Lead Intelligence:**

- Полный deep-scan групп (до `PREMIUM_MESSAGES_PER_CHAT`, не 10–20)
- Полные тексты постов в сильную модель (`gpt-4o` / Claude)
- 1 LLM-вызов = досье + score по поведению
- Экономия только: «ок/лол», дубли, пустые профили; батч 2–3

Если групп больше `PREMIUM_CHAT_TOP_K` — LLM-rank по ~120 постам, затем full scan топа.

---

### `POST /v1/collect/mailing-base`

Итоговая база: pending из включённых **не-isolated** баз (или одной `source_base_id`), без дублей / банбазы / blocklist / «кому писали» / `sent`.

```json
{
  "name": "Итоговая рассылка",
  "source_base_id": null
}
```

---

### `GET /v1/collect/history`

Журнал сборов. Query: `limit`, `offset`.

### `GET /v1/collect/history/{run_id}`

### `GET /v1/collect/history/{run_id}/export?fmt=txt|csv|xlsx`

---

## 11. Run (основная рассылка)

### `GET /v1/run/status`

`running`, `counts`, `continuous`, `running_keys` (включая `campaign:N`).

---

### `POST /v1/run/start`

Основная рассылка (кампания «Основной»). Берёт enabled + не-isolated базы, assigned аккаунты, все enabled офферы.

**409** если уже запущено.

---

### `POST /v1/run/stop`

Остановка основной рассылки.

---

## 12. History

### `GET /v1/history/sends`

Последние отправки. Поля включают `campaign_id`, `campaign_name`.

**Query:** `limit`, `offset`.

---

### `GET /v1/history/jobs`

Jobs (`outreach`, `campaign`, …) + `campaign_id` / `campaign_name`.

---

### `GET /v1/history/jobs/{job_id}`

Job + логи (до 100). В сообщениях логов — префикс `[Имя кампании]`.

---

### `GET /v1/history/jobs/{job_id}/logs`

Только логи. **Query:** `limit`.

---

## 13. Примеры curl

```bash
export BASE=https://outreachapi.arix.vu
export KEY=your-api-key
H=(-H "X-API-Key: $KEY" -H "Content-Type: application/json")

# health / stats
curl -s $BASE/v1/health
curl -s "${H[@]}" $BASE/v1/stats

# отдельный сбор → назначить в кампанию
curl -s "${H[@]}" -X POST $BASE/v1/collect/chat \
  -d '{"chat":"@somechat","mode":"writers","isolated":true}'
curl -s "${H[@]}" -X POST $BASE/v1/bases/3/assign -d '{"campaign_id":2}'

# кампания
curl -s "${H[@]}" -X POST $BASE/v1/campaigns -d '{"name":"Ретаргет"}'
curl -s "${H[@]}" -X PUT $BASE/v1/campaigns/2/bases -d '{"ids":[3,4]}'
curl -s "${H[@]}" -X PUT $BASE/v1/campaigns/2/accounts -d '{"ids":[1]}'
curl -s "${H[@]}" -X PUT $BASE/v1/campaigns/2/texts -d '{"ids":[1,2]}'
curl -s "${H[@]}" -X POST $BASE/v1/campaigns/2/start
curl -s "${H[@]}" $BASE/v1/campaigns/2/status
curl -s "${H[@]}" -X POST $BASE/v1/campaigns/2/stop

# edit оффера
curl -s "${H[@]}" -X PATCH $BASE/v1/texts/1 \
  -d '{"title":"A v2","text":"Обновлённый текст…"}'

# основная рассылка
curl -s "${H[@]}" -X POST $BASE/v1/run/start
curl -s "${H[@]}" -X POST $BASE/v1/run/stop
```

---

## Совместимость с ботом

Бот (`main.py`) и API (`api_main.py`) используют **одну** SQLite `data/outreach.db`.

- Управление из Telegram и через API.
- У каждого процесса свой in-memory `runtime`: стартуйте run/campaign в том процессе, которым управляете.

Рекомендация: бот для оператора, API для интеграций; рассылку — из одного места.

---

## Версия

`2.2.0` — кампании, отдельный сбор (`isolated`), assign баз, edit офферов, полные CRUD + run/history с метками кампаний.

#!/usr/bin/env python3
"""
Заливка 10 RU-офферов (universal-ru-21..30) в кампанию #2 Outreach API.

Запуск на Windows (нужен только Python 3, ничего доустанавливать не надо):

    set KEY=ваш-api-key
    python upload_offers_campaign2.py            # dry-run: только показать, ничего не пишет
    python upload_offers_campaign2.py --go        # реальная заливка

(в PowerShell вместо set: $env:KEY="ваш-api-key")

Рядом должен лежать offers-ru-campaign2.json — с эмодзи-маркерами {e:ID}
для 4 premium emoji, ротация по офферам.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("BASE", "https://outreachapi.arix.vu")
CAMPAIGN_ID = os.environ.get("CAMPAIGN_ID", "2")
JSON_PATH = os.environ.get("JSON", os.path.join(os.path.dirname(os.path.abspath(__file__)), "offers-ru-campaign2.json"))


def api(method, path, key, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-Key", key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}
    except urllib.error.URLError as e:
        print(f"Не удалось достучаться до {url}: {e.reason}")
        sys.exit(1)


def main():
    go = "--go" in sys.argv[1:]

    key = os.environ.get("KEY", "").strip()
    if not key:
        print("Нужен ключ. Windows cmd:  set KEY=ваш-ключ")
        print("PowerShell:               $env:KEY=\"ваш-ключ\"")
        sys.exit(1)

    if not os.path.isfile(JSON_PATH):
        print(f"Не найден файл {JSON_PATH} — он должен лежать рядом со скриптом.")
        sys.exit(1)

    with open(JSON_PATH, encoding="utf-8") as f:
        offers = json.load(f)

    print("== health ==")
    status, health = api("GET", "/v1/health", key)
    print(f"  HTTP {status}: {health}")
    if status != 200:
        print("API недоступен или ключ неверный — дальше не идём.")
        sys.exit(1)

    print()
    print(f"== кампания #{CAMPAIGN_ID} ==")
    status, camp = api("GET", f"/v1/campaigns/{CAMPAIGN_ID}", key)
    if status != 200:
        print(f"  Не удалось получить кампанию: HTTP {status}: {camp}")
        sys.exit(1)
    c = camp.get("campaign", {})
    print(f"  name={c.get('name')!r}  is_main={c.get('is_main')}  running={camp.get('running')}  pending={camp.get('pending')}")
    print(f"  bases={len(camp.get('base_ids', []))}  accounts={len(camp.get('account_ids', []))}  texts={len(camp.get('text_ids', []))}")

    if str(c.get("is_main")) == "1":
        print()
        print("  ВНИМАНИЕ: это кампания 'Основной' — офферы уйдут в общую рассылку.")
        print("  Если это не то, что нужно — Ctrl+C сейчас, есть 5 секунд.")
        time.sleep(5)

    print()
    print("== офферы, уже привязанные к кампании ==")
    status, texts_now = api("GET", f"/v1/campaigns/{CAMPAIGN_ID}/texts", key)
    if status == 200:
        owned = texts_now.get("owned", []) or []
        shared = texts_now.get("shared_linked", []) or []
        print(f"  свои: {len(owned)}, общие подключённые: {len(shared)}")
        for t in owned:
            print(f"    id={t.get('id')} enabled={t.get('enabled')} title={t.get('title')!r}")

    print()
    print(f"== к заливке: {len(offers)} офферов ==")
    for o in offers:
        print(f"  {o.get('_tag')}  {o.get('title')}")

    if not go:
        print()
        print("Это dry-run, ничего не записано. Для реальной заливки:")
        print("  python upload_offers_campaign2.py --go")
        return

    print()
    print("== заливка ==")
    ok, fail = 0, 0
    for o in offers:
        body = {k: v for k, v in o.items() if not k.startswith("_")}
        status, resp = api("POST", f"/v1/campaigns/{CAMPAIGN_ID}/texts", key, body)
        text_obj = resp.get("text", resp)
        text_id = text_obj.get("id") if isinstance(text_obj, dict) else None
        entities = text_obj.get("entities", []) if isinstance(text_obj, dict) else []
        n_emoji = sum(1 for e in entities if e.get("type") == "custom_emoji")
        if status in (200, 201) and text_id:
            print(f"  ok   {o.get('_tag')} -> text_id={text_id}, custom_emoji entities: {n_emoji}")
            ok += 1
        else:
            print(f"  FAIL {o.get('_tag')} -> HTTP {status}: {resp}")
            fail += 1
        time.sleep(0.4)

    print()
    print(f"залито: {ok}, ошибок: {fail}")

    print()
    print("== офферы кампании после заливки ==")
    status, texts_after = api("GET", f"/v1/campaigns/{CAMPAIGN_ID}/texts", key)
    if status == 200:
        for t in texts_after.get("owned", []) or []:
            print(f"  id={t.get('id')} enabled={t.get('enabled')} title={t.get('title')!r}")

    print()
    print("Проверить, что премиум-эмодзи развернулся в entity, для конкретного id:")
    print(f'  python -c "import urllib.request,json,os; r=urllib.request.Request(\'{BASE}/v1/texts/<id>\', headers={{\'X-API-Key\': os.environ[\'KEY\']}}); print(json.load(urllib.request.urlopen(r)))"')


if __name__ == "__main__":
    main()
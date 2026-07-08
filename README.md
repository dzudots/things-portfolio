# Стак — портфель имущества

Личный баланс активов: сколько стоят ваши вещи сейчас, как менялась оценка.

**Нейминг:** бренд **Стак** · слоган «твой стак имущества» · фичи: Портфель, Скан, Алерты, Достижения, тариф **Pro**.

Это **не** маркетплейс, **не** инвестиционные советы и **не** канал налоговой отчётности.
Оценка всегда как **диапазон + уверенность**. Данные портфеля — конфиденциальные.

## Конфиденциальность (как храним)

| Слой | Что |
|------|-----|
| Аккаунт | email + bcrypt пароль; имя шифруется |
| Портфель | цена покупки, override, заметки — **Fernet (AES) at rest** |
| Не собираем | ИНН, паспорт, VIN, серийники, точный адрес |
| Рынок | comps — обезличенные агрегаты, не привязаны к пользователю |
| Контроль | экспорт JSON + полное удаление аккаунта |

Ключ шифрования: `THINGS_DATA_KEY` (Fernet). Без него для локальной разработки ключ выводится из `THINGS_SECRET_KEY`.

Подробнее: страница `/privacy`.

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Или `run.bat`. Откройте http://127.0.0.1:8000

**Prod:** https://things-portfolio-production.up.railway.app  
Демо: `demo@things.local` / `demo1234`

На телефоне: откройте сайт → баннер «Установить» / iOS: Поделиться → «На экран Домой».

Smoke на проде: `python scripts/prod_smoke.py` (или `THINGS_PROD_URL=https://... python scripts/prod_smoke.py`)

## Возможности

- Портфель smartphone / laptop / car
- Оценка P25/P50/P75 внутри бакета состояния
- **Скан по фото** (`/scan`): AI identify → матч в каталоге → comps-диапазон
- Алерты при движении mid + недельный дайджест
- Аккаунт: настройки, экспорт, удаление
- PWA (manifest + service worker; приватные страницы не кэшируются)

## Env (production)

```
THINGS_SECRET_KEY=...
THINGS_DATA_KEY=...   # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
THINGS_DATABASE_URL=sqlite:///...  # или Postgres

# AI via Poe (OpenAI-compatible, vision scan)
THINGS_AI_API_KEY=...                 # sk-poe-... from poe.com (не коммитить)
THINGS_AI_BASE_URL=https://api.poe.com/v1
THINGS_AI_MODEL=claude-haiku-4.5      # vision + дёшево; alt: gemini-2.5-flash-lite
THINGS_AI_MARKUP_PCT=15
THINGS_FREE_SCANS_PER_DAY=5
THINGS_PRO_SCANS_PER_DAY=50
# без ключа или THINGS_AI_FORCE_MOCK=1 — стабильный mock-режим
# ЮKassa позже: THINGS_YOOKASSA_SHOP_ID / THINGS_YOOKASSA_SECRET_KEY
THINGS_ADMIN_EMAILS=you@email.com
THINGS_ADMIN_API_KEY=...
```

API: `POST /api/scan` (multipart `photo`), `GET /api/usage`, `GET /health`.

**Comps ingest (admin):** нужен `THINGS_ADMIN_EMAILS` или `X-Admin-Key`:
- `GET /api/admin/comps/sources` — whitelist source ids
- `POST /api/admin/comps/ingest` — body `{"source":"manual_json","rows":[...]}`
- `POST /api/admin/comps/refresh` — partner_feed, иначе mock (cron 02:00 UTC)
- CLI: `python scripts/ingest_comps.py data/sample_comps_ingest.json`

Наценка на AI: **10–30%** от estimated provider cost (дешёвые модели ближе к 10–15%, тяжёлые vision — до 30%). Цель сейчас — стабильность продукта; пассивный доход вторичен.

## Деплой (Railway + GitHub)

Репозиторий: [dzudots/things-portfolio](https://github.com/dzudots/things-portfolio). Прод: Railway, сборка по `Dockerfile` и `railway.toml`.

### Поток

1. **Push в `master`** → Railway пересобирает контейнер и ждёт `GET /health` (200 + `db_ok: true`).
2. **GitHub Actions** (`.github/workflows/ci.yml`):
   - на каждый push/PR — `python -m unittest discover -s tests`;
   - после успешных тестов на push в `master` — опциональный `scripts/prod_smoke.py` против прод-URL.
3. Локально перед push: `python -m unittest discover -s tests -v`.

### Переменные Railway

Обязательные для стабильного прода:

| Переменная | Назначение |
|------------|------------|
| `THINGS_SECRET_KEY` | сессии, подписи |
| `THINGS_DATA_KEY` | Fernet для полей портфеля |
| `DATABASE_URL` или `THINGS_DATABASE_URL` | Postgres (рекомендуется) |
| `THINGS_UPLOAD_DIR` | `/data/uploads/scans` (volume) |

Опционально: `THINGS_AI_*` (Poe: `https://api.poe.com/v1` + `claude-haiku-4.5`; без ключа — mock).
`THINGS_ADMIN_EMAILS` / `THINGS_ADMIN_API_KEY` — иначе `/api/admin/*` закрыт.
ЮKassa: `THINGS_YOOKASSA_*` когда будет магазин.

### Секреты GitHub Actions

| Secret | Обязателен | Описание |
|--------|------------|----------|
| `THINGS_PROD_URL` | нет | Базовый URL прода, напр. `https://things-portfolio-production.up.railway.app`. Без секрета prod smoke пропускается. |

### Health

`GET /health` → `{"ok": true, "db_ok": true, "ai_provider_ready": bool, "telegram_configured": bool, "product": "Стак"}`. При недоступной БД — HTTP 503, Railway/Docker не считают инстанс здоровым.
<!-- deploy: 2026-07-09-pro2 -->


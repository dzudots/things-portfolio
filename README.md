# Стак — портфель имущества

Личный баланс активов: сколько стоят ваши вещи сейчас, как менялась оценка.

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

Smoke на проде: `python scripts/prod_smoke.py`

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

# AI (OpenAI-compatible: OpenAI / Poe / OpenRouter)
THINGS_AI_API_KEY=...
THINGS_AI_BASE_URL=https://api.openai.com/v1
THINGS_AI_MODEL=gpt-4o-mini
THINGS_AI_MARKUP_PCT=20          # наценка 10–30% на cost модели
THINGS_FREE_SCANS_PER_DAY=5
THINGS_PRO_SCANS_PER_DAY=50
# без ключа или THINGS_AI_FORCE_MOCK=1 — стабильный mock-режим
```

API: `POST /api/scan` (multipart `photo`), `GET /api/usage`, `GET /health`.

Наценка на AI: **10–30%** от estimated provider cost (дешёвые модели ближе к 10–15%, тяжёлые vision — до 30%). Цель сейчас — стабильность продукта; пассивный доход вторичен.
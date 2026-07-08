FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bust layer cache when app code changes
ARG CACHE_BUST=20260709-pro3
RUN echo "cache_bust=${CACHE_BUST}" > /tmp/cache_bust.txt

COPY app ./app
COPY docs ./docs
COPY tests ./tests
COPY README.md .

RUN mkdir -p /data/uploads/scans /data \
    && python -c "from app.main import app; assert any(getattr(r,'path',None)=='/account/pro' for r in app.routes)"

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

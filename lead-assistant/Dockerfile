# Образ приложения: API с собранным интерфейсом и фоновый обработчик (одна сборка, две команды).
# Модель работает в отдельном контейнере llama.cpp (см. docker-compose.yml).

FROM node:22.12.0-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.8-slim-bookworm AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LEADS_DATA_DIR=/data \
    LEADS_RUNS_DIR=/data/runs \
    LEADS_LLM_HOME=/llm \
    LEADS_STATIC_DIR=/app/web/dist \
    LEADS_SEED_FILE=/app/data/leads.original.json \
    LEADS_HOST=0.0.0.0 \
    LEADS_PORT=8000
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir --no-deps --no-build-isolation -e .
COPY data/leads.original.json data/leads.original.json
COPY evals/ evals/
COPY --from=web /web/dist web/dist
RUN useradd --system --uid 10001 --home /app leads \
    && mkdir -p /data /llm && chown -R leads:leads /data /llm
USER leads
VOLUME ["/data", "/llm"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["leads-web"]

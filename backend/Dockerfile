FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STOCKLENS_ENV=production \
    STOCKLENS_DATA_DIR=/app/data \
    STOCKLENS_ACCOUNT_DB=/app/accounts/accounts.sqlite3
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && groupadd --gid 10001 stocklens \
    && useradd --uid 10001 --gid stocklens --no-create-home stocklens \
    && mkdir -p /app/data /app/accounts \
    && chown stocklens:stocklens /app/data /app/accounts
COPY backend/ /app/backend/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3))['status']=='ok'"
CMD ["python", "-m", "uvicorn", "app:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--limit-concurrency", "8", "--backlog", "64", "--timeout-keep-alive", "5"]

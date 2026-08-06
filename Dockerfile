# Fieldcraft POC — container image
FROM python:3.12-slim

# non-root user (sandbox hygiene: agent-written code + pytest run as this user)
RUN useradd -m -u 10001 fieldcraft
WORKDIR /app

# deps first (layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# app
COPY fieldcraft_aar ./fieldcraft_aar
COPY fieldcraft_loop ./fieldcraft_loop
COPY fieldcraft_web ./fieldcraft_web
COPY sample_task ./sample_task

# durable data (SQLite event + brief history); mount a volume here in prod
ENV FC_DATA_DIR=/data
RUN mkdir -p /data && chown -R fieldcraft:fieldcraft /data /app
USER fieldcraft

EXPOSE 8000
# sensible public defaults; override via env / fly secrets
ENV FC_ALLOW_LIVE=0 \
    FC_BRIEFS_PER_HOUR=10 \
    FC_MAX_CONCURRENT=4 \
    FC_DAILY_COST_CAP_USD=5 \
    FC_MAX_BUDGET_PER_RUN_USD=1 \
    FC_PYTEST_TIMEOUT_S=30

HEALTHCHECK --interval=30s --timeout=4s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz'); " || exit 1

CMD ["python","-m","uvicorn","fieldcraft_web.server:app","--host","0.0.0.0","--port","8000"]

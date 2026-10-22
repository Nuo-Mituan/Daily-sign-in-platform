# syntax=docker/dockerfile:1
# Production image: frontend build stage + slim Python runtime.
FROM node:22-alpine AS frontend-builder
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
LABEL org.opencontainers.image.title="Daily Check-in Platform" \
      org.opencontainers.image.description="Self-hosted daily check-in platform" \
      org.opencontainers.image.version="1.0.3"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    DATA_DIR=/app/data \
    MODULES_DIR=/app/modules \
    LOGS_DIR=/app/logs \
    FRONTEND_DIR=/app/static
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=frontend-builder /web/dist ./static
COPY modules ./modules
COPY templates ./templates
COPY docker-entrypoint.py /usr/local/bin/docker-entrypoint.py
COPY .env.example ./.env.example
RUN mkdir -p /app/data /app/logs /app/modules /app/app/push_drivers/custom \
    && chmod 700 /app/data /app/logs \
    && chmod 755 /usr/local/bin/docker-entrypoint.py \
    && chmod -R a+rX /app/app /app/static /app/templates /app/modules
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3).status == 200 else 1)"
ENTRYPOINT ["python", "/usr/local/bin/docker-entrypoint.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]

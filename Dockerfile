# syntax=docker/dockerfile:1
# Locuvi v0.1 — single container: FastAPI API + built React frontend + archive worker.
#
# Behind a TLS-intercepting proxy, pass its CA as an optional build secret:
#   docker build --secret id=build_ca,src=/path/to/ca.pem .
# Without it, the build uses the default public CAs. Nothing is stored in the image.

# ---- frontend build -------------------------------------------------------
FROM node:22.12.0-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- python dependencies --------------------------------------------------
FROM python:3.12.8-slim-bookworm AS backend
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir uv==0.11.32 \
 && uv sync --frozen --no-dev --no-install-project
COPY backend/locuvi ./locuvi
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --frozen --no-dev --no-editable

# ---- runtime ----------------------------------------------------------------
FROM python:3.12.8-slim-bookworm
LABEL org.opencontainers.image.title="Locuvi" \
      org.opencontainers.image.description="Personal GP locum invoicing (v0.1)" \
      org.opencontainers.image.version="0.1.0"
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DATA_DIR=/data \
    KEY_DIR=/keys \
    STATIC_DIR=/app/static \
    TZ=Europe/London
RUN groupadd --system --gid 10001 locuvi \
 && useradd --system --uid 10001 --gid locuvi --home-dir /app --shell /usr/sbin/nologin locuvi \
 && mkdir -p /data /keys \
 && chown locuvi:locuvi /data /keys \
 && chmod 0700 /keys
WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /src/dist /app/static
USER 10001:10001
VOLUME ["/data", "/keys"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=4).status == 200 else 1)"]
# One process only: SQLite single-writer + in-process archive worker.
CMD ["uvicorn", "locuvi.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]

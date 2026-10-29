# ============================================================
# Stage 1: Install dependencies
# ============================================================
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install

# El lock fija las versiones probadas; requirements.txt sólo lista lo directo.
COPY backend/requirements.lock .
RUN pip install --no-cache-dir --prefix=/install/deps -r requirements.lock


# ============================================================
# Stage 2: Production image
# ============================================================
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 shared-mime-info \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos '' appuser

COPY --from=builder /install/deps /usr/local

WORKDIR /app

ENV FLASK_APP=backend.app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY . .

# uploads/ (logo del negocio) no viene en el repo: sin crearla aquí, un volumen montado
# ahí nace con dueño root y appuser no puede guardar el logo.
RUN mkdir -p /app/backend/static/uploads/logos && chown -R appuser:appuser /app
USER appuser

EXPOSE 5005

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:5005/health')"

# Un solo worker eventlet: Socket.IO guarda las salas en memoria y con varios workers
# un aviso de cocina no llega al mesero conectado a otro. Mismo comando que el compose.
# PORT lo fijan algunas plataformas de nube; local queda en 5005.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5005} --worker-class eventlet --workers 1 --timeout 120 --access-logfile - --error-logfile - backend.app:app"]

# DocPilot backend image (FastAPI + Celery worker).
#
# Single image, two roles — the docker-compose file picks the role via the
# command override. Building once and running twice keeps the deploy simple.
#
# Stage 1 — install OS deps + Python deps in a builder
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build tools needed to compile some Python wheels (psycopg2, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Stage 2 — slim runtime
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/usr/local/bin:${PATH}"

# Runtime system deps:
#   ffmpeg     — extract audio + frames from uploads
#   libmagic1  — file-type sniffing (python-magic)
#   GTK/Pango/Cairo + fonts — WeasyPrint PDF rendering
#   libpq5     — psycopg2 runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libmagic1 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    libssl3 \
    libpq5 \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-noto-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Bring Python deps from the builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
COPY . .

# Drop privileges
RUN useradd -m -u 1000 docpilot && chown -R docpilot:docpilot /app
USER docpilot

# FastAPI listens on 8000 inside the container; nginx out front terminates SSL
EXPOSE 8000

# Default command runs the API server. The worker service overrides this in
# docker-compose with the celery command.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

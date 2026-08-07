# syntax=docker/dockerfile:1.7

# ============================================================
# MyM Waffles — Dagster + dbt + Python ingestion
# ============================================================
# Imagen base con Python 3.11 slim (Debian) + uv como package manager.
# Corre: Dagster (webserver + daemon), dbt, y código de ingesta.
# ============================================================

FROM python:3.11-slim-bookworm

# --- Metadatos ---
LABEL org.opencontainers.image.source="https://github.com/SabaM10/mym-waffles-data"
LABEL org.opencontainers.image.description="Dagster + dbt + Python para pipeline de MyM Waffles"

# --- Variables de entorno ---
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy

# --- Directorio de trabajo ---
WORKDIR /workspace

# --- Dependencias del sistema ---
# git: dbt lo necesita para gestionar packages
# curl: para healthchecks y debugging
# build-essential: por si alguna dep tiene que compilar C
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# --- Instalar uv ---
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# --- Instalar dependencias Python ---
# Copiamos primero solo pyproject.toml para aprovechar cache de Docker:
# si el código cambia pero las deps no, esta capa no se rehace.
COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

# --- Copiar el resto del código ---
# En dev, este directorio se sobrescribe con un bind mount desde el host
# (ver docker-compose.yml). En prod se usa este COPY.
COPY . .

# --- Dagster home ---
# Directorio donde Dagster guarda metadata de runs, logs, schedules.
ENV DAGSTER_HOME=/opt/dagster/dagster_home
RUN mkdir -p $DAGSTER_HOME

# --- Exponer puerto de Dagster UI ---
EXPOSE 3000

# --- Comando default ---
# Levanta el webserver de Dagster. El daemon (schedules/sensors) corre
# en un service aparte en docker-compose.yml.
CMD ["dagster", "dev", "--host", "0.0.0.0", "--port", "3000"]

# Industrial Packaging — Multi-stage Dockerfile for the
# Supply Chain Intelligence Agent.
#
# Stage 1 (builder): installs the build toolchain and creates a self-contained
# virtualenv at /opt/venv with all Python dependencies. This stage is heavy
# (~700 MB) but it never ships to production.
#
# Stage 2 (runtime): a clean slim image that copies only /opt/venv and the
# application source. No compilers, no caches, runs as a non-root user.
#
# Layer ordering is optimised so that source-only changes do NOT bust the
# expensive `pip install` cache layer.

ARG PYTHON_VERSION=3.11
ARG DEBIAN_RELEASE=bookworm

# ---------- Stage 1: builder ----------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System build dependencies. `--no-install-recommends` keeps the layer tight.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated virtualenv that we'll copy verbatim into the runtime
# image. This makes the runtime stage trivially reproducible and lets us drop
# the entire builder layer set.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Copy *only* requirements.txt first so this layer is cached unless deps
# actually change. Source code changes won't invalidate it.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt

# ---------- Stage 2: runtime ----------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    APP_HOME=/app \
    CHECKPOINT_DB_PATH=/app/checkpoints/checkpoint_db.sqlite

# Minimal runtime-only system packages: curl for the healthcheck, tini for
# correct PID-1 signal handling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. Industrial deployments must NOT run application code as root.
RUN groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid appuser --create-home --shell /usr/sbin/nologin appuser

WORKDIR ${APP_HOME}

# Copy the pre-built virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Copy the application source. Owned by appuser so the non-root user can read
# (and, for /app/checkpoints, write).
COPY --chown=appuser:appuser . ${APP_HOME}

# Pre-create writable directories for the checkpoint DB and any local caches.
RUN mkdir -p ${APP_HOME}/checkpoints ${APP_HOME}/chroma_db \
    && chown -R appuser:appuser ${APP_HOME}/checkpoints ${APP_HOME}/chroma_db

# Make the entrypoint executable.
RUN chmod +x ${APP_HOME}/entrypoint.sh

USER appuser

EXPOSE 8000

# Healthcheck hits the FastAPI /health endpoint. Uses curl (not python) so we
# avoid loading the agent's heavy import graph just to ping ourselves.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl --silent --fail http://localhost:8000/health || exit 1

# tini handles signal forwarding so `docker stop` cleanly shuts down uvicorn.
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

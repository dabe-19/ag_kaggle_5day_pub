# ----- Stage 1: builder -----
FROM python:3.14-slim AS builder

# System build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip + install poetry using build cache mount
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 10 --upgrade pip setuptools wheel "poetry>=2.0.0"

WORKDIR /app

# Copy dependency manifests and the README first to optimize caching
COPY pyproject.toml poetry.lock poetry.toml README.md ./

# Install only third-party dependencies using build cache mount
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry config installer.max-workers 10 && \
    poetry config virtualenvs.create false && \
    poetry install --only main --no-root --no-interaction --no-ansi

# Copy the actual application source code
COPY src/ ./src/

# Install the application package itself
RUN poetry install --only main --no-interaction --no-ansi


# ----- Stage 2: runtime -----
FROM python:3.14-slim AS runtime

# Force IPv4 preference system-wide to prevent IPv6 connection hangs in VPN/Docker networks
RUN echo "precedence ::ffff:0:0/96  100" >> /etc/gai.conf

# Non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy the fully-installed Python environment from the builder stage
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source so the package is importable at runtime
COPY --chown=appuser:appuser --from=builder /app/src ./src
COPY --chown=appuser:appuser service.yaml ./service.yaml

ENV PYTHONPATH="/app/src"

# Drop privileges
USER appuser

# uvicorn listens on 8000; nginx (or Cloud Run) handles the outside world
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "ag_kaggle_5day.app:app", "--host", "0.0.0.0", "--port", "8000"]

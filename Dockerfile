# ─────────────────────────────────────────────────────
# Module   : Dockerfile
# Layer    : Infrastructure / Deployment
# Pillar   : P0 (Bootstrap), P2 (Security), P5 (Scalability)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

# P2 (Security): Use specific SHA digest or narrow tag for base image
FROM python:3.12-slim-bookworm

# P2 (Security): Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/app

# P0 (Bootstrap): Install system dependencies (if any are needed for crypto/networking)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# P0 (Bootstrap): Install application dependencies
COPY pyproject.toml .
RUN pip install .

# P2 (Security): Create a non-root user to run the application
RUN groupadd -r botgroup && useradd -r -g botgroup botuser

# Copy application code
COPY ./app ./app

# P2 (Security): Transfer ownership to the non-root user
RUN chown -R botuser:botgroup /opt/app

# Switch to non-root user
USER botuser

# Expose the FastAPI health/probe port
EXPOSE 8000

# P0 (Bootstrap): Run Uvicorn. The Bot will be launched asynchronously inside main.py
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
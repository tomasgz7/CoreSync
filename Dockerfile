# =============================================================================
# CoreSync - Multi-Agent Identity Governance Pipeline
# Container image for deployment as a Hosted Agent in
# Microsoft Azure AI Foundry Agent Service.
#
# Microsoft Agents League Hackathon 2026 | Reasoning Agents Track
# =============================================================================

# Ultra-lightweight base image as mandated by the Hosted Agent packaging
# strategy - minimizes attack surface and cold-start time.
FROM python:3.11-slim

LABEL maintainer="CodeNoZhiend" \
      project="CoreSync" \
      track="Reasoning Agents - Microsoft Agents League Hackathon 2026" \
      description="Multi-agent reasoning pipeline for enterprise identity governance"

WORKDIR /app

# ---------------------------------------------------------------------------
# Dependency installation - cached as a separate layer
# ---------------------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Application source
# ---------------------------------------------------------------------------
COPY agent/ ./agent/
COPY connectors/ ./connectors/
COPY data/ ./data/
COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

# ---------------------------------------------------------------------------
# Security: run as a non-root user inside the Hosted Agent sandbox
# ---------------------------------------------------------------------------
RUN useradd --create-home --shell /bin/sh coresync \
    && chown -R coresync:coresync /app
USER coresync

# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EXECUTION_ENVIRONMENT=dev \
    INGESTION_DATA_PATH=/app/data/synthetic_records.json

# Foundry Agent Service injects AZURE_AI_PROJECT_ENDPOINT and
# AZURE_AI_MODEL_DEPLOYMENT at runtime via Managed Identity context.
# No secrets are baked into this image - see env.production.example.

ENTRYPOINT ["./entrypoint.sh"]

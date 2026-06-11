#!/bin/sh
# entrypoint.sh - CoreSync Hosted Agent Entrypoint
#
# Boots the CoreSync multi-agent orchestration pipeline inside the
# Foundry Agent Service Hosted Agent runtime.
#
# Mode selection:
#   - If AZURE_AI_PROJECT_ENDPOINT is unset, the container falls back to
#     --dry-run (Planner-Executor-Critic simulation, zero external calls).
#   - If AZURE_AI_PROJECT_ENDPOINT is set, the pipeline runs LIVE against
#     Azure OpenAI using the Managed Identity assigned to the Hosted Agent.
#
# Any arguments passed to `docker run` are forwarded to agent/main.py,
# allowing overrides such as --data or --signals for alternate datasets.

set -e

echo "============================================================"
echo "  CoreSync - Hosted Agent Bootstrap"
echo "  Microsoft Agents League Hackathon 2026 | Reasoning Agents"
echo "============================================================"
echo "  Execution environment : ${EXECUTION_ENVIRONMENT:-dev}"
echo "  Ingestion data path    : ${INGESTION_DATA_PATH:-/app/data/synthetic_records.json}"

if [ -z "$AZURE_AI_PROJECT_ENDPOINT" ]; then
    echo "  Mode                    : DRY-RUN (no AZURE_AI_PROJECT_ENDPOINT set)"
    echo "============================================================"
    exec python agent/main.py --dry-run \
        --data "${INGESTION_DATA_PATH:-/app/data/synthetic_records.json}" \
        "$@"
else
    echo "  Mode                    : LIVE (Managed Identity auth)"
    echo "  Project endpoint        : ${AZURE_AI_PROJECT_ENDPOINT}"
    echo "  Model deployment        : ${AZURE_AI_MODEL_DEPLOYMENT:-gpt-4o}"
    echo "============================================================"
    exec python agent/main.py \
        --data "${INGESTION_DATA_PATH:-/app/data/synthetic_records.json}" \
        "$@"
fi

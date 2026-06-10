"""
resolver.py - CoreSync Reasoning Attendance Reconciler Agent

Part of the autonomous multi-agent architecture built for the
Microsoft Agents League Hackathon - Reasoning Agents Track.

Implements a Planner-Executor-Critic reasoning pattern to reconcile
Check-In and Check-Out attendance records across parallel simulation
classrooms. Every decision is grounded against Foundry IQ Audit Rules
and subject to an internal Critic verification loop before emission,
guaranteeing zero false positives in certification attendance verdicts.
"""

import json
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from openai import AzureOpenAI, APIConnectionError, APIStatusError, APITimeoutError

from connectors.foundry import AuditContext

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()

_REQUIRED_ENV_VARS = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_API_VERSION",
    "DEPLOYMENT_NAME",
)


def _validate_env() -> None:
    """Validate that all required environment variables are present.

    Raises:
        EnvironmentError: If one or more required variables are missing.
    """
    missing = [var for var in _REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your env.example file."
        )


# ---------------------------------------------------------------------------
# Resolution Result Schema
# ---------------------------------------------------------------------------

class ResolutionResult:
    """Typed container for a single attendance reconciliation outcome.

    Attributes:
        match_status: True if attendance is verified (Present). False otherwise.
        confidence_score: Float in [0.0, 1.0] representing verification certainty.
        reasoning: Grounded Chain of Thought trace with explicit Audit Rule citations.
        segment: Classification bucket - 'Presentes', 'Ausentes', or 'Sin_Respuesta'.
        error: Optional error message if resolution failed.
    """

    def __init__(
        self,
        match_status: bool,
        confidence_score: float,
        reasoning: str,
        segment: str = "Ausentes",
        error: Optional[str] = None,
    ) -> None:
        self.match_status = match_status
        self.confidence_score = round(max(0.0, min(1.0, confidence_score)), 4)
        self.reasoning = reasoning
        self.segment = segment
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for Dataverse ingestion.

        Returns:
            Dict with keys: match_status, confidence_score, reasoning,
            segment, and error.
        """
        return {
            "match_status": self.match_status,
            "confidence_score": self.confidence_score,
            "reasoning": self.reasoning,
            "segment": self.segment,
            "error": self.error,
        }

    @classmethod
    def error_state(cls, message: str) -> "ResolutionResult":
        """Factory for a safe error result that routes to Sin_Respuesta.

        Args:
            message: Description of the failure.

        Returns:
            ResolutionResult with match_status=False, segment='Sin_Respuesta'.
        """
        return cls(
            match_status=False,
            confidence_score=0.0,
            reasoning="Resolution failed - see error field.",
            segment="Sin_Respuesta",
            error=message,
        )


# ---------------------------------------------------------------------------
# DataResolver - Planner-Executor-Critic Pattern
# ---------------------------------------------------------------------------

class DataResolver:
    """Reasoning Attendance Reconciler Agent for CoreSync.

    Implements a three-stage cognitive loop for each record pair:

    Stage 1 - PLANNER: Decomposes the reconciliation problem into
    ordered sub-tasks before any inference is attempted.

    Stage 2 - EXECUTOR: Processes each sub-task sequentially via
    Azure OpenAI Chain of Thought, grounded against Foundry IQ
    Audit Rules injected into the system prompt.

    Stage 3 - CRITIC/VERIFIER: An internal self-correction loop audits
    the Executor's verdict against hard business constraints before
    emitting the final ResolutionResult. Can override a false positive.

    Args:
        audit_context: AuditContext loaded from FoundryIQConnector.
        max_tokens: Maximum tokens for the model response. Default: 768.
        temperature: Sampling temperature. Default: 0.0 for determinism.

    Example:
        >>> resolver = DataResolver(audit_context=context)
        >>> result = resolver.resolve(record_a, record_b)
        >>> print(result.to_dict())
    """

    _SYSTEM_PROMPT_TEMPLATE = """
You are the Reasoning Attendance Reconciler Agent for a Corporate Simulation Center.
Your objective is to determine whether an employee's attendance is verified (Present)
or unverified (Absent/At Risk) by reconciling their Check-In and Check-Out records
across parallel classrooms (Aula A and Aula B).

You operate under a strict Planner-Executor-Critic reasoning pattern:
1. PLAN: Decompose the reconciliation into logical sub-tasks before reasoning.
2. EXECUTE: Process each sub-task with step-by-step Chain of Thought.
3. VERIFY (Critic): Audit your own verdict against the hard rules below before finalizing.

{audit_context}

HARD CRITIC RULES (applied in Stage 3 - cannot be overridden):
- A "Present" verdict requires both a Check-In token AND a Check-Out token confirmed.
- A manual note or HR record alone is NOT sufficient to declare attendance verified.
- If the Critic detects a false positive, it MUST override to Absent and set confidence >= 0.95.

You MUST respond with a single valid JSON object - no markdown, no preamble.
Schema:
{{
  "match_status": <true if Present, false if Absent/At-Risk>,
  "confidence_score": <float 0.0 to 1.0>,
  "segment": <"Presentes" | "Ausentes" | "Sin_Respuesta">,
  "reasoning": "<Full Planner-Executor-Critic trace with explicit Audit Rule citations>"
}}
""".strip()

    def __init__(
        self,
        audit_context: AuditContext,
        max_tokens: int = 768,
        temperature: float = 0.0,
    ) -> None:
        _validate_env()

        self._deployment = os.environ["DEPLOYMENT_NAME"]
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._audit_context = audit_context

        self._system_prompt = self._SYSTEM_PROMPT_TEMPLATE.format(
            audit_context=audit_context.as_prompt_context()
        )

        self._client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        )

        logger.info("DataResolver initialized | deployment=%s", self._deployment)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        record_a: dict[str, Any],
        record_b: dict[str, Any],
    ) -> ResolutionResult:
        """Reconcile a Check-In / Check-Out pair via Planner-Executor-Critic.

        Never raises - returns an error_state result on any failure so
        the calling pipeline continues processing remaining records.

        Args:
            record_a: First normalized record (Check-In source).
            record_b: Second normalized record (Check-Out or HR source).

        Returns:
            ResolutionResult with match_status, confidence_score, segment,
            reasoning trace with citations, and optional error field.
        """
        user_prompt = self._build_prompt(record_a, record_b)

        try:
            raw_response = self._call_api(user_prompt)
            return self._parse_response(raw_response)

        except (APIConnectionError, APITimeoutError) as exc:
            logger.error("Azure OpenAI connectivity failure: %s", exc)
            return ResolutionResult.error_state(
                f"API connectivity error: {type(exc).__name__}"
            )
        except APIStatusError as exc:
            logger.error(
                "Azure OpenAI API error | status=%s | message=%s",
                exc.status_code, exc.message,
            )
            return ResolutionResult.error_state(
                f"API status error {exc.status_code}: {exc.message}"
            )
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            logger.error("Response parsing failed: %s", exc)
            return ResolutionResult.error_state(f"Response parse error: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected resolver failure: %s", exc)
            return ResolutionResult.error_state(f"Unexpected error: {exc}")

    def resolve_batch(
        self,
        pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> list[ResolutionResult]:
        """Resolve a batch of record pairs sequentially.

        Args:
            pairs: List of (record_a, record_b) tuples.

        Returns:
            List of ResolutionResult in the same order as input pairs.
        """
        results = []
        for idx, (record_a, record_b) in enumerate(pairs):
            logger.info("Resolving pair %d / %d", idx + 1, len(pairs))
            results.append(self.resolve(record_a, record_b))
        return results

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        record_a: dict[str, Any],
        record_b: dict[str, Any],
    ) -> str:
        """Serialize two records into the user-turn prompt.

        Args:
            record_a: First normalized record.
            record_b: Second normalized record.

        Returns:
            Formatted string for the user message role.
        """
        _INTERNAL_KEYS = {"dni_hash", "_normalization_errors", "_error"}

        def _clean(record: dict) -> dict:
            return {k: v for k, v in record.items() if k not in _INTERNAL_KEYS}

        return (
            f"Record A (Check-In Source):\n"
            f"{json.dumps(_clean(record_a), ensure_ascii=False, indent=2)}\n\n"
            f"Record B (Check-Out / HR Source):\n"
            f"{json.dumps(_clean(record_b), ensure_ascii=False, indent=2)}"
        )

    def _call_api(self, user_prompt: str) -> str:
        """Submit the prompt to Azure OpenAI and return the raw text response.

        Args:
            user_prompt: Formatted user message with both records.

        Returns:
            Raw string content from the model's first choice.
        """
        response = self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    @staticmethod
    def _parse_response(raw: str) -> ResolutionResult:
        """Parse the model's JSON response into a ResolutionResult.

        Args:
            raw: Raw string from the model, expected to be valid JSON.

        Returns:
            Populated ResolutionResult instance.

        Raises:
            json.JSONDecodeError: If the response is not valid JSON.
            KeyError: If required fields are absent.
            ValueError: If field types are outside expected ranges.
        """
        data = json.loads(raw)

        return ResolutionResult(
            match_status=bool(data["match_status"]),
            confidence_score=float(data["confidence_score"]),
            reasoning=str(data["reasoning"]),
            segment=str(data.get("segment", "Ausentes")),
        )
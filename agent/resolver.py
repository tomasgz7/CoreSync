"""
resolver.py - CoreSync Conflict Resolution Module

Part of the autonomous agent architecture built for the
Microsoft Agents League Hackathon - Reasoning Agents Track.

This module consumes normalized records from `agent.normalizer` and
delegates conflict resolution to Azure OpenAI via a structured
Chain of Thought prompt. Results are returned as a standardized
JSON-compatible dict ready for Dataverse ingestion.
"""

import json
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from openai import AzureOpenAI, APIConnectionError, APIStatusError, APITimeoutError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment Loading
# ---------------------------------------------------------------------------

load_dotenv()  # Reads .env from project root; never commit that file.

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
            "Check your .env file."
        )


# ---------------------------------------------------------------------------
# Resolution Result Schema
# ---------------------------------------------------------------------------

class ResolutionResult:
    """Typed container for a single conflict resolution outcome.

    Attributes:
        match_status: True if both records refer to the same entity.
        confidence_score: Float in [0.0, 1.0] representing model certainty.
        reasoning: Human-readable explanation produced by the model.
        error: Optional error message if resolution failed.
    """

    def __init__(
        self,
        match_status: bool,
        confidence_score: float,
        reasoning: str,
        error: Optional[str] = None,
    ) -> None:
        self.match_status = match_status
        self.confidence_score = round(max(0.0, min(1.0, confidence_score)), 4)
        self.reasoning = reasoning
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for Dataverse ingestion.

        Returns:
            Dict with keys: match_status, confidence_score, reasoning, error.
        """
        return {
            "match_status": self.match_status,
            "confidence_score": self.confidence_score,
            "reasoning": self.reasoning,
            "error": self.error,
        }

    @classmethod
    def error_state(cls, message: str) -> "ResolutionResult":
        """Factory method for a safe error result that won't halt the pipeline.

        Args:
            message: Description of the failure.

        Returns:
            ResolutionResult with match_status=False, confidence=0.0.
        """
        return cls(
            match_status=False,
            confidence_score=0.0,
            reasoning="Resolution failed - see error field.",
            error=message,
        )


# ---------------------------------------------------------------------------
# DataResolver
# ---------------------------------------------------------------------------

class DataResolver:
    """Autonomous conflict resolution agent for CoreSync.

    Consumes pairs of normalized records (output of `DataNormalizer`)
    and submits them to Azure OpenAI with a structured Chain of Thought
    prompt. The model returns a JSON payload that is parsed and wrapped
    in a `ResolutionResult`.

    This class is designed to be instantiated once and reused across
    multiple `resolve()` calls within the Foundry IQ agent runtime.

    Args:
        max_tokens: Maximum tokens for the model response. Default: 512.
        temperature: Sampling temperature. Keep low (0.0-0.2) for
                     deterministic reasoning. Default: 0.0.

    Example:
        >>> resolver = DataResolver()
        >>> result = resolver.resolve(record_a, record_b)
        >>> print(result.to_dict())
    """

    _SYSTEM_PROMPT = """
You are a data reconciliation expert for an academic Simulation Center.
Your task is to determine whether two student records refer to the same person.

You will receive two normalized records in JSON format.
Reason step by step (Chain of Thought) before reaching a conclusion.

Consider: DNI match, name similarity (accounting for typos or encoding artifacts),
and any contextual fields provided.

You MUST respond with a single valid JSON object - no markdown, no explanation outside JSON.
Schema:
{
  "match_status": <true|false>,
  "confidence_score": <float 0.0 to 1.0>,
  "reasoning": "<concise explanation of your decision>"
}
""".strip()

    def __init__(
        self,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> None:
        _validate_env()

        self._deployment = os.environ["DEPLOYMENT_NAME"]
        self._max_tokens = max_tokens
        self._temperature = temperature

        self._client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        )

        logger.info(
            "DataResolver initialized | deployment=%s", self._deployment
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        record_a: dict[str, Any],
        record_b: dict[str, Any],
    ) -> ResolutionResult:
        """Resolve whether two normalized records represent the same entity.

        Builds a Chain of Thought prompt and submits it to Azure OpenAI.
        Parses the structured JSON response into a `ResolutionResult`.
        Never raises - returns an error_state result on any failure so
        the calling pipeline can continue processing remaining records.

        Args:
            record_a: First normalized record (output of DataNormalizer).
            record_b: Second normalized record (output of DataNormalizer).

        Returns:
            ResolutionResult with match_status, confidence_score, reasoning,
            and an optional error field populated on failure.

        Example:
            >>> result = resolver.resolve(
            ...     {"dni": "12345678", "name": "Garcia Juan"},
            ...     {"dni": "12345678", "name": "Garcia Juan P"},
            ... )
            >>> result.confidence_score
            0.97
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
                exc.status_code,
                exc.message,
            )
            return ResolutionResult.error_state(
                f"API status error {exc.status_code}: {exc.message}"
            )
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            logger.error("Response parsing failed: %s", exc)
            return ResolutionResult.error_state(
                f"Response parse error: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 - intentional broad catch
            logger.exception("Unexpected resolver failure: %s", exc)
            return ResolutionResult.error_state(f"Unexpected error: {exc}")

    def resolve_batch(
        self,
        pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> list[ResolutionResult]:
        """Resolve a batch of record pairs sequentially.

        Each pair is processed independently so a single failure does
        not abort the remaining resolutions.

        Args:
            pairs: List of (record_a, record_b) tuples.

        Returns:
            List of ResolutionResult in the same order as input pairs.

        Example:
            >>> results = resolver.resolve_batch([(a1, b1), (a2, b2)])
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
            Formatted string ready for the user message role.
        """
        # Strip internal pipeline fields before sending to the model
        _INTERNAL_KEYS = {"dni_hash", "_normalization_errors", "_error"}

        def _clean(record: dict) -> dict:
            return {k: v for k, v in record.items() if k not in _INTERNAL_KEYS}

        return (
            f"Record A:\n{json.dumps(_clean(record_a), ensure_ascii=False, indent=2)}\n\n"
            f"Record B:\n{json.dumps(_clean(record_b), ensure_ascii=False, indent=2)}"
        )

    def _call_api(self, user_prompt: str) -> str:
        """Submit the prompt to Azure OpenAI and return the raw text response.

        Args:
            user_prompt: Formatted user message containing both records.

        Returns:
            Raw string content from the model's first choice.

        Raises:
            APIConnectionError: On network-level failures.
            APIStatusError: On 4xx/5xx responses from Azure.
            APITimeoutError: On request timeout.
        """
        response = self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
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
            KeyError: If required fields are absent from the response.
            ValueError: If field types are outside expected ranges.
        """
        data = json.loads(raw)

        return ResolutionResult(
            match_status=bool(data["match_status"]),
            confidence_score=float(data["confidence_score"]),
            reasoning=str(data["reasoning"]),
        )

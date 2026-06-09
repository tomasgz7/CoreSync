"""
normalizer.py - CoreSync Data Normalization Module

Handles pre-processing of raw records before they enter the
Azure OpenAI reasoning layer via Microsoft Foundry IQ.
"""

import re
import unicodedata
import hashlib
from typing import Optional


class NormalizationError(Exception):
    """Raised when a critical normalization step fails."""
    pass


class DataNormalizer:
    """Stateless normalization utilities for CoreSync's ingestion pipeline.

    All methods are static and side-effect free, making this class safe
    for concurrent use within Foundry IQ's multi-threaded agent runtime.
    """

    # ------------------------------------------------------------------
    # DNI Normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_dni(raw: Optional[str]) -> Optional[str]:
        """Normalize an Argentine DNI to a clean 7-8 digit string.

        Strips dots, spaces, and any non-numeric character. Returns None
        for empty or non-recoverable inputs instead of raising, so the
        calling agent can decide how to handle the gap.

        Args:
            raw: Raw DNI string as received from the source system.
                 Examples: "12.345.678", " 12345678 ", "DNI: 12345678".

        Returns:
            Zero-padded 8-character numeric string (e.g. "12345678"),
            or None if the input cannot be reduced to a valid DNI.

        Example:
            >>> DataNormalizer.normalize_dni("12.345.678")
            '12345678'
            >>> DataNormalizer.normalize_dni(None)
            None
        """
        if not raw or not isinstance(raw, str):
            return None

        digits = re.sub(r"\D", "", raw.strip())

        if not digits:
            return None

        # Argentine DNIs are 7 or 8 digits
        if not (7 <= len(digits) <= 8):
            return None

        return digits.zfill(8)

    @staticmethod
    def hash_dni(normalized_dni: Optional[str]) -> Optional[str]:
        """Generate a SHA-256 hash of a normalized DNI for deduplication.

        Used to detect duplicate records across source systems without
        storing PII in intermediate pipeline stages.

        Args:
            normalized_dni: Output of `normalize_dni`. Must be an
                            8-digit numeric string.

        Returns:
            Hex-encoded SHA-256 digest string, or None if input is invalid.

        Example:
            >>> DataNormalizer.hash_dni("12345678")
            'ef797c8118f02dfb649607dd5d3f8c7623048c9c063d532cc95c5ed7a898a64f'
        """
        if not normalized_dni:
            return None

        return hashlib.sha256(normalized_dni.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Name Normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_name(raw: Optional[str]) -> Optional[str]:
        """Normalize a person's full name for consistent cross-system matching.

        Applies Unicode decomposition to strip diacritics, collapses
        whitespace, removes non-alphabetic characters, and converts to
        title case.

        Args:
            raw: Raw name string as received from the source system.
                 Examples: "  GARCIA, juan  ", "López Pérez, María".

        Returns:
            Title-cased, whitespace-normalized name string,
            or None if the input is empty or unrecoverable.

        Example:
            >>> DataNormalizer.normalize_name("  GARCÍA, juan  ")
            'Garcia Juan'
        """
        if not raw or not isinstance(raw, str):
            return None

        # Decompose unicode and strip diacritics (e.g. á -> a)
        nfkd = unicodedata.normalize("NFKD", raw)
        ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")

        # Remove non-alphabetic characters except spaces
        cleaned = re.sub(r"[^a-zA-Z\s]", " ", ascii_str)

        # Collapse multiple spaces and strip edges
        normalized = " ".join(cleaned.split()).title()

        return normalized if normalized else None

    # ------------------------------------------------------------------
    # Record-level Normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_record(record: dict) -> dict:
        """Apply full normalization pipeline to a raw ingestion record.

        Processes the `dni` and `name` fields in place and enriches the
        record with a `dni_hash` field for downstream deduplication.
        Unrecognized fields are passed through untouched.

        Args:
            record: Raw dict from a source system. Expected keys:
                    - `dni` (str): Raw DNI value.
                    - `name` (str): Raw full name.
                    Any additional keys are preserved as-is.

        Returns:
            Enriched dict with normalized `dni`, `name`, and new
            `dni_hash` field. A `_normalization_errors` list is appended
            if any field could not be processed.

        Raises:
            NormalizationError: If `record` is not a dict.

        Example:
            >>> DataNormalizer.normalize_record({"dni": "12.345.678", "name": "GARCIA juan"})
            {'dni': '12345678', 'name': 'Garcia Juan', 'dni_hash': '...', '_normalization_errors': []}
        """
        if not isinstance(record, dict):
            raise NormalizationError(
                f"Expected dict, got {type(record).__name__}"
            )

        result = record.copy()
        errors: list[str] = []

        # Normalize DNI
        raw_dni = result.get("dni")
        normalized_dni = DataNormalizer.normalize_dni(raw_dni)
        if normalized_dni is None and raw_dni is not None:
            errors.append(f"dni: could not normalize value '{raw_dni}'")
        result["dni"] = normalized_dni
        result["dni_hash"] = DataNormalizer.hash_dni(normalized_dni)

        # Normalize name
        raw_name = result.get("name")
        normalized_name = DataNormalizer.normalize_name(raw_name)
        if normalized_name is None and raw_name is not None:
            errors.append(f"name: could not normalize value '{raw_name}'")
        result["name"] = normalized_name

        result["_normalization_errors"] = errors

        return result

    # ------------------------------------------------------------------
    # Batch Processing
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_batch(
        records: list[dict],
        skip_on_error: bool = True,
    ) -> tuple[list[dict], list[dict]]:
        """Normalize a batch of raw records from the ingestion pipeline.

        Designed for high-throughput scenarios where Foundry IQ dispatches
        bulk payloads. Failed records are isolated rather than aborting
        the entire batch.

        Args:
            records: List of raw dicts to normalize.
            skip_on_error: If True, records that raise NormalizationError
                           are moved to the `failed` output list instead
                           of halting execution. Default: True.

        Returns:
            A tuple of (normalized, failed):
            - normalized: List of successfully processed records.
            - failed: List of dicts with the original record and an
                      `_error` key describing the failure.

        Example:
            >>> normalized, failed = DataNormalizer.normalize_batch(records)
            >>> print(f"OK: {len(normalized)} | Failed: {len(failed)}")
        """
        normalized: list[dict] = []
        failed: list[dict] = []

        for record in records:
            try:
                normalized.append(DataNormalizer.normalize_record(record))
            except NormalizationError as exc:
                if skip_on_error:
                    failed.append({**record, "_error": str(exc)})
                else:
                    raise

        return normalized, failed
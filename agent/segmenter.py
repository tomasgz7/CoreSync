"""
segmenter.py - CoreSync Data Segmenter & Enterprise Agent

Part of the autonomous multi-agent architecture built for the
Microsoft Agents League Hackathon - Reasoning Agents Track.

Consumes the certified output from the Reasoning Attendance Reconciler
Agent and partitions the corporate cohort into three strict semantic
collections: Presentes, Ausentes, and Sin_Respuesta.

Acts as the transactional business trigger layer:
- Presentes   -> fires Micro-Credential Issuance API
- Ausentes    -> injects severity metadata, routes to Engagement queue
- Sin_Respuesta -> isolates in DataGovernance critical log
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.resolver import ResolutionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Segmented Record Schema
# ---------------------------------------------------------------------------

@dataclass
class SegmentedRecord:
    """A single classified attendance record with action metadata.

    Attributes:
        employee_id: Normalized employee identifier.
        name: Normalized full name.
        certification_target: Target certification code (e.g. AZ-204-SIM).
        attendance_verified: True if attendance is confirmed Present.
        confidence_index: Confidence score from the Reconciler Agent.
        segment: Classification bucket.
        severity_flag: Risk flag for Ausentes and Sin_Respuesta records.
        action_triggered: Downstream action dispatched by this record.
        grounded_citation: Audit Rule citation from the Reconciler reasoning trace.
    """
    employee_id: str
    name: str
    certification_target: str
    attendance_verified: bool
    confidence_index: float
    segment: str
    severity_flag: str
    action_triggered: str
    grounded_citation: str


@dataclass
class SegmentationReport:
    """Full pipeline output artifact written to disk after Phase 3.

    Attributes:
        pipeline_id: Unique run identifier.
        timestamp: ISO 8601 UTC timestamp of report generation.
        total_processed_pairs: Number of record pairs submitted.
        execution_mode: 'DRY_RUN_SIMULATION' or 'LIVE'.
        presentes: List of verified attendance records.
        ausentes: List of unverified records with severity metadata.
        sin_respuesta: List of unresolvable or corrupted records.
    """
    pipeline_id: str
    timestamp: str
    total_processed_pairs: int
    execution_mode: str
    presentes: list[SegmentedRecord] = field(default_factory=list)
    ausentes: list[SegmentedRecord] = field(default_factory=list)
    sin_respuesta: list[SegmentedRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to the mandated output JSON structure.

        Returns:
            Dict matching the dataset_output_segmentado schema.
        """
        def _serialize(records: list[SegmentedRecord]) -> list[dict]:
            return [
                {
                    "employee_id": r.employee_id,
                    "name": r.name,
                    "certification_target": r.certification_target,
                    "attendance_verified": r.attendance_verified,
                    "confidence_index": r.confidence_index,
                    "severity_flag": r.severity_flag,
                    "action_triggered": r.action_triggered,
                    "grounded_citation": r.grounded_citation,
                }
                for r in records
            ]

        return {
            "generation_metadata": {
                "pipeline_id": self.pipeline_id,
                "timestamp": self.timestamp,
                "total_processed_pairs": self.total_processed_pairs,
                "execution_mode": self.execution_mode,
            },
            "segmentacion_matricula": {
                "Presentes": _serialize(self.presentes),
                "Ausentes": _serialize(self.ausentes),
                "Sin_Respuesta": _serialize(self.sin_respuesta),
            },
        }


# ---------------------------------------------------------------------------
# DataSegmenter
# ---------------------------------------------------------------------------

class DataSegmenter:
    """Data Segmenter & Enterprise Agent for CoreSync.

    Consumes ResolutionResult objects from the Reconciler Agent and
    classifies them into the three mandatory business collections.
    Enriches each record with action metadata and severity flags before
    writing the final segmentation artifact to disk.

    Args:
        execution_mode: 'DRY_RUN_SIMULATION' or 'LIVE'. Default: 'DRY_RUN_SIMULATION'.
        output_path: Optional path to write the output JSON artifact.

    Example:
        >>> segmenter = DataSegmenter()
        >>> report = segmenter.segment(pairs, results)
        >>> segmenter.write_report(report, Path("data/output_segmentado.json"))
    """

    # Action constants
    _ACTION_CREDENTIAL  = "EMIT_MICRO_CREDENTIAL_API_V1"
    _ACTION_ENGAGEMENT  = "ROUTE_TO_ENGAGEMENT_QUEUE"
    _ACTION_GOVERNANCE  = "ISOLATE_IN_CRITICAL_LOG"

    # Severity flags
    _SEVERITY_NONE      = "NONE"
    _SEVERITY_SKILL_GAP = "HIGH_SKILL_GAP_RISK"
    _SEVERITY_CORRUPT   = "DATA_GOVERNANCE_ESCALATION"
    _SEVERITY_ANOMALY   = "ATTENDANCE_ANOMALY_RISK"

    def __init__(
        self,
        execution_mode: str = "DRY_RUN_SIMULATION",
    ) -> None:
        self._execution_mode = execution_mode
        logger.info(
            "DataSegmenter initialized | execution_mode=%s", execution_mode
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def segment(
        self,
        pairs: list[tuple[dict[str, Any], dict[str, Any]]],
        results: list[ResolutionResult],
        pipeline_id: str = "CoreSync-SimulationCenter-Run",
    ) -> SegmentationReport:
        """Classify resolved pairs into the three business collections.

        Iterates over (pair, result) tuples, applies classification logic,
        enriches each record with action and severity metadata, and returns
        a fully populated SegmentationReport.

        Args:
            pairs: List of (record_a, record_b) tuples from the pipeline.
            results: List of ResolutionResult from the Reconciler Agent.
                     Must be the same length and order as pairs.
            pipeline_id: Identifier for this pipeline run.

        Returns:
            SegmentationReport with all three collections populated.

        Raises:
            ValueError: If pairs and results have different lengths.
        """
        if len(pairs) != len(results):
            raise ValueError(
                f"pairs ({len(pairs)}) and results ({len(results)}) "
                "must have the same length."
            )

        report = SegmentationReport(
            pipeline_id=pipeline_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_processed_pairs=len(pairs),
            execution_mode=self._execution_mode,
        )

        for (rec_a, rec_b), result in zip(pairs, results):
            segmented = self._classify(rec_a, rec_b, result)

            if segmented.segment == "Presentes":
                report.presentes.append(segmented)
                logger.info(
                    "Segmented %s -> Presentes | action=%s",
                    segmented.employee_id, segmented.action_triggered,
                )
            elif segmented.segment == "Ausentes":
                report.ausentes.append(segmented)
                logger.info(
                    "Segmented %s -> Ausentes | severity=%s",
                    segmented.employee_id, segmented.severity_flag,
                )
            else:
                report.sin_respuesta.append(segmented)
                logger.warning(
                    "Segmented %s -> Sin_Respuesta | severity=%s",
                    segmented.employee_id, segmented.severity_flag,
                )

        logger.info(
            "Segmentation complete | Presentes=%d | Ausentes=%d | Sin_Respuesta=%d",
            len(report.presentes),
            len(report.ausentes),
            len(report.sin_respuesta),
        )

        return report

    def write_report(
        self,
        report: SegmentationReport,
        output_path: Path,
    ) -> None:
        """Write the segmentation report artifact to disk.

        Args:
            report: Populated SegmentationReport instance.
            output_path: Destination path for the JSON artifact.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("Segmentation report written to %s", output_path)

    # ------------------------------------------------------------------
    # Private Classification Logic
    # ------------------------------------------------------------------

    def _classify(
        self,
        rec_a: dict[str, Any],
        rec_b: dict[str, Any],
        result: ResolutionResult,
    ) -> SegmentedRecord:
        """Apply classification and enrichment logic to a single resolved pair.

        Args:
            rec_a: First normalized record.
            rec_b: Second normalized record.
            result: Resolution outcome from the Reconciler Agent.

        Returns:
            SegmentedRecord with segment, action, severity, and citation.
        """
        employee_id = rec_a.get("employee_id") or rec_b.get("employee_id") or "UNKNOWN"
        name = rec_a.get("name") or rec_b.get("name") or "Unknown Participant"
        certification = rec_a.get("certification_target", "N/A")

        # Extract citation from reasoning trace
        grounded_citation = self._extract_citation(result.reasoning)

        # Corrupted / unresolvable -> Sin_Respuesta
        if result.error or result.segment == "Sin_Respuesta":
            return SegmentedRecord(
                employee_id=employee_id,
                name=name,
                certification_target=certification,
                attendance_verified=False,
                confidence_index=result.confidence_score,
                segment="Sin_Respuesta",
                severity_flag=self._SEVERITY_CORRUPT,
                action_triggered=self._ACTION_GOVERNANCE,
                grounded_citation=grounded_citation,
            )

        # Present -> Presentes
        if result.match_status:
            return SegmentedRecord(
                employee_id=employee_id,
                name=name,
                certification_target=certification,
                attendance_verified=True,
                confidence_index=result.confidence_score,
                segment="Presentes",
                severity_flag=self._SEVERITY_NONE,
                action_triggered=self._ACTION_CREDENTIAL,
                grounded_citation=grounded_citation,
            )

        # Absent -> Ausentes with severity enrichment
        severity = self._assess_severity(rec_a, rec_b, result)
        return SegmentedRecord(
            employee_id=employee_id,
            name=name,
            certification_target=certification,
            attendance_verified=False,
            confidence_index=result.confidence_score,
            segment="Ausentes",
            severity_flag=severity,
            action_triggered=self._ACTION_ENGAGEMENT,
            grounded_citation=grounded_citation,
        )

    @staticmethod
    def _extract_citation(reasoning: str) -> str:
        """Extract the grounded citation block from a reasoning trace.

        Args:
            reasoning: Full reasoning string from ResolutionResult.

        Returns:
            Extracted citation string, or a fallback label.
        """
        import re
        match = re.search(r"\[Grounded on:[^\]]+\]", reasoning)
        return match.group(0) if match else "[Grounded on: Foundry IQ Audit Rules]"

    @staticmethod
    def _assess_severity(
        rec_a: dict[str, Any],
        rec_b: dict[str, Any],
        result: ResolutionResult,
    ) -> str:
        """Determine severity flag for an Ausentes record.

        High confidence absences with missing Check-Out tokens are
        flagged as HIGH_SKILL_GAP_RISK. Lower confidence or anomalous
        records are flagged as ATTENDANCE_ANOMALY_RISK.

        Args:
            rec_a: First normalized record.
            rec_b: Second normalized record.
            result: Resolution outcome.

        Returns:
            Severity flag string.
        """
        notes_combined = (
            str(rec_a.get("notes", "")).lower()
            + str(rec_b.get("notes", "")).lower()
        )
        has_checkout_token = "checkout token" in notes_combined
        high_confidence_absence = result.confidence_score >= 0.85

        if high_confidence_absence and not has_checkout_token:
            return "HIGH_SKILL_GAP_RISK"
        return "ATTENDANCE_ANOMALY_RISK"
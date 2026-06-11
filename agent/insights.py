"""
insights.py - CoreSync Manager Insights Agent

Part of the autonomous multi-agent architecture built for the
Microsoft Agents League Hackathon - Reasoning Agents Track.

Aggregates the segmented attendance dataset and outreach logs into
executive-level analytics: institutional workforce readiness,
absenteeism trends per certification track, capability gap closing
indices, and engagement queue load. All output is abstracted to
aggregate counts and rates - no individual employee identifiers are
surfaced in the executive report, eliminating PII from leadership-facing
artifacts and driving operational reporting latency to zero.
"""

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.engagement import OutreachLog
from agent.segmenter import SegmentationReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Executive Insights Schema
# ---------------------------------------------------------------------------

@dataclass
class CertificationReadiness:
    """Aggregated readiness metrics for a single certification track.

    Attributes:
        certification_target: Certification code (e.g. AZ-204-SIM).
        total_candidates: Total candidates evaluated for this track.
        verified_present: Count of verified Present candidates.
        at_risk: Count of Ausentes candidates.
        unresolved: Count of Sin_Respuesta candidates.
        readiness_index: Ratio of verified_present to total_candidates.
    """
    certification_target: str
    total_candidates: int
    verified_present: int
    at_risk: int
    unresolved: int
    readiness_index: float


@dataclass
class ExecutiveInsightsReport:
    """Executive-level analytics artifact for leadership consumption.

    Attributes:
        pipeline_id: Identifier of the source pipeline run.
        timestamp: ISO 8601 UTC generation timestamp.
        execution_mode: 'DRY_RUN_SIMULATION' or 'LIVE'.
        total_cohort_size: Total number of evaluated candidate pairs.
        attendance_verified_count: Total Presentes count.
        absenteeism_count: Total Ausentes count.
        unresolved_count: Total Sin_Respuesta count.
        absenteeism_rate: Ausentes / total_cohort_size.
        escalation_rate: Sin_Respuesta / total_cohort_size.
        overall_readiness_index: Aggregate certification readiness across all tracks.
        certification_breakdown: Per-track CertificationReadiness list.
        severity_distribution: Counts of each severity_flag observed.
        engagement_queue_size: Number of records routed to the Engagement Agent.
        engagement_channel_distribution: Counts per outreach delivery channel.
        operational_report_latency_seconds: Time elapsed generating this report.
    """
    pipeline_id: str
    timestamp: str
    execution_mode: str
    total_cohort_size: int
    attendance_verified_count: int
    absenteeism_count: int
    unresolved_count: int
    absenteeism_rate: float
    escalation_rate: float
    overall_readiness_index: float
    certification_breakdown: list[CertificationReadiness] = field(default_factory=list)
    severity_distribution: dict[str, int] = field(default_factory=dict)
    engagement_queue_size: int = 0
    engagement_channel_distribution: dict[str, int] = field(default_factory=dict)
    operational_report_latency_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to a JSON-compatible dict.

        Returns:
            Dict representation suitable for Power BI / Fabric consumption.
            Contains zero individual employee identifiers (PII-abstracted).
        """
        return {
            "generation_metadata": {
                "pipeline_id": self.pipeline_id,
                "timestamp": self.timestamp,
                "execution_mode": self.execution_mode,
                "operational_report_latency_seconds": self.operational_report_latency_seconds,
                "pii_abstracted": True,
            },
            "workforce_readiness_summary": {
                "total_cohort_size": self.total_cohort_size,
                "attendance_verified_count": self.attendance_verified_count,
                "absenteeism_count": self.absenteeism_count,
                "unresolved_count": self.unresolved_count,
                "absenteeism_rate": round(self.absenteeism_rate, 4),
                "escalation_rate": round(self.escalation_rate, 4),
                "overall_readiness_index": round(self.overall_readiness_index, 4),
            },
            "certification_breakdown": [
                {
                    "certification_target": c.certification_target,
                    "total_candidates": c.total_candidates,
                    "verified_present": c.verified_present,
                    "at_risk": c.at_risk,
                    "unresolved": c.unresolved,
                    "readiness_index": round(c.readiness_index, 4),
                }
                for c in self.certification_breakdown
            ],
            "severity_distribution": self.severity_distribution,
            "engagement_summary": {
                "queue_size": self.engagement_queue_size,
                "channel_distribution": self.engagement_channel_distribution,
            },
        }


# ---------------------------------------------------------------------------
# ManagerInsightsAgent
# ---------------------------------------------------------------------------

class ManagerInsightsAgent:
    """Manager Insights Agent for CoreSync.

    Aggregates real-time segmented attendance data and outreach logs into
    executive-level analytics concerning institutional workforce readiness,
    absenteeism trends across certification tracks, and capability gap
    closing indices.

    All employee identifiers are deliberately excluded from the output -
    only aggregate counts, rates, and per-track breakdowns are surfaced,
    delivering a PII-free artifact optimized for leadership decision-making.

    Example:
        >>> agent = ManagerInsightsAgent()
        >>> insights = agent.generate(report, outreach_logs)
        >>> agent.write_report(insights, Path("data/manager_insights.json"))
    """

    def generate(
        self,
        report: SegmentationReport,
        outreach_logs: list[OutreachLog],
    ) -> ExecutiveInsightsReport:
        """Aggregate the segmentation report into executive insights.

        Args:
            report: SegmentationReport from the Data Segmenter & Enterprise Agent.
            outreach_logs: OutreachLog list from the Contextual Engagement Agent.

        Returns:
            Populated ExecutiveInsightsReport with PII-abstracted aggregates.
        """
        start = datetime.now(timezone.utc)

        total = report.total_processed_pairs
        present_count = len(report.presentes)
        absent_count = len(report.ausentes)
        unresolved_count = len(report.sin_respuesta)

        absenteeism_rate = absent_count / total if total else 0.0
        escalation_rate = unresolved_count / total if total else 0.0
        overall_readiness = present_count / total if total else 0.0

        certification_breakdown = self._build_certification_breakdown(report)
        severity_distribution = self._build_severity_distribution(report)
        channel_distribution = self._build_channel_distribution(outreach_logs)

        end = datetime.now(timezone.utc)
        latency = (end - start).total_seconds()

        insights = ExecutiveInsightsReport(
            pipeline_id=report.pipeline_id,
            timestamp=end.isoformat(),
            execution_mode=report.execution_mode,
            total_cohort_size=total,
            attendance_verified_count=present_count,
            absenteeism_count=absent_count,
            unresolved_count=unresolved_count,
            absenteeism_rate=absenteeism_rate,
            escalation_rate=escalation_rate,
            overall_readiness_index=overall_readiness,
            certification_breakdown=certification_breakdown,
            severity_distribution=severity_distribution,
            engagement_queue_size=len(outreach_logs),
            engagement_channel_distribution=channel_distribution,
            operational_report_latency_seconds=latency,
        )

        logger.info(
            "Executive insights generated | cohort=%d | readiness=%.2f | "
            "absenteeism=%.2f | escalation=%.2f | latency=%.6fs",
            total, overall_readiness, absenteeism_rate, escalation_rate, latency,
        )

        return insights

    def write_report(
        self,
        insights: ExecutiveInsightsReport,
        output_path: Path,
    ) -> None:
        """Write the executive insights artifact to disk.

        Args:
            insights: Populated ExecutiveInsightsReport instance.
            output_path: Destination path for the JSON artifact.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(insights.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("Executive insights report written to %s", output_path)

    # ------------------------------------------------------------------
    # Private Aggregation Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_certification_breakdown(
        report: SegmentationReport,
    ) -> list[CertificationReadiness]:
        """Group all segmented records by certification_target and compute
        per-track readiness metrics.

        Args:
            report: SegmentationReport with all three collections populated.

        Returns:
            List of CertificationReadiness, one per distinct certification target.
        """
        tracks: dict[str, dict[str, int]] = defaultdict(
            lambda: {"present": 0, "absent": 0, "unresolved": 0}
        )

        for rec in report.presentes:
            tracks[rec.certification_target]["present"] += 1
        for rec in report.ausentes:
            tracks[rec.certification_target]["absent"] += 1
        for rec in report.sin_respuesta:
            tracks[rec.certification_target]["unresolved"] += 1

        breakdown = []
        for target, counts in sorted(tracks.items()):
            total = counts["present"] + counts["absent"] + counts["unresolved"]
            readiness = counts["present"] / total if total else 0.0
            breakdown.append(
                CertificationReadiness(
                    certification_target=target,
                    total_candidates=total,
                    verified_present=counts["present"],
                    at_risk=counts["absent"],
                    unresolved=counts["unresolved"],
                    readiness_index=readiness,
                )
            )
        return breakdown

    @staticmethod
    def _build_severity_distribution(report: SegmentationReport) -> dict[str, int]:
        """Count occurrences of each severity_flag across Ausentes and
        Sin_Respuesta collections.

        Args:
            report: SegmentationReport with all three collections populated.

        Returns:
            Dict mapping severity_flag to occurrence count.
        """
        counter: Counter[str] = Counter()
        for rec in report.ausentes:
            counter[rec.severity_flag] += 1
        for rec in report.sin_respuesta:
            counter[rec.severity_flag] += 1
        return dict(counter)

    @staticmethod
    def _build_channel_distribution(outreach_logs: list[OutreachLog]) -> dict[str, int]:
        """Count outreach logs per delivery channel.

        Args:
            outreach_logs: OutreachLog list from the Engagement Agent.

        Returns:
            Dict mapping delivery_channel to occurrence count.
        """
        counter: Counter[str] = Counter(log.delivery_channel for log in outreach_logs)
        return dict(counter)
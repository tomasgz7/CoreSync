"""
engagement.py - CoreSync Contextual Engagement Agent

Part of the autonomous multi-agent architecture built for the
Microsoft Agents League Hackathon - Reasoning Agents Track.

Consumes the 'Ausentes' segment from the Data Segmenter & Enterprise
Agent and Work IQ activity signals to design a non-intrusive outreach
strategy. Instead of mass notifications, this agent determines the
optimal, least-disruptive contact window per employee based on
calendar availability, meeting density, and focus block signals.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent.normalizer import DataNormalizer
from agent.segmenter import SegmentedRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Work IQ Signal Schema
# ---------------------------------------------------------------------------

@dataclass
class WorkActivitySignal:
    """Work IQ activity signal for a single employee.

    Attributes:
        employee_id: Normalized employee identifier.
        role: Job role, used for severity weighting downstream.
        meeting_hours_per_week: Total weekly meeting load.
        focus_hours_per_week: Total weekly uninterrupted focus time.
        preferred_learning_slot: Employee-declared preferred time block.
        workload_stress_index: 'HIGH', 'MEDIUM', or 'LOW'.
        m365_status_signal: Real-time presence signal from Microsoft 365.
    """
    employee_id: str
    role: str
    meeting_hours_per_week: int
    focus_hours_per_week: int
    preferred_learning_slot: str
    workload_stress_index: str
    m365_status_signal: str


# ---------------------------------------------------------------------------
# Outreach Log Schema
# ---------------------------------------------------------------------------

@dataclass
class OutreachLog:
    """A single tailored outreach decision for an Ausentes record.

    Attributes:
        employee_id: Normalized employee identifier.
        certification_target: Certification the outreach pertains to.
        severity_flag: Severity inherited from the Segmenter Agent.
        delivery_channel: Notification channel (Teams, Outlook, Digest).
        optimal_window: Recommended delivery time window.
        m365_status_considered: M365 presence signal at decision time.
        message_tone: Tone classification for the outreach message.
        reasoning: Explanation of the window selection logic with citation.
    """
    employee_id: str
    certification_target: str
    severity_flag: str
    delivery_channel: str
    optimal_window: str
    m365_status_considered: str
    message_tone: str
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict.

        Returns:
            Dict representation of the outreach log entry.
        """
        return {
            "employee_id": self.employee_id,
            "certification_target": self.certification_target,
            "severity_flag": self.severity_flag,
            "delivery_channel": self.delivery_channel,
            "optimal_window": self.optimal_window,
            "m365_status_considered": self.m365_status_considered,
            "message_tone": self.message_tone,
            "reasoning": self.reasoning,
        }


# ---------------------------------------------------------------------------
# ContextualEngagementAgent
# ---------------------------------------------------------------------------

class ContextualEngagementAgent:
    """Contextual Engagement Agent for CoreSync.

    Focuses exclusively on the 'Ausentes' cohort. Loads Work IQ activity
    signals and determines the optimal, least-intrusive notification
    window per employee, respecting cognitive load boundaries while
    ensuring alignment with certification deadlines.

    Default fallback policy: when no Work IQ signal is available for an
    employee, a conservative 'Next_Business_Day_09:00' window is assigned
    via the Outlook digest channel - never an immediate interruption.

    Args:
        signals_path: Path to the work_activity_signals.json fixture.

    Example:
        >>> agent = ContextualEngagementAgent(signals_path)
        >>> logs = agent.process(report.ausentes)
    """

    _DEFAULT_WINDOW = "Next_Business_Day_09:00"
    _DEFAULT_CHANNEL = "Outlook_Digest"

    def __init__(self, signals_path: Path) -> None:
        self._signals: dict[str, WorkActivitySignal] = self._load_signals(signals_path)
        logger.info(
            "ContextualEngagementAgent initialized | signals_loaded=%d",
            len(self._signals),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        ausentes: list[SegmentedRecord],
    ) -> list[OutreachLog]:
        """Generate tailored outreach logs for the Ausentes cohort.

        Args:
            ausentes: List of SegmentedRecord classified as Ausentes by
                      the Data Segmenter & Enterprise Agent.

        Returns:
            List of OutreachLog entries, one per Ausentes record.
        """
        logs = []
        for record in ausentes:
            signal = self._signals.get(record.employee_id)
            log = self._build_outreach_log(record, signal)
            logs.append(log)
            logger.info(
                "Outreach planned | employee=%s | window=%s | channel=%s",
                log.employee_id, log.optimal_window, log.delivery_channel,
            )
        return logs

    def write_logs(self, logs: list[OutreachLog], output_path: Path) -> None:
        """Write outreach logs to disk as a JSON artifact.

        Args:
            logs: List of OutreachLog entries.
            output_path: Destination path for the JSON artifact.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump([log.to_dict() for log in logs], f, ensure_ascii=False, indent=2)
        logger.info("Outreach logs written to %s", output_path)

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_signals(path: Path) -> dict[str, WorkActivitySignal]:
        """Load Work IQ activity signals indexed by employee_id.

        Args:
            path: Path to the work_activity_signals.json fixture.

        Returns:
            Dict mapping employee_id to WorkActivitySignal. Returns an
            empty dict if the file is missing, allowing the agent to
            fall back to default outreach windows.
        """
        if not path.exists():
            logger.warning(
                "Work IQ signals file not found at %s - using fallback "
                "outreach policy for all records.", path,
            )
            return {}

        with path.open(encoding="utf-8") as f:
            raw = json.load(f)

        # Index by normalized Employee ID (Audit Rule #5 format) so that
        # lookups from SegmentedRecord.employee_id - which is normalized by
        # the Curator Agent - resolve correctly regardless of the hyphenation
        # used in the Work IQ fixture (e.g. "EMP-9014" -> "EMP9014").
        return {
            DataNormalizer.normalize_employee_id(item["employee_id"]): WorkActivitySignal(**item)
            for item in raw
        }

    def _build_outreach_log(
        self,
        record: SegmentedRecord,
        signal: Optional[WorkActivitySignal],
    ) -> OutreachLog:
        """Determine the outreach strategy for a single Ausentes record.

        Decision logic:
          - No Work IQ signal available: conservative default window via
            Outlook digest, supportive tone.
          - HIGH workload_stress_index: defer to the employee's declared
            preferred_learning_slot, low-intrusion tone, grounded on
            Audit Rule #2 (Workload Anomaly Allowance).
          - m365_status_signal == 'InAMeeting': queue for the next
            available slot rather than interrupting in real time.
          - LOW/MEDIUM stress with 'Available' status: immediate Teams
            notification is appropriate.

        Args:
            record: SegmentedRecord from the Ausentes collection.
            signal: Matching WorkActivitySignal, or None if unavailable.

        Returns:
            Populated OutreachLog instance.
        """
        if signal is None:
            return OutreachLog(
                employee_id=record.employee_id,
                certification_target=record.certification_target,
                severity_flag=record.severity_flag,
                delivery_channel=self._DEFAULT_CHANNEL,
                optimal_window=self._DEFAULT_WINDOW,
                m365_status_considered="UNKNOWN",
                message_tone="Supportive - General Reminder",
                reasoning=(
                    "No Work IQ activity signal available for this employee. "
                    "Applying conservative default policy: low-frequency Outlook "
                    "digest scheduled for the next business day to avoid "
                    "uninvited real-time interruptions."
                ),
            )

        # High workload -> defer to preferred slot, low-intrusion tone
        if signal.workload_stress_index == "HIGH" or signal.meeting_hours_per_week > 20:
            return OutreachLog(
                employee_id=record.employee_id,
                certification_target=record.certification_target,
                severity_flag=record.severity_flag,
                delivery_channel="Outlook_Digest",
                optimal_window=signal.preferred_learning_slot,
                m365_status_considered=signal.m365_status_signal,
                message_tone="Low-Intrusion - Deferred Reminder",
                reasoning=(
                    f"Employee {record.employee_id} has workload_stress_index="
                    f"{signal.workload_stress_index} with "
                    f"{signal.meeting_hours_per_week}h of weekly meetings "
                    f"({signal.focus_hours_per_week}h focus time available). "
                    f"Per Audit Rule #2 - Workload Anomaly Allowance, immediate "
                    f"notification is suppressed. Outreach deferred to the "
                    f"employee's declared preferred slot: "
                    f"{signal.preferred_learning_slot}, delivered as a "
                    f"low-priority Outlook digest to respect cognitive load "
                    f"boundaries while preserving certification deadline alignment."
                ),
            )

        # Currently in a meeting -> queue, do not interrupt
        if signal.m365_status_signal == "InAMeeting":
            return OutreachLog(
                employee_id=record.employee_id,
                certification_target=record.certification_target,
                severity_flag=record.severity_flag,
                delivery_channel="Teams_Queued",
                optimal_window=signal.preferred_learning_slot,
                m365_status_considered=signal.m365_status_signal,
                message_tone="Neutral - Queued Reminder",
                reasoning=(
                    f"Employee {record.employee_id} is currently 'InAMeeting' "
                    f"per Work IQ M365 status signal. Real-time Teams "
                    f"notification is queued rather than dispatched immediately, "
                    f"and will surface at the employee's preferred slot "
                    f"({signal.preferred_learning_slot}) to avoid disrupting "
                    f"active work."
                ),
            )

        # Low/medium stress, available -> immediate Teams notification
        return OutreachLog(
            employee_id=record.employee_id,
            certification_target=record.certification_target,
            severity_flag=record.severity_flag,
            delivery_channel="Teams_Immediate",
            optimal_window="Immediate",
            m365_status_considered=signal.m365_status_signal,
            message_tone="Direct - Action Required",
            reasoning=(
                f"Employee {record.employee_id} shows "
                f"workload_stress_index={signal.workload_stress_index} with "
                f"{signal.focus_hours_per_week}h of available focus time and "
                f"M365 status '{signal.m365_status_signal}'. No anomaly "
                f"allowance applies under Audit Rule #2. Cognitive load "
                f"permits an immediate, direct Teams notification requesting "
                f"completion of the missing certification checkout step."
            ),
        )
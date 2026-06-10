"""
foundry.py - CoreSync Foundry IQ Connector

Part of the autonomous multi-agent architecture built for the
Microsoft Agents League Hackathon - Reasoning Agents Track.

Simulates retrieval of grounded corporate audit directives from a
Microsoft Foundry IQ indexed Knowledge Base. Rules are numbered and
titled so the Reasoning Agent can produce explicit citations in its
Planner-Executor-Critic output, enabling auditable, traceable decisions.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy Schema
# ---------------------------------------------------------------------------

@dataclass
class AuditRule:
    """A single numbered audit directive retrieved from Foundry IQ.

    Attributes:
        rule_number: Sequential identifier used for downstream citation.
        title: Short descriptive title for display and logging.
        description: Full rule text injected into the reasoning prompt.
        match_threshold: Minimum confidence to auto-approve attendance.
        escalation_threshold: Scores below this trigger manual review.
        active: Whether this rule is currently enforced.
        metadata: Extensibility bag for versioning and ownership.
    """
    rule_number: int
    title: str
    description: str
    match_threshold: float
    escalation_threshold: float
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def citation_label(self) -> str:
        """Return the canonical citation string for reasoning traces.

        Returns:
            String formatted as 'Audit Rule #N - Title'.
        """
        return f"Audit Rule #{self.rule_number} - {self.title}"


@dataclass
class AuditContext:
    """Aggregated grounded context injected into the reasoning pipeline.

    Attributes:
        rules: List of AuditRule directives.
        domain_policies: High-level organizational attendance policies.
        source_system_trust: Trust coefficient per source system.
    """
    rules: list[AuditRule]
    domain_policies: list[str]
    source_system_trust: dict[str, float]

    def active_rules(self) -> list[AuditRule]:
        """Return only the currently active rules."""
        return [r for r in self.rules if r.active]

    def get_rule(self, rule_number: int) -> AuditRule | None:
        """Retrieve a specific rule by number.

        Args:
            rule_number: The rule number to look up.

        Returns:
            Matching AuditRule or None if not found.
        """
        return next(
            (r for r in self.rules if r.rule_number == rule_number), None
        )

    def as_prompt_context(self) -> str:
        """Serialize audit context into a prompt-injectable string.

        Returns:
            Structured multi-line string for system prompt injection.
        """
        active = self.active_rules()
        lines = [
            "=" * 60,
            "FOUNDRY IQ - GROUNDED ATTENDANCE AUDIT CONTEXT",
            "Source: Corporate Simulation Center Governance Knowledge Base",
            f"Active Rules: {len(active)} | Total Loaded: {len(self.rules)}",
            "=" * 60,
            "",
            "[ ACTIVE AUDIT RULES ]",
        ]

        for rule in active:
            lines.append(f"  {rule.citation_label()}")
            lines.append(f"    {rule.description}")
            lines.append(
                f"    Thresholds: auto-approve >= {rule.match_threshold} | "
                f"escalate < {rule.escalation_threshold}"
            )
            lines.append("")

        lines.append("[ DOMAIN POLICIES ]")
        for policy in self.domain_policies:
            lines.append(f"  * {policy}")

        lines.append("")
        lines.append("[ SOURCE SYSTEM TRUST COEFFICIENTS ]")
        for system, trust in self.source_system_trust.items():
            bar = "#" * int(trust * 10)
            lines.append(f"  {system:<35} {trust:.2f}  [{bar}]")

        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FoundryIQConnector
# ---------------------------------------------------------------------------

class FoundryIQConnector:
    """Simulated connector to Microsoft Foundry IQ Knowledge Base.

    Retrieves grounded attendance audit rules governing identity matching
    and certification attendance verification in a Corporate Simulation
    Center. The numbered rule format enables explicit citations in the
    Reasoning Agent's Planner-Executor-Critic output trace.

    Args:
        environment: Deployment environment. Accepts 'dev', 'staging', 'prod'.

    Example:
        >>> connector = FoundryIQConnector(environment="dev")
        >>> context = connector.fetch_audit_context()
        >>> print(context.as_prompt_context())
    """

    _RULE_FIXTURES: dict[str, list[dict[str, Any]]] = {
        "dev": [
            {
                "rule_number": 1,
                "title": "Strict Attendance Pass - Dual Token Requirement",
                "description": (
                    "Attendance is verified ONLY when both a digital Check-In token "
                    "and a digital Check-Out token are confirmed across any combination "
                    "of Aula A and Aula B form submissions. A Check-In record without "
                    "a corresponding Check-Out is insufficient for a Present verdict "
                    "regardless of any manual HR annotation."
                ),
                "match_threshold": 0.95,
                "escalation_threshold": 0.70,
                "active": True,
                "metadata": {"owner": "CertificationIntegrityBoard", "version": "3.0"},
            },
            {
                "rule_number": 2,
                "title": "Workload Anomaly Allowance",
                "description": (
                    "If a missing Check-Out is correlated with a workload_stress_index "
                    "of HIGH (meeting_hours_per_week > 20) retrieved via Work IQ signals, "
                    "the absence severity is reduced from CRITICAL to AT_RISK. "
                    "Confidence is capped at 0.65. The record is routed to the "
                    "Engagement Agent for contextual follow-up rather than immediate "
                    "DataGovernance escalation."
                ),
                "match_threshold": 0.65,
                "escalation_threshold": 0.40,
                "active": True,
                "metadata": {"owner": "HROperationsTeam", "version": "2.1"},
            },
            {
                "rule_number": 3,
                "title": "Clean Performance Validation - Perfect Score",
                "description": (
                    "Records where practice_score equals 100 and both Check-In and "
                    "Check-Out tokens are confirmed must receive a confidence score "
                    "of 0.97 or higher and be auto-approved as Present with no "
                    "manual review required. The Micro-Credential Issuance API must "
                    "be triggered immediately upon segmentation."
                ),
                "match_threshold": 0.97,
                "escalation_threshold": 0.85,
                "active": True,
                "metadata": {"owner": "AutomationTeam", "version": "1.2"},
            },
            {
                "rule_number": 4,
                "title": "Corrupted Record Isolation Protocol",
                "description": (
                    "Any record where the name field matches the pattern '%%*%%' "
                    "or the employee_id normalization produces an empty string must "
                    "be immediately classified as Sin_Respuesta and routed to the "
                    "DataGovernance critical log. These records must NOT be passed "
                    "to the Reasoning Agent and must never trigger credential issuance."
                ),
                "match_threshold": 0.00,
                "escalation_threshold": 0.00,
                "active": True,
                "metadata": {"owner": "DataGovernance", "version": "1.4"},
            },
            {
                "rule_number": 5,
                "title": "Employee ID Cross-System Normalization",
                "description": (
                    "Employee IDs from SYS-FORM-AULA-A and SYS-FORM-AULA-B must be "
                    "normalized to a flat alphanumeric format before comparison. "
                    "Hyphen separators (EMP-7721 -> EMP7721) are stripped. "
                    "Two IDs that reduce to the same sequence are considered equivalent "
                    "for attendance pairing purposes."
                ),
                "match_threshold": 0.90,
                "escalation_threshold": 0.55,
                "active": True,
                "metadata": {"owner": "DataGovernance", "version": "2.5"},
            },
        ]
    }

    _DOMAIN_POLICIES = [
        "POL-SIM-01: Each employee may register only one active session per certification simulation per day.",
        "POL-SIM-02: Check-In and Check-Out forms from different classrooms are considered valid pairs if submitted within the same calendar day.",
        "POL-SIM-03: Escalated records must be resolved by DataGovernance within 48 business hours.",
        "POL-SIM-04: Micro-credential issuance requires a confidence_score >= 0.95 and attendance_verified = True.",
        "POL-SIM-05: All resolved attendance decisions are written to Dataverse with the full Planner-Executor-Critic reasoning trace.",
    ]

    _SOURCE_TRUST: dict[str, float] = {
        "SYS-FORM-AULA-A":   0.95,
        "SYS-FORM-AULA-B":   0.95,
        "SYS-HR-MATRICULA":  0.80,
        "SYS-MANUAL-ENTRY":  0.60,
        "SYS-LEGACY-IMPORT": 0.45,
    }

    def __init__(self, environment: str = "dev") -> None:
        self._environment = environment
        logger.info(
            "FoundryIQConnector initialized | environment=%s", environment
        )

    def fetch_audit_context(self) -> AuditContext:
        """Retrieve the grounded attendance audit context from Foundry IQ.

        Returns:
            AuditContext populated with rules, policies, and trust scores.

        Raises:
            KeyError: If the environment has no registered fixtures.
        """
        raw_rules = self._RULE_FIXTURES.get(self._environment)
        if raw_rules is None:
            raise KeyError(
                f"No fixtures registered for environment '{self._environment}'. "
                f"Available: {list(self._RULE_FIXTURES.keys())}"
            )

        rules = [AuditRule(**r) for r in raw_rules]
        active_count = sum(1 for r in rules if r.active)

        logger.info(
            "Foundry IQ context loaded | total_rules=%d | active=%d",
            len(rules), active_count,
        )

        return AuditContext(
            rules=rules,
            domain_policies=self._DOMAIN_POLICIES,
            source_system_trust=self._SOURCE_TRUST,
        )
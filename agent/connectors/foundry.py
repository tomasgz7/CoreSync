"""
foundry.py - CoreSync Foundry IQ Connector

Part of the autonomous agent architecture built for the
Microsoft Agents League Hackathon - Reasoning Agents Track.

Simulates retrieval of corporate audit directives and reconciliation
policies from a Microsoft Foundry IQ Knowledge Base. In a production
deployment, this connector would authenticate against the Foundry IQ
API and query a live policy store backed by Dataverse.

For the hackathon demo, the knowledge base is an in-memory fixture
that mirrors the structure of a real Foundry IQ policy payload.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy Schema
# ---------------------------------------------------------------------------

@dataclass
class ReconciliationPolicy:
    """Represents a single policy directive retrieved from Foundry IQ.

    Attributes:
        policy_id: Unique identifier for the policy (e.g. POL-001).
        description: Human-readable description of the rule.
        match_threshold: Minimum confidence_score to auto-approve a match.
        escalation_threshold: Scores below this trigger manual review.
        active: Whether this policy is currently enforced.
        metadata: Arbitrary key-value pairs for extensibility.
    """
    policy_id: str
    description: str
    match_threshold: float
    escalation_threshold: float
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditContext:
    """Aggregated context injected into the reasoning pipeline.

    Attributes:
        policies: List of active ReconciliationPolicy directives.
        certification_rules: Domain-specific rules for academic certification.
        source_system_trust: Trust score per source system identifier.
    """
    policies: list[ReconciliationPolicy]
    certification_rules: list[str]
    source_system_trust: dict[str, float]

    def as_prompt_context(self) -> str:
        """Serialize the audit context into a prompt-injectable string.

        Returns:
            Formatted string summarizing active policies and rules,
            suitable for prepending to a Chain of Thought prompt.
        """
        active = [p for p in self.policies if p.active]
        lines = ["[FOUNDRY IQ AUDIT CONTEXT]"]
        lines.append(f"Active policies: {len(active)}")
        for p in active:
            lines.append(
                f"  - {p.policy_id}: {p.description} "
                f"(match >= {p.match_threshold}, escalate < {p.escalation_threshold})"
            )
        lines.append("Certification rules:")
        for rule in self.certification_rules:
            lines.append(f"  * {rule}")
        lines.append("Source system trust levels:")
        for system, trust in self.source_system_trust.items():
            lines.append(f"  - {system}: {trust:.2f}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FoundryIQConnector
# ---------------------------------------------------------------------------

class FoundryIQConnector:
    """Simulated connector to Microsoft Foundry IQ Knowledge Base.

    In production, this class would authenticate with Foundry IQ using
    managed identity or service principal credentials and query the
    policy store via the Foundry IQ REST API.

    For hackathon purposes, it returns a deterministic in-memory fixture
    that reflects realistic corporate audit directives for an academic
    Simulation Center.

    Args:
        environment: Deployment environment tag. Affects which policy
                     fixture is returned. Accepts 'dev', 'staging', 'prod'.
                     Default: 'dev'.

    Example:
        >>> connector = FoundryIQConnector(environment="dev")
        >>> context = connector.fetch_audit_context()
        >>> print(context.as_prompt_context())
    """

    _POLICY_FIXTURES: dict[str, list[dict[str, Any]]] = {
        "dev": [
            {
                "policy_id": "POL-001",
                "description": "Auto-approve DNI exact match with name similarity >= 80%",
                "match_threshold": 0.85,
                "escalation_threshold": 0.50,
                "active": True,
                "metadata": {"owner": "DataGovernance", "version": "2.1"},
            },
            {
                "policy_id": "POL-002",
                "description": "Flag missing check-out sessions exceeding 4-hour window",
                "match_threshold": 0.75,
                "escalation_threshold": 0.40,
                "active": True,
                "metadata": {"owner": "OperationsTeam", "version": "1.3"},
            },
            {
                "policy_id": "POL-003",
                "description": "Reject records where DNI normalization produced no digits",
                "match_threshold": 0.00,
                "escalation_threshold": 0.00,
                "active": True,
                "metadata": {"owner": "DataGovernance", "version": "1.0"},
            },
            {
                "policy_id": "POL-004",
                "description": "Cross-validate certification level against enrolled cohort",
                "match_threshold": 0.90,
                "escalation_threshold": 0.60,
                "active": False,  # Staged rollout - inactive in dev
                "metadata": {"owner": "AcademicRegistry", "version": "0.9-beta"},
            },
        ]
    }

    _CERTIFICATION_RULES = [
        "A student may only hold one active enrollment per simulation lab at a time.",
        "Certification level must be validated against the official cohort roster (CRT-L1 through CRT-L4).",
        "Records flagged for manual review must be resolved within 48 business hours.",
        "DNI normalization failures automatically trigger an escalation workflow in Dataverse.",
        "Confidence scores below 0.50 are classified as UNRESOLVABLE and routed to DataGovernance.",
    ]

    _SOURCE_TRUST: dict[str, float] = {
        "SYS-CLASSROOM-TERMINAL": 0.95,
        "SYS-ADMIN-PORTAL": 0.90,
        "SYS-SCHEDULING": 0.85,
        "SYS-LEGACY-IMPORT": 0.60,
        "SYS-MANUAL-ENTRY": 0.50,
    }

    def __init__(self, environment: str = "dev") -> None:
        self._environment = environment
        logger.info(
            "FoundryIQConnector initialized | environment=%s", environment
        )

    def fetch_audit_context(self) -> AuditContext:
        """Retrieve the active audit context from Foundry IQ.

        Fetches policy directives, certification rules, and source system
        trust scores applicable to the current reconciliation run.

        Returns:
            AuditContext populated with active policies and rules.

        Raises:
            KeyError: If the environment tag has no registered fixtures.

        Example:
            >>> context = connector.fetch_audit_context()
            >>> context.policies[0].policy_id
            'POL-001'
        """
        raw_policies = self._POLICY_FIXTURES.get(self._environment)
        if raw_policies is None:
            raise KeyError(
                f"No policy fixtures registered for environment '{self._environment}'. "
                f"Available: {list(self._POLICY_FIXTURES.keys())}"
            )

        policies = [ReconciliationPolicy(**p) for p in raw_policies]
        active_count = sum(1 for p in policies if p.active)

        logger.info(
            "Foundry IQ context loaded | total_policies=%d | active=%d",
            len(policies),
            active_count,
        )

        return AuditContext(
            policies=policies,
            certification_rules=self._CERTIFICATION_RULES,
            source_system_trust=self._SOURCE_TRUST,
        )

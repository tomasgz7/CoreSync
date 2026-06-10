"""
foundry.py - CoreSync Foundry IQ Connector

Part of the autonomous agent architecture built for the
Microsoft Agents League Hackathon - Reasoning Agents Track.

Simulates retrieval of grounded corporate audit directives from a
Microsoft Foundry IQ indexed Knowledge Base. In a production deployment,
this connector would authenticate against Foundry IQ using managed identity
and query a live policy store backed by Dataverse.

Each policy is assigned an explicit "Audit Rule #N" identifier so the
downstream Resolver Agent can cite specific rules in its reasoning trace,
enabling grounded, auditable decisions that minimize LLM hallucination.
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
        rule_number: Sequential rule identifier used for downstream citation.
        title: Short descriptive title for display and logging.
        description: Full rule text injected into the reasoning prompt.
        match_threshold: Minimum confidence_score to auto-approve a match.
        escalation_threshold: Scores below this value trigger manual review.
        active: Whether this rule is currently enforced in the environment.
        metadata: Arbitrary extensibility bag for versioning and ownership.
    """
    rule_number: int
    title: str
    description: str
    match_threshold: float
    escalation_threshold: float
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def citation_label(self) -> str:
        """Return the canonical citation string for use in reasoning traces.

        Returns:
            String formatted as 'Audit Rule #N - Title'.
        """
        return f"Audit Rule #{self.rule_number} - {self.title}"


@dataclass
class AuditContext:
    """Aggregated grounded context injected into the reasoning pipeline.

    Attributes:
        rules: List of active AuditRule directives.
        domain_policies: High-level organizational certification policies.
        source_system_trust: Trust coefficient per source system identifier.
    """
    rules: list[AuditRule]
    domain_policies: list[str]
    source_system_trust: dict[str, float]

    def active_rules(self) -> list[AuditRule]:
        """Return only the currently active rules.

        Returns:
            Filtered list of AuditRule instances where active is True.
        """
        return [r for r in self.rules if r.active]

    def as_prompt_context(self) -> str:
        """Serialize the audit context into a prompt-injectable string.

        Formats active rules with their full descriptions and citation labels
        so the Resolver Agent can reference specific rules in its output.
        This grounding mechanism is the primary defense against hallucination.

        Returns:
            Structured multi-line string ready for system prompt injection.
        """
        active = self.active_rules()
        lines = [
            "=" * 60,
            "FOUNDRY IQ - GROUNDED AUDIT CONTEXT",
            "Source: Enterprise Certification Governance Knowledge Base",
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

    Retrieves grounded audit rules and domain policies that govern
    enterprise certification identity matching. The numbered rule format
    (Audit Rule #N) enables the Resolver Agent to produce citations in
    its reasoning trace rather than free-form hallucinations.

    In production, the fetch_audit_context() method would replace the
    in-memory fixture with an authenticated REST call to the Foundry IQ
    indexing endpoint, returning semantically chunked policy documents
    from a Dataverse-backed knowledge store.

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
                "title": "Employee ID Format Normalization",
                "description": (
                    "All Employee IDs must be normalized to a flat alphanumeric "
                    "format before any join operation. UPN-style prefixes (e.g., "
                    "'DOMAIN\\\\user_id'), non-alphanumeric separators, and "
                    "case differences must be stripped. Two IDs that reduce to "
                    "the same alphanumeric sequence are considered equivalent."
                ),
                "match_threshold": 0.85,
                "escalation_threshold": 0.50,
                "active": True,
                "metadata": {"owner": "DataGovernance", "version": "3.1"},
            },
            {
                "rule_number": 2,
                "title": "OCR Character Substitution Detection",
                "description": (
                    "Records sourced from SYS-OCR-SCANNER must be evaluated for "
                    "common OCR substitution errors: digit '0' misread as letter 'O', "
                    "digit '1' misread as letter 'I' or 'l', digit '5' misread as 'S'. "
                    "If correcting known OCR patterns produces an exact Employee ID "
                    "match with the HR record, confidence must be boosted by +0.15."
                ),
                "match_threshold": 0.80,
                "escalation_threshold": 0.45,
                "active": True,
                "metadata": {"owner": "DocumentProcessingTeam", "version": "2.0"},
            },
            {
                "rule_number": 3,
                "title": "High Practice Score - Strict Identity Enforcement",
                "description": (
                    "If a candidate's practice_score is greater than 75%, "
                    "strict identity matching must be enforced. Both Employee ID "
                    "and full name (post-normalization) must align. A confidence "
                    "score below 0.90 for high-scoring candidates is insufficient "
                    "for auto-approval and must trigger an escalation workflow."
                ),
                "match_threshold": 0.90,
                "escalation_threshold": 0.70,
                "active": True,
                "metadata": {"owner": "CertificationIntegrityBoard", "version": "1.5"},
            },
            {
                "rule_number": 4,
                "title": "Corrupted Record Escalation Protocol",
                "description": (
                    "Any record where Employee ID normalization produces an empty "
                    "string, contains special characters only, or matches the "
                    "pattern '%%*%%' must be immediately flagged as UNRESOLVABLE. "
                    "These records must not be passed to the reasoning layer and "
                    "must be routed to the DataGovernance escalation queue."
                ),
                "match_threshold": 0.00,
                "escalation_threshold": 0.00,
                "active": True,
                "metadata": {"owner": "DataGovernance", "version": "1.2"},
            },
            {
                "rule_number": 5,
                "title": "Name Whitespace and Casing Normalization",
                "description": (
                    "All name fields must undergo NFKD unicode normalization, "
                    "diacritic stripping, whitespace collapsing, and title-casing "
                    "before comparison. Two names that produce the same normalized "
                    "string are considered identical regardless of the original "
                    "source format. Abbreviated middle names (e.g., 'N.' vs 'Nicolas') "
                    "must not reduce confidence below 0.85 when Employee ID matches exactly."
                ),
                "match_threshold": 0.85,
                "escalation_threshold": 0.50,
                "active": True,
                "metadata": {"owner": "DataGovernance", "version": "2.3"},
            },
            {
                "rule_number": 6,
                "title": "Baseline Clean Record Validation",
                "description": (
                    "Records where Employee ID, certification target, practice score, "
                    "and exam registration ID are all identical across both sources "
                    "qualify as a CLEAN MATCH and must receive a confidence score "
                    "of 0.97 or higher. No manual review is required for clean matches."
                ),
                "match_threshold": 0.97,
                "escalation_threshold": 0.85,
                "active": True,
                "metadata": {"owner": "AutomationTeam", "version": "1.0"},
            },
        ]
    }

    _DOMAIN_POLICIES = [
        "POL-ENT-01: An employee may hold only one active exam registration per certification track per quarter.",
        "POL-ENT-02: Certification validations sourced from SYS-LEGACY-IMPORT require dual-source confirmation.",
        "POL-ENT-03: Escalated records must be resolved within 48 business hours by the DataGovernance team.",
        "POL-ENT-04: Practice scores below 60% do not qualify for expedited exam registration.",
        "POL-ENT-05: All resolved identities are written back to Dataverse with a full reasoning audit trail.",
    ]

    _SOURCE_TRUST: dict[str, float] = {
        "SYS-HR-DATABASE":  0.95,
        "SYS-MSLEARN":      0.90,
        "SYS-CERT-UPLOAD":  0.80,
        "SYS-MANUAL-ENTRY": 0.65,
        "SYS-OCR-SCANNER":  0.60,
        "SYS-LEGACY-IMPORT": 0.45,
    }

    def __init__(self, environment: str = "dev") -> None:
        self._environment = environment
        logger.info(
            "FoundryIQConnector initialized | environment=%s", environment
        )

    def fetch_audit_context(self) -> AuditContext:
        """Retrieve the grounded audit context from Foundry IQ.

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
            len(rules),
            active_count,
        )

        return AuditContext(
            rules=rules,
            domain_policies=self._DOMAIN_POLICIES,
            source_system_trust=self._SOURCE_TRUST,
        )
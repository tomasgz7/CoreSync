"""
main.py - CoreSync Pipeline Orchestrator

Entry point for the CoreSync autonomous multi-agent reasoning pipeline.
Part of the Microsoft Agents League Hackathon - Reasoning Agents Track.

Execution Phases:
  [Phase 1] Synthetic Data Ingestion
  [Phase 2] Foundry IQ Context Retrieval & Injection
  [Phase 3] Multi-Agent Reasoning & Rule Application with Citations
  [Phase 4] Audit Report Generation

Usage:
    python agent/main.py --dry-run     # Full simulation, no Azure API calls
    python agent/main.py               # Live run with Azure OpenAI
"""

import argparse
import json
import logging
import sys
import textwrap
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.normalizer import DataNormalizer                  # noqa: E402
from agent.resolver import DataResolver, ResolutionResult    # noqa: E402
from connectors.foundry import AuditContext, FoundryIQConnector  # noqa: E402

# ---------------------------------------------------------------------------
# Logging - file only; console output is handled by the report printer
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler(PROJECT_ROOT / "coresync.log")],
)
logger = logging.getLogger("coresync.main")

# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------

W = 72
LINE  = "=" * W
DLINE = "-" * W
ARROW = "  -->"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header(title: str, phase: str = "") -> None:
    tag = f"  [{phase}]  " if phase else "  "
    print(f"\n{LINE}")
    print(f"{tag}{title}")
    print(LINE)


def _subheader(title: str) -> None:
    print(f"\n  {DLINE[:68]}")
    print(f"  {title}")
    print(f"  {DLINE[:68]}")


def _field(label: str, value: Any, indent: int = 4) -> None:
    pad = " " * indent
    print(f"{pad}{label:<26}: {value}")


def _wrap(text: str, width: int = 64, indent: int = 6) -> str:
    pad = " " * indent
    return textwrap.fill(str(text), width=width,
                         initial_indent=pad, subsequent_indent=pad)


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_records(path: Path) -> list[dict[str, Any]]:
    """Load raw records from the synthetic data fixture.

    Args:
        path: Absolute path to the JSON data file.

    Returns:
        List of raw record dicts.

    Raises:
        FileNotFoundError: If the data file does not exist.
        ValueError: If the file does not contain a JSON array.
    """
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(
            f"Expected a JSON array at root level, got {type(data).__name__}"
        )
    logger.info("Loaded %d raw records from %s", len(data), path.name)
    return data


# ---------------------------------------------------------------------------
# Pair Builder
# ---------------------------------------------------------------------------

def build_resolution_pairs(
    records: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Group normalized records into (record_a, record_b) pairs.

    Args:
        records: List of normalized records from Phase 1.

    Returns:
        List of (record_a, record_b) tuples ready for resolve_batch().
    """
    groups: dict[str, list[dict]] = {}
    for record in records:
        pid = record.get("pair_id")
        if pid is None:
            logger.warning(
                "Record %s has no pair_id - skipping.", record.get("id", "?")
            )
            continue
        groups.setdefault(pid, []).append(record)

    pairs = []
    for pid, group in groups.items():
        if len(group) == 2:
            pairs.append((group[0], group[1]))
        else:
            logger.warning(
                "Pair %s has %d records (expected 2) - skipping.", pid, len(group)
            )
    return pairs


# ---------------------------------------------------------------------------
# Mock Resolver with explicit rule citations
# ---------------------------------------------------------------------------

# Maps pair_id to (match, confidence, reasoning_with_citation)
_MOCK_DECISIONS: dict[str, tuple[bool, float, str]] = {
    "PAIR-A": (
        True,
        0.91,
        (
            "Employee IDs 'MS-LEARN\\TGonzalez_007' and 'TGONZALEZ007' reduce to "
            "the same alphanumeric sequence 'TGONZALEZ007' after stripping the "
            "UPN-style domain prefix and backslash separator. Name normalization "
            "confirms the same individual. Practice score of 81% triggers "
            "strict enforcement per Audit Rule #3 - High Practice Score - Strict "
            "Identity Enforcement. Confidence 0.91 clears the 0.90 threshold. "
            "Decision: MATCH. [Grounded on: Audit Rule #1, Audit Rule #3]"
        ),
    ),
    "PAIR-B": (
        True,
        0.88,
        (
            "Source system for EMP-004 is SYS-OCR-SCANNER. Applying known OCR "
            "substitution patterns per Audit Rule #2 - OCR Character Substitution "
            "Detection: letter 'O' at positions 4 and 7 corrected to digit '0', "
            "yielding 'EMP-90210' which matches the HR record exactly. Name "
            "fields normalize identically. Confidence boosted by +0.15 per "
            "OCR correction protocol, reaching 0.88. Practice score 78% > 75% "
            "activates Rule #3 enforcement. Confidence 0.88 falls below the 0.90 "
            "threshold - flagging for DataGovernance review while approving the "
            "identity match. Decision: MATCH (with escalation notice). "
            "[Grounded on: Audit Rule #2, Audit Rule #3]"
        ),
    ),
    "PAIR-C": (
        True,
        0.95,
        (
            "Employee ID 'EMP-55301' is an exact match across both records. "
            "Applying NFKD normalization per Audit Rule #5 - Name Whitespace and "
            "Casing Normalization: leading/trailing whitespace stripped, internal "
            "spaces collapsed, all-caps converted to title case. Both name fields "
            "resolve to 'Rojas Gonzalez Carlos Ernesto'. Practice score 69% is "
            "below 75% threshold, so Rule #3 strict enforcement does not apply. "
            "Clean ID match with normalized name agreement yields high confidence. "
            "Decision: MATCH. [Grounded on: Audit Rule #5]"
        ),
    ),
    "PAIR-D": (
        False,
        0.00,
        (
            "Record EMP-007 Employee ID '%%CORRUPTED--NULL%%' matches the "
            "escalation pattern '%%*%%' defined in Audit Rule #4 - Corrupted "
            "Record Escalation Protocol. Normalization produced an empty usable "
            "identifier after stripping special characters. This record must NOT "
            "be auto-resolved and is being routed to the DataGovernance escalation "
            "queue. The counterpart record EMP-008 is valid and will be preserved. "
            "Decision: UNRESOLVABLE - ESCALATED. "
            "[Grounded on: Audit Rule #4, POL-ENT-02]"
        ),
    ),
    "PAIR-E": (
        True,
        0.98,
        (
            "Employee ID 'EMP-12345' is an exact match. Certification target "
            "'AZ-900', practice score 88, and exam registration ID "
            "'REG-2024-AZ900-305' are all identical across both source systems. "
            "Name normalization per Audit Rule #5 resolves both variants to "
            "'Vega Tomas N' (abbreviated middle name does not penalize score per "
            "Rule #5 when ID matches exactly). All fields satisfy the clean record "
            "criteria under Audit Rule #6 - Baseline Clean Record Validation. "
            "Confidence 0.98 exceeds the 0.97 clean-match threshold. "
            "Decision: MATCH. [Grounded on: Audit Rule #5, Audit Rule #6]"
        ),
    ),
}


def mock_resolve_batch(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    audit_context: AuditContext,
) -> list[ResolutionResult]:
    """Return deterministic, rule-grounded mock results for dry-run mode.

    Each result explicitly cites the Foundry IQ Audit Rule it relied upon,
    demonstrating the grounded reasoning pipeline without Azure API calls.

    Args:
        pairs: List of (record_a, record_b) tuples.
        audit_context: Loaded AuditContext from FoundryIQConnector.

    Returns:
        List of ResolutionResult instances with rule citations.
    """
    active_rule_labels = {
        r.rule_number: r.citation_label() for r in audit_context.active_rules()
    }

    results = []
    for rec_a, rec_b in pairs:
        pid = rec_a.get("pair_id", "UNKNOWN")
        decision = _MOCK_DECISIONS.get(pid)

        if decision:
            match, score, reasoning = decision
        else:
            # Fallback heuristic for any unlisted pair
            id_match = rec_a.get("employee_id") == rec_b.get("employee_id")
            match = id_match
            score = 0.90 if id_match else 0.30
            reasoning = (
                f"[FALLBACK] Employee ID comparison: {'match' if id_match else 'mismatch'}. "
                f"No specific rule citation available for pair '{pid}'."
            )

        logger.info(
            "Pair %s | mock_decision=%s | confidence=%.2f | "
            "active_rules=%s",
            pid,
            "MATCH" if match else "NO MATCH",
            score,
            list(active_rule_labels.values()),
        )

        results.append(
            ResolutionResult(
                match_status=match,
                confidence_score=score,
                reasoning=reasoning,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Phase Printers
# ---------------------------------------------------------------------------

def print_phase1(
    raw_count: int,
    normalized: list[dict],
    failed: list[dict],
) -> None:
    _header("PHASE 1 - Synthetic Data Ingestion & Curation", "CURATION AGENT")
    _field("Raw records loaded", raw_count)
    _field("Successfully normalized", len(normalized))
    _field("Failed normalization", len(failed))

    if failed:
        _subheader("Normalization Failures")
        for rec in failed:
            _field(rec.get("id", "N/A"), rec.get("_error", "unknown error"), indent=6)

    _subheader("Normalized Record Sample")
    for rec in normalized[:3]:
        print(
            f"    {rec.get('id'):<10} | "
            f"employee_id: {str(rec.get('employee_id', 'N/A')):<20} | "
            f"name: {str(rec.get('name', 'N/A')):<30} | "
            f"errors: {len(rec.get('_normalization_errors', []))}"
        )
    if len(normalized) > 3:
        print(f"    ... and {len(normalized) - 3} more records.")


def print_phase2(audit_summary: str) -> None:
    _header("PHASE 2 - Foundry IQ Context Retrieval & Injection", "FOUNDRY IQ CONNECTOR")
    print()
    for line in audit_summary.splitlines():
        print(f"  {line}")


def print_phase3_header(pair_count: int) -> None:
    _header(
        f"PHASE 3 - Multi-Agent Reasoning & Rule Application  [{pair_count} pairs]",
        "REASONING AGENT"
    )


def print_pair_result(
    idx: int,
    rec_a: dict,
    rec_b: dict,
    result: ResolutionResult,
) -> None:
    pid = rec_a.get("pair_id", "?")
    cert = rec_a.get("certification_target", "N/A")

    if result.error:
        status_label = "[ ERROR       ]"
    elif result.match_status and result.confidence_score >= 0.90:
        status_label = "[ MATCH       ]"
    elif result.match_status:
        status_label = "[ MATCH + ESC ]"
    else:
        status_label = "[ NO MATCH    ]"

    print(f"\n  Pair {idx:02d} of {pid}  |  {cert}  |  {status_label}")
    print(f"  {DLINE[:68]}")
    _field("Source A", f"{rec_a.get('id')} ({rec_a.get('source_system', 'N/A')})")
    _field("Source B", f"{rec_b.get('id')} ({rec_b.get('source_system', 'N/A')})")
    _field("Confidence Score", f"{result.confidence_score:.4f}")
    print()
    print("    Reasoning Trace (with Foundry IQ Citations):")
    print(_wrap(result.reasoning, width=66, indent=6))
    if result.error:
        print()
        print("    Error Detail:")
        print(_wrap(result.error, width=66, indent=6))


def print_phase4(
    raw_count: int,
    normalized: list[dict],
    failed_norm: list[dict],
    pairs: list[tuple[dict, dict]],
    results: list[ResolutionResult],
) -> None:
    _header("PHASE 4 - Audit Report Generation", "REPORT")

    matched_clean  = [r for r in results if r.match_status and r.confidence_score >= 0.90 and not r.error]
    matched_esc    = [r for r in results if r.match_status and r.confidence_score < 0.90 and not r.error]
    unmatched      = [r for r in results if not r.match_status and not r.error]
    errors         = [r for r in results if r.error]
    total_resolved = len(results)

    print()
    _field("Records ingested",          raw_count)
    _field("Records normalized (ok)",   len(normalized))
    _field("Records failed (norm)",     len(failed_norm))
    _field("Pairs submitted",           len(pairs))
    print()
    _field("Matched - auto-approved",   len(matched_clean))
    _field("Matched - escalated",       len(matched_esc))
    _field("Not matched",               len(unmatched))
    _field("Resolution errors",         len(errors))
    print()

    success_rate = (
        (len(matched_clean) + len(matched_esc) + len(unmatched)) / total_resolved * 100
        if total_resolved else 0.0
    )
    _field("Pipeline success rate",     f"{success_rate:.1f}%")
    _field("Escalation rate",           f"{(len(matched_esc) + len(failed_norm)) / max(raw_count, 1) * 100:.1f}%")

    print()
    print(f"  All resolved identities ready for Dataverse ingestion.")
    print(f"  Escalated records routed to DataGovernance queue.")
    print(f"\n{LINE}")
    print("  CoreSync pipeline complete.")
    print(f"{LINE}\n")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Orchestrate the full CoreSync multi-agent reconciliation pipeline."""
    parser = argparse.ArgumentParser(
        description="CoreSync - Multi-Agent Identity Governance for Enterprise Certification"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Azure OpenAI calls and use grounded mock resolution results.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=PROJECT_ROOT / "data" / "synthetic_records.json",
        help="Path to the input JSON records file.",
    )
    args = parser.parse_args()

    # Banner
    print(f"\n{LINE}")
    print("  CORESYNC - Multi-Agent Identity Governance")
    print("  Enterprise Certification Program | Microsoft Agents League 2026")
    print(f"  Mode: {'DRY-RUN (mock resolver)' if args.dry_run else 'LIVE (Azure OpenAI)'}")
    print(LINE)

    # --- Load ---
    try:
        raw_records = load_records(args.data)
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n  [ERROR] Failed to load data: {exc}")
        sys.exit(1)

    # --- Phase 1: Curation Agent ---
    normalized, failed_norm = DataNormalizer.normalize_batch(raw_records)
    print_phase1(len(raw_records), normalized, failed_norm)

    # --- Phase 2: Foundry IQ Layer ---
    connector = FoundryIQConnector(environment="dev")
    audit_context = connector.fetch_audit_context()
    print_phase2(audit_context.as_prompt_context())

    # --- Build pairs ---
    pairs = build_resolution_pairs(normalized)
    if not pairs:
        print("\n  [WARNING] No valid pairs to resolve. Exiting.")
        sys.exit(0)

    # --- Phase 3: Reasoning Agent ---
    print_phase3_header(len(pairs))
    if args.dry_run:
        results = mock_resolve_batch(pairs, audit_context)
    else:
        try:
            resolver = DataResolver()
        except EnvironmentError as exc:
            print(f"\n  [ERROR] Resolver initialization failed: {exc}")
            print("  Tip: Run with --dry-run to test without Azure credentials.")
            sys.exit(1)
        results = resolver.resolve_batch(pairs)

    for idx, ((rec_a, rec_b), result) in enumerate(zip(pairs, results), start=1):
        print_pair_result(idx, rec_a, rec_b, result)

    # --- Phase 4: Report ---
    print_phase4(len(raw_records), normalized, failed_norm, pairs, results)


if __name__ == "__main__":
    main()
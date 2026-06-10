"""
main.py - CoreSync Pipeline Orchestrator

Entry point for the CoreSync autonomous multi-agent reasoning pipeline.
Part of the Microsoft Agents League Hackathon - Reasoning Agents Track.

Execution Phases:
  [Phase 1] Synthetic Data Ingestion & Curation
  [Phase 2] Foundry IQ Context Retrieval & Injection
  [Phase 3] Multi-Agent Reasoning & Rule Application with Citations
  [Phase 4] Segmentation, Action Dispatch & Audit Report Generation

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

from agent.normalizer import DataNormalizer                          # noqa: E402
from agent.resolver import DataResolver, ResolutionResult            # noqa: E402
from agent.segmenter import DataSegmenter, SegmentationReport        # noqa: E402
from connectors.foundry import AuditContext, FoundryIQConnector      # noqa: E402

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

W     = 72
LINE  = "=" * W
DLINE = "-" * W


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
    print(f"{pad}{label:<28}: {value}")


def _wrap(text: str, width: int = 64, indent: int = 6) -> str:
    pad = " " * indent
    return textwrap.fill(
        str(text), width=width, initial_indent=pad, subsequent_indent=pad
    )


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
        List of (record_a, record_b) tuples for the Reconciler Agent.
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
# Mock Resolver - Planner-Executor-Critic simulation (dry-run)
# ---------------------------------------------------------------------------

_MOCK_DECISIONS: dict[str, tuple[bool, float, str, str]] = {
    "PAIR-CONF-1001": (
        True,
        0.98,
        "Presentes",
        (
            "[PLANNER] Sub-tasks: (1) Normalize IDs across Aula A and Aula B. "
            "(2) Retrieve dual-token requirement from Foundry IQ. "
            "(3) Verify Check-In and Check-Out tokens. (4) Run Critic audit. "
            "[EXECUTOR] RAW-001 source SYS-FORM-AULA-A contains digital Check-In token. "
            "RAW-002 source SYS-FORM-AULA-B notes confirm successful checkout token. "
            "Employee IDs 'EMP-7721' and 'EMP7721' normalize to the same sequence per "
            "Audit Rule #5. Practice score is 100 - triggers Rule #3 clean validation. "
            "[CRITIC] Verified: Check-In token confirmed (RAW-001). Check-Out token "
            "confirmed (RAW-002 notes). No false positive detected. Verdict stands. "
            "Decision: PRESENT. [Grounded on: Audit Rule #3, Audit Rule #5]"
        ),
    ),
    "PAIR-CONF-1002": (
        False,
        0.90,
        "Ausentes",
        (
            "[PLANNER] Sub-tasks: (1) Identify available attendance tokens. "
            "(2) Check for workload anomaly signals. (3) Apply strict pass rule. "
            "(4) Run Critic to prevent false positive. "
            "[EXECUTOR] RAW-003 confirms digital Check-In from SYS-FORM-AULA-A. "
            "No Check-Out token found across any classroom record at end of day. "
            "RAW-004 is an HR control record - not a digital form submission. "
            "HR annotation alone cannot satisfy Audit Rule #1 dual-token requirement. "
            "RAW-004 notes contain 'high weekly meeting overhead' - evaluating "
            "Audit Rule #2 workload anomaly allowance. "
            "[CRITIC] Executor finding: Check-In confirmed, Check-Out MISSING. "
            "HR record is not a valid attendance token. Rule #1 hard constraint applies. "
            "Workload signal reduces severity to AT_RISK per Rule #2 but does NOT "
            "override the absent verdict. Confidence capped at 0.90. "
            "Decision: ABSENT. [Grounded on: Audit Rule #1, Audit Rule #2]"
        ),
    ),
    "PAIR-CONF-1003": (
        False,
        1.00,
        "Sin_Respuesta",
        (
            "[PLANNER] Sub-tasks: (1) Validate identity fields. "
            "(2) Check for corruption pattern. (3) Apply isolation protocol. "
            "(4) Critic confirms - no further reasoning required. "
            "[EXECUTOR] RAW-005 name field contains '%%CORRUPTED_ID%%' matching "
            "the corruption pattern defined in Audit Rule #4. "
            "practice_score is null. Employee ID normalization on RAW-006 produces "
            "a valid ID but the paired record identity is unrecoverable. "
            "[CRITIC] Corruption pattern confirmed. Audit Rule #4 hard constraint: "
            "record must NOT be passed to credential issuance under any circumstances. "
            "Routing to DataGovernance critical log. "
            "Decision: UNRESOLVABLE - ESCALATED. [Grounded on: Audit Rule #4]"
        ),
    ),
}


def mock_resolve_batch(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    audit_context: AuditContext,
) -> list[ResolutionResult]:
    """Return deterministic Planner-Executor-Critic mock results for dry-run.

    Each result explicitly cites the Foundry IQ Audit Rule it relied upon,
    demonstrating grounded multi-step reasoning without Azure API calls.

    Args:
        pairs: List of (record_a, record_b) tuples.
        audit_context: Loaded AuditContext from FoundryIQConnector.

    Returns:
        List of ResolutionResult instances with full reasoning traces.
    """
    results = []
    for rec_a, rec_b in pairs:
        pid = rec_a.get("pair_id", "UNKNOWN")
        decision = _MOCK_DECISIONS.get(pid)

        if decision:
            match, score, segment, reasoning = decision
        else:
            id_a = str(rec_a.get("employee_id", "")).replace("-", "").upper()
            id_b = str(rec_b.get("employee_id", "")).replace("-", "").upper()
            match = id_a == id_b and bool(id_a)
            score = 0.90 if match else 0.30
            segment = "Presentes" if match else "Ausentes"
            reasoning = (
                f"[FALLBACK] No specific fixture for pair '{pid}'. "
                f"ID comparison: {'match' if match else 'mismatch'}. "
                "[Grounded on: Audit Rule #5]"
            )

        results.append(
            ResolutionResult(
                match_status=match,
                confidence_score=score,
                reasoning=reasoning,
                segment=segment,
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
    _header(
        "PHASE 1 - Synthetic Data Ingestion & Curation",
        "LEARNING PATH & CENTER CURATOR AGENT"
    )
    _field("Raw records loaded", raw_count)
    _field("Successfully normalized", len(normalized))
    _field("Failed normalization", len(failed))

    if failed:
        _subheader("Normalization Failures")
        for rec in failed:
            _field(rec.get("id", "N/A"), rec.get("_error", "unknown"), indent=6)

    _subheader("Ingested Record Sample")
    for rec in normalized[:4]:
        errors = len(rec.get("_normalization_errors", []))
        print(
            f"    {rec.get('id'):<10} | "
            f"emp_id: {str(rec.get('employee_id', 'N/A')):<15} | "
            f"source: {str(rec.get('source_system', 'N/A')):<22} | "
            f"norm_errors: {errors}"
        )
    if len(normalized) > 4:
        print(f"    ... and {len(normalized) - 4} more records.")


def print_phase2(audit_summary: str) -> None:
    _header(
        "PHASE 2 - Foundry IQ Context Retrieval & Injection",
        "FOUNDRY IQ CONNECTOR"
    )
    print()
    for line in audit_summary.splitlines():
        print(f"  {line}")


def print_phase3_header(pair_count: int) -> None:
    _header(
        f"PHASE 3 - Multi-Agent Reasoning & Rule Application  [{pair_count} pairs]",
        "REASONING ATTENDANCE RECONCILER AGENT"
    )


def print_pair_result(
    idx: int,
    total: int,
    rec_a: dict,
    rec_b: dict,
    result: ResolutionResult,
) -> None:
    pid = rec_a.get("pair_id", "?")
    cert = rec_a.get("certification_target", "N/A")

    if result.error:
        status_label = "[ ERROR          ]"
    elif result.segment == "Presentes":
        status_label = "[ PRESENT - AUTO ]"
    elif result.segment == "Ausentes":
        status_label = "[ ABSENT - RISK  ]"
    else:
        status_label = "[ SIN RESPUESTA  ]"

    print(f"\n  Pair {idx:02d}/{total:02d}  |  {pid}  |  {cert}  |  {status_label}")
    print(f"  {DLINE[:68]}")
    _field("Source A", f"{rec_a.get('id')} ({rec_a.get('source_system', 'N/A')})")
    _field("Source B", f"{rec_b.get('id')} ({rec_b.get('source_system', 'N/A')})")
    _field("Segment", result.segment)
    _field("Confidence Score", f"{result.confidence_score:.4f}")
    print()
    print("    Planner-Executor-Critic Reasoning Trace:")
    print(_wrap(result.reasoning, width=66, indent=6))
    if result.error:
        print()
        print("    Error Detail:")
        print(_wrap(result.error, width=66, indent=6))


def print_phase4(
    report: SegmentationReport,
    dry_run: bool,
    output_path: Path,
) -> None:
    _header(
        "PHASE 4 - Segmentation, Action Dispatch & Audit Report",
        "DATA SEGMENTER & ENTERPRISE AGENT"
    )

    total = report.total_processed_pairs

    print()
    _field("Pipeline ID", report.pipeline_id)
    _field("Execution mode", report.execution_mode)
    _field("Timestamp", report.timestamp)
    _field("Total pairs processed", total)

    _subheader("Segmentation Results")
    _field("Presentes  (action: EMIT_MICRO_CREDENTIAL)", len(report.presentes))
    _field("Ausentes   (action: ROUTE_TO_ENGAGEMENT)", len(report.ausentes))
    _field("Sin_Respuesta (action: ISOLATE_CRITICAL_LOG)", len(report.sin_respuesta))

    if report.presentes:
        _subheader("Presentes - Micro-Credential Dispatch")
        for rec in report.presentes:
            print(f"    {rec.employee_id:<12} | {rec.certification_target:<15} | "
                  f"confidence: {rec.confidence_index:.4f} | {rec.grounded_citation}")

    if report.ausentes:
        _subheader("Ausentes - Engagement Queue Routing")
        for rec in report.ausentes:
            print(f"    {rec.employee_id:<12} | severity: {rec.severity_flag:<25} | "
                  f"{rec.grounded_citation}")

    if report.sin_respuesta:
        _subheader("Sin Respuesta - DataGovernance Escalation")
        for rec in report.sin_respuesta:
            print(f"    {rec.employee_id:<12} | severity: {rec.severity_flag:<25} | "
                  f"{rec.grounded_citation}")

    success_rate = (
        (len(report.presentes) + len(report.ausentes)) / total * 100
        if total else 0.0
    )

    print()
    _field("Pipeline success rate", f"{success_rate:.1f}%")
    _field("Report artifact", str(output_path))

    print(f"\n{LINE}")
    print("  CoreSync pipeline complete.")
    print(f"  All resolved identities ready for Dataverse ingestion.")
    print(f"  Escalated records routed to DataGovernance queue.")
    print(f"{LINE}\n")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Orchestrate the full CoreSync multi-agent attendance reconciliation pipeline."""
    parser = argparse.ArgumentParser(
        description="CoreSync - Multi-Agent Identity Governance for Corporate Simulation Centers"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Azure OpenAI calls and use grounded mock Planner-Executor-Critic results.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=PROJECT_ROOT / "data" / "synthetic_records.json",
        help="Path to the input JSON records file.",
    )
    args = parser.parse_args()

    output_path = PROJECT_ROOT / "data" / "output_segmentado.json"

    # Banner
    print(f"\n{LINE}")
    print("  CORESYNC - Multi-Agent Identity Governance")
    print("  Corporate Simulation Center | Microsoft Agents League 2026")
    print(f"  Mode: {'DRY-RUN (Planner-Executor-Critic simulation)' if args.dry_run else 'LIVE (Azure OpenAI)'}")
    print(LINE)

    # --- Load raw records ---
    try:
        raw_records = load_records(args.data)
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n  [ERROR] Failed to load data: {exc}")
        sys.exit(1)

    # --- Phase 1: Learning Path & Center Curator Agent ---
    normalized, failed_norm = DataNormalizer.normalize_batch(raw_records)
    print_phase1(len(raw_records), normalized, failed_norm)

    # --- Phase 2: Foundry IQ Context Retrieval ---
    connector = FoundryIQConnector(environment="dev")
    audit_context = connector.fetch_audit_context()
    print_phase2(audit_context.as_prompt_context())

    # --- Build pairs ---
    pairs = build_resolution_pairs(normalized)
    if not pairs:
        print("\n  [WARNING] No valid pairs to resolve. Exiting.")
        sys.exit(0)

    # --- Phase 3: Reasoning Attendance Reconciler Agent ---
    print_phase3_header(len(pairs))

    if args.dry_run:
        results = mock_resolve_batch(pairs, audit_context)
    else:
        try:
            resolver = DataResolver(audit_context=audit_context)
        except EnvironmentError as exc:
            print(f"\n  [ERROR] Resolver initialization failed: {exc}")
            print("  Tip: Run with --dry-run to test without Azure credentials.")
            sys.exit(1)
        results = resolver.resolve_batch(pairs)

    for idx, ((rec_a, rec_b), result) in enumerate(zip(pairs, results), start=1):
        print_pair_result(idx, len(pairs), rec_a, rec_b, result)

    # --- Phase 4: Data Segmenter & Enterprise Agent ---
    segmenter = DataSegmenter(
        execution_mode="DRY_RUN_SIMULATION" if args.dry_run else "LIVE"
    )
    report = segmenter.segment(pairs, results)
    segmenter.write_report(report, output_path)
    print_phase4(report, args.dry_run, output_path)


if __name__ == "__main__":
    main()
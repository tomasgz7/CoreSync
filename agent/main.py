"""
main.py - CoreSync Pipeline Orchestrator

Entry point for the CoreSync autonomous reasoning agent.
Part of the Microsoft Agents League Hackathon - Reasoning Agents Track.

Execution flow:
  Phase 1 - Curation Agent    : DataNormalizer.normalize_batch()
  Phase 2 - Foundry IQ Layer  : FoundryIQConnector.fetch_audit_context()
  Phase 3 - Reasoning Agent   : DataResolver.resolve_batch()
  Phase 4 - Report            : Structured console output

Usage:
    python agent/main.py
    python agent/main.py --dry-run   # Skip Azure OpenAI calls, use mock results
"""

import argparse
import json
import logging
import sys
import textwrap
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap - allows running from project root or agent/ directory
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.normalizer import DataNormalizer                  # noqa: E402
from agent.resolver import DataResolver, ResolutionResult    # noqa: E402
from connectors.foundry import FoundryIQConnector            # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("coresync.main")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_PATH = PROJECT_ROOT / "data" / "synthetic_records.json"
SEPARATOR = "-" * 72


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
        raise ValueError(f"Expected a JSON array at root level, got {type(data).__name__}")

    logger.info("Loaded %d raw records from %s", len(data), path.name)
    return data


# ---------------------------------------------------------------------------
# Pair Builder
# ---------------------------------------------------------------------------

def build_resolution_pairs(
    records: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Group normalized records into (record_a, record_b) pairs for resolution.

    Pairs records by shared `pair_id` field. Records without a `pair_id`
    are skipped with a warning.

    Args:
        records: List of normalized records from Phase 1.

    Returns:
        List of (record_a, record_b) tuples ready for resolve_batch().
    """
    groups: dict[str, list[dict]] = {}
    for record in records:
        pid = record.get("pair_id")
        if pid is None:
            logger.warning("Record %s has no pair_id - skipping.", record.get("id", "UNKNOWN"))
            continue
        groups.setdefault(pid, []).append(record)

    pairs = []
    for pid, group in groups.items():
        if len(group) == 2:
            pairs.append((group[0], group[1]))
        else:
            logger.warning("Pair %s has %d records (expected 2) - skipping.", pid, len(group))

    logger.info("Built %d resolution pairs.", len(pairs))
    return pairs


# ---------------------------------------------------------------------------
# Mock Resolver (dry-run mode)
# ---------------------------------------------------------------------------

def mock_resolve_batch(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[ResolutionResult]:
    """Return deterministic mock results for dry-run mode.

    Simulates the Azure OpenAI call using simple DNI comparison heuristics.
    Used to validate the full pipeline without consuming API quota.

    Args:
        pairs: List of (record_a, record_b) tuples.

    Returns:
        List of ResolutionResult instances.
    """
    results = []
    for a, b in pairs:
        dni_match = (a.get("dni") is not None) and (a.get("dni") == b.get("dni"))
        score = 0.97 if dni_match else 0.31
        results.append(
            ResolutionResult(
                match_status=dni_match,
                confidence_score=score,
                reasoning=(
                    "[DRY-RUN] DNI exact match detected. Name comparison passed heuristic threshold."
                    if dni_match else
                    "[DRY-RUN] DNI mismatch. Records likely represent different individuals."
                ),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Report Printer
# ---------------------------------------------------------------------------

def print_report(
    raw_count: int,
    normalized: list[dict],
    failed_norm: list[dict],
    pairs: list[tuple[dict, dict]],
    results: list[ResolutionResult],
    audit_summary: str,
) -> None:
    """Print the final pipeline report to stdout.

    Args:
        raw_count: Total number of raw input records.
        normalized: Successfully normalized records.
        failed_norm: Records that failed normalization.
        pairs: Resolution pairs submitted to the reasoning agent.
        results: Resolution outcomes from DataResolver.
        audit_summary: Formatted Foundry IQ context summary.
    """
    print(f"\n{SEPARATOR}")
    print("  CORESYNC - PIPELINE EXECUTION REPORT")
    print(f"  Microsoft Agents League Hackathon 2026 | Reasoning Agents Track")
    print(SEPARATOR)

    # --- Phase 1 Summary ---
    print("\n[PHASE 1] Curation Agent - Normalization Results")
    print(f"  Raw records ingested  : {raw_count}")
    print(f"  Successfully normalized: {len(normalized)}")
    print(f"  Failed normalization  : {len(failed_norm)}")

    if failed_norm:
        print("\n  Failed Records:")
        for rec in failed_norm:
            print(f"    - ID: {rec.get('id', 'N/A')} | Error: {rec.get('_error', 'unknown')}")

    # --- Phase 2 Summary ---
    print(f"\n{SEPARATOR}")
    print("[PHASE 2] Foundry IQ Layer - Audit Context")
    for line in audit_summary.splitlines():
        print(f"  {line}")

    # --- Phase 3 Summary ---
    print(f"\n{SEPARATOR}")
    print(f"[PHASE 3] Reasoning Agent - Resolution Decisions ({len(results)} pairs)")

    matched = [r for r in results if r.match_status and not r.error]
    unmatched = [r for r in results if not r.match_status and not r.error]
    errors = [r for r in results if r.error]

    print(f"  Matched     : {len(matched)}")
    print(f"  Not matched : {len(unmatched)}")
    print(f"  API errors  : {len(errors)}")

    print()
    for idx, ((rec_a, rec_b), result) in enumerate(zip(pairs, results), start=1):
        status_icon = "MATCH" if result.match_status else ("ERROR" if result.error else "NO MATCH")
        print(f"  Pair {idx:02d} | {rec_a.get('id', '?')} <-> {rec_b.get('id', '?')}")
        print(f"    Status          : {status_icon}")
        print(f"    Confidence Score: {result.confidence_score:.4f}")
        reasoning_wrapped = textwrap.fill(result.reasoning, width=60, initial_indent="    ", subsequent_indent="    ")
        print(f"    Reasoning:\n{reasoning_wrapped}")
        if result.error:
            print(f"    Error Detail    : {result.error}")
        print()

    # --- Final Summary ---
    print(SEPARATOR)
    total = len(results)
    success_rate = (len(matched) + len(unmatched)) / total * 100 if total else 0
    print(f"  Pipeline completed | Success rate: {success_rate:.1f}% | Total pairs: {total}")
    print(SEPARATOR)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Orchestrate the full CoreSync reconciliation pipeline.

    Parses CLI arguments, loads data, runs all three pipeline phases,
    and prints the structured execution report.
    """
    parser = argparse.ArgumentParser(
        description="CoreSync - Autonomous Data Reconciliation Agent"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Azure OpenAI calls and use mock resolution results.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DATA_PATH,
        help=f"Path to the input JSON records file. Default: {DATA_PATH}",
    )
    args = parser.parse_args()

    logger.info("CoreSync pipeline starting | dry_run=%s", args.dry_run)

    # --- Load raw records ---
    try:
        raw_records = load_records(args.data)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Failed to load data: %s", exc)
        sys.exit(1)

    # --- Phase 1: Curation Agent ---
    logger.info("Phase 1: Running DataNormalizer...")
    normalized, failed_norm = DataNormalizer.normalize_batch(raw_records)
    logger.info(
        "Normalization complete | ok=%d | failed=%d", len(normalized), len(failed_norm)
    )

    # --- Phase 2: Foundry IQ Layer ---
    logger.info("Phase 2: Fetching Foundry IQ audit context...")
    connector = FoundryIQConnector(environment="dev")
    audit_context = connector.fetch_audit_context()
    audit_summary = audit_context.as_prompt_context()

    # --- Build resolution pairs ---
    pairs = build_resolution_pairs(normalized)
    if not pairs:
        logger.warning("No valid pairs to resolve. Check pair_id assignments in data.")
        sys.exit(0)

    # --- Phase 3: Reasoning Agent ---
    if args.dry_run:
        logger.info("Phase 3: DRY-RUN mode - using mock resolver.")
        results = mock_resolve_batch(pairs)
    else:
        logger.info("Phase 3: Initializing DataResolver...")
        try:
            resolver = DataResolver()
        except EnvironmentError as exc:
            logger.error("Resolver initialization failed: %s", exc)
            logger.error("Run with --dry-run to test the pipeline without Azure credentials.")
            sys.exit(1)
        results = resolver.resolve_batch(pairs)

    # --- Phase 4: Report ---
    print_report(
        raw_count=len(raw_records),
        normalized=normalized,
        failed_norm=failed_norm,
        pairs=pairs,
        results=results,
        audit_summary=audit_summary,
    )


if __name__ == "__main__":
    main()

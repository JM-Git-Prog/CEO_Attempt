"""Run the v16 zero-state qualification harness (mocked GPU).

Executes QualificationHarness.run_qualification() with:
  - 1 smoke round (built-in)
  - 5 headless rounds
  - 5 human-like rounds

All GPU stages use mocked handlers — this qualifies the structural pipeline
(stage ordering, gates, parity, hash binding, append-only evidence), NOT
actual neural generation quality.

Exit 0 if all rounds pass, exit 1 if any fail.
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Ensure project root is on sys.path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.unified_pipeline.qualification import QualificationHarness


REPORT_OUTPUT = PROJECT_ROOT / "output" / "qualification" / "v16-qualification-report.json"


async def main() -> int:
    """Run qualification and save report."""
    output_root = PROJECT_ROOT / "output" / "qualification" / "v16-sessions"

    print("=" * 70)
    print("  UNIFIED WORLD PIPELINE — v16 QUALIFICATION (MOCKED GPU)")
    print("=" * 70)
    print()
    print(f"  Output root: {output_root}")
    print(f"  Report path: {REPORT_OUTPUT}")
    print(f"  Mode: MOCKED (GPU stages complete immediately with mock results)")
    print()

    harness = QualificationHarness(output_root, mocked=True)

    print("Running qualification: 1 smoke + 5 headless + 5 human-like rounds...")
    print()

    report = await harness.run_qualification(headless_rounds=5, human_rounds=5)

    # Save the report to the canonical output path
    REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    report_data = asdict(report)
    report_data["_meta"] = {
        "qualification_version": "v16",
        "gpu_mode": "MOCKED",
        "note": (
            "This is a MOCKED qualification. GPU stages complete immediately "
            "with mock results. This qualifies the structural pipeline (stage "
            "ordering, gates, parity, hash binding, append-only evidence). "
            "Live GPU qualification requires a human operator with ComfyUI running."
        ),
    }
    REPORT_OUTPUT.write_text(
        json.dumps(report_data, indent=2, default=str),
        encoding="utf-8",
    )

    # Print summary
    print("-" * 70)
    print("  QUALIFICATION SUMMARY")
    print("-" * 70)
    print(f"  Total rounds:  {report.total_rounds}")
    print(f"  Passed rounds: {report.total_rounds - report.failed_rounds}")
    print(f"  Failed rounds: {report.failed_rounds}")
    print(f"  All passed:    {report.all_passed}")
    print()

    # Per-round detail
    for i, round_result in enumerate(report.rounds):
        label = "SMOKE" if i == 0 else f"{'HEADLESS' if i <= 5 else 'HUMAN'} #{i}"
        status = "PASS" if round_result.passed else "FAIL"
        hash_short = round_result.contract_hash[:16] + "..." if round_result.contract_hash else "NONE"
        stage_count = len(round_result.stage_results)
        print(f"  Round {i+1:2d} [{label:12s}]: {status}  |  stages={stage_count}  |  hash={hash_short}")
        if not round_result.passed:
            print(f"         FAILURE: stage={round_result.failure_stage}, reason={round_result.failure_reason}")

    print()

    # Contract hashes
    print("  Contract hashes:")
    for i, round_result in enumerate(report.rounds):
        print(f"    Round {i+1:2d}: {round_result.contract_hash}")

    print()

    # Failure analysis
    if report.failed_rounds > 0:
        print("  FAILURES DETECTED:")
        for i, round_result in enumerate(report.rounds):
            if not round_result.passed:
                print(f"    Round {i+1}: stage={round_result.failure_stage}")
                print(f"             reason={round_result.failure_reason}")
        print()

    print(f"  Report saved to: {REPORT_OUTPUT}")
    print()

    if report.all_passed:
        print("  ✓ ALL ROUNDS PASSED — qualification successful (mocked GPU)")
        return 0
    else:
        print("  ✗ QUALIFICATION FAILED — see failure details above")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

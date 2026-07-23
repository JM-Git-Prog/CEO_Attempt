from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.qa_evidence import (
    ALL_QA_CATEGORIES,
    AppendOnlyQALedger,
    ArtifactBinding,
    CompilerGateEvidence,
    HumanVerdict,
    QABinding,
    QADecision,
    create_human_evidence,
    create_vision_evidence,
    run_qwen_screening,
)

H = "c" * 64


def _binding() -> QABinding:
    return QABinding(
        session_id="qa-session", interface_version=11, workflow_profile_id="upbge-r1",
        plan_revision=2, canon_attempt=3,
        artifacts=(ArtifactBinding(role="canon", sha256=H),),
    )


def _payload(confidence: float = 0.8, passed: bool = True):
    return {
        "status": "completed", "passed": passed, "confidence": confidence,
        "categories": [
            {
                "category": category.value, "passed": passed,
                "confidence": confidence, "findings": [],
            }
            for category in ALL_QA_CATEGORIES
        ],
    }


def test_qwen_strict_seven_category_result_auto_passes_only_at_threshold(tmp_path):
    image = tmp_path / "canon.png"
    image.write_bytes(b"image")
    prompts: list[str] = []
    screening = run_qwen_screening(
        (image,),
        invoker=lambda prompt, paths: prompts.append(prompt) or _payload(0.8),
        user_prompt="A warm 1950s diner",
    )
    below = run_qwen_screening(
        (image,), invoker=lambda prompt, paths: _payload(0.79)
    )

    assert len(screening.categories) == 7
    assert screening.automatic_pass is True
    assert "1) Floor Plan, 2) Blockout, 3) Canon" in prompts[0]
    assert "A warm 1950s diner" in prompts[0]
    assert "Categories must be a JSON array" in prompts[0]
    assert all(category.value in prompts[0] for category in ALL_QA_CATEGORIES)
    assert create_vision_evidence(_binding(), screening).decision == QADecision.AUTO_ACCEPTED
    assert create_vision_evidence(_binding(), below).decision == QADecision.HUMAN_REQUIRED


def test_keyed_category_mapping_is_normalized_then_strictly_validated(tmp_path):
    image = tmp_path / "canon.png"
    image.write_bytes(b"image")
    keyed = _payload()
    keyed["categories"] = {
        item["category"]: {
            key: value for key, value in item.items() if key != "category"
        }
        for item in keyed["categories"]
    }

    screening = run_qwen_screening(
        (image,), invoker=lambda prompt, paths: keyed,
    )

    assert screening.status == "completed"
    assert screening.automatic_pass is True
    assert tuple(item.category for item in screening.categories) == ALL_QA_CATEGORIES


def test_malformed_or_inconsistent_vision_output_fails_closed_to_human_review(tmp_path):
    image = tmp_path / "canon.png"
    image.write_bytes(b"image")
    missing_category = _payload()
    missing_category["categories"].pop()
    inconsistent = _payload(passed=True)
    inconsistent["categories"][0]["passed"] = False

    malformed = run_qwen_screening(
        (image,), invoker=lambda prompt, paths: missing_category
    )
    contradictory = run_qwen_screening(
        (image,), invoker=lambda prompt, paths: inconsistent
    )

    assert malformed.status == "failed"
    assert contradictory.status == "failed"
    assert create_vision_evidence(_binding(), malformed).decision == QADecision.HUMAN_REQUIRED
    assert create_vision_evidence(_binding(), contradictory).decision == QADecision.HUMAN_REQUIRED


def test_unavailable_or_failed_vision_requires_human_adjudication(tmp_path):
    unavailable = run_qwen_screening((tmp_path / "missing.png",), invoker=None)
    failed = run_qwen_screening(
        (), invoker=lambda prompt, paths: (_ for _ in ()).throw(RuntimeError("offline"))
    )

    assert unavailable.status == "unavailable"
    assert failed.status == "failed"
    assert create_vision_evidence(_binding(), unavailable).decision == QADecision.HUMAN_REQUIRED
    assert create_vision_evidence(_binding(), failed).decision == QADecision.HUMAN_REQUIRED


def test_human_adjudication_requires_named_reviewer_and_rationale():
    with pytest.raises(ValidationError, match="cannot be blank"):
        HumanVerdict(reviewer_id="  ", verdict="approved", rationale="checked")
    with pytest.raises(ValidationError, match="cannot be blank"):
        HumanVerdict(reviewer_id="reviewer-1", verdict="rejected", rationale="  ")


def test_append_only_ledger_deduplicates_and_supersedes_without_deletion(tmp_path):
    ledger = AppendOnlyQALedger(tmp_path / "qa.jsonl")
    screen = run_qwen_screening((), invoker=lambda prompt, paths: _payload())
    vision = create_vision_evidence(_binding(), screen)

    first = ledger.append(vision)
    duplicate = ledger.append(vision)
    human = create_human_evidence(
        _binding(), HumanVerdict(
            reviewer_id="reviewer-1", verdict="approved", rationale="manually verified"
        )
    )
    superseding = ledger.append(human)

    assert first.appended is True
    assert duplicate.deduplicated is True
    assert superseding.entry.supersedes == vision.evidence_id
    assert len(ledger.entries()) == 2
    assert ledger.entries()[0].evidence_id == vision.evidence_id


def test_compiler_parity_and_runtime_evidence_fail_closed():
    screening = run_qwen_screening((), invoker=lambda prompt, paths: _payload())
    compiler = CompilerGateEvidence(
        parity_report_hash="d" * 64, parity_passed=True,
        runtime_smoke_report_hash="e" * 64, runtime_applicable=True,
        runtime_passed=False,
    )
    entry = create_vision_evidence(
        _binding(), screening, compiler_evidence=compiler
    )

    assert entry.decision == QADecision.COMPILER_REJECTED
    assert entry.compiler_evidence.runtime_passed is False

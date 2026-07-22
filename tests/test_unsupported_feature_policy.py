from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from src.unsupported_feature_policy import (
    FAIL_CLOSED_STAGES,
    AdapterKind,
    BuildOutcome,
    FailureStage,
    FallbackPolicy,
    FallbackTrigger,
    FeatureDisposition,
    FeatureRepresentation,
    classify_build_outcome,
    decide_fallback,
    select_primary_adapter,
)


def _upbge_to_godot_policy(**overrides) -> FallbackPolicy:
    values = {
        "primary_adapter": AdapterKind.UPBGE,
        "fallback_adapter": AdapterKind.GODOT,
        "allowed_triggers": frozenset(
            {
                FallbackTrigger.UNAVAILABLE,
                FallbackTrigger.TIMEOUT,
                FallbackTrigger.PROCESS_FAILURE,
            }
        ),
        "retry_budget": 1,
    }
    values.update(overrides)
    return FallbackPolicy(**values)


def test_declared_eligible_failure_selects_fallback_after_retry_budget():
    decision = decide_fallback(
        _upbge_to_godot_policy(),
        stage=FailureStage.COMPILE,
        trigger=FallbackTrigger.TIMEOUT,
        retries_used=1,
    )

    assert decision.allowed is True
    assert decision.selected_adapter == AdapterKind.GODOT
    assert decision.outcome_ceiling == BuildOutcome.FALLBACK_SUCCESS
    assert decision.canonical_input_required is True


def test_retryable_failure_does_not_fallback_before_budget_is_exhausted():
    decision = decide_fallback(
        _upbge_to_godot_policy(retry_budget=2),
        stage=FailureStage.COMPILE,
        trigger=FallbackTrigger.PROCESS_FAILURE,
        retries_used=1,
    )

    assert decision.allowed is False
    assert decision.reason_code == "retry_budget_remaining"


def test_no_declared_fallback_fails_without_adapter_substitution():
    policy = FallbackPolicy(primary_adapter=AdapterKind.UPBGE)

    decision = decide_fallback(
        policy,
        stage=FailureStage.CAPABILITY_PROBE,
        trigger=FallbackTrigger.UNAVAILABLE,
    )

    assert decision.allowed is False
    assert decision.selected_adapter is None
    assert decision.reason_code == "fallback_not_declared"


@pytest.mark.parametrize("stage", sorted(FAIL_CLOSED_STAGES, key=str))
def test_fail_closed_stages_never_invoke_declared_fallback(stage: FailureStage):
    decision = decide_fallback(
        _upbge_to_godot_policy(),
        stage=stage,
        trigger=FallbackTrigger.PROCESS_FAILURE,
        retries_used=1,
    )

    assert decision.allowed is False
    assert decision.reason_code == f"fail_closed:{stage.value}"


def test_runtime_smoke_failure_cannot_be_recast_as_compile_fallback():
    decision = decide_fallback(
        _upbge_to_godot_policy(),
        stage=FailureStage.RUNTIME_SMOKE,
        trigger=FallbackTrigger.PROCESS_FAILURE,
        retries_used=1,
    )

    assert decision.allowed is False
    assert decision.reason_code == "trigger_stage_mismatch"


def test_runtime_rejection_keeps_only_independently_valid_portable_output():
    outcome = classify_build_outcome(
        primary_adapter=AdapterKind.UPBGE,
        producing_adapter=AdapterKind.UPBGE,
        requested_artifacts=frozenset({"scene.glb", "playable-package"}),
        independently_valid_artifacts=frozenset({"scene.glb"}),
        runtime_artifacts=frozenset({"playable-package"}),
    )

    assert outcome == BuildOutcome.PARTIAL_EXPORT


def test_complete_fallback_is_truthfully_distinct_from_native_success():
    outcome = classify_build_outcome(
        primary_adapter=AdapterKind.UPBGE,
        producing_adapter=AdapterKind.GODOT,
        requested_artifacts=frozenset({"portable-project"}),
        independently_valid_artifacts=frozenset({"portable-project"}),
    )

    assert outcome == BuildOutcome.FALLBACK_SUCCESS


def test_regular_blender_requires_compile_only_authorization_and_cannot_claim_runtime():
    with pytest.raises(ValueError, match="compile-only"):
        FallbackPolicy(
            primary_adapter=AdapterKind.UPBGE,
            fallback_adapter=AdapterKind.REGULAR_BLENDER,
            allowed_triggers=frozenset({FallbackTrigger.UNAVAILABLE}),
        )

    with pytest.raises(ValueError, match="cannot validate UPBGE runtime"):
        classify_build_outcome(
            primary_adapter=AdapterKind.UPBGE,
            producing_adapter=AdapterKind.REGULAR_BLENDER,
            requested_artifacts=frozenset({"playable-package"}),
            independently_valid_artifacts=frozenset({"playable-package"}),
            runtime_artifacts=frozenset({"playable-package"}),
        )


@pytest.mark.parametrize(
    ("disposition", "version"),
    [
        (FeatureDisposition.SIDECAR_METADATA, "interaction-metadata/v1"),
        (FeatureDisposition.TARGET_SPECIFIC, "godot-door/v1"),
    ],
)
def test_non_native_representation_requires_explicit_version(disposition, version):
    representation = FeatureRepresentation("door.open", disposition, version)
    assert representation.declaration_version == version

    with pytest.raises(ValueError, match="explicit declaration version"):
        FeatureRepresentation("door.open", disposition)


def test_native_and_unsupported_dispositions_do_not_hide_substitution_versions():
    assert FeatureRepresentation(
        "light.punctual", FeatureDisposition.NATIVE
    ).declaration_version is None
    assert FeatureRepresentation(
        "interaction.custom", FeatureDisposition.UNSUPPORTED
    ).declaration_version is None

    with pytest.raises(ValueError, match="explicit declaration version"):
        FeatureRepresentation(
            "interaction.custom", FeatureDisposition.UNSUPPORTED, "placeholder/v1"
        )


_ELIGIBLE_TRIGGER_STAGES = [
    (FallbackTrigger.UNAVAILABLE, FailureStage.CAPABILITY_PROBE),
    (FallbackTrigger.INCOMPATIBLE, FailureStage.CAPABILITY_PROBE),
    (FallbackTrigger.TIMEOUT, FailureStage.CAPABILITY_PROBE),
    (FallbackTrigger.TIMEOUT, FailureStage.COMPILE),
    (FallbackTrigger.TIMEOUT, FailureStage.EXPORT),
    (FallbackTrigger.PROCESS_FAILURE, FailureStage.CAPABILITY_PROBE),
    (FallbackTrigger.PROCESS_FAILURE, FailureStage.COMPILE),
    (FallbackTrigger.PROCESS_FAILURE, FailureStage.EXPORT),
    (FallbackTrigger.UNSUPPORTED_REQUIRED_FEATURE, FailureStage.CAPABILITY_PROBE),
    (FallbackTrigger.UNSUPPORTED_REQUIRED_FEATURE, FailureStage.COMPILE),
    (FallbackTrigger.UNSUPPORTED_REQUIRED_FEATURE, FailureStage.EXPORT),
]


# Property 8: Fallback Transparency
# **Validates: Requirements 11.4, 11.5**
@given(
    trigger_stage=st.sampled_from(_ELIGIBLE_TRIGGER_STAGES),
    retry_budget=st.integers(min_value=0, max_value=5),
)
def test_property_fallback_transparency(trigger_stage, retry_budget):
    trigger, stage = trigger_stage
    policy = _upbge_to_godot_policy(
        allowed_triggers=frozenset({trigger}), retry_budget=retry_budget
    )

    decision = decide_fallback(
        policy, stage=stage, trigger=trigger, retries_used=retry_budget
    )
    outcome = classify_build_outcome(
        primary_adapter=policy.primary_adapter,
        producing_adapter=decision.selected_adapter,
        requested_artifacts=frozenset({"artifact"}),
        independently_valid_artifacts=frozenset({"artifact"}),
    )

    assert decision.allowed is True
    assert decision.outcome_ceiling == BuildOutcome.FALLBACK_SUCCESS
    assert outcome == BuildOutcome.FALLBACK_SUCCESS
    assert outcome != BuildOutcome.NATIVE_SUCCESS


# Property 9: Historical Stability
# **Validates: Requirements 11.1, 11.3**
@given(
    installed_before=st.sets(st.sampled_from(list(AdapterKind))),
    installed_after=st.sets(st.sampled_from(list(AdapterKind))),
)
def test_property_historical_stability(installed_before, installed_after):
    policy = _upbge_to_godot_policy(retained_profile=True)

    before = select_primary_adapter(
        policy, installed_adapters=frozenset(installed_before)
    )
    after = select_primary_adapter(
        policy, installed_adapters=frozenset(installed_after)
    )

    assert before == after == AdapterKind.UPBGE

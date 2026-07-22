"""Versioned unsupported-feature and fallback policy primitives.

This module is deliberately isolated from pipeline and adapter execution. It defines
truthful outcomes and pure profile-driven decisions before UPBGE routing exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import FrozenSet


class AdapterKind(StrEnum):
    UPBGE = "upbge"
    GODOT = "godot"
    THREE_JS = "three_js"
    REGULAR_BLENDER = "regular_blender"


class BuildOutcome(StrEnum):
    NATIVE_SUCCESS = "native_success"
    FALLBACK_SUCCESS = "fallback_success"
    PARTIAL_EXPORT = "partial_export"
    FAILURE = "failure"


class FeatureDisposition(StrEnum):
    NATIVE = "native"
    SIDECAR_METADATA = "sidecar_metadata"
    TARGET_SPECIFIC = "target_specific"
    UNSUPPORTED = "unsupported"


class FailureStage(StrEnum):
    CONTRACT = "contract"
    COMMAND_VALIDATION = "command_validation"
    CONSTRAINT_SOLVING = "constraint_solving"
    SECURITY = "security"
    CAPABILITY_PROBE = "capability_probe"
    COMPILE = "compile"
    EXPORT = "export"
    PARITY = "parity"
    RUNTIME_SMOKE = "runtime_smoke"
    QA = "qa"
    PROVENANCE = "provenance"
    FALLBACK = "fallback"


class FallbackTrigger(StrEnum):
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    TIMEOUT = "timeout"
    PROCESS_FAILURE = "process_failure"
    UNSUPPORTED_REQUIRED_FEATURE = "unsupported_required_feature"


FAIL_CLOSED_STAGES = frozenset(
    {
        FailureStage.CONTRACT,
        FailureStage.COMMAND_VALIDATION,
        FailureStage.CONSTRAINT_SOLVING,
        FailureStage.SECURITY,
        FailureStage.PARITY,
        FailureStage.QA,
        FailureStage.PROVENANCE,
        FailureStage.FALLBACK,
    }
)

_TRIGGER_STAGES = {
    FallbackTrigger.UNAVAILABLE: frozenset({FailureStage.CAPABILITY_PROBE}),
    FallbackTrigger.INCOMPATIBLE: frozenset({FailureStage.CAPABILITY_PROBE}),
    FallbackTrigger.TIMEOUT: frozenset(
        {FailureStage.CAPABILITY_PROBE, FailureStage.COMPILE, FailureStage.EXPORT}
    ),
    FallbackTrigger.PROCESS_FAILURE: frozenset(
        {FailureStage.CAPABILITY_PROBE, FailureStage.COMPILE, FailureStage.EXPORT}
    ),
    FallbackTrigger.UNSUPPORTED_REQUIRED_FEATURE: frozenset(
        {FailureStage.CAPABILITY_PROBE, FailureStage.COMPILE, FailureStage.EXPORT}
    ),
}
_RETRYABLE_TRIGGERS = frozenset(
    {FallbackTrigger.TIMEOUT, FallbackTrigger.PROCESS_FAILURE}
)


@dataclass(frozen=True)
class FeatureRepresentation:
    """An adapter's explicit, non-substituting representation of one feature."""

    feature_id: str
    disposition: FeatureDisposition
    declaration_version: str | None = None

    def __post_init__(self) -> None:
        if not self.feature_id.strip():
            raise ValueError("feature_id must be non-empty")
        requires_version = self.disposition in {
            FeatureDisposition.SIDECAR_METADATA,
            FeatureDisposition.TARGET_SPECIFIC,
        }
        if requires_version != bool(self.declaration_version):
            raise ValueError(
                "sidecar and target-specific representations require exactly one "
                "explicit declaration version"
            )


@dataclass(frozen=True)
class FallbackPolicy:
    """Immutable routing policy supplied by a workflow profile."""

    primary_adapter: AdapterKind
    fallback_adapter: AdapterKind | None = None
    allowed_triggers: FrozenSet[FallbackTrigger] = field(default_factory=frozenset)
    retry_budget: int = 0
    retained_profile: bool = False
    regular_blender_compile_only: bool = False
    schema_version: str = "fallback-policy/v1"

    def __post_init__(self) -> None:
        if self.schema_version != "fallback-policy/v1":
            raise ValueError(f"unsupported fallback policy: {self.schema_version}")
        if self.retry_budget < 0:
            raise ValueError("retry_budget must be non-negative")
        if self.fallback_adapter == self.primary_adapter:
            raise ValueError("fallback_adapter must differ from primary_adapter")
        if self.allowed_triggers and self.fallback_adapter is None:
            raise ValueError("allowed_triggers require a declared fallback_adapter")
        if (
            self.fallback_adapter == AdapterKind.REGULAR_BLENDER
            and not self.regular_blender_compile_only
        ):
            raise ValueError(
                "regular Blender requires explicit compile-only profile authorization"
            )


@dataclass(frozen=True)
class FallbackDecision:
    allowed: bool
    selected_adapter: AdapterKind | None
    reason_code: str
    outcome_ceiling: BuildOutcome
    canonical_input_required: bool = True


def select_primary_adapter(
    policy: FallbackPolicy,
    *,
    installed_adapters: FrozenSet[AdapterKind] = frozenset(),
) -> AdapterKind:
    """Return profile-declared routing; installation state is evidence, not policy."""

    del installed_adapters
    return policy.primary_adapter


def decide_fallback(
    policy: FallbackPolicy,
    *,
    stage: FailureStage,
    trigger: FallbackTrigger,
    retries_used: int = 0,
) -> FallbackDecision:
    """Decide fallback without inspecting engines or mutating canonical input."""

    denied = FallbackDecision(False, None, "fallback_not_permitted", BuildOutcome.FAILURE)
    if retries_used < 0:
        raise ValueError("retries_used must be non-negative")
    if stage in FAIL_CLOSED_STAGES:
        return FallbackDecision(False, None, f"fail_closed:{stage.value}", BuildOutcome.FAILURE)
    if stage not in _TRIGGER_STAGES[trigger]:
        return FallbackDecision(
            False, None, "trigger_stage_mismatch", BuildOutcome.FAILURE
        )
    if policy.fallback_adapter is None:
        return FallbackDecision(False, None, "fallback_not_declared", BuildOutcome.FAILURE)
    if trigger not in policy.allowed_triggers:
        return denied
    if trigger in _RETRYABLE_TRIGGERS and retries_used < policy.retry_budget:
        return FallbackDecision(
            False, None, "retry_budget_remaining", BuildOutcome.FAILURE
        )
    return FallbackDecision(
        True,
        policy.fallback_adapter,
        f"declared_fallback:{trigger.value}",
        BuildOutcome.FALLBACK_SUCCESS,
    )


def classify_build_outcome(
    *,
    primary_adapter: AdapterKind,
    producing_adapter: AdapterKind | None,
    requested_artifacts: FrozenSet[str],
    independently_valid_artifacts: FrozenSet[str],
    runtime_artifacts: FrozenSet[str] = frozenset(),
) -> BuildOutcome:
    """Classify only artifacts requested and independently accepted by their gates.

    Runtime-smoke rejection therefore leaves, at most, a partial export when other
    requested portable artifacts passed their own structural and content gates.
    """

    if independently_valid_artifacts - requested_artifacts:
        raise ValueError("valid artifacts must be a subset of requested artifacts")
    if runtime_artifacts - requested_artifacts:
        raise ValueError("runtime artifacts must be a subset of requested artifacts")
    if independently_valid_artifacts and producing_adapter is None:
        raise ValueError("valid artifacts require a producing adapter")
    if (
        producing_adapter == AdapterKind.REGULAR_BLENDER
        and independently_valid_artifacts & runtime_artifacts
    ):
        raise ValueError("regular Blender cannot validate UPBGE runtime artifacts")
    if not requested_artifacts or not independently_valid_artifacts:
        return BuildOutcome.FAILURE
    if independently_valid_artifacts != requested_artifacts:
        return BuildOutcome.PARTIAL_EXPORT
    if producing_adapter == primary_adapter:
        return BuildOutcome.NATIVE_SUCCESS
    return BuildOutcome.FALLBACK_SUCCESS

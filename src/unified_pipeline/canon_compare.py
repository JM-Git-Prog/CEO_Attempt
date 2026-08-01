"""Strict three-view identity and Scene Canon fidelity evidence.

The Metric Plan remains the sole spatial authority.  This module compares
measured, evidence-only observations from the Plan-derived Blockout/blueprint,
Scene Canon, and first-person World render; it never writes geometry or camera
state back into any authority.

**Validates: Requirements 22.6, 31.1-31.4, 32.7, 33.9, 34.1, 35.1-35.5,
36.1-36.3**
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class FidelityVerdict(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class RegionKind(str, Enum):
    SHELL = "shell"
    OPENING = "opening"
    OBJECT = "object"


class ViewKind(str, Enum):
    BLOCKOUT = "blockout"
    CANON = "canon"
    WORLD = "world"


class MismatchSeverity(str, Enum):
    AMBER = "amber"
    RED = "red"


class FinalQABlockedError(ValueError):
    """Raised when configured release policy rejects comparison evidence."""


class EvidenceWriteError(ValueError):
    """Raised rather than replacing different immutable comparison evidence."""


@dataclass(frozen=True)
class ComparisonBinding:
    """Trusted authority hashes to which the report is bound."""

    plan_revision: int
    plan_hash: str
    camera_hash: str
    canon_hash: str
    world_contract_hash: str

    def __post_init__(self) -> None:
        if self.plan_revision <= 0:
            raise ValueError("plan_revision must be nonzero")
        for name in ("plan_hash", "camera_hash", "canon_hash", "world_contract_hash"):
            if not _SHA256_RE.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_revision": self.plan_revision,
            "plan_hash": self.plan_hash,
            "camera_hash": self.camera_hash,
            "canon_hash": self.canon_hash,
            "world_contract_hash": self.world_contract_hash,
        }


@dataclass(frozen=True)
class ArtifactEvidence:
    """One view artifact plus its claimed authority bindings."""

    path: str
    sha256: str
    plan_revision: int
    plan_hash: str
    camera_hash: str
    canon_hash: str
    world_contract_hash: str
    source_approved: bool
    approval_revision: int
    provenance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "plan_revision": self.plan_revision,
            "plan_hash": self.plan_hash,
            "camera_hash": self.camera_hash,
            "canon_hash": self.canon_hash,
            "world_contract_hash": self.world_contract_hash,
            "source_approved": self.source_approved,
            "approval_revision": self.approval_revision,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class RegionObservation:
    """Measured region observation; never an authoritative transform source."""

    region_id: str
    kind: RegionKind
    position_m: tuple[float, float, float]
    dimensions_m: tuple[float, float, float]
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    stable_uuid: str = ""
    category: str = ""
    present: bool = True
    forbidden_overlap_ids: tuple[str, ...] = ()
    palette: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()
    prompt_tags: tuple[str, ...] = ()
    prompt_fidelity: float = 0.0

    @property
    def subject_id(self) -> str:
        return self.stable_uuid if self.kind is RegionKind.OBJECT else self.region_id

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.subject_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "kind": self.kind.value,
            "stable_uuid": self.stable_uuid,
            "category": self.category,
            "position_m": list(self.position_m),
            "dimensions_m": list(self.dimensions_m),
            "rotation_deg": list(self.rotation_deg),
            "present": self.present,
            "forbidden_overlap_ids": list(self.forbidden_overlap_ids),
            "palette": list(self.palette),
            "materials": list(self.materials),
            "prompt_tags": list(self.prompt_tags),
            "prompt_fidelity": self.prompt_fidelity,
        }


@dataclass(frozen=True)
class ViewEvidence:
    """Measured observations for one of the three required views."""

    kind: ViewKind
    artifact: ArtifactEvidence
    regions: tuple[RegionObservation, ...]
    authority_claim: str = "evidence_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "artifact": self.artifact.to_dict(),
            "authority_claim": self.authority_claim,
            "regions": [region.to_dict() for region in self.regions],
        }


@dataclass(frozen=True)
class FidelityIntent:
    """Approved appearance and prompt intent for one UUID or named region."""

    kind: RegionKind
    subject_id: str
    category: str
    palette: tuple[str, ...]
    materials: tuple[str, ...]
    prompt_tags: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.subject_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "category": self.category,
            "palette": list(self.palette),
            "materials": list(self.materials),
            "prompt_tags": list(self.prompt_tags),
        }


@dataclass(frozen=True)
class ComparisonRequest:
    """Manifest identity and appearance expectations for strict comparison."""

    requested_object_uuids: tuple[str, ...]
    intents: tuple[FidelityIntent, ...]
    forbidden_overlap_pairs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.requested_object_uuids)) != len(self.requested_object_uuids):
            raise ValueError("requested object UUIDs must be unique")
        if any(not _is_canonical_uuid(value) for value in self.requested_object_uuids):
            raise ValueError("requested object identities must be canonical stable UUIDs")
        keys = [intent.key for intent in self.intents]
        if len(set(keys)) != len(keys):
            raise ValueError("fidelity intents must have unique UUID/region keys")
        if any(
            intent.kind is RegionKind.OBJECT
            and not _is_canonical_uuid(intent.subject_id)
            for intent in self.intents
        ):
            raise ValueError("object fidelity intents must use canonical stable UUIDs")
        object.__setattr__(
            self, "requested_object_uuids", tuple(sorted(self.requested_object_uuids))
        )
        object.__setattr__(
            self, "intents", tuple(sorted(self.intents, key=lambda item: item.key))
        )
        normalized_pairs = tuple(sorted(
            tuple(sorted((str(left), str(right))))
            for left, right in self.forbidden_overlap_pairs
        ))
        if len(set(normalized_pairs)) != len(normalized_pairs):
            raise ValueError("forbidden overlap pairs must be unique")
        object.__setattr__(self, "forbidden_overlap_pairs", normalized_pairs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_object_uuids": list(self.requested_object_uuids),
            "intents": [intent.to_dict() for intent in self.intents],
            "forbidden_overlap_pairs": [list(pair) for pair in self.forbidden_overlap_pairs],
        }


@dataclass(frozen=True)
class ComparisonThresholds:
    placement_tolerance_m: float = 0.05
    dimension_absolute_tolerance_m: float = 0.03
    dimension_relative_tolerance: float = 0.05
    extent_absolute_tolerance_m: float = 0.04
    extent_relative_tolerance: float = 0.05
    palette_distance: float = 0.08
    prompt_fidelity_minimum: float = 0.80

    def __post_init__(self) -> None:
        values = self.to_dict().values()
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("comparison thresholds must be finite and non-negative")
        if self.palette_distance > 1.0 or self.prompt_fidelity_minimum > 1.0:
            raise ValueError("normalized comparison thresholds cannot exceed 1")

    def to_dict(self) -> dict[str, float]:
        return {
            "placement_tolerance_m": self.placement_tolerance_m,
            "dimension_absolute_tolerance_m": self.dimension_absolute_tolerance_m,
            "dimension_relative_tolerance": self.dimension_relative_tolerance,
            "extent_absolute_tolerance_m": self.extent_absolute_tolerance_m,
            "extent_relative_tolerance": self.extent_relative_tolerance,
            "palette_distance": self.palette_distance,
            "prompt_fidelity_minimum": self.prompt_fidelity_minimum,
        }


@dataclass(frozen=True)
class FidelityMismatch:
    check: str
    severity: MismatchSeverity
    code: str
    view: str
    subject_id: str
    metric: str
    expected: str
    actual: str
    discrepancy: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity.value,
            "code": self.code,
            "view": self.view,
            "subject_id": self.subject_id,
            "metric": self.metric,
            "expected": self.expected,
            "actual": self.actual,
            "discrepancy": self.discrepancy,
        }


@dataclass(frozen=True)
class ComparisonCheck:
    name: str
    passed: bool
    mismatch_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "mismatch_codes": list(self.mismatch_codes),
        }


@dataclass(frozen=True)
class ThreeViewIdentityReport:
    schema_version: str
    binding: ComparisonBinding
    verdict: FidelityVerdict
    thresholds: ComparisonThresholds
    request: ComparisonRequest
    artifact_hashes: tuple[tuple[str, str], ...]
    checks: tuple[ComparisonCheck, ...]
    mismatches: tuple[FidelityMismatch, ...]
    human_review_required: bool = True
    evidence_hash: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict is FidelityVerdict.GREEN

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "binding": self.binding.to_dict(),
            "verdict": self.verdict.value,
            "thresholds": self.thresholds.to_dict(),
            "request": self.request.to_dict(),
            "artifact_hashes": {name: digest for name, digest in self.artifact_hashes},
            "checks": [check.to_dict() for check in self.checks],
            "mismatches": [mismatch.to_dict() for mismatch in self.mismatches],
            "human_review_required": self.human_review_required,
        }
        if include_hash:
            payload["evidence_hash"] = self.evidence_hash
        return payload

    def verify_hash(self) -> bool:
        return self.evidence_hash == _payload_hash(self.to_dict(include_hash=False))


@dataclass(frozen=True)
class ReleasePolicy:
    """Configured final-QA policy; release defaults fail closed on amber and red."""

    name: str = "strict-release"
    block_amber: bool = True
    block_red: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("release policy name must be non-empty")
        if not isinstance(self.block_amber, bool) or not isinstance(self.block_red, bool):
            raise ValueError("release policy block settings must be explicit booleans")


@dataclass(frozen=True)
class FinalQAToken:
    evidence_hash: str
    plan_revision: int
    plan_hash: str
    camera_hash: str
    canon_hash: str
    world_contract_hash: str
    policy_name: str
    verdict: FidelityVerdict
    human_review_required: bool = True


_CHECK_NAMES = (
    "binding",
    "stable_identity",
    "shell_opening_truth",
    "requested_objects",
    "placement",
    "rotation_aware_extents",
    "dimensions_heights",
    "forbidden_overlap",
    "palette_material_fidelity",
    "prompt_fidelity",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_canonical_uuid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return False
    return str(parsed) == value.lower()


def _normalized_tokens(values: Iterable[str]) -> set[str]:
    return {" ".join(value.casefold().split()) for value in values if value.strip()}


def _vector_string(value: Iterable[float]) -> str:
    return "[" + ",".join(f"{item:.6g}" for item in value) + "]"


def _finite_vector(value: tuple[float, float, float], *, positive: bool = False) -> bool:
    return (
        len(value) == 3
        and all(math.isfinite(item) for item in value)
        and (not positive or all(item > 0.0 for item in value))
    )


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b)))


def _within(expected: float, actual: float, absolute: float, relative: float) -> bool:
    return abs(expected - actual) <= max(absolute, abs(expected) * relative)


def rotation_aware_extents(region: RegionObservation) -> tuple[float, float, float]:
    """Return world-axis full extents for XYZ Euler rotation in degrees."""

    rx, ry, rz = (math.radians(value) for value in region.rotation_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    matrix = (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )
    half = tuple(value / 2.0 for value in region.dimensions_m)
    world_half = tuple(
        sum(abs(matrix[row][column]) * half[column] for column in range(3))
        for row in range(3)
    )
    return tuple(value * 2.0 for value in world_half)


def _palette_distance(expected: str, actual: str) -> float:
    if not _HEX_COLOR_RE.fullmatch(expected) or not _HEX_COLOR_RE.fullmatch(actual):
        return math.inf
    left = tuple(int(expected[index:index + 2], 16) for index in (1, 3, 5))
    right = tuple(int(actual[index:index + 2], 16) for index in (1, 3, 5))
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right))) / math.sqrt(3 * 255**2)


def _boxes_overlap(left: RegionObservation, right: RegionObservation) -> bool:
    left_extent = rotation_aware_extents(left)
    right_extent = rotation_aware_extents(right)
    return all(
        abs(left.position_m[index] - right.position_m[index])
        < (left_extent[index] + right_extent[index]) / 2.0 - 1e-9
        for index in range(3)
    )


class ThreeViewIdentityComparator:
    """Compare three measured views without mutating any authority artifact."""

    schema_version = "three-view-identity/v1"

    def __init__(self, thresholds: ComparisonThresholds | None = None) -> None:
        self.thresholds = thresholds or ComparisonThresholds()

    def compare(
        self,
        blockout: ViewEvidence,
        canon: ViewEvidence,
        world: ViewEvidence,
        *,
        binding: ComparisonBinding,
        request: ComparisonRequest,
    ) -> ThreeViewIdentityReport:
        mismatches: list[FidelityMismatch] = []
        views = (blockout, canon, world)
        expected_kinds = (ViewKind.BLOCKOUT, ViewKind.CANON, ViewKind.WORLD)
        for view, expected_kind in zip(views, expected_kinds):
            if view.kind is not expected_kind:
                self._add(
                    mismatches, "binding", MismatchSeverity.RED,
                    "view.kind", view.kind.value, "view", expected_kind.value,
                    view.kind.value,
                )
            self._check_binding(view, binding, mismatches)

        indices: dict[ViewKind, dict[str, RegionObservation]] = {}
        valid_keys: dict[ViewKind, set[str]] = {}
        for view in views:
            index: dict[str, RegionObservation] = {}
            valid: set[str] = set()
            for region in view.regions:
                if not region.subject_id:
                    self._add(
                        mismatches, "stable_identity", MismatchSeverity.RED,
                        "identity.empty", view.kind.value, region.region_id,
                        "stable UUID/region", "non-empty", "empty",
                    )
                    continue
                if region.kind is RegionKind.OBJECT and not region.stable_uuid:
                    self._add(
                        mismatches, "stable_identity", MismatchSeverity.RED,
                        "identity.object_uuid", view.kind.value, region.region_id,
                        "stable_uuid", "canonical UUID", "empty",
                    )
                    continue
                if region.kind is RegionKind.OBJECT and not _is_canonical_uuid(region.stable_uuid):
                    self._add(
                        mismatches, "stable_identity", MismatchSeverity.RED,
                        "identity.object_uuid_format", view.kind.value, region.region_id,
                        "stable_uuid", "canonical UUID", region.stable_uuid,
                    )
                if not region.category.strip():
                    self._add(
                        mismatches, "stable_identity", MismatchSeverity.RED,
                        "identity.category_missing", view.kind.value, region.subject_id,
                        "category", "explicit category", "empty",
                    )
                if region.key in index:
                    self._add(
                        mismatches, "stable_identity", MismatchSeverity.RED,
                        "identity.duplicate", view.kind.value, region.subject_id,
                        "membership", "one observation", "duplicate",
                    )
                    continue
                index[region.key] = region
                if (
                    _finite_vector(region.position_m)
                    and _finite_vector(region.dimensions_m, positive=True)
                    and _finite_vector(region.rotation_deg)
                    and math.isfinite(region.prompt_fidelity)
                    and 0.0 <= region.prompt_fidelity <= 1.0
                ):
                    valid.add(region.key)
                else:
                    self._add(
                        mismatches, "binding", MismatchSeverity.RED,
                        "measurement.invalid", view.kind.value, region.subject_id,
                        "measurement", "finite positive dimensions and normalized score",
                        "invalid",
                    )
            indices[view.kind] = index
            valid_keys[view.kind] = valid

        authority = indices.get(ViewKind.BLOCKOUT, {})
        shells = [item for item in authority.values() if item.kind is RegionKind.SHELL]
        if not shells:
            self._add(
                mismatches, "shell_opening_truth", MismatchSeverity.RED,
                "shell.missing", ViewKind.BLOCKOUT.value, "shell",
                "membership", "at least one Plan-derived shell region", "none",
            )

        authority_keys = set(authority)
        requested_keys = {f"object:{value}" for value in request.requested_object_uuids}
        authority_object_keys = {
            key for key, value in authority.items() if value.kind is RegionKind.OBJECT
        }
        for key in sorted(authority_object_keys - requested_keys):
            self._add(
                mismatches, "stable_identity", MismatchSeverity.RED,
                "identity.unrequested_object", ViewKind.BLOCKOUT.value,
                authority[key].subject_id, "membership", "requested stable UUID", "unrequested",
            )

        for view in views:
            index = indices.get(view.kind, {})
            for key in sorted(authority_keys - set(index)):
                authority_region = authority[key]
                check = (
                    "requested_objects" if authority_region.kind is RegionKind.OBJECT
                    else "shell_opening_truth"
                )
                self._add(
                    mismatches, check, MismatchSeverity.RED,
                    "identity.missing_region", view.kind.value,
                    authority_region.subject_id, "membership", "present", "missing",
                )
            for key in sorted(set(index) - authority_keys):
                self._add(
                    mismatches, "stable_identity", MismatchSeverity.RED,
                    "identity.unplanned_region", view.kind.value,
                    index[key].subject_id, "membership", "Plan-derived region", "extra",
                )
            for region in index.values():
                if not region.present:
                    check = (
                        "requested_objects" if region.kind is RegionKind.OBJECT
                        else "shell_opening_truth"
                    )
                    self._add(
                        mismatches, check, MismatchSeverity.RED,
                        "identity.not_present", view.kind.value, region.subject_id,
                        "presence", "present", "not present",
                    )

        for key in sorted(requested_keys):
            for view in views:
                if key not in indices.get(view.kind, {}):
                    self._add(
                        mismatches, "requested_objects", MismatchSeverity.RED,
                        "object.requested_missing", view.kind.value,
                        key.split(":", 1)[1], "requested UUID", "present", "missing",
                    )

        for target_view in (ViewKind.CANON, ViewKind.WORLD):
            target = indices.get(target_view, {})
            for key, expected in authority.items():
                actual = target.get(key)
                if (
                    actual is None
                    or key not in valid_keys.get(ViewKind.BLOCKOUT, set())
                    or key not in valid_keys.get(target_view, set())
                ):
                    continue
                severity = (
                    MismatchSeverity.RED
                    if expected.kind in (RegionKind.SHELL, RegionKind.OPENING)
                    else MismatchSeverity.AMBER
                )
                if " ".join(expected.category.casefold().split()) != " ".join(
                    actual.category.casefold().split()
                ):
                    self._add(
                        mismatches, "stable_identity", MismatchSeverity.RED,
                        "identity.category", target_view.value, expected.subject_id,
                        "category", expected.category, actual.category,
                    )
                self._compare_geometry(expected, actual, target_view, severity, mismatches)

        self._check_overlap(views, indices, request, mismatches)
        self._check_appearance(canon, world, indices, authority, request, mismatches)
        mismatches.sort(key=lambda item: (
            item.check, item.code, item.view, item.subject_id, item.metric,
            item.expected, item.actual,
            -1.0 if item.discrepancy is None else item.discrepancy,
        ))

        checks = tuple(
            ComparisonCheck(
                name=name,
                passed=not any(item.check == name for item in mismatches),
                mismatch_codes=tuple(
                    item.code for item in mismatches if item.check == name
                ),
            )
            for name in _CHECK_NAMES
        )
        verdict = FidelityVerdict.GREEN
        if any(item.severity is MismatchSeverity.RED for item in mismatches):
            verdict = FidelityVerdict.RED
        elif mismatches:
            verdict = FidelityVerdict.AMBER
        report = ThreeViewIdentityReport(
            schema_version=self.schema_version,
            binding=binding,
            verdict=verdict,
            thresholds=self.thresholds,
            request=request,
            artifact_hashes=tuple(
                (view.kind.value, view.artifact.sha256) for view in views
            ),
            checks=checks,
            mismatches=tuple(mismatches),
        )
        return replace(
            report,
            evidence_hash=_payload_hash(report.to_dict(include_hash=False)),
        )

    @staticmethod
    def _add(
        mismatches: list[FidelityMismatch],
        check: str,
        severity: MismatchSeverity,
        code: str,
        view: str,
        subject_id: str,
        metric: str,
        expected: str,
        actual: str,
        discrepancy: float | None = None,
    ) -> None:
        mismatches.append(FidelityMismatch(
            check, severity, code, view, subject_id, metric,
            expected, actual, discrepancy,
        ))

    def _check_binding(
        self,
        view: ViewEvidence,
        binding: ComparisonBinding,
        mismatches: list[FidelityMismatch],
    ) -> None:
        if view.authority_claim != "evidence_only":
            self._add(
                mismatches, "binding", MismatchSeverity.RED,
                "authority.forbidden_claim", view.kind.value, view.kind.value,
                "authority_claim", "evidence_only", view.authority_claim,
            )
        artifact = view.artifact
        expected_provenance = {
            ViewKind.BLOCKOUT: "approved_plan_blockout",
            ViewKind.CANON: "approved_scene_canon",
            ViewKind.WORLD: "world_contract_render",
        }[view.kind]
        if (
            not artifact.source_approved
            or artifact.approval_revision <= 0
            or artifact.provenance != expected_provenance
        ):
            self._add(
                mismatches, "binding", MismatchSeverity.RED,
                "provenance.unapproved_or_mismatched", view.kind.value,
                view.kind.value, "approved provenance",
                f"{expected_provenance}@positive-revision",
                f"{artifact.provenance}@{artifact.approval_revision}; approved={artifact.source_approved}",
            )
        for name, expected in binding.to_dict().items():
            actual = getattr(artifact, name)
            if actual != expected:
                self._add(
                    mismatches, "binding", MismatchSeverity.RED,
                    f"binding.{name}_drift", view.kind.value, view.kind.value,
                    name, str(expected), str(actual),
                )
        path = Path(artifact.path)
        if not _SHA256_RE.fullmatch(artifact.sha256):
            self._add(
                mismatches, "binding", MismatchSeverity.RED,
                "artifact.invalid_hash", view.kind.value, view.kind.value,
                "artifact_sha256", "lowercase SHA-256", artifact.sha256,
            )
        if not path.is_file():
            self._add(
                mismatches, "binding", MismatchSeverity.RED,
                "artifact.missing", view.kind.value, view.kind.value,
                "artifact_path", "existing file", artifact.path,
            )
        else:
            actual_hash = _file_hash(path)
            if actual_hash != artifact.sha256:
                self._add(
                    mismatches, "binding", MismatchSeverity.RED,
                    "artifact.hash_drift", view.kind.value, view.kind.value,
                    "artifact_sha256", artifact.sha256, actual_hash,
                )

    def _compare_geometry(
        self,
        expected: RegionObservation,
        actual: RegionObservation,
        view: ViewKind,
        severity: MismatchSeverity,
        mismatches: list[FidelityMismatch],
    ) -> None:
        placement_delta = _distance(expected.position_m, actual.position_m)
        if placement_delta > self.thresholds.placement_tolerance_m:
            self._add(
                mismatches, "placement", severity, "geometry.placement",
                view.value, expected.subject_id, "position_m",
                _vector_string(expected.position_m), _vector_string(actual.position_m),
                placement_delta,
            )

        planar_failures = []
        for index, axis in ((0, "width"), (2, "depth")):
            if not _within(
                expected.dimensions_m[index], actual.dimensions_m[index],
                self.thresholds.dimension_absolute_tolerance_m,
                self.thresholds.dimension_relative_tolerance,
            ):
                planar_failures.append(axis)
        if planar_failures:
            self._add(
                mismatches, "dimensions_heights", severity,
                "geometry.dimensions", view.value, expected.subject_id,
                ",".join(planar_failures), _vector_string(expected.dimensions_m),
                _vector_string(actual.dimensions_m),
                max(
                    abs(expected.dimensions_m[index] - actual.dimensions_m[index])
                    for index in (0, 2)
                ),
            )
        if not _within(
            expected.dimensions_m[1], actual.dimensions_m[1],
            self.thresholds.dimension_absolute_tolerance_m,
            self.thresholds.dimension_relative_tolerance,
        ):
            self._add(
                mismatches, "dimensions_heights", severity,
                "geometry.height", view.value, expected.subject_id, "height_m",
                str(expected.dimensions_m[1]), str(actual.dimensions_m[1]),
                abs(expected.dimensions_m[1] - actual.dimensions_m[1]),
            )

        expected_extents = rotation_aware_extents(expected)
        actual_extents = rotation_aware_extents(actual)
        if any(
            not _within(
                expected_extents[index], actual_extents[index],
                self.thresholds.extent_absolute_tolerance_m,
                self.thresholds.extent_relative_tolerance,
            )
            for index in range(3)
        ):
            self._add(
                mismatches, "rotation_aware_extents", severity,
                "geometry.rotation_aware_extents", view.value,
                expected.subject_id, "world_aabb_extents_m",
                _vector_string(expected_extents), _vector_string(actual_extents),
                max(abs(a - b) for a, b in zip(expected_extents, actual_extents)),
            )

    def _check_overlap(
        self,
        views: tuple[ViewEvidence, ...],
        indices: dict[ViewKind, dict[str, RegionObservation]],
        request: ComparisonRequest,
        mismatches: list[FidelityMismatch],
    ) -> None:
        for view in views:
            index = indices.get(view.kind, {})
            for region in index.values():
                if region.forbidden_overlap_ids:
                    self._add(
                        mismatches, "forbidden_overlap", MismatchSeverity.RED,
                        "overlap.measured", view.kind.value, region.subject_id,
                        "forbidden_overlap_ids", "[]",
                        _canonical_json(sorted(region.forbidden_overlap_ids)),
                    )
            for left_key, right_key in request.forbidden_overlap_pairs:
                left, right = index.get(left_key), index.get(right_key)
                if left is not None and right is not None and _boxes_overlap(left, right):
                    self._add(
                        mismatches, "forbidden_overlap", MismatchSeverity.RED,
                        "overlap.computed", view.kind.value,
                        f"{left.subject_id}|{right.subject_id}", "AABB intersection",
                        "zero", "overlap",
                    )

    def _check_appearance(
        self,
        canon: ViewEvidence,
        world: ViewEvidence,
        indices: dict[ViewKind, dict[str, RegionObservation]],
        authority: dict[str, RegionObservation],
        request: ComparisonRequest,
        mismatches: list[FidelityMismatch],
    ) -> None:
        intents = {intent.key: intent for intent in request.intents}
        for key, authority_region in authority.items():
            if key not in intents:
                self._add(
                    mismatches, "palette_material_fidelity", MismatchSeverity.AMBER,
                    "appearance.intent_missing", "request", authority_region.subject_id,
                    "appearance intent", "palette and materials", "missing",
                )
                self._add(
                    mismatches, "prompt_fidelity", MismatchSeverity.AMBER,
                    "prompt.intent_missing", "request", authority_region.subject_id,
                    "prompt tags", "non-empty", "missing",
                )

        for key, intent in intents.items():
            if key not in authority:
                self._add(
                    mismatches, "stable_identity", MismatchSeverity.RED,
                    "identity.intent_without_plan_region", "request", intent.subject_id,
                    "intent subject", "Plan-derived UUID/region", "missing",
                )
                continue
            authority_category = " ".join(authority[key].category.casefold().split())
            intent_category = " ".join(intent.category.casefold().split())
            if not intent_category or intent_category != authority_category:
                self._add(
                    mismatches, "stable_identity", MismatchSeverity.RED,
                    "identity.category_intent", "request", intent.subject_id,
                    "category", authority[key].category, intent.category or "empty",
                )
            if not intent.palette or not all(
                _HEX_COLOR_RE.fullmatch(color) for color in intent.palette
            ):
                self._add(
                    mismatches, "palette_material_fidelity", MismatchSeverity.AMBER,
                    "appearance.palette_intent_invalid", "request", intent.subject_id,
                    "palette intent", "non-empty #RRGGBB colors",
                    _canonical_json(intent.palette),
                )
            if not _normalized_tokens(intent.materials):
                self._add(
                    mismatches, "palette_material_fidelity", MismatchSeverity.AMBER,
                    "appearance.material_intent_missing", "request", intent.subject_id,
                    "material intent", "non-empty", "missing",
                )
            if not _normalized_tokens(intent.prompt_tags):
                self._add(
                    mismatches, "prompt_fidelity", MismatchSeverity.AMBER,
                    "prompt.intent_empty", "request", intent.subject_id,
                    "prompt tags", "non-empty", "missing",
                )

            for view in (canon, world):
                observed = indices.get(view.kind, {}).get(key)
                if observed is None:
                    continue
                for expected_color in intent.palette:
                    distances = [
                        _palette_distance(expected_color, actual_color)
                        for actual_color in observed.palette
                    ]
                    best = min(distances, default=math.inf)
                    if best > self.thresholds.palette_distance:
                        self._add(
                            mismatches, "palette_material_fidelity",
                            MismatchSeverity.AMBER, "appearance.palette",
                            view.kind.value, intent.subject_id, "palette_distance",
                            expected_color, _canonical_json(observed.palette), best,
                        )
                expected_materials = _normalized_tokens(intent.materials)
                observed_materials = _normalized_tokens(observed.materials)
                missing_materials = expected_materials - observed_materials
                if missing_materials:
                    self._add(
                        mismatches, "palette_material_fidelity",
                        MismatchSeverity.AMBER, "appearance.material",
                        view.kind.value, intent.subject_id, "materials",
                        _canonical_json(sorted(expected_materials)),
                        _canonical_json(sorted(observed_materials)),
                    )
                expected_tags = _normalized_tokens(intent.prompt_tags)
                observed_tags = _normalized_tokens(observed.prompt_tags)
                missing_tags = expected_tags - observed_tags
                if missing_tags:
                    self._add(
                        mismatches, "prompt_fidelity", MismatchSeverity.AMBER,
                        "prompt.tags", view.kind.value, intent.subject_id,
                        "prompt_tags", _canonical_json(sorted(expected_tags)),
                        _canonical_json(sorted(observed_tags)),
                    )
                if observed.prompt_fidelity < self.thresholds.prompt_fidelity_minimum:
                    self._add(
                        mismatches, "prompt_fidelity", MismatchSeverity.AMBER,
                        "prompt.score", view.kind.value, intent.subject_id,
                        "prompt_fidelity", str(self.thresholds.prompt_fidelity_minimum),
                        str(observed.prompt_fidelity),
                        self.thresholds.prompt_fidelity_minimum - observed.prompt_fidelity,
                    )


def authorize_final_qa(
    report: ThreeViewIdentityReport,
    policy: ReleasePolicy | None = None,
) -> FinalQAToken:
    """Authorize final QA only when the configured policy accepts the verdict."""

    selected = policy or ReleasePolicy()
    if not report.verify_hash():
        raise FinalQABlockedError("final QA blocked: comparison evidence hash is invalid")
    blocked = (
        report.verdict is FidelityVerdict.RED and selected.block_red
    ) or (
        report.verdict is FidelityVerdict.AMBER and selected.block_amber
    )
    if blocked:
        raise FinalQABlockedError(
            f"final QA blocked by {selected.name}: three-view verdict is "
            f"{report.verdict.value}"
        )
    return FinalQAToken(
        evidence_hash=report.evidence_hash,
        plan_revision=report.binding.plan_revision,
        plan_hash=report.binding.plan_hash,
        camera_hash=report.binding.camera_hash,
        canon_hash=report.binding.canon_hash,
        world_contract_hash=report.binding.world_contract_hash,
        policy_name=selected.name,
        verdict=report.verdict,
        human_review_required=True,
    )


def store_evidence(
    report: ThreeViewIdentityReport,
    evidence_directory: str | Path,
    *,
    stored_at_utc: str | None = None,
) -> Path:
    """Append one immutable report record and never replace existing evidence."""

    if not report.verify_hash():
        raise EvidenceWriteError("cannot store comparison evidence with an invalid hash")
    directory = Path(evidence_directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"three_view_identity_{report.evidence_hash}.json"
    timestamp = stored_at_utc or datetime.now(timezone.utc).isoformat()
    envelope = {
        "record_type": "three_view_identity_evidence",
        "stored_at_utc": timestamp,
        "release_evidence_eligible": report.verdict is FidelityVerdict.GREEN,
        "report": report.to_dict(),
    }
    encoded = (_canonical_json(envelope) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceWriteError(
                f"existing evidence is unreadable and will not be replaced: {path}"
            ) from exc
        if existing.get("report") != report.to_dict():
            raise EvidenceWriteError(
                f"immutable evidence collision; refusing replacement: {path}"
            )
        return path
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path

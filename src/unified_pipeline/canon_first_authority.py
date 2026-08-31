"""Canon-first bridge to candidate Plan/Camera authority.

Durable Brief intent and constrained deterministic planning own space. Canon
inventory is used only to prove semantic identity, and DA3 remains an optional
non-authoritative reference. Human authority is intentionally deferred to the
subsequent blockout approval stage.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.depth_bridge import FORBIDDEN_DEPTH_AUTHORITIES
from src.unified_pipeline.models import Brief, MetricPlan
from src.unified_pipeline.object_manifest import file_sha256
from src.unified_pipeline.plan_generator import MetricPlanGenerator
from src.unified_pipeline.plan_validator import MIN_CIRCULATION_WIDTH, PlanValidator


class CandidateAuthorityError(RuntimeError):
    """Candidate authority could not be established without ambiguity."""


_CONCEPTS: dict[str, dict[str, frozenset[str]]] = {
    "table": {
        "brief": frozenset({"table", "round table", "dining table"}),
        "detected": frozenset({"table", "round table", "dining table"}),
        "categories": frozenset({"furniture"}),
    },
    "chair": {
        "brief": frozenset({"chair", "chairs", "two chairs"}),
        "detected": frozenset({"chair", "chairs", "dining chair"}),
        "categories": frozenset({"furniture"}),
    },
    "window": {
        "brief": frozenset({"window", "rain window"}),
        "detected": frozenset({"window", "rain window"}),
        "categories": frozenset({"architectural"}),
    },
    "counter": {
        "brief": frozenset({
            "counter",
            "countertop",
            "kitchen counter",
            "built in counter",
            "cabinet",
            "cabinet/storage",
        }),
        "detected": frozenset({
            "counter",
            "countertop",
            "kitchen counter",
            "built in counter",
            "cabinet",
            "cabinet/storage",
        }),
        "categories": frozenset({"architectural", "furniture", "storage"}),
    },
    "coffee_maker": {
        "brief": frozenset({"coffee maker", "coffee machine", "coffeemaker"}),
        "detected": frozenset({"coffee maker", "coffee machine", "coffeemaker"}),
        "categories": frozenset({"appliance"}),
    },
}


def canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_name(value: Any) -> str:
    return " ".join(str(value).strip().casefold().replace("-", " ").split())


def _semantic_concept(name: str, *, source: str) -> str | None:
    normalized = _normalized_name(name)
    for concept, rules in _CONCEPTS.items():
        if normalized in rules[source]:
            return concept
    return None


# Minimum intersection-over-union at which two same-concept detections are
# treated as one over-segmented physical surface rather than two distinct
# objects. Vision models routinely report one counter as "counter"+"countertop"
# (or two adjacent segments of an L-shaped surface) with heavily overlapping
# boxes; a genuine second object sits in a spatially disjoint box. This gate is
# identity/inventory only — coalescing never emits coordinates or scale.
_OVERSEGMENT_IOU = 0.5


def _bbox(item: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    raw = item.get("bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _iou(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    """Intersection-over-union of two detection boxes; 0.0 if either lacks one."""
    box_a = _bbox(a)
    box_b = _bbox(b)
    if box_a is None or box_b is None:
        return 0.0
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0.0:
        return 0.0
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def _coalesce_oversegmented(
    matches: list[Mapping[str, Any]],
) -> list[list[Mapping[str, Any]]]:
    """Group same-concept detections that overlap into one physical surface.

    Returns a list of groups, each a list of detections that transitively
    overlap (IoU >= threshold). One group == one physical object. Spatially
    disjoint detections form their own single-member groups and therefore
    remain distinct (genuine duplicates stay ambiguous downstream). Order is
    deterministic: groups are keyed and sorted by their lowest detection_index.
    """
    def _index(item: Mapping[str, Any]) -> int:
        return int(item.get("detection_index", 0))

    ordered = sorted(matches, key=lambda item: (_index(item), str(item.get("object_id", ""))))
    groups: list[list[Mapping[str, Any]]] = []
    for item in ordered:
        placed = False
        for group in groups:
            if any(_iou(item, member) >= _OVERSEGMENT_IOU for member in group):
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])
    groups.sort(key=lambda group: min(_index(member) for member in group))
    return groups


def _bind_semantic_observations(
    brief: Brief, detected: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate required semantic observations before any Plan is generated.

    This is an identity/inventory gate only. It cannot emit coordinates,
    transforms, dimensions, openings, or any other spatial constraint.
    """
    detections = detected.get("objects", [])
    if not isinstance(detections, list):
        raise CandidateAuthorityError("detected object inventory is invalid")
    used_detection_ids: set[str] = set()
    bindings: list[dict[str, Any]] = []

    for manifest in brief.object_manifest:
        try:
            uuid.UUID(str(manifest.id))
        except (ValueError, AttributeError) as exc:
            raise CandidateAuthorityError(
                f"Brief manifest identity is not a stable UUID: {manifest.id!r}"
            ) from exc
        concept = _semantic_concept(manifest.name, source="brief")
        if concept is None:
            raise CandidateAuthorityError(
                f"required Brief object has no constrained semantic rule: {manifest.name!r}"
            )
        rules = _CONCEPTS[concept]
        matches = []
        for item in detections:
            if not isinstance(item, Mapping):
                continue
            detection_id = str(item.get("object_id", ""))
            detection_concept = _semantic_concept(
                str(item.get("name", "")), source="detected"
            )
            category = _normalized_name(item.get("category", ""))
            if (
                detection_id
                and detection_id not in used_detection_ids
                and detection_concept == concept
                and category in rules["categories"]
            ):
                matches.append(item)
        matches.sort(
            key=lambda item: (
                int(item.get("detection_index", 0)),
                str(item.get("object_id", "")),
            )
        )
        required_count = int(manifest.count)
        if len(matches) < required_count:
            raise CandidateAuthorityError(
                f"missing required semantic observations for {manifest.name!r}: "
                f"expected {required_count}, found {len(matches)}"
            )

        # Surplus detections are reconciled in two layered steps, and the Brief
        # manifest count is the authority throughout (identity intent owns the
        # count; vision observations never override it).
        #
        #   1. Coalesce over-SEGMENTATION: one physical surface reported as
        #      multiple overlapping boxes (e.g. "counter"+"countertop") merges
        #      into a single object via bbox IoU.
        #   2. Coalesced/counted down to the required N: if spatially DISTINCT
        #      instances still exceed the Brief count (e.g. vision finds 3 chairs
        #      when the Brief says 2), the Brief wins — bind the first N
        #      (deterministic by detection_index) and let the surplus distinct
        #      detections fall through to extra_observations. The pipeline never
        #      silently discards them: they are preserved as extras, and no
        #      coordinates/scale are emitted here.
        coalesced_object_ids: list[str] = []
        surplus_object_ids: list[str] = []
        if len(matches) > required_count:
            groups = _coalesce_oversegmented(matches)
            # One representative per group (lowest detection_index); other
            # members of the same group are recorded as coalesced over-segments.
            representatives: list[Mapping[str, Any]] = []
            for group in groups:
                group_sorted = sorted(
                    group,
                    key=lambda item: (
                        int(item.get("detection_index", 0)),
                        str(item.get("object_id", "")),
                    ),
                )
                representatives.append(group_sorted[0])
                coalesced_object_ids.extend(
                    str(member["object_id"]) for member in group_sorted[1:]
                )
            if len(representatives) > required_count:
                # Brief count is authority: bind the first N distinct instances,
                # surplus distinct detections become extra observations.
                bound_reps = representatives[:required_count]
                surplus_reps = representatives[required_count:]
                surplus_object_ids = [str(item["object_id"]) for item in surplus_reps]
                matches = bound_reps
            else:
                matches = representatives

        detected_ids = [str(item["object_id"]) for item in matches]
        used_detection_ids.update(detected_ids)
        # Coalesced over-segments are consumed (not unrelated extras). Surplus
        # distinct detections are intentionally NOT marked used, so the extras
        # collector below preserves them as extra_observations.
        used_detection_ids.update(coalesced_object_ids)
        binding = {
            "manifest_id": str(manifest.id),
            "manifest_name": manifest.name,
            "semantic_concept": concept,
            "required_count": required_count,
            "is_architectural": bool(manifest.is_architectural),
            "detected_object_ids": detected_ids,
            "detected_categories": [str(item.get("category", "")) for item in matches],
            "plan_binding_ids": [],
            "identity_authority": "brief_manifest_uuid",
            "observation_authority": False,
        }
        if coalesced_object_ids:
            binding["coalesced_oversegment_ids"] = coalesced_object_ids
        if surplus_object_ids:
            binding["surplus_observation_ids"] = surplus_object_ids
        bindings.append(binding)

    extras = [
        dict(item)
        for item in detections
        if isinstance(item, Mapping)
        and str(item.get("object_id", "")) not in used_detection_ids
    ]
    return {
        "required_bindings": bindings,
        "extra_observations": extras,
        "binding_method": "exact_constrained_semantic_alias_and_category_count",
        "semantic_gate_precedes_plan_generation": True,
        "fuzzy_matching_used": False,
        "detection_coordinates_used_for_plan": False,
    }


def _attach_plan_bindings(
    brief: Brief, semantic: dict[str, Any], plan: MetricPlan
) -> dict[str, Any]:
    """Bind Brief identity to Plan-owned instances/openings after validation."""
    placement_ids = {str(item.get("id", "")) for item in plan.object_placements}
    by_manifest = {
        str(item["manifest_id"]): dict(item)
        for item in semantic["required_bindings"]
    }
    bound: list[dict[str, Any]] = []
    for manifest in brief.object_manifest:
        item = by_manifest[str(manifest.id)]
        required_count = int(manifest.count)
        expected_instance_ids = (
            [str(manifest.id)]
            if required_count == 1
            else [f"{manifest.id}-{index + 1}" for index in range(required_count)]
        )
        if item["semantic_concept"] == "window":
            plan_bindings = [
                f"opening:{index}"
                for index, opening in enumerate(plan.openings)
                if str(opening.get("type", opening.get("kind", ""))) == "window"
            ]
            if len(plan_bindings) != required_count:
                raise CandidateAuthorityError(
                    "required window count does not match Plan-owned openings"
                )
        else:
            missing = sorted(set(expected_instance_ids) - placement_ids)
            if missing:
                raise CandidateAuthorityError(
                    "candidate Plan lost required Brief instance identity: "
                    + ", ".join(missing)
                )
            plan_bindings = expected_instance_ids
        item["plan_binding_ids"] = plan_bindings
        bound.append(item)

    return {**semantic, "required_bindings": bound}


def bind_required_manifest(
    brief: Brief, detected: Mapping[str, Any], plan: MetricPlan
) -> dict[str, Any]:
    """Bind required Brief UUIDs without granting observations spatial authority."""
    return _attach_plan_bindings(
        brief, _bind_semantic_observations(brief, detected), plan
    )


def validate_optional_depth_reference(artifacts: Path) -> dict[str, Any] | None:
    evidence_path = artifacts / "depth_evidence.json"
    mesh_path = artifacts / "room_shell_raw.glb"
    if not evidence_path.exists() and not mesh_path.exists():
        return None
    if not evidence_path.is_file() or not mesh_path.is_file():
        raise CandidateAuthorityError("optional depth reference is incomplete")
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    stored = str(document.pop("evidence_sha256", ""))
    if stored != canonical_sha256(document):
        raise CandidateAuthorityError("optional depth evidence hash is invalid")
    expected = {
        "evidence_kind": "depth_evidence",
        "evidence_only": True,
        "optional": True,
        "spatial_authority": False,
        "collision_enabled": False,
        "authority_claims": [],
        "forbidden_authorities": list(FORBIDDEN_DEPTH_AUTHORITIES),
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise CandidateAuthorityError(f"depth reference violates authority label {key!r}")
    mesh_sha256 = file_sha256(mesh_path)
    if mesh_sha256 != str(document.get("mesh", {}).get("sha256", "")):
        raise CandidateAuthorityError("optional depth mesh does not match its evidence")
    return {
        "path": str(mesh_path),
        "sha256": mesh_sha256,
        "evidence_path": str(evidence_path),
        "evidence_sha256": stored,
        **expected,
        "used_for": "non_authoritative_appearance_reference_only",
        "used_for_plan": False,
        "used_for_camera": False,
        "used_for_object_transforms": False,
    }


def _validated_candidate_plan(
    brief: Brief,
    revision_feedback: Mapping[str, Any] | None = None,
) -> tuple[MetricPlan, dict[str, Any], dict[str, Any]]:
    generator = MetricPlanGenerator()
    generated = generator.generate_deterministic(brief)
    revision_provenance: dict[str, Any] = {"kind": "initial_candidate"}
    plan = generated
    if revision_feedback is not None:
        prior_raw = revision_feedback.get("prior_metric_plan")
        if not isinstance(prior_raw, Mapping):
            raise CandidateAuthorityError("revision feedback lacks prior MetricPlan")
        prior = MetricPlan.from_dict(dict(prior_raw))
        prior_validation = PlanValidator().validate(prior)
        if not prior_validation.valid or not prior.revisions:
            raise CandidateAuthorityError("revision feedback references an invalid prior Plan")
        expected_revision = int(revision_feedback.get("prior_plan_revision", 0))
        if prior.revisions[-1].revision != expected_revision or expected_revision <= 0:
            raise CandidateAuthorityError("revision feedback prior Plan revision mismatch")
        expected_hash = str(revision_feedback.get("prior_metric_plan_sha256", ""))
        if not expected_hash or canonical_sha256(prior.to_dict()) != expected_hash:
            raise CandidateAuthorityError("revision feedback prior Plan hash mismatch")
        if prior.template_id != generated.template_id:
            raise CandidateAuthorityError(
                "revision feedback Plan template differs from current Brief authority"
            )
        if prior.room_dimensions != generated.room_dimensions:
            raise CandidateAuthorityError(
                "revision feedback Plan dimensions differ from current Brief authority"
            )
        prior_ids = {str(item.get("id", "")) for item in prior.object_placements}
        generated_ids = {
            str(item.get("id", "")) for item in generated.object_placements
        }
        if prior_ids != generated_ids:
            raise CandidateAuthorityError(
                "revision feedback Plan identities differ from current Brief authority"
            )
        feedback = str(revision_feedback.get("feedback", "")).strip()
        rejection_sha256 = str(revision_feedback.get("rejection_sha256", ""))
        if not feedback or len(rejection_sha256) != 64:
            raise CandidateAuthorityError("revision feedback lacks rejection provenance")
        plan = generator.revise(
            prior,
            changed="camera_contract_and_blockout_framing",
            reason=f"Blockout rejection: {feedback}",
        )
        revision_provenance = {
            "kind": "blockout_rejection_revision",
            "prior_plan_revision": expected_revision,
            "prior_metric_plan_sha256": expected_hash,
            "rejection_sha256": rejection_sha256,
            "feedback": feedback,
            "geometry_changed": False,
            "camera_rederived": True,
        }
    history: list[dict[str, Any]] = []
    for _ in range(3):
        result = PlanValidator().validate(plan)
        history.append({
            "input_revision": plan.revisions[-1].revision if plan.revisions else 0,
            "valid": result.valid,
            "violations": [item.rule for item in result.violations],
        })
        if result.valid:
            break
        if result.plan is None or result.plan == plan:
            raise CandidateAuthorityError("PlanValidator could not correct candidate Plan")
        plan = result.plan
    else:
        raise CandidateAuthorityError("candidate Plan did not validate after bounded correction")
    if not result.valid or not plan.revisions or plan.revisions[-1].revision <= 0:
        raise CandidateAuthorityError("candidate Plan lacks nonzero validated revision")
    if not any(str(item.get("type", item.get("kind", ""))) == "window" for item in plan.openings):
        raise CandidateAuthorityError("candidate kitchenette Plan lacks requested window opening")
    if not plan.circulation_paths or any(
        float(item.get("min_width", 0.0)) < MIN_CIRCULATION_WIDTH
        for item in plan.circulation_paths
    ):
        raise CandidateAuthorityError("candidate Plan lacks 0.6m circulation intent")
    return plan, {"valid": True, "attempts": history}, revision_provenance


def derive_camera_from_plan(plan: MetricPlan, *, raster_width: int, raster_height: int) -> CameraContract:
    width, depth, height = (float(value) for value in plan.room_dimensions)
    if raster_width <= 0 or raster_height <= 0:
        raise CandidateAuthorityError("camera raster must be positive")
    revision = plan.revisions[-1].revision if plan.revisions else 0
    if revision >= 2:
        # Rejected framing receives a high, oblique, interior architectural view.
        # Every value remains a pure function of Plan dimensions/revision; depth
        # evidence and detected pixel coordinates never participate.
        position = (0.475 * width, min(0.93 * height, height - 0.10), 0.0)
        target = (-0.10 * width, min(0.20 * height, height - 0.50), 0.0)
        vfov = 100.0
    else:
        position = (-0.30 * width, min(1.60, height - 0.25), -0.5 * depth + 0.75)
        target = (0.0, min(1.10, height - 0.5), 0.15 * depth)
        vfov = 60.0
    camera = CameraContract(
        position=position,
        target=target,
        up=(0.0, 1.0, 0.0),
        vfov=vfov,
        aspect=raster_width / raster_height,
        near=0.05,
        far=max(20.0, 4.0 * (width * width + depth * depth + height * height) ** 0.5),
        raster_width=raster_width,
        raster_height=raster_height,
    )
    x, y, z = camera.position
    if not (-width / 2.0 < x < width / 2.0 and 0.0 < y < height and -depth / 2.0 < z < depth / 2.0):
        raise CandidateAuthorityError("Plan-derived camera is outside navigable room bounds")
    return camera


@dataclass(frozen=True)
class CandidateAuthority:
    plan: MetricPlan
    camera: CameraContract
    validation: dict[str, Any]
    bindings: dict[str, Any]
    depth_reference: dict[str, Any] | None
    revision_provenance: dict[str, Any]

    def documents(self, *, brief_sha256: str, detected_sha256: str, canon_sha256: str) -> dict[str, dict[str, Any]]:
        plan_hash = canonical_sha256(self.plan.to_dict())
        camera_hash = self.camera.compute_hash()
        revision = self.plan.revisions[-1].revision
        plan_document: dict[str, Any] = {
            "schema_version": "candidate-metric-plan/v1",
            "authority_state": "validated_candidate_pending_blockout_approval",
            "human_approved": False,
            "plan_revision": revision,
            "metric_plan_sha256": plan_hash,
            "metric_plan": self.plan.to_dict(),
            "brief_sha256": brief_sha256,
            "validation": self.validation,
            "revision_provenance": self.revision_provenance,
        }
        plan_document["document_sha256"] = canonical_sha256(plan_document)
        camera_document: dict[str, Any] = {
            "schema_version": "candidate-camera-contract/v1",
            "authority_state": "immutable_plan_derived_pending_blockout_approval",
            "human_approved": False,
            "plan_revision": revision,
            "metric_plan_sha256": plan_hash,
            "camera_sha256": camera_hash,
            "camera": self.camera.to_dict(),
            "revision_provenance": self.revision_provenance,
        }
        camera_document["document_sha256"] = canonical_sha256(camera_document)
        spatial: dict[str, Any] = {
            "schema_version": "strict-real-candidate-spatial-solution/v2",
            "authority_state": "validated_candidate_pending_blockout_approval",
            "human_approved": False,
            "plan_revision": revision,
            "brief_sha256": brief_sha256,
            "canon_sha256": canon_sha256,
            "detected_objects_sha256": detected_sha256,
            "metric_plan_sha256": plan_hash,
            "metric_plan": self.plan.to_dict(),
            "room_dimensions_m": list(self.plan.room_dimensions),
            "camera": self.camera.to_dict(),
            "camera_sha256": camera_hash,
            "validation": self.validation,
            "semantic_bindings": self.bindings,
            "depth_reference": self.depth_reference,
            "provenance": {
                "spatial_authority": "durable_brief_plus_constrained_metric_plan_template",
                "template_id": self.plan.template_id,
                "normalization": "MetricPlanGenerator deterministic template parameterization",
                "plan_constraint_solver": "PlanValidator dimensions/closure/opening/overlap/circulation/door-swing",
                "world_relationship_solver": "deferred_until_post_approval_world_assembly",
                "canon_role": "semantic_observation_only",
                "detection_role": "semantic_identity_observation_only",
                "depth_role": "optional_non_authoritative_reference_only",
                "independent_axis_scaling_used": False,
                "min_max_normalization_used": False,
                "revision": self.revision_provenance,
            },
        }
        spatial["solution_sha256"] = canonical_sha256(spatial)
        return {"plan": plan_document, "camera": camera_document, "spatial": spatial}


def build_candidate_authority(
    brief: Brief,
    detected: Mapping[str, Any],
    *,
    artifacts: Path,
    revision_feedback: Mapping[str, Any] | None = None,
) -> CandidateAuthority:
    # Semantic evidence is validated first, but can only confirm inventory and
    # identity. Planning remains a pure Brief/template operation.
    semantic = _bind_semantic_observations(brief, detected)
    plan, validation, revision_provenance = _validated_candidate_plan(
        brief, revision_feedback
    )
    bindings = _attach_plan_bindings(brief, semantic, plan)
    depth_reference = validate_optional_depth_reference(artifacts)
    camera = derive_camera_from_plan(
        plan,
        raster_width=int(detected.get("image_width", 0)),
        raster_height=int(detected.get("image_height", 0)),
    )
    return CandidateAuthority(
        plan,
        camera,
        validation,
        bindings,
        depth_reference,
        revision_provenance,
    )

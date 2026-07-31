"""Plan-derived architectural finish primitives with no CSG or booleans.

Finish geometry remains wall-local and derivative-only: the approved normalized
MetricPlan owns every parent wall, opening, parameter, and fixture elevation.
Requirements: 17.1-17.7, 31.1-31.4, 34.1.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from src.unified_pipeline.models import ArtBible, MetricPlan


_ID_NAMESPACE = uuid.UUID("ee944bc6-125c-56de-a17f-4b1f5cc5f43c")
_EPSILON = 1e-9


class FinishPassError(ValueError):
    """Raised when input cannot be bound safely to an approved Plan revision."""


@dataclass(frozen=True)
class WallPathPoint:
    """A wall-local point; parameter is 0..1 and elevation is metres."""

    parameter: float
    elevation_m: float


@dataclass(frozen=True)
class FinishPrimitive:
    """Compiler-neutral primitive placement derived from one parent wall."""

    id: str
    kind: str
    geometry: str
    parent_wall_id: str
    parent_opening_id: str = ""
    source_detail_id: str = ""
    path: tuple[WallPathPoint, ...] = ()
    profile_m: tuple[tuple[float, float], ...] = ()
    dimensions_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    style: str = ""
    material_role: str = ""
    authority_claim: str = "derived_only"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = [asdict(point) for point in self.path]
        return data


@dataclass(frozen=True)
class FinishPassResult:
    """Immutable finish output bound to one approved Plan revision and hash."""

    plan_revision: int
    plan_hash: str
    primitives: tuple[FinishPrimitive, ...]
    omitted_details: tuple[str, ...] = ()
    spatial_authority: str = "approved_normalized_metric_plan"
    authority_claim: str = "derived_only"
    uses_csg: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_revision": self.plan_revision,
            "plan_hash": self.plan_hash,
            "primitives": [item.to_dict() for item in self.primitives],
            "omitted_details": list(self.omitted_details),
            "spatial_authority": self.spatial_authority,
            "authority_claim": self.authority_claim,
            "uses_csg": self.uses_csg,
        }


@dataclass(frozen=True)
class _EraElectricalProfile:
    name: str
    outlet_style: str
    switch_style: str
    outlet_height_range_m: tuple[float, float]
    switch_height_range_m: tuple[float, float]


_ELECTRICAL_PROFILES: tuple[tuple[tuple[str, ...], _EraElectricalProfile], ...] = (
    (("1930", "1940", "1950", "1960", "mid-century", "midcentury"),
     _EraElectricalProfile("mid_century", "period_duplex", "period_toggle", (0.20, 0.45), (1.00, 1.40))),
    (("1970", "1980", "1990", "late twentieth"),
     _EraElectricalProfile("late_twentieth_century", "duplex", "toggle", (0.20, 0.50), (0.95, 1.40))),
    (("contemporary", "modern", "2000", "2010", "2020"),
     _EraElectricalProfile("contemporary", "decorator_receptacle", "decorator_switch", (0.20, 0.50), (0.95, 1.35))),
)

_BASEBOARD_PROFILE = ((0.0, 0.0), (0.015, 0.0), (0.015, 0.09), (0.0, 0.09))
_CASING_PROFILE = ((0.0, 0.0), (0.012, 0.0), (0.012, 0.07), (0.0, 0.07))
_FRAME_DIMENSIONS = (0.04, 0.025, 0.0)
_DECAL_DIMENSIONS = (0.07, 0.003, 0.12)


def _stable_id(*parts: object) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, ":".join(str(part) for part in parts)))


def _wall_length(wall: dict[str, Any]) -> float:
    try:
        start = tuple(float(v) for v in wall["start"])
        end = tuple(float(v) for v in wall["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FinishPassError("Every approved wall requires finite start/end coordinates") from exc
    if len(start) != 3 or len(end) != 3 or not all(math.isfinite(v) for v in start + end):
        raise FinishPassError("Every approved wall requires finite 3D start/end coordinates")
    length = math.dist(start, end)
    if length <= _EPSILON:
        raise FinishPassError("Approved wall length must be positive")
    return length


def _art_bible_text(art_bible: ArtBible) -> str:
    parts: list[str] = [*art_bible.era_exclusions]
    for value in art_bible.era_rules.values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value)
    return " ".join(parts).lower()


def _electrical_profile(art_bible: ArtBible) -> _EraElectricalProfile | None:
    text = _art_bible_text(art_bible)
    if "victorian" in text or "edwardian" in text:
        return None
    for tokens, profile in _ELECTRICAL_PROFILES:
        if any(token in text for token in tokens):
            return profile
    return None


def _excluded(kind: str, art_bible: ArtBible) -> bool:
    exclusions = " ".join(art_bible.era_exclusions).lower()
    exclusions += " " + " ".join(
        str(item).lower() for item in art_bible.era_rules.get("excludes", ())
    )
    if "no electrical fixtures" in exclusions or "no visible electrical" in exclusions:
        return True
    if kind == "outlet":
        return bool(re.search(r"no (?:electrical )?outlets? visible|no (?:electrical )?outlets?\b", exclusions))
    if kind == "switch":
        return bool(re.search(r"no (?:modern )?(?:light )?switches?\b", exclusions))
    return False


def _primitive(
    *,
    identity: tuple[object, ...],
    kind: str,
    geometry: str,
    wall_id: str,
    path: Iterable[WallPathPoint],
    opening_id: str = "",
    source_detail_id: str = "",
    profile: tuple[tuple[float, float], ...] = (),
    dimensions: tuple[float, float, float] = (0.0, 0.0, 0.0),
    style: str = "",
    material_role: str = "",
) -> FinishPrimitive:
    return FinishPrimitive(
        id=_stable_id(*identity),
        kind=kind,
        geometry=geometry,
        parent_wall_id=wall_id,
        parent_opening_id=opening_id,
        source_detail_id=source_detail_id,
        path=tuple(path),
        profile_m=profile,
        dimensions_m=dimensions,
        style=style,
        material_role=material_role,
    )


class FinishPass:
    """Build wall-local finish primitives from an explicitly approved Plan revision."""

    def run(
        self,
        plan: MetricPlan,
        art_bible: ArtBible,
        *,
        approved_plan_revision: int,
    ) -> FinishPassResult:
        revision, plan_hash = self._validate_approval(plan, approved_plan_revision)
        walls = self._validated_walls(plan)
        openings, omitted = self._validated_openings(plan, walls)
        primitives: list[FinishPrimitive] = []

        for wall_id, wall in walls.items():
            wall_openings = [item for item in openings if item["wall"] == wall_id]
            primitives.extend(self._baseboards(wall_id, wall, wall_openings))
            for opening in wall_openings:
                generated, reason = self._opening_finishes(wall_id, wall, opening)
                primitives.extend(generated)
                if reason:
                    omitted.append(reason)
            generated, reasons = self._electrical(wall_id, wall, art_bible)
            primitives.extend(generated)
            omitted.extend(reasons)

        if not any(wall.get("finish_fixtures") for wall in walls.values()):
            omitted.append("electrical fixtures omitted: no approved parent-wall directives")

        return FinishPassResult(
            plan_revision=revision,
            plan_hash=plan_hash,
            primitives=tuple(primitives),
            omitted_details=tuple(dict.fromkeys(omitted)),
        )

    @staticmethod
    def _validate_approval(plan: MetricPlan, approved_revision: int) -> tuple[int, str]:
        if not plan.revisions:
            raise FinishPassError("FinishPass requires an approved nonzero Plan revision")
        latest = max(plan.revisions, key=lambda item: item.revision)
        if approved_revision <= 0 or approved_revision != latest.revision:
            raise FinishPassError("Approved Plan revision must match the latest nonzero revision")
        if not latest.plan_hash:
            raise FinishPassError("Approved Plan revision requires a provenance-bearing plan hash")
        return latest.revision, latest.plan_hash

    @staticmethod
    def _validated_walls(plan: MetricPlan) -> dict[str, dict[str, Any]]:
        walls: dict[str, dict[str, Any]] = {}
        for wall in plan.walls:
            wall_id = str(wall.get("id", "")).strip()
            if not wall_id or wall_id in walls:
                raise FinishPassError("Approved walls require unique stable IDs")
            _wall_length(wall)
            walls[wall_id] = wall
        if not walls:
            raise FinishPassError("FinishPass requires approved parent walls")
        return walls

    @staticmethod
    def _validated_openings(
        plan: MetricPlan,
        walls: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        result: list[dict[str, Any]] = []
        omitted: list[str] = []
        seen_ids: set[str] = set()
        for index, source in enumerate(plan.openings):
            kind = str(source.get("type", "")).lower()
            if kind not in {"door", "window"}:
                omitted.append(f"opening {index} omitted: unknown opening type")
                continue
            wall_id = str(source.get("wall", ""))
            if wall_id not in walls:
                raise FinishPassError(f"Opening {index} references unknown parent wall '{wall_id}'")
            try:
                parameter = float(source["parameter"])
                width = float(source["width"])
                height = float(source["height"])
            except (KeyError, TypeError, ValueError) as exc:
                raise FinishPassError(f"Opening {index} lacks approved metric values") from exc
            if not all(math.isfinite(value) for value in (parameter, width, height)):
                raise FinishPassError(f"Opening {index} contains non-finite values")
            wall_length = _wall_length(walls[wall_id])
            half_span = width / (2.0 * wall_length)
            if width <= 0 or height <= 0 or parameter - half_span < 0 or parameter + half_span > 1:
                raise FinishPassError(f"Opening {index} lies outside its approved parent wall")
            source_id = str(source.get("id") or f"opening-{index}")
            opening_id = source_id if source.get("id") else _stable_id("opening", wall_id, source_id)
            if opening_id in seen_ids:
                raise FinishPassError("Approved openings require unique stable IDs")
            seen_ids.add(opening_id)
            item = dict(source)
            item.update({
                "id": opening_id,
                "source_id": source_id,
                "type": kind,
                "wall": wall_id,
                "parameter": parameter,
                "width": width,
                "height": height,
                "left": parameter - half_span,
                "right": parameter + half_span,
            })
            result.append(item)
        return result, omitted

    @staticmethod
    def _baseboards(
        wall_id: str,
        wall: dict[str, Any],
        openings: list[dict[str, Any]],
    ) -> list[FinishPrimitive]:
        cuts = sorted((item["left"], item["right"]) for item in openings if item["type"] == "door")
        intervals: list[tuple[float, float]] = []
        cursor = 0.0
        for left, right in cuts:
            if left > cursor + _EPSILON:
                intervals.append((cursor, left))
            cursor = max(cursor, right)
        if cursor < 1.0 - _EPSILON:
            intervals.append((cursor, 1.0))
        return [
            _primitive(
                identity=("baseboard", wall_id, segment),
                kind="baseboard",
                geometry="profile_sweep",
                wall_id=wall_id,
                path=(WallPathPoint(start, 0.0), WallPathPoint(end, 0.0)),
                profile=_BASEBOARD_PROFILE,
                style="built_in_baseboard_profile",
                material_role="trim",
            )
            for segment, (start, end) in enumerate(intervals)
        ]

    def _opening_finishes(
        self,
        wall_id: str,
        wall: dict[str, Any],
        opening: dict[str, Any],
    ) -> tuple[list[FinishPrimitive], str]:
        bottom = 0.0
        if opening["type"] == "window":
            raw_bottom = opening.get("sill_height", opening.get("bottom_height"))
            if raw_bottom is None:
                return [], f"window {opening['source_id']} omitted: approved sill height is unknown"
            try:
                bottom = float(raw_bottom)
            except (TypeError, ValueError):
                return [], f"window {opening['source_id']} omitted: approved sill height is invalid"
            if not math.isfinite(bottom) or bottom < 0:
                return [], f"window {opening['source_id']} omitted: approved sill height is invalid"
        top = bottom + opening["height"]
        wall_height = float(wall.get("height", top))
        if top > wall_height + _EPSILON:
            raise FinishPassError(f"Opening {opening['source_id']} exceeds approved wall height")
        left, right = opening["left"], opening["right"]
        opening_id = opening["id"]
        source_id = opening["source_id"]
        result: list[FinishPrimitive] = []
        members = [("left", left, bottom, left, top), ("right", right, bottom, right, top),
                   ("top", left, top, right, top)]
        if opening["type"] == "window":
            members.append(("bottom", left, bottom, right, bottom))
        for member, p0, h0, p1, h1 in members:
            result.append(_primitive(
                identity=(opening["type"], "frame", wall_id, source_id, member),
                kind=f"{opening['type']}_frame",
                geometry="box_extrusion",
                wall_id=wall_id,
                opening_id=opening_id,
                source_detail_id=source_id,
                path=(WallPathPoint(p0, h0), WallPathPoint(p1, h1)),
                dimensions=_FRAME_DIMENSIONS,
                style="built_in_frame_box",
                material_role="trim",
            ))

        perimeter = [WallPathPoint(left, bottom), WallPathPoint(left, top),
                     WallPathPoint(right, top), WallPathPoint(right, bottom)]
        if opening["type"] == "window":
            perimeter.append(WallPathPoint(left, bottom))
        result.append(_primitive(
            identity=("casing", wall_id, source_id),
            kind="casing",
            geometry="profile_sweep",
            wall_id=wall_id,
            opening_id=opening_id,
            source_detail_id=source_id,
            path=perimeter,
            profile=_CASING_PROFILE,
            style="built_in_casing_profile",
            material_role="trim",
        ))
        return result, ""

    @staticmethod
    def _electrical(
        wall_id: str,
        wall: dict[str, Any],
        art_bible: ArtBible,
    ) -> tuple[list[FinishPrimitive], list[str]]:
        directives = wall.get("finish_fixtures", ())
        if not isinstance(directives, (tuple, list)):
            raise FinishPassError(f"Wall '{wall_id}' finish_fixtures must be a sequence")
        profile = _electrical_profile(art_bible)
        result: list[FinishPrimitive] = []
        omitted: list[str] = []
        seen: set[str] = set()
        for index, directive in enumerate(directives):
            if not isinstance(directive, dict):
                omitted.append(f"wall {wall_id} fixture {index} omitted: invalid directive")
                continue
            source_id = str(directive.get("id", "")).strip()
            kind = str(directive.get("kind", "")).lower()
            if not source_id or source_id in seen:
                raise FinishPassError(f"Wall '{wall_id}' fixtures require unique stable IDs")
            seen.add(source_id)
            if kind not in {"outlet", "switch"}:
                omitted.append(f"fixture {source_id} omitted: unknown detail kind")
                continue
            if profile is None:
                omitted.append(f"fixture {source_id} omitted: ArtBible era is not safely classifiable")
                continue
            if _excluded(kind, art_bible):
                omitted.append(f"fixture {source_id} omitted: excluded by ArtBible")
                continue
            try:
                parameter = float(directive["parameter"])
                elevation = float(directive["elevation_m"])
            except (KeyError, TypeError, ValueError):
                omitted.append(f"fixture {source_id} omitted: approved parameter/elevation is unknown")
                continue
            if not math.isfinite(parameter) or not math.isfinite(elevation) or not 0 <= parameter <= 1:
                raise FinishPassError(f"Fixture '{source_id}' has invalid approved placement")
            allowed = profile.outlet_height_range_m if kind == "outlet" else profile.switch_height_range_m
            if not allowed[0] <= elevation <= allowed[1]:
                omitted.append(f"fixture {source_id} omitted: approved height conflicts with ArtBible era profile")
                continue
            style = profile.outlet_style if kind == "outlet" else profile.switch_style
            result.append(_primitive(
                identity=("electrical", wall_id, source_id),
                kind=kind,
                geometry="quad_decal",
                wall_id=wall_id,
                source_detail_id=source_id,
                path=(WallPathPoint(parameter, elevation),),
                dimensions=_DECAL_DIMENSIONS,
                style=style,
                material_role="electrical_trim",
            ))
        return result, omitted

    # Post-MVP interfaces are intentionally inert; callers can depend on their shape.
    def crown_molding(self, plan: MetricPlan, art_bible: ArtBible) -> tuple[FinishPrimitive, ...]:
        return ()

    def wainscoting(self, plan: MetricPlan, art_bible: ArtBible) -> tuple[FinishPrimitive, ...]:
        return ()

    def vent_covers(self, plan: MetricPlan, art_bible: ArtBible) -> tuple[FinishPrimitive, ...]:
        return ()


def generate_finish_pass(
    plan: MetricPlan,
    art_bible: ArtBible,
    *,
    approved_plan_revision: int,
) -> FinishPassResult:
    """Functional entry point for the procedural FinishPass."""

    return FinishPass().run(
        plan,
        art_bible,
        approved_plan_revision=approved_plan_revision,
    )


__all__ = [
    "FinishPass",
    "FinishPassError",
    "FinishPassResult",
    "FinishPrimitive",
    "WallPathPoint",
    "generate_finish_pass",
]

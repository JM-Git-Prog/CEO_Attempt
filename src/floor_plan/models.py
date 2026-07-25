"""Typed contract for the approved spatial plan."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PlanRoom(BaseModel):
    width: float = Field(ge=2.5, le=30.0)
    depth: float = Field(ge=2.5, le=30.0)
    height: float = Field(default=2.8, ge=2.1, le=8.0)


class PlanItem(BaseModel):
    id: str
    name: str
    category: Literal["furniture", "fixture", "architectural", "decor"]
    mount: Literal["floor", "wall", "ceiling"] = "floor"
    x: float
    z: float
    width: float = Field(gt=0.0, le=20.0)
    depth: float = Field(gt=0.0, le=20.0)
    height: float = Field(gt=0.0, le=8.0)
    elevation: float = Field(default=0.0, ge=0.0, le=8.0)
    rotation_deg: float = 0.0
    fixed: bool = False
    clearance_m: float = Field(default=0.75, ge=0.0, le=3.0)
    description: str = ""


class PlanOpening(BaseModel):
    id: str
    kind: Literal["door", "window"]
    wall: Literal["north", "south", "east", "west"]
    offset: float = 0.0
    width: float = Field(default=0.9, gt=0.2, le=8.0)
    height: float = Field(default=2.1, gt=0.2, le=5.0)
    sill_height: float = Field(default=0.0, ge=0.0, le=4.0)


class PlanCamera(BaseModel):
    x: float
    y: float = Field(default=1.6, ge=0.2, le=5.0)
    z: float
    target_x: float = 0.0
    target_y: float = 1.1
    target_z: float = 0.0
    fov_deg: float = Field(default=55.0, ge=30.0, le=90.0)


class PlanValidationIssue(BaseModel):
    code: str
    message: str
    item_ids: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class PlanValidationReport(BaseModel):
    valid: bool = True
    blockers: list[PlanValidationIssue] = Field(default_factory=list)
    warnings: list[PlanValidationIssue] = Field(default_factory=list)
    tolerance_warnings: list[dict] = Field(default_factory=list)
    """Structured MVP tolerance warnings: each dict has keys
    warning_type, affected_id, measured_deviation, threshold."""

    @property
    def mvp_warnings(self) -> list:
        """Return tolerance warnings as PlanValidationWarning frozen dataclass instances.

        Defers the import to avoid circular dependency (src.models imports this module).
        Used by the compiler manifest recorder (task 2.3) for structured provenance.
        """
        from src.models import PlanValidationWarning

        return [
            PlanValidationWarning(
                warning_type=w["warning_type"],
                affected_id=w["affected_id"],
                measured_deviation=w["measured_deviation"],
                threshold=w["threshold"],
            )
            for w in self.tolerance_warnings
        ]


class FloorPlan(BaseModel):
    name: str
    room: PlanRoom
    items: list[PlanItem] = Field(default_factory=list)
    openings: list[PlanOpening] = Field(default_factory=list)
    camera: PlanCamera
    circulation_notes: list[str] = Field(default_factory=list)
    design_notes: list[str] = Field(default_factory=list)


RelationKind = Literal[
    "centered", "against_wall", "adjacent_to", "north_of", "south_of",
    "east_of", "west_of", "around", "above", "facing", "near_corner",
]
WallName = Literal["north", "south", "east", "west"]
CornerName = Literal["northwest", "northeast", "southwest", "southeast"]


class PlanRelation(BaseModel):
    """One V11 typed placement instruction owned by the approved Plan."""

    subject_id: str
    kind: RelationKind
    target_id: str | None = None
    wall: WallName | None = None
    parameters_m: dict[str, float] = Field(default_factory=dict)
    weight: float = Field(default=1.0, gt=0.0)
    relaxable: bool = False

    @model_validator(mode="after")
    def valid_reference_and_distribution(self) -> "PlanRelation":
        wall_kinds = {"against_wall", "near_corner"}
        target_optional = wall_kinds | {"centered"}
        if self.kind in wall_kinds and self.wall is None:
            raise ValueError(f"{self.kind} requires wall")
        if self.kind not in target_optional and self.target_id is None:
            raise ValueError(f"{self.kind} requires target_id")
        index = self.parameters_m.get("distribution_index")
        count = self.parameters_m.get("distribution_count")
        if (index is None) != (count is None):
            raise ValueError("distribution_index and distribution_count must be paired")
        if index is not None:
            if not index.is_integer() or not count.is_integer():
                raise ValueError("distribution index/count must be integers")
            if count < 1 or index < 0 or index >= count:
                raise ValueError("distribution slot is outside its declared count")
        return self


class OpeningPlacementIntent(BaseModel):
    opening_id: str
    wall: WallName
    placement: Literal["centered", "near_corner"]
    corner: CornerName | None = None
    margin_m: float = Field(default=0.1, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def corner_required(self) -> "OpeningPlacementIntent":
        if self.placement == "near_corner" and self.corner is None:
            raise ValueError("near_corner opening placement requires corner")
        return self


class CameraPlacementIntent(BaseModel):
    corner: CornerName
    target_id: str
    inset_m: float = Field(default=0.45, ge=0.2, le=2.0)
    eye_height_m: float = Field(default=1.6, ge=0.2, le=5.0)
    target_height_m: float = Field(default=1.2, ge=0.0, le=5.0)
    fov_deg: float = Field(default=55.0, ge=30.0, le=90.0)


class FloorPlanV11(FloorPlan):
    """V11 Plan authority with explicit, persisted spatial intent."""

    schema_version: Literal["floor-plan/v11"]
    relationships: list[PlanRelation]
    opening_intents: list[OpeningPlacementIntent]
    camera_intent: CameraPlacementIntent

    @model_validator(mode="after")
    def complete_non_conflicting_intent(self) -> "FloorPlanV11":
        item_ids = {item.id for item in self.items}
        subjects = [relation.subject_id for relation in self.relationships]
        if len(item_ids) != len(self.items):
            raise ValueError("V11 Plan item IDs must be unique")
        if len(subjects) != len(set(subjects)):
            raise ValueError("V11 Plan subjects must have exactly one placement relation")
        if set(subjects) != item_ids:
            raise ValueError("V11 Plan requires exactly one typed placement relation per item")
        for relation in self.relationships:
            if relation.target_id is not None and relation.target_id not in item_ids:
                raise ValueError(f"dangling Plan relation target {relation.target_id}")
            if relation.target_id == relation.subject_id:
                raise ValueError("Plan relation cannot target itself")
        opening_ids = {opening.id for opening in self.openings}
        intent_ids = [intent.opening_id for intent in self.opening_intents]
        if len(intent_ids) != len(set(intent_ids)) or set(intent_ids) != opening_ids:
            raise ValueError("V11 Plan requires exactly one placement intent per opening")
        if self.camera_intent.target_id not in item_ids:
            raise ValueError("camera intent has dangling target")

        graph = {
            relation.subject_id: relation.target_id
            for relation in self.relationships if relation.target_id in item_ids
        }
        for subject in graph:
            seen: set[str] = set()
            current: str | None = subject
            while current in graph:
                if current in seen:
                    raise ValueError("Plan relation cycle detected")
                seen.add(current)
                current = graph[current]
        return self

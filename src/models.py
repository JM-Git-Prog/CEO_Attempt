"""
Core data models for The Living Room.
These are the contracts between every component in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from src.camera_contract import CameraContract
from src.compiler_manifest import CanonicalDocument
from src.floor_plan.models import FloorPlan, FloorPlanV11, PlanValidationReport

if TYPE_CHECKING:
    from src.auto_launch import LaunchResult


# --- MVP Mode ---


class SessionMode(str, Enum):
    """Pipeline execution mode: MVP (shortened, relaxed) or FULL (V11 strict)."""

    MVP = "mvp"
    FULL = "full"


# --- MVP Pipeline Data Models ---


@dataclass(frozen=True)
class PlanValidationWarning:
    """A non-fatal validation warning from MVP-tolerant plan checks."""

    warning_type: str  # "overlap", "relationship_offset", "clearance"
    affected_id: str
    measured_deviation: float
    threshold: float


@dataclass(frozen=True)
class StageFailure:
    """Structured error propagation for pipeline stage failures."""

    stage: str  # e.g. "planning", "compiling", "validating"
    reason_code: str
    diagnostic: str
    recoverable: bool = False


@dataclass(frozen=True)
class MVPPipelineResult:
    """Immutable result of a complete MVP pipeline execution."""

    success: bool
    artifact_path: Path | None
    launch_result: LaunchResult | None
    quality_label: str  # "smoke_structural", "smoke_skipped", "parity_only"
    warnings: list[PlanValidationWarning] = field(default_factory=list)
    failure_stage: str | None = None
    failure_reason_code: str | None = None
    failure_diagnostic: str | None = None
    duration_ms: int = 0
    model_used: str = ""  # Which lane produced the accepted plan
    attempts: int = 0  # How many plan generation attempts were needed


# --- Scene Concept (output of Orchestrator) ---


class SceneConcept(BaseModel):
    """The AI's interpretation of the user's description."""

    era: str = Field(description="Time period / style era")
    mood: str = Field(description="Emotional tone: warm, cold, moody, bright, etc.")
    palette: str = Field(description="Dominant color palette description")
    architecture_notes: str = Field(description="Brief on walls, floor, ceiling style")
    key_objects: list[str] = Field(description="List of main objects in the scene")
    lighting_notes: str = Field(description="Brief on lighting mood and sources")
    image_prompt: str = Field(description="Optimized prompt for photorealistic image generation")


# --- Scene Graph (spatial layout for 3D construction) ---


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class PhysicsBody(str, Enum):
    STATIC = "static"
    RIGID = "rigid"
    KINEMATIC = "kinematic"


class PhysicsProps(BaseModel):
    body_type: PhysicsBody = PhysicsBody.STATIC
    mass_kg: float = 1.0
    friction: float = 0.5
    restitution: float = 0.1
    can_topple: bool = False


class MaterialProps(BaseModel):
    base_color: str = Field(default="#808080", description="Hex color or material name")
    metallic: float = Field(default=0.0, ge=0.0, le=1.0)
    roughness: float = Field(default=0.8, ge=0.0, le=1.0)
    emission_color: Optional[str] = None
    emission_strength: float = 0.0


class SceneObject(BaseModel):
    id: str
    name: str
    object_type: str = Field(description="Category: furniture, fixture, architectural, decor")
    position: Vec3
    rotation: Vec3 = Field(default_factory=Vec3)
    scale: Vec3 = Field(default_factory=lambda: Vec3(x=1.0, y=1.0, z=1.0))
    dimensions: Vec3 = Field(description="Bounding box size in meters")
    physics: PhysicsProps = Field(default_factory=PhysicsProps)
    material: MaterialProps = Field(default_factory=MaterialProps)
    mesh_type: str = Field(
        default="primitive",
        description="'primitive' for procedural gen, 'generated' for AI reconstruction",
    )
    primitive_shape: Optional[str] = Field(
        default=None, description="box, cylinder, sphere, plane, capsule"
    )
    description: str = Field(default="", description="Visual description for mesh generation")


class LightType(str, Enum):
    POINT = "point"
    SPOT = "spot"
    DIRECTIONAL = "directional"
    AREA = "area"


class SceneLight(BaseModel):
    id: str
    name: str
    light_type: LightType
    position: Vec3
    direction: Vec3 = Field(default_factory=lambda: Vec3(x=0, y=-1, z=0))
    color: str = Field(description="Hex color")
    color_temperature_k: int = Field(default=4000, description="Color temp in Kelvin")
    intensity: float = Field(default=1.0, description="Energy/intensity value")
    range_meters: float = Field(default=5.0, description="Effective radius")
    spot_angle_deg: float = Field(default=45.0, description="Spot cone angle")
    cast_shadows: bool = True


class RoomShell(BaseModel):
    width: float = Field(description="X dimension in meters")
    depth: float = Field(description="Z dimension in meters")
    height: float = Field(description="Y dimension in meters")
    floor_material: MaterialProps = Field(default_factory=MaterialProps)
    wall_material: MaterialProps = Field(default_factory=MaterialProps)
    ceiling_material: MaterialProps = Field(default_factory=MaterialProps)


class DoorSpec(BaseModel):
    id: str
    position: Vec3
    wall: str = Field(description="north, south, east, west")
    width: float = 0.9
    height: float = 2.1
    swing_direction: str = "inward"
    physics: PhysicsProps = Field(
        default_factory=lambda: PhysicsProps(body_type=PhysicsBody.RIGID, mass_kg=15.0)
    )


class WindowSpec(BaseModel):
    id: str
    position: Vec3
    wall: str
    width: float = 1.2
    height: float = 1.0
    sill_height: float = 0.9


class SceneGraph(BaseModel):
    """Complete spatial description of the world to be built."""

    name: str
    description: str
    room: RoomShell
    objects: list[SceneObject] = Field(default_factory=list)
    lights: list[SceneLight] = Field(default_factory=list)
    doors: list[DoorSpec] = Field(default_factory=list)
    windows: list[WindowSpec] = Field(default_factory=list)
    ambient_color: str = Field(default="#1a1a2e", description="Global ambient light color")
    ambient_energy: float = Field(default=0.3, description="Global ambient intensity")


# --- Pipeline State ---


class PipelineState(str, Enum):
    AWAITING_DESCRIPTION = "awaiting_description"
    GENERATING_CONCEPT = "generating_concept"
    GENERATING_PLAN = "generating_plan"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    GENERATING_IMAGE = "generating_image"
    AWAITING_APPROVAL = "awaiting_approval"
    BUILDING_SCENE_GRAPH = "building_scene_graph"
    GENERATING_ASSETS = "generating_assets"
    ASSEMBLING_WORLD = "assembling_world"
    AWAITING_QA = "awaiting_qa"
    REFINING_WORLD = "refining_world"
    READY = "ready"
    ERROR = "error"


class WorldSession(BaseModel):
    """Tracks the state and revision memory of a world-building session."""

    session_id: str
    mode: SessionMode = SessionMode.MVP  # default to MVP per Req 10.4
    source_type: str = "text"  # "text" or "photo" — Req 14.5
    quality_label: str | None = None  # "smoke_structural", "smoke_skipped", "parity_only"
    game_pid: int | None = None  # PID of launched blenderplayer process
    interface_version: int = 11
    workflow_profile_id: str = ""
    workflow_profile: dict = Field(default_factory=dict)
    workflow_snapshot_count: int = 0
    workflow_records: list[str] = Field(default_factory=list)
    generation_manifests: list[str] = Field(default_factory=list)
    compiler_manifests: list[str] = Field(default_factory=list)
    state: PipelineState = PipelineState.AWAITING_DESCRIPTION
    user_description: str = ""
    scene_concept: Optional[SceneConcept] = None
    floor_plan: Optional[FloorPlanV11 | FloorPlan] = None
    camera_contract: Optional[CameraContract] = None
    composition_evidence: Optional[dict] = None
    floor_plan_path: Optional[str] = None
    blockout_path: Optional[str] = None
    floor_plan_approved: bool = False
    canon_image_path: Optional[str] = None
    canon_provider: Optional[str] = None
    canon_alignment: Optional[dict] = None
    scene_graph: Optional[SceneGraph] = None
    world_contract: Optional[dict] = None
    relationship_solver_report: Optional[dict] = None
    semantic_command_records: list[dict] = Field(default_factory=list)
    conditioning_metadata: dict = Field(default_factory=dict)
    conditioning_records: tuple[CanonicalDocument, ...] = ()
    compiler_result: Optional[dict] = None
    compiler_attempt_records: tuple[CanonicalDocument, ...] = ()
    export_results: dict = Field(default_factory=dict)
    parity_report: Optional[dict] = None
    runtime_smoke_report: Optional[dict] = None
    qa_evidence: list[dict] = Field(default_factory=list)
    output_path: Optional[str] = None
    plan_revision: int = 0
    plan_warnings: list[str] = Field(default_factory=list)
    plan_validation: PlanValidationReport = Field(default_factory=PlanValidationReport)
    canon_attempt: int = 0
    canon_alignment_reviews: list[dict] = Field(default_factory=list)
    world_revision: int = 0
    render_paths: list[str] = Field(default_factory=list)
    revision_history: list[dict] = Field(default_factory=list)
    error: Optional[str] = None
    progress_messages: list[str] = Field(default_factory=list)
    launch_fallback: Optional[dict] = None  # Stores launch failure info when pipeline succeeded but auto-launch failed

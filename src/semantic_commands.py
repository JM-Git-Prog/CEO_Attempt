"""Typed, non-executable LLM commands for transactional WorldContract revision."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Annotated, Any, Literal, Mapping, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

from src.world_contract import (
    ContractModel,
    InteractionIntent,
    MaterialIntent,
    PhysicsIntent,
    RelationIntent,
    RelationKind,
    Vector3,
    WorldContract,
    WorldInstance,
    WorldLight,
)

COMMAND_VERSION = "semantic-command/v1"
_PROMPT_HASH = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("filesystem path", re.compile(r"(?:[A-Za-z]:[\\/]|(?:^|\s)[~/\\]|(?:^|[\\/])\.\.?[\\/]|(?:file|https?)://)", re.I)),
    ("executable path", re.compile(r"\.(?:py|pyw|sh|bash|zsh|ps1|bat|cmd|exe|com|dll|blend)(?:\s|$)", re.I)),
    ("Python source", re.compile(r"(?:\b(?:exec|eval|compile|__import__|open)\s*\(|\b(?:import|from)\s+[A-Za-z_]|\b(?:def|class|lambda)\b|__\w+__)", re.I)),
    ("shell command", re.compile(r"(?:\b(?:bash|zsh|powershell|cmd\.exe|sudo)\b|\brm\s+-|\bcurl\s+|\bwget\s+|\$\(|&&|\|\||`)", re.I)),
    ("engine operator", re.compile(r"(?:\b(?:bpy|bge)\.(?:ops|data|context|app)\b|\bEngine\.|\bget_tree\s*\(|\b(?:_process|_physics_process|queue_free)\s*\()", re.I)),
    ("shader or driver source", re.compile(r"(?:\bshader_type\b|\bgl_Position\b|#version\s+\d+|\bdriver[_ ]expression\b)", re.I)),
    ("per-frame control", re.compile(r"(?:\bevery frame\b|\bper[- ]frame\b|\bframe loop\b)", re.I)),
)


_PROSE_ONLY_FIELDS = frozenset({"rationale"})


def _validate_safe_value(value: Any, field: str = "command") -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_safe_value(str(key), f"{field}.key")
            _validate_safe_value(item, f"{field}.{key}")
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            _validate_safe_value(item, f"{field}[{index}]")
        return
    if not isinstance(value, str):
        return
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ValueError(f"unsafe content in {field}: control character")
    # Prose-only fields (rationale) are never executed — check length/control only.
    field_leaf = field.rsplit(".", 1)[-1] if "." in field else field
    if field_leaf in _PROSE_ONLY_FIELDS:
        return
    for label, pattern in _UNSAFE_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"unsafe content in {field}: {label} is prohibited")


class CommandOp(str, Enum):
    CREATE_INSTANCE = "create_instance"
    REMOVE_INSTANCE = "remove_instance"
    REPLACE_INSTANCE = "replace_instance"
    SET_RELATION = "set_relation"
    SET_STYLE = "set_style"
    SET_LIGHT_INTENT = "set_light_intent"
    CAMERA_REQUEST = "camera_request"
    SET_PHYSICS_INTENT = "set_physics_intent"
    SET_INTERACTION_INTENT = "set_interaction_intent"


class SemanticCommandModel(ContractModel):
    version: Literal["semantic-command/v1"] = COMMAND_VERSION
    command_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")

    @model_validator(mode="after")
    def prohibit_executable_content(self) -> "SemanticCommandModel":
        _validate_safe_value(self.model_dump(mode="json"))
        return self


class CreateInstanceCommand(SemanticCommandModel):
    op: Literal["create_instance"] = "create_instance"
    instance: WorldInstance
    material: MaterialIntent
    physics: PhysicsIntent

    @model_validator(mode="after")
    def matching_dependencies(self) -> "CreateInstanceCommand":
        if self.instance.material_id != self.material.id:
            raise ValueError("instance material_id must match the supplied material")
        if self.instance.physics_intent_id != self.physics.id:
            raise ValueError("instance physics_intent_id must match the supplied physics intent")
        if self.physics.subject_id != self.instance.id:
            raise ValueError("physics subject_id must match the created instance")
        return self


class RemoveInstanceCommand(SemanticCommandModel):
    op: Literal["remove_instance"] = "remove_instance"
    subject_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")


class ReplaceInstanceCommand(SemanticCommandModel):
    op: Literal["replace_instance"] = "replace_instance"
    subject_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
    instance: WorldInstance
    material: MaterialIntent
    physics: PhysicsIntent

    @model_validator(mode="after")
    def matching_identity(self) -> "ReplaceInstanceCommand":
        if self.instance.id != self.subject_id:
            raise ValueError("replacement instance ID must preserve subject_id")
        if self.instance.material_id != self.material.id:
            raise ValueError("replacement material identity does not match")
        if self.instance.physics_intent_id != self.physics.id:
            raise ValueError("replacement physics identity does not match")
        if self.physics.subject_id != self.subject_id:
            raise ValueError("replacement physics subject does not match")
        return self


class SetRelationCommand(SemanticCommandModel):
    op: Literal["set_relation"] = "set_relation"
    subject_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
    relation: RelationIntent


class MaterialPatch(ContractModel):
    base_color: str | None = None
    metallic: float | None = Field(default=None, ge=0.0, le=1.0)
    roughness: float | None = Field(default=None, ge=0.0, le=1.0)
    emission_color: str | None = None
    emission_strength: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def not_empty(self) -> "MaterialPatch":
        if not self.model_dump(exclude_none=True):
            raise ValueError("style patch must set at least one allowlisted field")
        _validate_safe_value(self.model_dump(mode="json", exclude_none=True), "style")
        return self


class SetStyleCommand(SemanticCommandModel):
    op: Literal["set_style"] = "set_style"
    material_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
    style: MaterialPatch


class SetLightIntentCommand(SemanticCommandModel):
    op: Literal["set_light_intent"] = "set_light_intent"
    light: WorldLight


class CameraRequestCommand(SemanticCommandModel):
    op: Literal["camera_request"] = "camera_request"
    position_m: Vector3 | None = None
    target_m: Vector3 | None = None
    up: Vector3 | None = None
    vertical_fov_deg: float | None = Field(default=None, gt=0.0, lt=180.0)
    rationale: str = Field(default="", max_length=512)

    @model_validator(mode="after")
    def has_requested_change(self) -> "CameraRequestCommand":
        if all(value is None for value in (
            self.position_m, self.target_m, self.up, self.vertical_fov_deg
        )):
            raise ValueError("camera request must request at least one camera value")
        return self


class SetPhysicsIntentCommand(SemanticCommandModel):
    op: Literal["set_physics_intent"] = "set_physics_intent"
    intent: PhysicsIntent


class SetInteractionIntentCommand(SemanticCommandModel):
    op: Literal["set_interaction_intent"] = "set_interaction_intent"
    intent: InteractionIntent


SemanticCommand = Annotated[
    Union[
        CreateInstanceCommand,
        RemoveInstanceCommand,
        ReplaceInstanceCommand,
        SetRelationCommand,
        SetStyleCommand,
        SetLightIntentCommand,
        CameraRequestCommand,
        SetPhysicsIntentCommand,
        SetInteractionIntentCommand,
    ],
    Field(discriminator="op"),
]
_COMMAND_ADAPTER = TypeAdapter(SemanticCommand)


class CommandLimits(ContractModel):
    max_commands: int = Field(default=64, ge=1, le=1024)
    max_instances: int = Field(default=256, ge=0)
    max_lights: int = Field(default=64, ge=0)
    max_interactions: int = Field(default=128, ge=0)
    max_relations_per_instance: int = Field(default=16, ge=0)
    max_canonical_bytes: int = Field(default=262_144, ge=1)


class CommandAuthorization(ContractModel):
    principal_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
    authorized_model_ids: frozenset[str] = frozenset()
    allowed_ops: frozenset[CommandOp] = frozenset()
    mutable_instance_ids: frozenset[str] = frozenset()
    mutable_material_ids: frozenset[str] = frozenset()
    mutable_light_ids: frozenset[str] = frozenset()
    mutable_interaction_ids: frozenset[str] = frozenset()

    @field_validator(
        "authorized_model_ids", "mutable_instance_ids", "mutable_material_ids",
        "mutable_light_ids", "mutable_interaction_ids",
    )
    @classmethod
    def safe_identity_sets(cls, values: frozenset[str]) -> frozenset[str]:
        for value in values:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", value):
                raise ValueError("authorization contains an invalid stable identifier")
        return values


class CommandProvenance(ContractModel):
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
    source_prompt_hash: str

    @field_validator("source_prompt_hash")
    @classmethod
    def valid_prompt_hash(cls, value: str) -> str:
        if not _PROMPT_HASH.fullmatch(value):
            raise ValueError("source_prompt_hash must be a lowercase SHA-256 hash")
        return value


class RejectionCode(str, Enum):
    SCHEMA_INVALID = "schema_invalid"
    UNSAFE_CONTENT = "unsafe_content"
    DUPLICATE_IDENTITY = "duplicate_identity"
    DANGLING_REFERENCE = "dangling_reference"
    LIMIT_EXCEEDED = "limit_exceeded"
    UNAUTHORIZED = "unauthorized"
    IMMUTABLE_AUTHORITY = "immutable_authority"
    RELATION_CYCLE = "relation_cycle"
    CONTRADICTORY_RELATION = "contradictory_relation"
    CONTRACT_INVALID = "contract_invalid"


class CommandRejection(ContractModel):
    command_index: int | None = None
    command_id: str | None = None
    op: str | None = None
    code: RejectionCode
    field: str | None = None
    message: str


class CommandBatchRecord(ContractModel):
    schema_version: Literal["semantic-command-batch-record/v1"] = "semantic-command-batch-record/v1"
    model_id: str
    source_prompt_hash: str
    canonical_commands_json: str
    command_log_hash: str
    before_hash: str
    after_hash: str


class CommandBatchResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=False, frozen=True)
    accepted: bool
    contract: WorldContract
    before_hash: str
    after_hash: str
    record: CommandBatchRecord | None = None
    camera_requests: tuple[CameraRequestCommand, ...] = ()
    rejections: tuple[CommandRejection, ...] = ()


def semantic_command_json_schema() -> dict[str, Any]:
    """Return the only schema the LLM director is allowed to emit."""
    return _COMMAND_ADAPTER.json_schema()


def parse_semantic_command(value: SemanticCommand | Mapping[str, Any]) -> SemanticCommand:
    if isinstance(value, SemanticCommandModel):
        return value
    return _COMMAND_ADAPTER.validate_python(value)


def _canonical_commands(commands: Sequence[SemanticCommand]) -> tuple[str, str]:
    payload = [command.model_dump(mode="json", exclude_none=True) for command in commands]
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rejection(
    code: RejectionCode,
    message: str,
    *,
    index: int | None = None,
    command: SemanticCommand | None = None,
    field: str | None = None,
) -> CommandRejection:
    return CommandRejection(
        command_index=index,
        command_id=command.command_id if command else None,
        op=command.op if command else None,
        code=code,
        field=field,
        message=message,
    )


def _failed(contract: WorldContract, rejections: Sequence[CommandRejection]) -> CommandBatchResult:
    before_hash = contract.content_hash()
    return CommandBatchResult(
        accepted=False,
        contract=contract,
        before_hash=before_hash,
        after_hash=before_hash,
        rejections=tuple(rejections),
    )


def _validate_authorization(
    contract: WorldContract,
    commands: Sequence[SemanticCommand],
    authorization: CommandAuthorization,
    provenance: CommandProvenance,
) -> list[CommandRejection]:
    issues: list[CommandRejection] = []
    if provenance.model_id not in authorization.authorized_model_ids:
        issues.append(_rejection(
            RejectionCode.UNAUTHORIZED,
            f"model {provenance.model_id} is not authorized for this command boundary",
            field="model_id",
        ))
        return issues
    existing_instances = {item.id: item for item in contract.instances}
    existing_lights = {item.id for item in contract.lights}
    existing_interactions = {item.id for item in contract.interactions}
    for index, command in enumerate(commands):
        op = CommandOp(command.op)
        if op not in authorization.allowed_ops:
            issues.append(_rejection(
                RejectionCode.UNAUTHORIZED, f"operation {op.value} is not authorized",
                index=index, command=command, field="op",
            ))
            continue
        subject_id: str | None = None
        if isinstance(command, (RemoveInstanceCommand, ReplaceInstanceCommand, SetRelationCommand)):
            subject_id = command.subject_id
        elif isinstance(command, SetPhysicsIntentCommand):
            subject_id = command.intent.subject_id
        if subject_id in existing_instances and subject_id not in authorization.mutable_instance_ids:
            issues.append(_rejection(
                RejectionCode.IMMUTABLE_AUTHORITY,
                f"approved instance {subject_id} is immutable for this authorization",
                index=index, command=command, field="subject_id",
            ))
        if isinstance(command, SetStyleCommand) and command.material_id not in authorization.mutable_material_ids:
            issues.append(_rejection(
                RejectionCode.IMMUTABLE_AUTHORITY,
                f"material {command.material_id} is immutable for this authorization",
                index=index, command=command, field="material_id",
            ))
        if isinstance(command, SetLightIntentCommand):
            if command.light.id in existing_lights and command.light.id not in authorization.mutable_light_ids:
                issues.append(_rejection(
                    RejectionCode.IMMUTABLE_AUTHORITY,
                    f"light {command.light.id} is immutable for this authorization",
                    index=index, command=command, field="light.id",
                ))
        if isinstance(command, SetInteractionIntentCommand):
            if command.intent.id in existing_interactions and command.intent.id not in authorization.mutable_interaction_ids:
                issues.append(_rejection(
                    RejectionCode.IMMUTABLE_AUTHORITY,
                    f"interaction {command.intent.id} is immutable for this authorization",
                    index=index, command=command, field="intent.id",
                ))
    return issues


def _validate_references(
    contract: WorldContract, commands: Sequence[SemanticCommand]
) -> list[CommandRejection]:
    issues: list[CommandRejection] = []
    instances = {item.id: item for item in contract.instances}
    openings = {item.id: item for item in contract.openings}
    materials = {item.id for item in contract.materials}
    physics = {item.id: item for item in contract.physics.intents}
    create_commands = [item for item in commands if isinstance(item, CreateInstanceCommand)]
    created_ids = {item.instance.id for item in create_commands}
    reference_ids = set(instances) | set(openings) | created_ids | {contract.room.id}

    identity_groups: tuple[tuple[str, list[str]], ...] = (
        ("instance", [item.instance.id for item in create_commands]),
        ("material", [item.material.id for item in create_commands]),
        ("physics", [item.physics.id for item in create_commands]),
        ("command", [item.command_id for item in commands]),
    )
    for label, values in identity_groups:
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            issues.append(_rejection(
                RejectionCode.DUPLICATE_IDENTITY,
                f"duplicate {label} identities in batch: {', '.join(duplicates)}",
                field=f"{label}_id",
            ))
    for index, command in enumerate(commands):
        if isinstance(command, CreateInstanceCommand):
            collisions = []
            if command.instance.id in instances or command.instance.id in openings or command.instance.id == contract.room.id:
                collisions.append(command.instance.id)
            if command.material.id in materials:
                collisions.append(command.material.id)
            if command.physics.id in physics:
                collisions.append(command.physics.id)
            if collisions:
                issues.append(_rejection(
                    RejectionCode.DUPLICATE_IDENTITY,
                    f"create identities already exist: {', '.join(sorted(collisions))}",
                    index=index, command=command,
                ))
        elif isinstance(command, (RemoveInstanceCommand, ReplaceInstanceCommand)):
            if command.subject_id not in instances:
                issues.append(_rejection(
                    RejectionCode.DANGLING_REFERENCE,
                    f"{command.op} requires an existing instance {command.subject_id}",
                    index=index, command=command, field="subject_id",
                ))
            elif isinstance(command, ReplaceInstanceCommand):
                current = instances[command.subject_id]
                if (
                    command.instance.material_id != current.material_id
                    or command.instance.physics_intent_id != current.physics_intent_id
                ):
                    issues.append(_rejection(
                        RejectionCode.IMMUTABLE_AUTHORITY,
                        "replace_instance must preserve material and physics stable identities",
                        index=index, command=command,
                    ))
        elif isinstance(command, SetRelationCommand):
            if command.subject_id not in set(instances) | created_ids:
                issues.append(_rejection(
                    RejectionCode.DANGLING_REFERENCE,
                    f"relation subject {command.subject_id} is neither existing nor explicitly created",
                    index=index, command=command, field="subject_id",
                ))
            target = command.relation.target_id
            if target is not None and target not in reference_ids:
                issues.append(_rejection(
                    RejectionCode.DANGLING_REFERENCE,
                    f"relation target {target} is neither existing nor explicitly created",
                    index=index, command=command, field="relation.target_id",
                ))
            if target == command.subject_id:
                issues.append(_rejection(
                    RejectionCode.RELATION_CYCLE, "self-relation is cyclic",
                    index=index, command=command, field="relation.target_id",
                ))
        elif isinstance(command, SetStyleCommand):
            if command.material_id not in materials:
                issues.append(_rejection(
                    RejectionCode.DANGLING_REFERENCE,
                    f"style material {command.material_id} does not exist",
                    index=index, command=command, field="material_id",
                ))
        elif isinstance(command, SetLightIntentCommand):
            fixture = command.light.fixture_instance_id
            if fixture is not None and fixture not in set(instances) | created_ids:
                issues.append(_rejection(
                    RejectionCode.DANGLING_REFERENCE,
                    f"light fixture {fixture} is neither existing nor explicitly created",
                    index=index, command=command, field="light.fixture_instance_id",
                ))
        elif isinstance(command, SetPhysicsIntentCommand):
            subject = command.intent.subject_id
            if subject not in set(instances) | set(openings) | created_ids:
                issues.append(_rejection(
                    RejectionCode.DANGLING_REFERENCE,
                    f"physics subject {subject} is neither existing nor explicitly created",
                    index=index, command=command, field="intent.subject_id",
                ))
            elif subject in instances and command.intent.id != instances[subject].physics_intent_id:
                issues.append(_rejection(
                    RejectionCode.IMMUTABLE_AUTHORITY,
                    "physics update must preserve the instance physics_intent_id",
                    index=index, command=command, field="intent.id",
                ))
            elif subject in openings and command.intent.id != openings[subject].physics_intent_id:
                issues.append(_rejection(
                    RejectionCode.IMMUTABLE_AUTHORITY,
                    "physics update must preserve the opening physics_intent_id",
                    index=index, command=command, field="intent.id",
                ))
        elif isinstance(command, SetInteractionIntentCommand):
            intent = command.intent
            if intent.subject_id not in reference_ids:
                issues.append(_rejection(
                    RejectionCode.DANGLING_REFERENCE,
                    f"interaction subject {intent.subject_id} is neither existing nor explicitly created",
                    index=index, command=command, field="intent.subject_id",
                ))
            if intent.target_id is not None and intent.target_id not in reference_ids:
                issues.append(_rejection(
                    RejectionCode.DANGLING_REFERENCE,
                    f"interaction target {intent.target_id} is neither existing nor explicitly created",
                    index=index, command=command, field="intent.target_id",
                ))
    return issues


def _relation_issues(instances: Mapping[str, WorldInstance]) -> list[CommandRejection]:
    graph: dict[str, set[str]] = {identity: set() for identity in instances}
    opposites = {
        RelationKind.NORTH_OF: RelationKind.SOUTH_OF,
        RelationKind.SOUTH_OF: RelationKind.NORTH_OF,
        RelationKind.EAST_OF: RelationKind.WEST_OF,
        RelationKind.WEST_OF: RelationKind.EAST_OF,
    }
    for instance in instances.values():
        by_target: dict[str, set[RelationKind]] = {}
        for relation in instance.relations:
            if relation.target_id in graph:
                graph[instance.id].add(relation.target_id)
                by_target.setdefault(relation.target_id, set()).add(relation.kind)
        for target, kinds in by_target.items():
            for kind in kinds:
                if opposites.get(kind) in kinds:
                    return [_rejection(
                        RejectionCode.CONTRADICTORY_RELATION,
                        f"{instance.id} is both {kind.value} and {opposites[kind].value} {target}",
                        field="relation",
                    )]
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, trail: tuple[str, ...]) -> tuple[str, ...] | None:
        if node in visiting:
            start = trail.index(node)
            return trail[start:] + (node,)
        if node in visited:
            return None
        visiting.add(node)
        for target in sorted(graph[node]):
            cycle = visit(target, trail + (target,))
            if cycle:
                return cycle
        visiting.remove(node)
        visited.add(node)
        return None

    for identity in sorted(graph):
        cycle = visit(identity, (identity,))
        if cycle:
            return [_rejection(
                RejectionCode.RELATION_CYCLE,
                "relation cycle: " + " -> ".join(cycle),
                field="relation.target_id",
            )]
    return []


def _apply_commands(
    contract: WorldContract, commands: Sequence[SemanticCommand]
) -> tuple[WorldContract, tuple[CameraRequestCommand, ...]]:
    instances = {item.id: item for item in contract.instances}
    materials = {item.id: item for item in contract.materials}
    physics = {item.id: item for item in contract.physics.intents}
    lights = {item.id: item for item in contract.lights}
    interactions = {item.id: item for item in contract.interactions}
    camera_requests: list[CameraRequestCommand] = []

    # Explicit creates establish identities for forward references anywhere in the batch.
    for command in commands:
        if isinstance(command, CreateInstanceCommand):
            instances[command.instance.id] = command.instance
            materials[command.material.id] = command.material
            physics[command.physics.id] = command.physics

    for command in commands:
        if isinstance(command, CreateInstanceCommand):
            continue
        if isinstance(command, RemoveInstanceCommand):
            removed = instances.pop(command.subject_id)
            materials.pop(removed.material_id, None)
            physics.pop(removed.physics_intent_id, None)
        elif isinstance(command, ReplaceInstanceCommand):
            instances[command.subject_id] = command.instance
            materials[command.material.id] = command.material
            physics[command.physics.id] = command.physics
        elif isinstance(command, SetRelationCommand):
            instance = instances[command.subject_id]
            relations = list(instance.relations)
            if command.relation not in relations:
                relations.append(command.relation)
            instances[command.subject_id] = instance.model_copy(
                update={"relations": tuple(relations)}
            )
        elif isinstance(command, SetStyleCommand):
            current = materials[command.material_id]
            materials[command.material_id] = current.model_copy(
                update=command.style.model_dump(exclude_none=True)
            )
        elif isinstance(command, SetLightIntentCommand):
            lights[command.light.id] = command.light
        elif isinstance(command, CameraRequestCommand):
            camera_requests.append(command)
        elif isinstance(command, SetPhysicsIntentCommand):
            physics[command.intent.id] = command.intent
        elif isinstance(command, SetInteractionIntentCommand):
            interactions[command.intent.id] = command.intent

    candidate = contract.model_copy(update={
        "instances": tuple(instances.values()),
        "materials": tuple(materials.values()),
        "lights": tuple(lights.values()),
        "physics": contract.physics.model_copy(update={"intents": tuple(physics.values())}),
        "interactions": tuple(interactions.values()),
    })
    # model_copy does not re-run aggregate validators; round-trip through validation.
    return WorldContract.model_validate(candidate.model_dump(mode="json")), tuple(camera_requests)


def apply_semantic_command_batch(
    contract: WorldContract,
    values: Sequence[SemanticCommand | Mapping[str, Any]],
    *,
    authorization: CommandAuthorization,
    provenance: CommandProvenance,
    limits: CommandLimits | None = None,
) -> CommandBatchResult:
    """Validate and atomically apply a complete command batch.

    The input contract is immutable. Any schema, safety, authority, reference, limit,
    relation, or aggregate-contract failure returns that exact contract and identical
    before/after hashes.
    """
    limits = limits or CommandLimits()
    if len(values) > limits.max_commands:
        return _failed(contract, [_rejection(
            RejectionCode.LIMIT_EXCEEDED,
            f"batch contains {len(values)} commands; limit is {limits.max_commands}",
            field="commands",
        )])

    commands: list[SemanticCommand] = []
    parse_issues: list[CommandRejection] = []
    for index, value in enumerate(values):
        try:
            commands.append(parse_semantic_command(value))
        except (ValidationError, ValueError) as exc:
            message = str(exc)
            code = RejectionCode.UNSAFE_CONTENT if "unsafe content" in message else RejectionCode.SCHEMA_INVALID
            parse_issues.append(_rejection(code, message, index=index, field="command"))
    if parse_issues:
        return _failed(contract, parse_issues)

    canonical_text, _ = _canonical_commands(commands)
    if len(canonical_text.encode("utf-8")) > limits.max_canonical_bytes:
        return _failed(contract, [_rejection(
            RejectionCode.LIMIT_EXCEEDED,
            "canonical command batch exceeds configured byte limit",
            field="commands",
        )])

    issues = _validate_authorization(contract, commands, authorization, provenance)
    issues.extend(_validate_references(contract, commands))
    if issues:
        return _failed(contract, issues)

    try:
        candidate, camera_requests = _apply_commands(contract, commands)
    except (ValidationError, ValueError, KeyError) as exc:
        return _failed(contract, [_rejection(
            RejectionCode.CONTRACT_INVALID,
            f"command batch would violate WorldContract invariants: {exc}",
        )])

    relation_issues = _relation_issues({item.id: item for item in candidate.instances})
    relation_count = max((len(item.relations) for item in candidate.instances), default=0)
    limit_issues: list[CommandRejection] = []
    for label, actual, maximum in (
        ("instances", len(candidate.instances), limits.max_instances),
        ("lights", len(candidate.lights), limits.max_lights),
        ("interactions", len(candidate.interactions), limits.max_interactions),
        ("relations_per_instance", relation_count, limits.max_relations_per_instance),
    ):
        if actual > maximum:
            limit_issues.append(_rejection(
                RejectionCode.LIMIT_EXCEEDED,
                f"{label} count {actual} exceeds configured limit {maximum}",
                field=label,
            ))
    if relation_issues or limit_issues:
        return _failed(contract, [*relation_issues, *limit_issues])

    canonical_text, command_hash = _canonical_commands(commands)
    before_hash = contract.content_hash()
    after_hash = candidate.content_hash()
    record = CommandBatchRecord(
        model_id=provenance.model_id,
        source_prompt_hash=provenance.source_prompt_hash,
        canonical_commands_json=canonical_text,
        command_log_hash=command_hash,
        before_hash=before_hash,
        after_hash=after_hash,
    )
    return CommandBatchResult(
        accepted=True,
        contract=candidate,
        before_hash=before_hash,
        after_hash=after_hash,
        record=record,
        camera_requests=camera_requests,
    )

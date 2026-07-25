"""Immutable prepared/terminal compiler manifests and exclusive storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

_HASH = r"^[0-9a-f]{64}$"
_ID = re.compile(r"[^A-Za-z0-9_.-]+")


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class CanonicalDocument(ManifestModel):
    """Deeply immutable JSON value represented by its exact canonical text and hash."""

    canonical_json: str
    sha256: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def verify_canonical_hash(self) -> "CanonicalDocument":
        value = json.loads(self.canonical_json)
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        if canonical != self.canonical_json:
            raise ValueError("canonical_json is not canonical")
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("canonical document hash mismatch")
        return self

    @classmethod
    def from_value(cls, value: Any) -> "CanonicalDocument":
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        text = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        return cls(canonical_json=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())

    def value(self) -> Any:
        return json.loads(self.canonical_json)

    def __getitem__(self, key: str) -> Any:
        return self.value()[key]

    def get(self, key: str, default: Any = None) -> Any:
        value = self.value()
        return value.get(key, default) if isinstance(value, dict) else default


class ManifestBinding(ManifestModel):
    session_id: str
    interface_version: int = Field(ge=1)
    workflow_profile_id: str
    workflow_profile: CanonicalDocument
    world_contract_version: str
    world_contract_hash: str = Field(pattern=_HASH)
    world_contract: CanonicalDocument
    plan_revision: int = Field(ge=0)
    plan_hash: str = Field(pattern=_HASH)
    camera_contract_id: str
    camera_contract_hash: str = Field(pattern=_HASH)
    compiler_script_hash: str = Field(pattern=_HASH)
    command_log_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def exact_documents_match_bindings(self) -> "ManifestBinding":
        profile = self.workflow_profile.value()
        if not isinstance(profile, dict) or profile.get("id") != self.workflow_profile_id:
            raise ValueError("workflow profile document does not match workflow_profile_id")
        contract = self.world_contract.value()
        if not isinstance(contract, dict):
            raise ValueError("world contract document must be an object")
        if self.world_contract.sha256 != self.world_contract_hash:
            raise ValueError("world contract document does not match world_contract_hash")
        if contract.get("schema_version") != self.world_contract_version:
            raise ValueError("world contract document does not match world_contract_version")
        return self


class CompilerVersions(ManifestModel):
    product: str
    product_version: str
    blender_version: str | None = None
    python_version: str | None = None
    compiler_version: str
    runtime_capable: bool


class TimingRecord(ManifestModel):
    stage: str
    started_at: datetime
    ended_at: datetime
    duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def valid_order(self) -> "TimingRecord":
        if self.ended_at < self.started_at:
            raise ValueError("timing ended_at precedes started_at")
        return self


class CompilerDiagnostic(ManifestModel):
    stage: str
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    violated_limit: str | None = None


class ArtifactMetadata(ManifestModel):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=_HASH)
    media_type: str
    target_role: str

    @classmethod
    def from_path(cls, path: str | Path, *, media_type: str, target_role: str) -> "ArtifactMetadata":
        artifact = Path(path)
        digest = hashlib.sha256()
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return cls(
            path=str(artifact), bytes=artifact.stat().st_size, sha256=digest.hexdigest(),
            media_type=media_type, target_role=target_role,
        )


class PreparedCompilerManifest(ManifestModel):
    schema_version: Literal["compiler-manifest/v1"] = "compiler-manifest/v1"
    manifest_id: str
    compilation_id: str
    status: Literal["prepared"] = "prepared"
    prepared_at: datetime
    binding: ManifestBinding
    compiler: CompilerVersions
    configuration: CanonicalDocument
    input_bytes: int = Field(ge=0)
    plan_validation_warnings: tuple[dict, ...] = ()

    @model_validator(mode="after")
    def exact_input_size(self) -> "PreparedCompilerManifest":
        expected = len(self.binding.world_contract.canonical_json.encode("utf-8"))
        if self.input_bytes != expected:
            raise ValueError("input_bytes does not match the canonical WorldContract bytes")
        return self


class TerminalCompilerManifest(ManifestModel):
    schema_version: Literal["compiler-manifest/v1"] = "compiler-manifest/v1"
    manifest_id: str
    compilation_id: str
    prepared_manifest_id: str
    prepared_manifest_sha256: str = Field(pattern=_HASH)
    status: Literal["completed", "failed", "timed_out", "rejected"]
    terminated_at: datetime
    binding: ManifestBinding
    compiler: CompilerVersions
    configuration: CanonicalDocument
    timings: tuple[TimingRecord, ...] = ()
    diagnostics: tuple[CompilerDiagnostic, ...] = ()
    artifacts: tuple[ArtifactMetadata, ...] = ()
    plan_validation_warnings: tuple[dict, ...] = ()

    @model_validator(mode="after")
    def unique_artifacts(self) -> "TerminalCompilerManifest":
        paths = [item.path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("terminal manifest contains duplicate artifact paths")
        if self.status == "completed" and any(
            item.severity == "error" for item in self.diagnostics
        ):
            raise ValueError("completed manifest cannot contain error diagnostics")
        return self


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def manifest_bytes(manifest: PreparedCompilerManifest | TerminalCompilerManifest) -> bytes:
    return json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def manifest_hash(manifest: PreparedCompilerManifest | TerminalCompilerManifest) -> str:
    return hashlib.sha256(manifest_bytes(manifest)).hexdigest()


def write_manifest_exclusive(
    path: str | Path, manifest: PreparedCompilerManifest | TerminalCompilerManifest,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(manifest_bytes(manifest))
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def read_prepared_manifest(path: str | Path) -> PreparedCompilerManifest:
    return PreparedCompilerManifest.model_validate_json(Path(path).read_bytes())


def read_terminal_manifest(path: str | Path) -> TerminalCompilerManifest:
    return TerminalCompilerManifest.model_validate_json(Path(path).read_bytes())


def create_prepared_manifest(
    *,
    compilation_id: str,
    binding: ManifestBinding,
    compiler: CompilerVersions,
    configuration: CanonicalDocument | Mapping[str, Any],
    input_bytes: int,
    prepared_at: datetime | None = None,
    plan_validation_warnings: Sequence[dict] = (),
) -> PreparedCompilerManifest:
    config = configuration if isinstance(configuration, CanonicalDocument) else CanonicalDocument.from_value(configuration)
    return PreparedCompilerManifest(
        manifest_id=f"{compilation_id}:prepared", compilation_id=compilation_id,
        prepared_at=prepared_at or _utc_now(), binding=binding, compiler=compiler,
        configuration=config, input_bytes=input_bytes,
        plan_validation_warnings=tuple(plan_validation_warnings),
    )


def create_terminal_manifest(
    prepared: PreparedCompilerManifest,
    *,
    status: Literal["completed", "failed", "timed_out", "rejected"],
    timings: Sequence[TimingRecord] = (),
    diagnostics: Sequence[CompilerDiagnostic] = (),
    artifacts: Sequence[ArtifactMetadata] = (),
    terminated_at: datetime | None = None,
) -> TerminalCompilerManifest:
    return TerminalCompilerManifest(
        manifest_id=f"{prepared.compilation_id}:{status}",
        compilation_id=prepared.compilation_id,
        prepared_manifest_id=prepared.manifest_id,
        prepared_manifest_sha256=manifest_hash(prepared), status=status,
        terminated_at=terminated_at or _utc_now(), binding=prepared.binding,
        compiler=prepared.compiler, configuration=prepared.configuration,
        timings=tuple(timings), diagnostics=tuple(diagnostics), artifacts=tuple(artifacts),
        plan_validation_warnings=prepared.plan_validation_warnings,
    )


class CompilerManifestStore:
    """One directory per compile attempt with exclusive prepared and terminal records."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def allocate_recompile_id(self, session_id: str) -> str:
        safe_session = _ID.sub("-", session_id).strip("-.") or "session"
        for _ in range(32):
            timestamp = _utc_now().strftime("%Y%m%dT%H%M%S%fZ")
            compilation_id = f"{safe_session}-{timestamp}-{uuid.uuid4().hex[:12]}"
            try:
                (self.root / compilation_id).mkdir()
            except FileExistsError:
                continue
            return compilation_id
        raise FileExistsError("could not allocate a unique non-overwriting compilation ID")

    def paths(self, compilation_id: str) -> tuple[Path, Path]:
        directory = self.root / compilation_id
        return directory / "prepared.json", directory / "terminal.json"

    def write_prepared(self, manifest: PreparedCompilerManifest) -> Path:
        prepared_path, _ = self.paths(manifest.compilation_id)
        return write_manifest_exclusive(prepared_path, manifest)

    def write_terminal(self, manifest: TerminalCompilerManifest) -> Path:
        prepared_path, terminal_path = self.paths(manifest.compilation_id)
        if not prepared_path.is_file():
            raise FileNotFoundError("terminal manifest requires its immutable prepared manifest")
        prepared_bytes = prepared_path.read_bytes()
        prepared = PreparedCompilerManifest.model_validate_json(prepared_bytes)
        if prepared.manifest_id != manifest.prepared_manifest_id:
            raise ValueError("terminal manifest references a different prepared manifest")
        if hashlib.sha256(prepared_bytes).hexdigest() != manifest.prepared_manifest_sha256:
            raise ValueError("terminal manifest prepared hash does not match stored bytes")
        if prepared.binding != manifest.binding or prepared.configuration != manifest.configuration:
            raise ValueError("terminal manifest inputs differ from prepared inputs")
        return write_manifest_exclusive(terminal_path, manifest)

    def prepare(
        self,
        *,
        binding: ManifestBinding,
        compiler: CompilerVersions,
        configuration: CanonicalDocument | Mapping[str, Any],
        input_bytes: int,
        prepared_at: datetime | None = None,
        plan_validation_warnings: Sequence[dict] = (),
    ) -> tuple[PreparedCompilerManifest, Path]:
        compilation_id = self.allocate_recompile_id(binding.session_id)
        manifest = create_prepared_manifest(
            compilation_id=compilation_id, binding=binding, compiler=compiler,
            configuration=configuration, input_bytes=input_bytes, prepared_at=prepared_at,
            plan_validation_warnings=plan_validation_warnings,
        )
        return manifest, self.write_prepared(manifest)

    def terminate(
        self,
        prepared: PreparedCompilerManifest,
        *,
        status: Literal["completed", "failed", "timed_out", "rejected"],
        timings: Sequence[TimingRecord] = (),
        diagnostics: Sequence[CompilerDiagnostic] = (),
        artifacts: Sequence[ArtifactMetadata] = (),
        terminated_at: datetime | None = None,
    ) -> tuple[TerminalCompilerManifest, Path]:
        terminal = create_terminal_manifest(
            prepared, status=status, timings=timings, diagnostics=diagnostics,
            artifacts=artifacts, terminated_at=terminated_at,
        )
        return terminal, self.write_terminal(terminal)

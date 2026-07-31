"""Read-only REAL-mode surface bindings for the Unified World Pipeline.

The binder owns behavior payloads only. It never emits or mutates geometry,
materials, lighting, transforms, or physics state.

Requirements: 24.1, 24.2, 24.3, 24.4, 24.5
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .modes import RealOverlay


READ_ONLY_ANNOTATIONS: dict[str, bool] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

_MISSING = object()


class RealBindingError(ValueError):
    """Base error for invalid or unsafe REAL-mode bindings."""


class ReadOnlyViolation(RealBindingError):
    """Raised when a tool binding is not explicitly safe for read-only v1."""


class UnknownSurfaceError(RealBindingError):
    """Raised when a surface UUID is malformed, unknown, or unbound."""


def _json_copy(value: Any) -> Any:
    """Return a detached JSON-compatible value or reject it."""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise RealBindingError("REAL surface data must be finite JSON-compatible data") from exc


@dataclass(frozen=True)
class MCPToolBinding:
    """MCP-compatible descriptor for one explicitly read-only tool call."""

    server_name: str
    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    annotations: Mapping[str, bool] = field(
        default_factory=lambda: dict(READ_ONLY_ANNOTATIONS)
    )

    def __post_init__(self) -> None:
        if not self.server_name.strip() or not self.tool_name.strip():
            raise RealBindingError("MCP server_name and tool_name must be non-empty")
        annotations = {**READ_ONLY_ANNOTATIONS, **dict(self.annotations)}
        if annotations.get("readOnlyHint") is not True:
            raise ReadOnlyViolation("REAL v1 requires MCP readOnlyHint=true")
        if annotations.get("destructiveHint") is not False:
            raise ReadOnlyViolation("REAL v1 requires MCP destructiveHint=false")
        object.__setattr__(self, "arguments", _json_copy(dict(self.arguments)))
        object.__setattr__(self, "annotations", annotations)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable MCP connection descriptor."""
        return {
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "arguments": _json_copy(self.arguments),
            "annotations": dict(self.annotations),
        }

    def call_request(self, request_id: str | int = 1) -> dict[str, Any]:
        """Build an MCP ``tools/call`` JSON-RPC request without executing it."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": self.tool_name,
                "arguments": _json_copy(self.arguments),
            },
        }


@dataclass(frozen=True)
class SurfaceBinding:
    """One read-only behavior binding assigned by stable surface UUID."""

    surface_uuid: str
    tool_type: str
    surface_binding: str
    mcp: MCPToolBinding
    static_data: Any = field(default=None, repr=False)
    has_static_data: bool = False

    def to_overlay_dict(self) -> dict[str, Any]:
        return {
            "tool_type": self.tool_type,
            "surface_binding": self.surface_binding,
            "read_only": True,
            "mcp": self.mcp.to_dict(),
        }


@dataclass(frozen=True)
class SurfaceDisplay:
    """Renderer-neutral text/data payload for a bound surface."""

    surface_uuid: str
    text: str
    content_type: str
    data: Any
    source: Mapping[str, str]
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface_uuid": self.surface_uuid,
            "text": self.text,
            "content_type": self.content_type,
            "data": _json_copy(self.data),
            "source": dict(self.source),
            "read_only": self.read_only,
        }


class RealBinder:
    """Assign read-only MCP tools or static data to UUID-addressed surfaces."""

    def __init__(self, surface_uuids: Iterable[str] | None = None) -> None:
        self._allowed_surfaces = (
            {self._canonical_uuid(value) for value in surface_uuids}
            if surface_uuids is not None
            else None
        )
        self._bindings: dict[str, SurfaceBinding] = {}

    @staticmethod
    def _canonical_uuid(surface_uuid: str) -> str:
        try:
            return str(uuid.UUID(surface_uuid))
        except (AttributeError, TypeError, ValueError) as exc:
            raise UnknownSurfaceError(
                f"surface binding requires a stable UUID, got {surface_uuid!r}"
            ) from exc

    def _surface(self, surface_uuid: str) -> str:
        canonical = self._canonical_uuid(surface_uuid)
        if self._allowed_surfaces is not None and canonical not in self._allowed_surfaces:
            raise UnknownSurfaceError(f"surface UUID is not present in the room: {canonical}")
        return canonical

    def bind_mcp(
        self,
        surface_uuid: str,
        *,
        tool_type: str,
        surface_binding: str,
        server_name: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        annotations: Mapping[str, bool] | None = None,
    ) -> SurfaceBinding:
        """Bind an MCP read tool; tool execution remains an adapter concern."""
        canonical = self._surface(surface_uuid)
        if not tool_type.strip() or not surface_binding.strip():
            raise RealBindingError("tool_type and surface_binding must be non-empty")
        if canonical in self._bindings:
            raise RealBindingError(f"surface already has a REAL binding: {canonical}")
        binding = SurfaceBinding(
            surface_uuid=canonical,
            tool_type=tool_type,
            surface_binding=surface_binding,
            mcp=MCPToolBinding(
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments or {},
                annotations=annotations or READ_ONLY_ANNOTATIONS,
            ),
        )
        self._bindings[canonical] = binding
        return binding

    def bind_static(
        self,
        surface_uuid: str,
        data: Any,
        *,
        surface_binding: str = "display",
    ) -> SurfaceBinding:
        """Create the MVP working binding for static text or JSON data."""
        canonical = self._surface(surface_uuid)
        if canonical in self._bindings:
            raise RealBindingError(f"surface already has a REAL binding: {canonical}")
        copied = _json_copy(data)
        binding = SurfaceBinding(
            surface_uuid=canonical,
            tool_type="static_data",
            surface_binding=surface_binding,
            mcp=MCPToolBinding(
                server_name="builtin.static",
                tool_name="read_static_data",
                arguments={},
            ),
            static_data=copied,
            has_static_data=True,
        )
        self._bindings[canonical] = binding
        return binding

    def binding_for(self, surface_uuid: str) -> SurfaceBinding:
        canonical = self._surface(surface_uuid)
        try:
            return self._bindings[canonical]
        except KeyError as exc:
            raise UnknownSurfaceError(f"surface has no REAL binding: {canonical}") from exc

    def build_mcp_request(
        self, surface_uuid: str, request_id: str | int = 1
    ) -> dict[str, Any]:
        """Build the standard request an MCP client adapter can send."""
        return self.binding_for(surface_uuid).mcp.call_request(request_id)

    def display(self, surface_uuid: str, data: Any = _MISSING) -> SurfaceDisplay:
        """Render static or adapter-supplied data without changing world visuals."""
        binding = self.binding_for(surface_uuid)
        if data is _MISSING:
            if not binding.has_static_data:
                raise RealBindingError(
                    "MCP binding needs read result data before it can be displayed"
                )
            value = _json_copy(binding.static_data)
        else:
            value = _json_copy(data)

        if isinstance(value, str):
            text = value
            content_type = "text/plain"
        else:
            text = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            content_type = "application/json"
        return SurfaceDisplay(
            surface_uuid=binding.surface_uuid,
            text=text,
            content_type=content_type,
            data=value,
            source={
                "server_name": binding.mcp.server_name,
                "tool_name": binding.mcp.tool_name,
            },
        )

    def to_overlay(self) -> RealOverlay:
        """Snapshot all bindings into the existing immutable REAL overlay model."""
        return RealOverlay(
            tool_bindings={
                surface_uuid: binding.to_overlay_dict()
                for surface_uuid, binding in self._bindings.items()
            },
            read_only=True,
        )

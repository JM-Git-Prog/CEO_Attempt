"""Project an equirectangular 360° panorama onto a known room box.

Given a panorama captured (or generated) as if from the CENTER of the room, and
the room's exact dimensions, this builds a textured, collidable room-shell GLB:
the 6 interior surfaces (floor, ceiling, 4 walls) are tessellated grids whose
per-vertex UVs sample the panorama by direction-from-center. The result *looks*
like the real room and gives real walls to collide with — the "inject geometry,
don't extract it" principle applied to the shell.

Coordinate convention (matches v2_mesh_builder._generate_room_shell + depth_placement):
  room centered at origin, floor at y=0, ceiling at y=h, up = +y,
  x in [-w/2, +w/2], z in [-d/2, +d/2]. room_dimensions = (width, depth, ceiling).

Equirectangular mapping for a direction (dx, dy, dz) from the room center:
  u = 0.5 + atan2(dx, dz) / (2*pi)     # longitude, wraps 0..1
  v = 0.5 - asin(dy / r) / pi          # latitude,  r = |(dx,dy,dz)|

The whole shell shares one panorama image as its baseColorTexture; each surface's
UVs index into it. A per-quad seam fix handles the u wraparound at ±180°.
"""
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Sequence

import numpy as np

logger = logging.getLogger("live_trace")


def _equirect_uv(px: float, py: float, pz: float, center_y: float) -> tuple[float, float]:
    """Direction from room center (0, center_y, 0) -> equirectangular (u, v)."""
    dx = px - 0.0
    dy = py - center_y
    dz = pz - 0.0
    r = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-9
    u = 0.5 + math.atan2(dx, dz) / (2.0 * math.pi)
    v = 0.5 - math.asin(max(-1.0, min(1.0, dy / r))) / math.pi
    return u, v


def _grid_surface(
    corner: tuple[float, float, float],
    u_axis: tuple[float, float, float],
    v_axis: tuple[float, float, float],
    n: int,
    center_y: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Tessellate a flat quad into an n×n grid.

    The quad spans `corner + s*u_axis + t*v_axis` for s,t in [0,1]. Returns
    (vertices Nx3, faces Mx3, uv Nx2) with per-vertex equirectangular UVs and a
    per-quad seam fix for the u wraparound.
    """
    cx, cy, cz = corner
    ux, uy, uz = u_axis
    vx, vy, vz = v_axis

    verts: list[list[float]] = []
    uvs: list[list[float]] = []
    for j in range(n + 1):
        t = j / n
        for i in range(n + 1):
            s = i / n
            x = cx + s * ux + t * vx
            y = cy + s * uy + t * vy
            z = cz + s * uz + t * vz
            verts.append([x, y, z])
            uu, vv = _equirect_uv(x, y, z, center_y)
            uvs.append([uu, vv])

    stride = n + 1
    faces: list[list[int]] = []

    def idx(i: int, j: int) -> int:
        return j * stride + i

    uv_arr = [list(p) for p in uvs]

    for j in range(n):
        for i in range(n):
            a = idx(i, j)
            b = idx(i + 1, j)
            c = idx(i + 1, j + 1)
            d = idx(i, j + 1)
            # Two triangles per quad. The ±180° u-seam is handled after
            # tessellation by _fix_seam_faces (per-triangle vertex duplication).
            faces.append([a, b, c])
            faces.append([a, c, d])

    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int64), np.array(uv_arr, dtype=np.float64)


def _fix_seam_faces(verts: np.ndarray, faces: np.ndarray, uv: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Duplicate vertices on wrapping triangles so each triangle's u values are
    continuous (no full-panorama smear across the ±180° seam)."""
    verts = verts.copy()
    uv = uv.copy()
    faces = faces.copy()
    extra_v: list[np.ndarray] = []
    extra_uv: list[list[float]] = []
    next_idx = len(verts)
    for f in range(len(faces)):
        tri = faces[f]
        us = uv[tri, 0]
        if us.max() - us.min() > 0.5:
            # remap the low-u corners of this triangle to a duplicate with u+1
            for c in range(3):
                vi = tri[c]
                if uv[vi, 0] < 0.5:
                    extra_v.append(verts[vi])
                    extra_uv.append([uv[vi, 0] + 1.0, uv[vi, 1]])
                    faces[f, c] = next_idx
                    next_idx += 1
    if extra_v:
        verts = np.vstack([verts, np.array(extra_v, dtype=np.float64)])
        uv = np.vstack([uv, np.array(extra_uv, dtype=np.float64)])
    return verts, faces, uv


def build_textured_room_shell(
    panorama_path: Path,
    room_dimensions: Sequence[float],
    output_dir: Path,
    *,
    tessellation: int = 24,
) -> Path | None:
    """Build a textured room-shell GLB from an equirectangular panorama.

    Args:
        panorama_path: equirectangular 2:1 PNG captured from the room center.
        room_dimensions: (width, depth, ceiling_height).
        output_dir: directory to write room_shell.glb into.
        tessellation: grid subdivisions per surface (higher = smoother sampling).

    Returns:
        Path to the written room_shell.glb, or None on failure.
    """
    try:
        import trimesh
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        logger.error(f"  panorama_box: trimesh/PIL unavailable: {exc}")
        return None

    panorama_path = Path(panorama_path)
    if not panorama_path.is_file():
        logger.error(f"  panorama_box: panorama not found: {panorama_path}")
        return None

    w = float(room_dimensions[0])
    d = float(room_dimensions[1])
    h = float(room_dimensions[2])
    hw, hd = w / 2.0, d / 2.0
    center_y = h / 2.0
    n = max(2, int(tessellation))

    pano = Image.open(panorama_path).convert("RGB")
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=pano,
        metallicFactor=0.0,
        roughnessFactor=0.9,
        doubleSided=True,
    )

    # Define the 6 interior surfaces as (corner, u_axis, v_axis) spanning s,t in [0,1].
    surfaces = {
        # Floor: y=0 plane, span x then z
        "floor": ((-hw, 0.0, -hd), (w, 0.0, 0.0), (0.0, 0.0, d)),
        # Ceiling: y=h plane
        "ceiling": ((-hw, h, -hd), (w, 0.0, 0.0), (0.0, 0.0, d)),
        # North wall (+Z): plane z=+hd, span x then y
        "wall_north": ((-hw, 0.0, hd), (w, 0.0, 0.0), (0.0, h, 0.0)),
        # South wall (-Z): plane z=-hd
        "wall_south": ((-hw, 0.0, -hd), (w, 0.0, 0.0), (0.0, h, 0.0)),
        # East wall (+X): plane x=+hw, span z then y
        "wall_east": ((hw, 0.0, -hd), (0.0, 0.0, d), (0.0, h, 0.0)),
        # West wall (-X): plane x=-hw
        "wall_west": ((-hw, 0.0, -hd), (0.0, 0.0, d), (0.0, h, 0.0)),
    }

    scene = trimesh.Scene()
    total_faces = 0
    total_verts = 0
    for name, (corner, u_axis, v_axis) in surfaces.items():
        verts, faces, uv = _grid_surface(corner, u_axis, v_axis, n, center_y)
        verts, faces, uv = _fix_seam_faces(verts, faces, uv)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
        scene.add_geometry(mesh, node_name=name)
        total_faces += len(faces)
        total_verts += len(verts)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "room_shell.glb"
    scene.export(str(out_path), file_type="glb")
    logger.info(
        f"  panorama_box: textured shell -> {out_path} "
        f"({total_faces} faces, {total_verts} verts, tess={n})"
    )
    return out_path


def _main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m src.unified_pipeline.panorama_box_projection <session_id>")
        return 2
    import json

    sid = sys.argv[1]
    root = Path(__file__).resolve().parents[2]
    art = root / "output" / sid / "artifacts"
    pano = art / "panorama.png"
    if not pano.is_file():
        print(f"panorama not found: {pano} (generate it first)")
        return 1
    plan_path = art / "metric_plan.json"
    dims = (5.0, 4.5, 2.7)
    if plan_path.is_file():
        try:
            dims = tuple(json.loads(plan_path.read_text(encoding="utf-8")).get("room_dimensions", dims))
        except Exception:  # noqa: BLE001
            pass
    out = build_textured_room_shell(pano, dims, art / "meshes")
    if out is None:
        print("shell build failed")
        return 1
    import trimesh

    loaded = trimesh.load(str(out), force="scene")
    faces = sum(len(g.faces) for g in loaded.geometry.values())
    verts = sum(len(g.vertices) for g in loaded.geometry.values())
    print(f"OK: {out}  faces={faces} verts={verts}  dims={dims}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

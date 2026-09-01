"""Mesh fit QA — reject a generated mesh whose PROPORTIONS cannot fit its box.

The pipeline forces every generated mesh into its catalogue bounding box by
applying a per-axis instance scale in the WorldContract. Nothing checks whether
that scale is uniform. Measured on session 39009e89 (2026-08-31):

    chair  raw 0.49 x 0.84 x 1.97   ->  box 0.50 x 0.90 x 0.55
           per-axis scale [1.02, 1.07, 0.28]  = crushed to 28% depth

A mesh scaled 1.02 on one axis and 0.28 on another is not resized, it is
deformed. That anisotropic crush - not the raw generation quality alone - is
what makes the furniture read as melted.

This module measures the mismatch BEFORE the scale is applied, so a bad mesh
can be regenerated instead of squashed. No GPU, no engine: it reads the GLB
accessor min/max that glTF already stores.

Orientation is not shape. A chair whose mesh came out lying on its side is the
right shape wearing the wrong axes, and rotating it costs nothing. So the score
is computed over every axis permutation and the BEST one wins - the verdict
then separates "regenerate this, it is the wrong shape" from "rotate this, the
shape is fine".
"""

from __future__ import annotations

import json
import struct
from itertools import permutations
from pathlib import Path
from typing import Sequence

# A mesh needing more than this ratio between its largest and smallest axis
# scale is being deformed, not resized. 1.0 is a perfect proportional match.
MAX_ANISOTROPY = 1.3

_AXIS = ("x", "y", "z")


def mesh_bbox(glb_path: str | Path) -> tuple[float, float, float]:
    """Return the (w, h, d) extent of a .glb from its glTF accessor bounds.

    glTF requires POSITION accessors to carry min/max, so the bounding box is
    readable straight from the JSON chunk - no mesh library, no GPU, no parse
    of the binary payload.
    """
    path = Path(glb_path)
    with path.open("rb") as stream:
        if stream.read(4) != b"glTF":
            raise ValueError(f"not a GLB file: {path}")
        stream.read(8)  # version + total length
        chunk_len = struct.unpack("<I", stream.read(4))[0]
        if stream.read(4) != b"JSON":
            raise ValueError(f"first GLB chunk is not JSON: {path}")
        gltf = json.loads(stream.read(chunk_len))

    lows: list[Sequence[float]] = []
    highs: list[Sequence[float]] = []
    for mesh in gltf.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            index = primitive.get("attributes", {}).get("POSITION")
            if index is None:
                continue
            accessor = gltf["accessors"][index]
            if "min" in accessor and "max" in accessor:
                lows.append(accessor["min"])
                highs.append(accessor["max"])
    if not lows:
        raise ValueError(f"no POSITION bounds found in {path}")

    return tuple(
        max(h[i] for h in highs) - min(l[i] for l in lows) for i in range(3)
    )  # type: ignore[return-value]


def best_fit(
    raw: Sequence[float], target: Sequence[float]
) -> tuple[tuple[int, ...], tuple[float, ...], float]:
    """Find the axis mapping that fits `raw` into `target` most uniformly.

    Returns (permutation, per_axis_scale, anisotropy). The permutation maps
    target axis i to raw axis permutation[i].
    """
    best: tuple[tuple[int, ...], tuple[float, ...], float] | None = None
    for order in permutations(range(3)):
        scales = tuple(
            target[i] / raw[order[i]] if raw[order[i]] > 1e-9 else float("inf")
            for i in range(3)
        )
        if any(s == float("inf") for s in scales):
            continue
        anisotropy = max(scales) / min(scales)
        if best is None or anisotropy < best[2]:
            best = (order, scales, anisotropy)
    if best is None:
        raise ValueError(f"degenerate mesh bounds: {tuple(raw)}")
    return best


def evaluate(
    glb_path: str | Path,
    target_dims: Sequence[float],
    max_anisotropy: float = MAX_ANISOTROPY,
) -> dict:
    """Judge whether a mesh can fit its catalogue box without being deformed."""
    raw = mesh_bbox(glb_path)
    order, scales, anisotropy = best_fit(raw, target_dims)

    # The scale the pipeline actually applies today: no permutation, straight
    # axis-for-axis. Comparing the two says whether a rotation would rescue it.
    naive = tuple(
        target_dims[i] / raw[i] if raw[i] > 1e-9 else float("inf") for i in range(3)
    )
    naive_anisotropy = max(naive) / min(naive)

    passes = anisotropy <= max_anisotropy
    needs_rotation = passes and order != (0, 1, 2)

    if not passes:
        verdict = "REGENERATE"
        reason = (
            f"no axis mapping fits: best anisotropy {anisotropy:.2f} "
            f"exceeds {max_anisotropy}"
        )
    elif needs_rotation:
        verdict = "ROTATE"
        reason = (
            f"shape is correct but axes are swapped: "
            f"{naive_anisotropy:.2f} -> {anisotropy:.2f} when remapped "
            f"({'->'.join(_AXIS[o] for o in order)})"
        )
    else:
        verdict = "PASS"
        reason = f"fits within {max_anisotropy} (anisotropy {anisotropy:.2f})"

    return {
        "verdict": verdict,
        "reason": reason,
        "raw_bbox": [round(v, 4) for v in raw],
        "target_dims": [round(v, 4) for v in target_dims],
        "applied_scale": [round(v, 4) for v in naive],
        "applied_anisotropy": round(naive_anisotropy, 3),
        "best_scale": [round(v, 4) for v in scales],
        "best_anisotropy": round(anisotropy, 3),
        "axis_map": list(order),
    }

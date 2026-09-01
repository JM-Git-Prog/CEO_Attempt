"""Per-asset prompt engineering — one room prompt in, mesh-ready asset prompts out.

The failures this module exists to fix, both measured 2026-08-31:

    generated chair   raw 0.49 x 0.84 x 1.97 m  ->  slot 0.50 x 0.90 x 0.55
                      anisotropy 2.24, REGENERATE

    warehouse mug     raw 0.98 x 0.73 x 0.70 m  (a mug the size of a washer)

The chair came out nearly four times too deep. The mug is an owned asset and is
just as wrong. The common cause is not the mesh model: it is that nothing
anywhere in either chain ever states how big the object is, so nothing in the
chain can be wrong about it. An unstated size cannot be checked.

So every prompt this module builds carries three things the old ones did not:

1. The object's real-world size in metres, said out loud.
2. Its SHAPE as ratios ("twice as wide as it is deep"). Generators have no feel
   for metres but do respond to proportion language, and proportion is exactly
   what the anisotropy gate measures.
3. A fixed reference-image contract. Depth is the axis image-to-mesh guesses at,
   so the camera is pinned to a three-quarter view where depth is visible rather
   than inferred, with the whole object in frame on empty ground.

`retry_prompt` closes the loop: when the gate rejects a mesh, the measured error
goes back into the next prompt as a correction in plain language, so attempt two
is told exactly which axis came out wrong and by how much.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# --------------------------------------------------------------------------
# The reference-image contract
# --------------------------------------------------------------------------
# Every one of these clauses is here because its absence produced a specific
# defect. Cropping costs the model the object's extent; a busy background gets
# meshed along with the subject; a head-on view leaves depth unobserved and the
# model invents it, which is how a 0.55 m chair became 1.97 m deep.

FRAMING = (
    "single isolated object, one object only, nothing else in frame, "
    "three-quarter view from 35 degrees above and 30 degrees to the side so the "
    "front, one side and the top are all visible at once, "
    "entire object fully inside the frame with clear empty margin on every side, "
    "not cropped, not cut off, resting on a plain seamless mid-grey backdrop, "
    "even soft studio lighting, no cast shadows on the backdrop, no floor line, "
    "no people, no hands, no text, no watermark, no props, no scale reference"
)

NEGATIVE = (
    "cropped, cut off, partial object, multiple objects, group of objects, "
    "busy background, room interior, wall, floor boards, text, watermark, "
    "people, hands, extreme perspective, fisheye, tilted horizon, motion blur"
)


# --------------------------------------------------------------------------
# Real-world dimension priors (width x height x depth, metres)
# --------------------------------------------------------------------------
# Not a catalogue of what to build — a sanity floor. Anything the room program
# invents gets checked against the nearest prior so "coffee mug: 0.98 m" is
# caught before a GPU minute is spent on it.

DIMENSION_PRIORS: Mapping[str, tuple[float, float, float]] = {
    # seating
    "executive chair": (0.71, 1.22, 0.76),
    "visitor chair": (0.61, 0.99, 0.66),
    "sofa": (1.98, 0.79, 0.89),
    # tables and case goods
    "executive desk": (1.83, 0.76, 0.91),
    "credenza": (1.83, 0.76, 0.51),
    "coffee table": (1.07, 0.43, 0.61),
    "side table": (0.51, 0.61, 0.51),
    "round meeting table": (1.07, 0.74, 1.07),
    "bookshelf": (0.91, 2.13, 0.36),
    "filing cabinet": (0.46, 1.32, 0.62),
    # lighting
    "floor lamp": (0.41, 1.68, 0.41),
    "desk lamp": (0.36, 0.38, 0.20),
    # desk-top objects
    "telephone": (0.25, 0.10, 0.23),
    "coffee mug": (0.12, 0.10, 0.09),
    "pen set": (0.20, 0.10, 0.10),
    "ashtray": (0.15, 0.05, 0.15),
    "cigar box": (0.23, 0.08, 0.15),
    "rolodex": (0.18, 0.13, 0.15),
    "desk globe": (0.36, 0.46, 0.36),
    "nameplate": (0.25, 0.05, 0.06),
    "book": (0.16, 0.24, 0.04),
    # floor and wall
    "potted plant": (0.91, 1.83, 0.91),
    "waste basket": (0.30, 0.36, 0.30),
    "framed picture": (0.46, 0.36, 0.03),
    "wall clock": (0.36, 0.36, 0.06),
    "area rug": (2.74, 0.02, 3.66),
}

# A generated size this far from its prior is a mistake, not a design choice.
PRIOR_TOLERANCE = 2.5


@dataclass(frozen=True)
class AssetSpec:
    """One object the room needs, with the size it is supposed to be."""

    name: str
    dims: tuple[float, float, float]  # width, height, depth in metres
    material: str = ""
    notes: str = ""


def _ratio_sentence(width: float, height: float, depth: float) -> str:
    """Describe the object's proportions in words a generator responds to.

    Metres mean nothing to a diffusion model. Ratios do, and ratios are exactly
    what the anisotropy gate measures, so this sentence is the prompt speaking
    the same language as the check that will judge it.
    """
    parts: list[str] = []

    if depth > 1e-6:
        wd = width / depth
        if wd >= 1.6:
            parts.append(f"about {wd:.1f} times wider than it is deep, a shallow object")
        elif wd <= 0.62:
            parts.append(f"about {1 / wd:.1f} times deeper than it is wide")
        else:
            parts.append("roughly as wide as it is deep")

    if height > 1e-6:
        hw = height / width
        if hw >= 1.6:
            parts.append(f"and clearly tall, about {hw:.1f} times taller than wide")
        elif hw <= 0.62:
            parts.append(f"and low, only about {hw:.2f} times its width in height")
        else:
            parts.append("and about as tall as it is wide")

    return ", ".join(parts)


def check_against_prior(name: str, dims: Sequence[float]) -> str | None:
    """Return a complaint if these dimensions are absurd for this object.

    Matches on the longest prior key contained in the name, so "oxblood leather
    executive chair" finds "executive chair" rather than the shorter "chair".
    """
    key = max(
        (k for k in DIMENSION_PRIORS if k in name.lower()),
        key=len,
        default=None,
    )
    if key is None:
        return None

    prior = DIMENSION_PRIORS[key]
    axis_names = ("width", "height", "depth")

    # Per axis, never on volume. Volume averages the axes together, and that
    # average hides exactly the errors worth catching: a 6.00 x 0.76 x 3.00 m
    # desk is 3.3x too wide and 3.3x too deep with a correct height, which
    # cube-roots down to 2.2x and slips under any sane volume tolerance. The
    # anisotropy gate downstream measures axes independently; so does this.
    worst_axis, worst_ratio = -1, 1.0
    for i in range(3):
        if prior[i] <= 1e-6 or dims[i] <= 1e-6:
            continue
        ratio = dims[i] / prior[i]
        skew = max(ratio, 1 / ratio)
        if skew > max(worst_ratio, 1 / worst_ratio):
            worst_axis, worst_ratio = i, ratio

    if worst_axis < 0:
        return None

    skew = max(worst_ratio, 1 / worst_ratio)
    if skew > PRIOR_TOLERANCE:
        direction = "too large" if worst_ratio > 1 else "too small"
        return (
            f"{name} is specified at {dims[0]:.2f} x {dims[1]:.2f} x {dims[2]:.2f} m "
            f"but a real {key} is about {prior[0]:.2f} x {prior[1]:.2f} x {prior[2]:.2f} m "
            f"— its {axis_names[worst_axis]} is {skew:.1f}x {direction}"
        )
    return None


def build_prompt(spec: AssetSpec, style: str) -> dict[str, str]:
    """Build the reference-image prompt for one asset."""
    width, height, depth = spec.dims
    material = f", {spec.material}" if spec.material else ""
    notes = f", {spec.notes}" if spec.notes else ""

    positive = (
        f"{spec.name}{material}{notes}, {style}, "
        f"real-world size {width:.2f} m wide, {height:.2f} m tall, {depth:.2f} m deep, "
        f"{_ratio_sentence(width, height, depth)}, "
        f"correct real-world proportions, product photography, sharp focus, "
        f"physically based materials, {FRAMING}"
    )
    return {"prompt": positive, "negative": NEGATIVE}


def retry_prompt(
    spec: AssetSpec, style: str, gate_result: Mapping, attempt: int
) -> dict[str, str]:
    """Rebuild the prompt after the anisotropy gate rejected the mesh.

    The gate already knows which axis went wrong and by how much. Handing that
    back as plain language is the whole point: attempt two is not a reroll of
    the same dice, it is a corrected instruction.
    """
    raw = gate_result.get("raw_bbox") or [0.0, 0.0, 0.0]
    target = spec.dims
    axis_names = ("width", "height", "depth")

    # Name the single worst axis rather than listing all three — one clear
    # correction outperforms three competing ones.
    worst_axis, worst_factor = 0, 1.0
    for i in range(3):
        if raw[i] > 1e-6 and target[i] > 1e-6:
            factor = raw[i] / target[i]
            if abs(factor - 1.0) > abs(worst_factor - 1.0):
                worst_axis, worst_factor = i, factor

    if worst_factor > 1.0:
        correction = (
            f"CRITICAL: the previous attempt came out {worst_factor:.1f} times too "
            f"{'deep' if worst_axis == 2 else 'large in ' + axis_names[worst_axis]}. "
            f"Make the {axis_names[worst_axis]} much smaller. "
            f"The {axis_names[worst_axis]} must be only {target[worst_axis]:.2f} m"
        )
    else:
        correction = (
            f"CRITICAL: the previous attempt came out {1 / worst_factor:.1f} times too "
            f"shallow in {axis_names[worst_axis]}. "
            f"The {axis_names[worst_axis]} must be {target[worst_axis]:.2f} m"
        )

    base = build_prompt(spec, style)
    # Escalate the camera on later attempts: if three-quarter framing did not
    # pin the depth down, a straight side elevation makes depth unambiguous.
    if attempt >= 2:
        base["prompt"] = base["prompt"].replace(
            "three-quarter view from 35 degrees above and 30 degrees to the side so the "
            "front, one side and the top are all visible at once",
            "strict side elevation view, camera exactly level with the object and "
            "square to its side, so the object's true depth is directly visible",
        )

    base["prompt"] = f"{correction}. {base['prompt']}"
    return base

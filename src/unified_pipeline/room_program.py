"""The room program — what a room contains, how big each thing is, where it goes.

This sits between the single user prompt and the asset generator. The prompt
says "a 20x20 executive office"; the program says there are 31 objects in it,
that the desk is 1.83 x 0.76 x 0.91 m, and that it stands in the north half
facing the door. Without it the generator is guessing at both the inventory and
the sizes, and today proved it guesses badly: a chair came back 1.97 m deep.

Passes exist because a fully dressed room is a long GPU session and the style
should be judged before the props are paid for. Pass 1 is a walkable shell,
pass 2 makes it an office, pass 3 makes it lived in. Each pass is reviewable.

Placement is expressed as an ANCHOR, not a coordinate. "Against the west wall"
survives a change of room size; "x=0.31" does not. The placement solver already
owns clearances and door swing, so this file states intent and lets it solve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .asset_prompt import AssetSpec, check_against_prior

# 20 ft x 20 ft x 9 ft, in metres. 1 ft = 0.3048 m exactly.
ROOM_WIDTH = 6.096
ROOM_DEPTH = 6.096
ROOM_HEIGHT = 2.743

STYLE = (
    "1980s executive noir, dark walnut and oxblood leather, brass and smoked "
    "glass, warm tungsten light, deep shadows, film-noir contrast, "
    "corporate power office, slightly worn and lived in, not showroom clean"
)


@dataclass(frozen=True)
class PlacedAsset:
    """One asset plus where it belongs in the room."""

    spec: AssetSpec
    anchor: str          # wall-north | wall-south | wall-east | wall-west | floor | on:<name>
    pass_no: int
    facing: str = ""     # which way it looks, for objects that have a front
    count: int = 1       # instanced: generated once, placed `count` times
    # How this asset comes into existence. Getting this wrong is expensive:
    # a 6.10 m wall sent to image-to-mesh is minutes of GPU for geometry a
    # BoxGeometry gives exactly right in a millisecond, and the mesh version
    # would fail the proportion gate anyway. Architecture is parametric and
    # only its SURFACE is generated; objects are meshed.
    method: str = "mesh"   # mesh | parametric


def _a(name, dims, material="", notes="", *, anchor, pass_no,
       facing="", count=1, method="mesh"):
    return PlacedAsset(
        spec=AssetSpec(name=name, dims=dims, material=material, notes=notes),
        anchor=anchor, pass_no=pass_no, facing=facing, count=count, method=method,
    )


# --------------------------------------------------------------------------
# PASS 1 — the shell. Walkable, lit, enterable. No furniture.
# --------------------------------------------------------------------------
# Windows on north and east make it a corner office, which is the whole point
# of an executive office and also costs two walls of storage. The west wall is
# therefore the only long solid run, and pass 2 spends all of it.

PASS_1_SHELL: list[PlacedAsset] = [
    _a("oak parquet floor", (ROOM_WIDTH, 0.02, ROOM_DEPTH),
       "dark stained oak parquet in a herringbone pattern, satin finish",
       anchor="floor", pass_no=1, method="parametric"),
    _a("coffered ceiling", (ROOM_WIDTH, 0.20, ROOM_DEPTH),
       "painted plaster with a shallow perimeter cove",
       anchor="ceiling", pass_no=1, method="parametric"),
    _a("panelled wall section", (ROOM_WIDTH, ROOM_HEIGHT, 0.12),
       "raised-panel walnut wainscot to 1.0 m with a chair rail, "
       "grasscloth wallpaper above",
       anchor="wall-all", pass_no=1, count=4, method="parametric"),
    _a("solid oak office door", (0.914, 2.032, 0.045),
       "solid walnut with a brass lever handle and a kick plate",
       notes="in a moulded casing, opening inward",
       anchor="wall-south", pass_no=1, facing="north", method="parametric"),
    _a("bronze-framed window", (1.22, 1.40, 0.10),
       "bronze anodised frame, smoked glass, sill at 0.90 m",
       anchor="wall-north", pass_no=1, count=3, method="parametric"),
    _a("bronze-framed window", (1.22, 1.40, 0.10),
       "bronze anodised frame, smoked glass, sill at 0.90 m",
       anchor="wall-east", pass_no=1, count=3, method="parametric"),
    _a("walnut baseboard", (ROOM_WIDTH, 0.15, 0.02),
       "stained walnut, simple ogee profile",
       anchor="wall-all", pass_no=1, count=4, method="parametric"),
    _a("recessed ceiling downlight", (0.15, 0.10, 0.15),
       "brushed brass trim, warm tungsten",
       anchor="ceiling", pass_no=1, count=6, method="parametric"),
]

# --------------------------------------------------------------------------
# PASS 2 — hero furniture. Now it is an office.
# --------------------------------------------------------------------------

PASS_2_HERO: list[PlacedAsset] = [
    _a("executive desk", (1.83, 0.76, 0.91),
       "walnut burl top with a leather inlay writing surface, brass hardware",
       notes="large partner's desk with a modesty panel",
       anchor="floor", pass_no=2, facing="south"),
    _a("high-back executive chair", (0.71, 1.22, 0.76),
       "oxblood tufted leather, brass nailhead trim, five-star castor base",
       anchor="floor", pass_no=2, facing="south"),
    _a("visitor chair", (0.61, 0.99, 0.66),
       "oxblood leather with a walnut frame and brass nailheads",
       anchor="floor", pass_no=2, facing="north", count=2),
    _a("credenza", (1.83, 0.76, 0.51),
       "walnut burl with brass pulls and a smoked glass top",
       anchor="wall-west", pass_no=2, facing="east"),
    _a("bookshelf", (0.91, 2.13, 0.36),
       "built-in walnut shelving with a brass rail",
       anchor="wall-west", pass_no=2, facing="east", count=2),
    _a("chesterfield sofa", (1.98, 0.79, 0.89),
       "oxblood button-tufted leather with rolled arms",
       anchor="floor", pass_no=2, facing="west"),
    _a("coffee table", (1.07, 0.43, 0.61),
       "smoked glass top on a brass frame",
       anchor="floor", pass_no=2),
    _a("area rug", (2.74, 0.02, 3.66),
       "deep red and navy persian pattern, low pile, worn in the traffic path",
       anchor="floor", pass_no=2),
    _a("brass floor lamp", (0.41, 1.68, 0.41),
       "brass torchiere with a pleated shade",
       anchor="floor", pass_no=2),
    _a("potted plant", (0.91, 1.83, 0.91),
       "large ficus in a brass planter",
       anchor="floor", pass_no=2),
]

# --------------------------------------------------------------------------
# PASS 3 — dressing. Now someone works here.
# --------------------------------------------------------------------------

PASS_3_DRESSING: list[PlacedAsset] = [
    _a("leather desk blotter", (0.61, 0.02, 0.46),
       "oxblood leather with brass corners",
       anchor="on:executive desk", pass_no=3),
    _a("brass banker's desk lamp", (0.36, 0.38, 0.20),
       "brass with a green glass shade",
       anchor="on:executive desk", pass_no=3),
    _a("multiline telephone", (0.25, 0.10, 0.23),
       "cream plastic with a coiled cord and lit line buttons",
       anchor="on:executive desk", pass_no=3),
    _a("rolodex", (0.18, 0.13, 0.15), "black plastic with white cards",
       anchor="on:executive desk", pass_no=3),
    _a("brass pen set", (0.20, 0.10, 0.10), "marble base with two brass pens",
       anchor="on:executive desk", pass_no=3),
    _a("crystal ashtray", (0.15, 0.05, 0.15), "heavy cut lead crystal",
       anchor="on:executive desk", pass_no=3),
    _a("cigar box", (0.23, 0.08, 0.15), "spanish cedar with a brass clasp",
       anchor="on:executive desk", pass_no=3),
    _a("stack of manila files", (0.32, 0.12, 0.24), "worn manila folders, slightly askew",
       anchor="on:executive desk", pass_no=3),
    _a("brass nameplate", (0.25, 0.05, 0.06), "engraved brass on a walnut base",
       anchor="on:executive desk", pass_no=3),
    _a("crystal whiskey decanter", (0.18, 0.28, 0.18), "cut crystal with a stopper",
       anchor="on:credenza", pass_no=3),
    _a("lowball glass", (0.08, 0.09, 0.08), "cut crystal",
       anchor="on:credenza", pass_no=3, count=2),
    _a("desk globe", (0.36, 0.46, 0.36), "antiqued paper globe in a brass meridian",
       anchor="on:credenza", pass_no=3),
    _a("framed photograph", (0.20, 0.25, 0.03), "brass frame, faded colour photo",
       anchor="on:credenza", pass_no=3, count=2),
    _a("book", (0.16, 0.24, 0.04), "cloth-bound legal volumes, mixed reds and browns",
       anchor="on:bookshelf", pass_no=3, count=24),
    _a("framed diploma", (0.46, 0.36, 0.03), "black frame with a cream mat",
       anchor="wall-west", pass_no=3),
    _a("oil painting", (1.07, 0.81, 0.06), "dark harbour scene in a heavy gilt frame",
       anchor="wall-south", pass_no=3),
    _a("wall clock", (0.36, 0.36, 0.06), "brass rim with a cream face",
       anchor="wall-south", pass_no=3),
    _a("waste basket", (0.30, 0.36, 0.30), "walnut veneer with a brass rim",
       anchor="floor", pass_no=3),
    _a("leather briefcase", (0.45, 0.33, 0.12), "worn oxblood leather, brass latches",
       anchor="floor", pass_no=3),
]

ALL_PASSES: list[PlacedAsset] = PASS_1_SHELL + PASS_2_HERO + PASS_3_DRESSING


def validate(program: list[PlacedAsset] | None = None) -> list[str]:
    """Check every asset's stated size against its real-world prior.

    Runs before a single GPU second is spent. A program that fails this is a
    program that would have produced a mug the size of a washing machine.
    """
    problems: list[str] = []
    for item in program if program is not None else ALL_PASSES:
        complaint = check_against_prior(item.spec.name, item.spec.dims)
        if complaint:
            problems.append(complaint)
    return problems


def summary() -> str:
    lines = [
        f"Executive office — {ROOM_WIDTH:.2f} x {ROOM_DEPTH:.2f} x {ROOM_HEIGHT:.2f} m "
        f"(20 x 20 x 9 ft)",
    ]
    for number, group, label in (
        (1, PASS_1_SHELL, "shell"),
        (2, PASS_2_HERO, "hero furniture"),
        (3, PASS_3_DRESSING, "dressing"),
    ):
        unique = len(group)
        placed = sum(item.count for item in group)
        lines.append(f"  pass {number} ({label}): {unique} assets to generate, "
                     f"{placed} placed instances")
    total_unique = len(ALL_PASSES)
    total_placed = sum(item.count for item in ALL_PASSES)
    lines.append(f"  total: {total_unique} generated, {total_placed} placed")
    return "\n".join(lines)

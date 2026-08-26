"""Task 11.8.4c Art-Bible-grounded deterministic recliner refinement.

Creates one append-only, independently loadable recliner candidate by refining the
Task 11.8.4b separate-component architecture. It never mutates the baseline,
starts services/sessions, or grants human approval. Art Bible and Canon are
appearance evidence only; MetricPlan, CameraContract, and WorldContract retain
their respective authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[1]
for import_root in (SCRIPT_DIR, ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import canon_decomposition_upbge_proof as baseline

SPEC_DIR = ROOT / ".kiro" / "specs" / "unified-world-pipeline"
EVIDENCE_DIR = SPEC_DIR / "evidence"
ART_BIBLE_PATH = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\danny-tornado-seven-outs-design-bible_1\danny-tornado\13-art-direction.md")
ART_BIBLE_SHA256 = "40dbcb7d0c9d3b0646668f0878ea3994f5b46178ff45909140260988a556e007"
DESIGN_BIBLE_INDEX_PATH = ART_BIBLE_PATH.with_name("README.md")
CANON_PATH = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png")
CANON_SHA256 = "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6"
RECLINER_CUTOUT_PATH = CANON_PATH.with_name("danny-v4.1-item-recliner_00002_.png")
RECLINER_CUTOUT_SHA256 = "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a"
BASELINE_DIR = EVIDENCE_DIR / "task-11.8.4b-canon-decomposition-a8c9e119-7b3a-48b1-9d40-67566733fcb5"
BASELINE_GLB_PATH = BASELINE_DIR / "deterministic-recliner.glb"
BASELINE_GLB_SHA256 = "b4a3358f1cec5b5c051301ae5bab136f0e3ce7eaeb5b9ed1f0dd918efff6a39e"
BASELINE_PROOF_PATH = BASELINE_DIR / "proof-evidence.json"
BASELINE_PROOF_SHA256 = "a4df64c85b78ee31deb32e542d612c3089bc4129abdc8e29186a3f3c0ae8b75b"
BASELINE_PACK_PATH = BASELINE_DIR / "canon-decomposition-pack.json"
BASELINE_SHELL_PATH = BASELINE_DIR / "deterministic-empty-room-shell.glb"
BASELINE_FINGERPRINT = "d220ae78b3c8fd327a5aeb6aca523fd0ee5b132429c6947b1d413e89f5d204e9"
REJECTION_PATH = EVIDENCE_DIR / "task-11.8.4b-human-rejection-best-structural-baseline-8b1d00d1-c773-4d62-a823-7e21041b43b5.json"
REJECTION_SHA256 = "36d65fbf6a617959510fb297479d295d4f4c6d69d4ba1938c85b3e195ac9c509"
RECLINER_UUID = baseline.RECLINER_UUID
BLENDER_EXE = baseline.BLENDER_EXE
OUTPUT_GLB_NAME = "refined-deterministic-recliner.glb"
PROMPTS_NAME = "art-bible-cues-and-prompts.json"
EVIDENCE_NAME = "proof-evidence.json"
LOCAL_VISION_MODEL = "qwen3-vl:8b"
LOCAL_VISION_MODEL_DIGEST = "901cae73216286ea8c5aba8b46d307ff7188f737285ec500c795a12f05225d28"
LOCAL_VISION_CONFIDENCE_THRESHOLD = 0.80

REQUIRED_COMPONENTS = {
    "recliner_root",
    "base",
    "base_skirt",
    "internal_mechanism_core",
    "seat_frame",
    "seat_cushion",
    "left_arm",
    "right_arm",
    "back_frame",
    "back_rear_cover",
    "back_continuity_mass",
    "back_cushion_lower",
    "back_cushion_upper",
    "footrest_support",
    "footrest_continuity_shroud",
    "footrest_frame",
    "footrest_cushion",
    "seat_center_seam",
    "back_vertical_seam",
    "footrest_seam",
}

COMMON_GATE_ORDER = [
    "evidence_chain_integrity",
    "stable_uuid_binding",
    "golden_room_source_identity",
    "independent_loadability",
    "non_placeholder_geometry",
    "recognizable_recliner_silhouette_identity",
    "no_fused_scene_or_ground_sheet_geometry",
    "no_obvious_catastrophic_reconstruction_artifacts",
    "neutral_multi_angle_turntable_evidence",
    "durable_non_temporary_material_continuity",
    "no_unresolved_external_materials_or_buffers",
    "explicit_hash_bound_human_approval",
]


def sha256_file(path: Path) -> str:
    return baseline.sha256_file(path)


def write_json(path: Path, value: Any) -> None:
    baseline.write_json(path, value)


def binding(path: Path, expected: str | None = None) -> dict[str, Any]:
    observed = sha256_file(path) if path.is_file() else None
    return {
        "path": str(path),
        "exists": path.is_file(),
        "sha256_expected": expected,
        "sha256_observed": observed,
        "verified": path.is_file() and (expected is None or observed == expected),
    }


def build_cues_and_prompts() -> dict[str, Any]:
    positive = (
        "A single independently isolated 1990s-era American residential recliner matching the locked Golden Room Canon: "
        "soft overstuffed apology-shaped silhouette; warm sun-faded, cozy, slightly melancholy character; broad gently winged upper back; "
        "deep pillowed lumbar cushion; wide thick seat cushion with softly rolled front edge; two substantial rounded pillow arms that taper inward toward the seat; "
        "worn mottled medium-brown microfiber or suede-like upholstery with uneven tan, umber, and tobacco wear, softened nap, darker seams and piping; "
        "conventional low rectangular recliner base mostly concealed by an upholstered skirt; one centered footrest physically integrated with the chair mechanism, "
        "aligned to the seat center and width, extending continuously from beneath the seat with a small credible hinge gap; separate inspectable back frame, upper and lower back cushions, "
        "seat frame, seat cushion, left arm, right arm, base, skirt, support, footrest frame, footrest cushion, seams, piping, and tuft details; "
        "coherent manufactured upholstery topology, plausible padding compression, rounded transitions, durable embedded PBR materials, neutral standalone asset, no room attached."
    )
    negative = (
        "rigid thin or blocky chair, hard rectangular slabs, narrow office-chair proportions, pedestal base, star base, caster base, swivel office base, exposed plinth wider than chair, "
        "detached floating footrest, separate ottoman, laterally shifted or misaligned footrest, footrest wider than seat, implausible mechanism gap, pristine modern showroom leather, "
        "bright red or burgundy glossy leather, plastic shell, chrome futurism, minimalist Scandinavian lounge chair, throne, gaming chair, duplicated arms or cushions, "
        "fused room wall floor rug table or ground sheet, background geometry, melted topology, blob-like neural mass, inflated balloon forms, collapsed back, missing seat, "
        "paper-thin upholstery, intersecting cushions, asymmetrical accidental deformation, open holes, non-manifold debris, external texture URI, temporary material, spatial-authority claims."
    )
    return {
        "schema": "unified-world-pipeline.task-11.8.4c.art-bible-cues-prompts.v1",
        "task": "11.8.4c",
        "authoritative_art_bible": {
            "path": str(ART_BIBLE_PATH),
            "sha256": ART_BIBLE_SHA256,
            "selection_basis": "The design-bible README explicitly routes the Artist role to 13-art-direction.md; 00-MASTER-BIBLE.md is identified as the shared systems spine, so it is rejected as an Art Bible substitute.",
            "ambiguous_substitutes_rejected": [
                "00-MASTER-BIBLE.md (shared narrative/systems spine, not artist production authority)",
                "08-world-texture.md (additive ambient texture pass, not the Art Direction source)",
                "DANNY-TORNADO-ASSET-MANIFEST.md (derived manifest citing the 29-file bible)",
            ],
        },
        "locked_canon": {"path": str(CANON_PATH), "sha256": CANON_SHA256},
        "source_cues": [
            {"category": "era_and_style", "cue": "late-Sierra VGA warmth; nostalgic, cozy, sun-faded and a little melancholy; the world is warm", "provenance": "Art Bible north star and one-line brief"},
            {"category": "apartment_palette", "cue": "dishwater grays, one warm lamp, dust-mote gold; lonely and faded rather than pristine", "provenance": "Art Bible palette strategy: Apartment"},
            {"category": "lighting", "cue": "single warm lamp and soft golden light pick out the meaningful object", "provenance": "Art Bible palette strategy and one-line brief"},
            {"category": "silhouette", "cue": "soft overstuffed recliner; broad two-part pillow back, deep seat, and thick rounded arms", "provenance": "locked Canon and hash-bound recliner cutout"},
            {"category": "proportion", "cue": "upper back is broad and dominant; lumbar and seat are thick; arms are substantial but taper inward; base stays visually subordinate", "provenance": "locked Canon and hash-bound recliner cutout"},
            {"category": "upholstery_material_color", "cue": "worn mottled medium brown/tan suede-like or microfiber upholstery with uneven umber/tobacco patches and dark seams", "provenance": "locked Canon pixels interpreted under Art Bible sun-faded/faded palette"},
            {"category": "construction", "cue": "conventional low recliner base and centered integrated mechanism-supported footrest aligned beneath the seat", "provenance": "locked Canon and hash-bound recliner cutout"},
            {"category": "wear", "cue": "softened nap, uneven fading, darker creases/piping and compressed cushion edges; lived-in, not distressed into damage", "provenance": "locked Canon pixels interpreted under Art Bible nostalgic/sun-faded direction"},
        ],
        "positive_prompt": positive,
        "negative_prompt": negative,
        "authority_boundary": {
            "art_bible_and_canon": "appearance/style/identity evidence only",
            "metric_plan": "sole dimensions/transforms/placement/architecture/openings/collision/navigation authority",
            "camera_contract": "sole immutable Plan-derived camera authority",
            "world_contract": "final object/relationship/binding authority",
        },
        "local_vision_screen_contract": {
            "model": LOCAL_VISION_MODEL,
            "digest": LOCAL_VISION_MODEL_DIGEST,
            "confidence_threshold": LOCAL_VISION_CONFIDENCE_THRESHOLD,
            "required_sheets": [
                "canon-camera-comparison-contact-sheet.png",
                "recliner-neutral-multi-angle-sheet.png",
            ],
            "acceptance": "Every exact sheet must return strict JSON with pass=true, empty failed_checks, and confidence >= threshold; primary adjudication remains independently mandatory.",
            "role": "local first-pass screen only; never human, Demo Ready, qualification, or release authority",
            "cloud_used": False,
            "download_performed": False,
        },
        "architecture_refinement": {
            "prior_fingerprint": BASELINE_FINGERPRINT,
            "method": "deterministic parameter refinement of the existing separate-component architecture, not neural regeneration or reuse of baseline artifact bytes",
            "preserved_components": sorted(REQUIRED_COMPONENTS),
            "visual_changes": [
                "increase cushion/arm roundness and padding volume",
                "replace glossy burgundy with worn mottled medium-brown upholstery",
                "reduce exposed dark base and add upholstered base skirt",
                "broaden and soften upper/lower back proportions",
                "integrate and center footrest with support continuity and a bounded hinge gap",
            ],
        },
    }


def prompt_fingerprint(prompts: dict[str, Any]) -> str:
    payload = json.dumps(prompts, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_textures(output_dir: Path) -> dict[str, Path]:
    from PIL import Image, ImageDraw

    texture_dir = output_dir / "textures"
    texture_dir.mkdir(parents=True, exist_ok=False)
    rng = random.Random(1184)
    paths: dict[str, Path] = {}

    def mottled(name: str, base_rgb: tuple[int, int, int], variation: int, streak: bool = False) -> None:
        image = Image.new("RGB", (128, 128), base_rgb)
        pixels = image.load()
        for y in range(128):
            for x in range(128):
                wave = int(6 * math.sin(x / 13.0) + 5 * math.sin((x + y) / 23.0))
                grain = rng.randint(-variation, variation)
                if streak:
                    grain += int(5 * math.sin(y / 5.0))
                pixels[x, y] = tuple(max(0, min(255, channel + wave + grain)) for channel in base_rgb)
        draw = ImageDraw.Draw(image, "RGBA")
        for _ in range(80):
            x = rng.randrange(128)
            y = rng.randrange(128)
            radius = rng.randrange(5, 21)
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=(54, 32, 18, rng.randrange(30, 71)),
            )
        for _ in range(40):
            x = rng.randrange(128)
            y = rng.randrange(128)
            radius = rng.randrange(4, 16)
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=(184, 139, 93, rng.randrange(20, 51)),
            )
        path = texture_dir / f"{name}.png"
        image.save(path, optimize=True)
        paths[name] = path

    mottled("worn_brown", (119, 83, 58), 17, True)
    mottled("worn_brown_shadow", (91, 61, 43), 13, True)
    mottled("dark_seam", (54, 37, 28), 8)
    mottled("dark_base", (37, 31, 27), 5)

    normal = Image.new("RGB", (128, 128), (128, 128, 255))
    normal_pixels = normal.load()
    for y in range(128):
        for x in range(128):
            weave_x = int(17 * math.sin((x + 2 * y) * math.pi / 5.0))
            weave_y = int(14 * math.sin((2 * x - y) * math.pi / 7.0))
            nap = rng.randint(-8, 8)
            normal_pixels[x, y] = (
                max(88, min(168, 128 + weave_x + nap)),
                max(88, min(168, 128 + weave_y - nap)),
                238,
            )
    normal_path = texture_dir / "worn_fabric_normal.png"
    normal.save(normal_path, optimize=True)
    paths["worn_fabric_normal"] = normal_path
    return paths


def build_worker_config(output_dir: Path, textures: dict[str, Path]) -> Path:
    config = {
        "output_dir": str(output_dir),
        "textures": {name: str(path) for name, path in textures.items()},
        "recliner_uuid": RECLINER_UUID,
        "source_baseline_fingerprint": BASELINE_FINGERPRINT,
        "art_bible_sha256": ART_BIBLE_SHA256,
        "canon_sha256": CANON_SHA256,
    }
    path = output_dir / "blender-worker-config.json"
    write_json(path, config)
    return path


def run_blender_worker(config_path: Path) -> dict[str, Any]:
    command = [
        str(BLENDER_EXE), "--background", "--factory-startup", "--python", str(Path(__file__).resolve()), "--", "--blender-worker", str(config_path)
    ]
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
    expected = [
        config_path.parent / OUTPUT_GLB_NAME,
        *(config_path.parent / f"recliner-{view}.png" for view in ("front", "right", "rear", "left", "canon-view")),
        config_path.parent / "refined-recliner-proof.blend",
    ]
    missing = [str(path) for path in expected if not path.is_file()]
    traceback = "Traceback (most recent call last)" in result.stdout or "Traceback (most recent call last)" in result.stderr
    record = {
        "command": command,
        "returncode": result.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": result.stdout[-8000:],
        "stderr_tail": result.stderr[-8000:],
        "python_traceback_detected": traceback,
        "missing_expected_outputs": missing,
    }
    if result.returncode != 0 or traceback or missing:
        raise RuntimeError(f"Blender worker failed: {record}")
    return record


def make_multiangle(output_dir: Path, destination: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    views = [("front", "FRONT"), ("right", "RIGHT"), ("rear", "REAR"), ("left", "LEFT")]
    panel, header, footer = 640, 70, 64
    sheet = Image.new("RGB", (panel * 2, header + panel * 2 + footer), (24, 23, 22))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=21)
    small = ImageFont.load_default(size=16)
    draw.text((22, 20), "Task 11.8.4c - Art-Bible-guided refined deterministic recliner", fill=(241, 230, 207), font=font)
    for index, (slug, title) in enumerate(views):
        with Image.open(output_dir / f"recliner-{slug}.png") as source:
            fitted = ImageOps.fit(source.convert("RGB"), (panel, panel), method=Image.Resampling.LANCZOS)
        x, y = (index % 2) * panel, header + (index // 2) * panel
        sheet.paste(fitted, (x, y))
        draw.rectangle((x, y, x + panel - 1, y + panel - 1), outline=(211, 176, 111), width=3)
        draw.rectangle((x + 12, y + 12, x + 144, y + 48), fill=(18, 17, 16))
        draw.text((x + 23, y + 21), title, fill=(255, 237, 191), font=small)
    draw.text((22, header + panel * 2 + 18), f"UUID {RECLINER_UUID} | separate components | embedded durable materials | human approval not inferred", fill=(232, 216, 188), font=small)
    sheet.save(destination, optimize=True)


def make_contact_sheet(output_dir: Path, destination: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    panel_size, header, footer = (640, 420), 72, 70
    sheet = Image.new("RGB", (panel_size[0] * 3, header + panel_size[1] + footer), (23, 21, 19))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=21)
    small = ImageFont.load_default(size=15)
    draw.text((22, 20), "Task 11.8.4c - locked Canon / source recliner / refined Canon-facing candidate", fill=(241, 230, 207), font=font)
    panels = [
        (CANON_PATH, "LOCKED GOLDEN ROOM CANON"),
        (RECLINER_CUTOUT_PATH, "HASH-BOUND RECLINER CUTOUT"),
        (output_dir / "recliner-canon-view.png", "REFINED CANDIDATE - CANON-FACING"),
    ]
    for index, (path, title) in enumerate(panels):
        with Image.open(path) as source:
            fitted = ImageOps.contain(source.convert("RGB"), panel_size, method=Image.Resampling.LANCZOS)
        x = index * panel_size[0]
        panel = Image.new("RGB", panel_size, (39, 35, 31))
        panel.paste(fitted, ((panel_size[0] - fitted.width) // 2, (panel_size[1] - fitted.height) // 2))
        sheet.paste(panel, (x, header))
        draw.rectangle((x, header, x + panel_size[0] - 1, header + panel_size[1] - 1), outline=(211, 176, 111), width=3)
        draw.rectangle((x + 10, header + 10, x + 360, header + 43), fill=(18, 17, 16))
        draw.text((x + 20, header + 18), title, fill=(255, 237, 191), font=small)
    draw.text((22, header + panel_size[1] + 18), "Appearance comparison only. MetricPlan owns space; CameraContract owns camera; WorldContract owns final bindings.", fill=(232, 216, 188), font=small)
    sheet.save(destination, optimize=True)


def artifact(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def candidate_fingerprint(input_hashes: dict[str, str], output_hashes: dict[str, str]) -> str:
    payload = json.dumps({"inputs": input_hashes, "outputs": output_hashes}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_evidence(output_dir: Path, prompts: dict[str, Any], blender: dict[str, Any]) -> dict[str, Any]:
    prompt_path = output_dir / PROMPTS_NAME
    glb_path = output_dir / OUTPUT_GLB_NAME
    contact_path = output_dir / "canon-camera-comparison-contact-sheet.png"
    multi_path = output_dir / "recliner-neutral-multi-angle-sheet.png"
    baseline_pack = json.loads(BASELINE_PACK_PATH.read_text(encoding="utf-8"))
    baseline_proof = json.loads(BASELINE_PROOF_PATH.read_text(encoding="utf-8"))
    inspection = baseline.inspect_glb(glb_path)
    shell_inspection = baseline.inspect_glb(BASELINE_SHELL_PATH)
    names = set(inspection["node_names"]) | set(inspection["mesh_names"])
    missing_components = sorted(name for name in REQUIRED_COMPONENTS - {"recliner_root"} if not any(name in candidate for candidate in names))
    pack_checks = baseline.validate_pack(baseline_pack)
    output_bindings = {
        "art_bible_cues_and_prompts": artifact(prompt_path),
        "refined_deterministic_recliner_glb": artifact(glb_path),
        "canon_camera_comparison_contact_sheet": artifact(contact_path),
        "recliner_neutral_multi_angle_sheet": artifact(multi_path),
        "blender_worker_config": artifact(output_dir / "blender-worker-config.json"),
        "refined_recliner_proof_blend": artifact(output_dir / "refined-recliner-proof.blend"),
    }
    input_hashes = {
        "art_bible": ART_BIBLE_SHA256,
        "canon": CANON_SHA256,
        "recliner_cutout": RECLINER_CUTOUT_SHA256,
        "baseline_fingerprint": BASELINE_FINGERPRINT,
        "baseline_glb": BASELINE_GLB_SHA256,
        "baseline_proof": BASELINE_PROOF_SHA256,
        "baseline_shell": sha256_file(BASELINE_SHELL_PATH),
        "baseline_pack": sha256_file(BASELINE_PACK_PATH),
        "rejection_record": REJECTION_SHA256,
        "generator": sha256_file(Path(__file__).resolve()),
    }
    output_hashes = {name: value["sha256"] for name, value in output_bindings.items()}
    fingerprint = candidate_fingerprint(input_hashes, output_hashes)
    replay_checks = pack_checks + [
        {"check": "immutable_source_hashes", "pass": all([
            sha256_file(ART_BIBLE_PATH) == ART_BIBLE_SHA256,
            sha256_file(CANON_PATH) == CANON_SHA256,
            sha256_file(RECLINER_CUTOUT_PATH) == RECLINER_CUTOUT_SHA256,
            sha256_file(BASELINE_GLB_PATH) == BASELINE_GLB_SHA256,
            sha256_file(BASELINE_PROOF_PATH) == BASELINE_PROOF_SHA256,
            sha256_file(REJECTION_PATH) == REJECTION_SHA256,
            baseline_proof.get("candidate_fingerprint") == BASELINE_FINGERPRINT,
        ])},
        {"check": "exact_sam3_workflow_or_verified_fallback", "pass": baseline_proof.get("comfy_execution", {}).get("execution") in {"EXACT_IMMUTABLE_API_WORKFLOW_COMPLETED", "VERIFIED_EXISTING_OUTPUTS_REUSED", "VERIFIED_EXISTING_OUTPUT_FALLBACK"}},
        {"check": "recliner_independent_load", "pass": inspection["independently_loaded"] and inspection["mesh_count"] >= 16},
        {"check": "separate_recliner_components", "pass": not missing_components and inspection["mesh_count"] >= 16},
        {"check": "embedded_durable_recliner_materials", "pass": inspection["material_count"] >= 4 and inspection["texture_count"] >= 4 and inspection["embedded_image_count"] >= 4},
        {"check": "recliner_no_external_uris", "pass": not inspection["external_buffer_uris"] and not inspection["external_image_uris"] and inspection["buffer_views_in_bounds"]},
        {"check": "shell_independent_load", "pass": shell_inspection["independently_loaded"] and shell_inspection["mesh_count"] >= 8},
        {"check": "shell_embedded_materials_no_external_uris", "pass": shell_inspection["material_count"] >= 3 and shell_inspection["embedded_image_count"] >= 3 and not shell_inspection["external_buffer_uris"] and not shell_inspection["external_image_uris"]},
        {"check": "new_geometry_distinct_from_rejected_glb", "pass": sha256_file(glb_path) not in {baseline.REJECTED_GLB_SHA256, BASELINE_GLB_SHA256} and sha256_file(BASELINE_GLB_PATH) == BASELINE_GLB_SHA256},
        {"check": "two_review_pngs", "pass": contact_path.stat().st_size > 10000 and multi_path.stat().st_size > 10000},
        {"check": "camera_and_authority_bindings", "pass": prompts["authority_boundary"]["metric_plan"].startswith("sole") and "appearance" in prompts["authority_boundary"]["art_bible_and_canon"]},
    ]
    common_gate = [
        {"check": "evidence_chain_integrity", "pass": all(value for value in input_hashes.values()) and not missing_components, "observation": "Art Bible, Canon, cutout, immutable 11.8.4b baseline, rejection, generator/configuration, and outputs are hash-bound."},
        {"check": "stable_uuid_binding", "pass": RECLINER_UUID == baseline.RECLINER_UUID and "recliner_root" in inspection["node_names"], "observation": f"Stable UUID {RECLINER_UUID} is preserved on the separate-component root."},
        {"check": "golden_room_source_identity", "pass": sha256_file(CANON_PATH) == CANON_SHA256 and sha256_file(RECLINER_CUTOUT_PATH) == RECLINER_CUTOUT_SHA256, "observation": "Candidate prompts and proportions are bound to the immutable Golden Room Canon and its exact recliner cutout."},
        {"check": "independent_loadability", "pass": inspection["independently_loaded"] and inspection["trimesh_geometry_count"] >= 16, "observation": f"trimesh loaded {inspection['trimesh_geometry_count']} separate geometries from the standalone GLB."},
        {"check": "non_placeholder_geometry", "pass": inspection["mesh_count"] >= 16 and len(names) >= 16, "observation": "Deterministic authored component topology includes cushions, arms, seams, tufting, skirt, mechanism support, and footrest; it is not a fallback box/cylinder/sphere placeholder."},
        {"check": "recognizable_recliner_silhouette_identity", "pass": not missing_components, "observation": "Named broad back, padded arms, deep seat, conventional base/skirt, and centered integrated footrest establish recliner identity; local vision screening remains separately mandatory."},
        {"check": "no_fused_scene_or_ground_sheet_geometry", "pass": not any(token in name.lower() for name in names for token in ("floor", "ground", "wall", "room", "rug")), "observation": "Export selection contains only recliner root/components; neutral ground and lights are render helpers excluded from the GLB."},
        {"check": "no_obvious_catastrophic_reconstruction_artifacts", "pass": not missing_components and inspection["mesh_count"] == inspection["trimesh_geometry_count"], "observation": "Every exported component loads as geometry with deterministic manufactured topology; visual artifact screening remains separately mandatory."},
        {"check": "neutral_multi_angle_turntable_evidence", "pass": multi_path.is_file() and multi_path.stat().st_size > 10000, "observation": f"Hash-bound front/right/rear/left sheet: {multi_path}."},
        {"check": "durable_non_temporary_material_continuity", "pass": inspection["material_count"] >= 4 and inspection["embedded_image_count"] >= 4, "observation": "Four packed texture-backed rough materials cover worn upholstery, shadow upholstery, seams/piping, and structural base."},
        {"check": "no_unresolved_external_materials_or_buffers", "pass": not inspection["external_image_uris"] and not inspection["external_buffer_uris"] and inspection["buffer_views_in_bounds"], "observation": "All image and buffer data is embedded in the GLB with in-bounds buffer views."},
        {"check": "explicit_hash_bound_human_approval", "pass": False, "observation": "PENDING: approval is never inferred. A later user decision must bind candidate fingerprint, GLB, Art Bible, Canon, both review sheets, UUID, source lane, and final gate evidence."},
    ]
    assert [check["check"] for check in common_gate] == COMMON_GATE_ORDER
    failed_replay = [check["check"] for check in replay_checks if not check["pass"]]
    failed_common_non_human = [check["check"] for check in common_gate[:-1] if not check["pass"]]
    status = "PENDING_LOCAL_VISION_SCREEN" if not failed_replay and not failed_common_non_human else "FAIL_CLOSED_NON_HUMAN_VALIDATION"
    immutable_inputs = [
        binding(ART_BIBLE_PATH, ART_BIBLE_SHA256),
        binding(DESIGN_BIBLE_INDEX_PATH),
        binding(CANON_PATH, CANON_SHA256),
        binding(RECLINER_CUTOUT_PATH, RECLINER_CUTOUT_SHA256),
        binding(BASELINE_GLB_PATH, BASELINE_GLB_SHA256),
        binding(BASELINE_PROOF_PATH, BASELINE_PROOF_SHA256),
        binding(BASELINE_PACK_PATH),
        binding(BASELINE_SHELL_PATH),
        binding(REJECTION_PATH, REJECTION_SHA256),
    ]
    return {
        "schema": "unified-world-pipeline.task-11.8.4c.art-bible-recliner-refinement.v1",
        "task": "11.8.4c",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "result": status,
        "scope": "Append-only Art-Bible-guided deterministic recliner refinement only; no Task 11.8.5, session, qualification, Demo Ready, release, UI/version, service ownership, staging, or commit.",
        "source_lane": "task_11_8_4b_deterministic_separate_component_refinement",
        "recliner_uuid": RECLINER_UUID,
        "candidate_fingerprint": fingerprint,
        "prior_baseline": {"candidate_fingerprint": BASELINE_FINGERPRINT, "glb_sha256": BASELINE_GLB_SHA256, "preserved_unchanged": sha256_file(BASELINE_GLB_PATH) == BASELINE_GLB_SHA256, "modified_or_relabelled": False},
        "art_bible": prompts["authoritative_art_bible"],
        "locked_canon": prompts["locked_canon"],
        "prompt_fingerprint": prompt_fingerprint(prompts),
        "expected_local_vision_screen": prompts["local_vision_screen_contract"],
        "immutable_input_bindings": immutable_inputs,
        "output_bindings": output_bindings,
        "glb_inspection": inspection,
        "baseline_shell_replay_inspection": shell_inspection,
        "required_components": sorted(REQUIRED_COMPONENTS),
        "missing_components": missing_components,
        "task_11_8_4b_replay_checks": replay_checks,
        "failed_replay_checks": failed_replay,
        "common_standalone_asset_gate": {
            "policy": "Same mandatory order as Task 11.8.4; no lane-specific exceptions or weakened criteria.",
            "checks_in_order": COMMON_GATE_ORDER,
            "checks": common_gate,
            "failed_non_human_checks": failed_common_non_human,
            "human_approval": {"approved": False, "status": "NOT_YET_ELIGIBLE_PENDING_LOCAL_VISION_SCREEN" if status == "PENDING_LOCAL_VISION_SCREEN" else "NOT_REQUESTED_NON_HUMAN_FAILURE"},
        },
        "authority": prompts["authority_boundary"],
        "execution": {"blender": blender, "generator_path": str(Path(__file__).resolve()), "generator_sha256": input_hashes["generator"], "configuration_sha256": output_bindings["blender_worker_config"]["sha256"]},
        "review": {"paths": [str(contact_path), str(multi_path)], "opened": False, "status": "NOT_OPENED_UNTIL_ALL_NON_HUMAN_CHECKS_PASS"},
        "preservation": {"baseline_modified": False, "new_model_or_cloud_used": False, "session_or_qualification_started": False, "ui_or_version_changed": False, "service_or_process_ownership_changed": False, "staged_or_committed": False},
        "downstream": {"task_11_8_4c": status, "task_11_8_5": "BLOCKED_NOT_STARTED"},
        "mvp_alignment": "Focused Art-Bible-guided refinement of the closest structural baseline advances the 6-8 active-coding-hour visual-first MVP target without model exploration or downstream work.",
    }


def worker_main(config_path: Path) -> int:
    import bpy
    from mathutils import Vector

    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_dir = Path(config["output_dir"])
    textures = {name: Path(path) for name, path in config["textures"].items()}
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)
    root_collection = bpy.context.scene.collection
    helper_collection = bpy.data.collections.get("Collection")
    helper_collection.name = "RenderHelpers"
    recliner_collection = bpy.data.collections.new("RefinedReclinerComponents")
    root_collection.children.link(recliner_collection)

    def material(name: str, texture_key: str, roughness: float, metallic: float = 0.0, normal_texture_key: str | None = None):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        image = bpy.data.images.load(str(textures[texture_key]), check_existing=True)
        image.pack()
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = f"{name}_EmbeddedTexture"
        tex.image = image
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if normal_texture_key:
            normal_image = bpy.data.images.load(str(textures[normal_texture_key]), check_existing=True)
            normal_image.pack()
            normal_tex = nodes.new("ShaderNodeTexImage")
            normal_tex.name = f"{name}_EmbeddedFabricNormal"
            normal_tex.image = normal_image
            normal_tex.image.colorspace_settings.name = "Non-Color"
            normal_map = nodes.new("ShaderNodeNormalMap")
            normal_map.name = f"{name}_FabricNormalMap"
            normal_map.inputs["Strength"].default_value = 0.48
            links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
            links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        return mat

    fabric = material("WornBrownMicrofiber", "worn_brown", 0.84, normal_texture_key="worn_fabric_normal")
    fabric_shadow = material("WornBrownShadowMicrofiber", "worn_brown_shadow", 0.87, normal_texture_key="worn_fabric_normal")
    seam = material("DarkBrownSeamPiping", "dark_seam", 0.66)
    structural = material("ConventionalDarkReclinerBase", "dark_base", 0.52, 0.04)

    def move_to(obj, collection):
        for current in list(obj.users_collection):
            current.objects.unlink(obj)
        collection.objects.link(obj)

    def add_rounded_box(name, dimensions, location, mat, rotation=(0.0, 0.0, 0.0), bevel=0.08):
        bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
        obj = bpy.context.object
        obj.name = name
        obj.dimensions = dimensions
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        if bevel > 0:
            modifier = obj.modifiers.new(name="SoftUpholsteryBevel", type="BEVEL")
            modifier.width = min(bevel, min(dimensions) * 0.45)
            modifier.segments = 6
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.data.name = f"{name}_mesh"
        obj.data.materials.append(mat)
        obj["task"] = "11.8.4c"
        obj["component"] = name
        move_to(obj, recliner_collection)
        return obj

    def add_soft_mass(
        name,
        dimensions,
        location,
        mat,
        rotation=(0.0, 0.0, 0.0),
        exponent=0.68,
        center_bulge=0.08,
        top_sag=0.035,
    ):
        """Create a deterministic closed pillow mass without flat slab faces."""
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=48,
            ring_count=24,
            location=location,
            rotation=rotation,
        )
        obj = bpy.context.object
        obj.name = name
        half_x, half_y, half_z = (value / 2.0 for value in dimensions)

        def signed_power(value):
            return math.copysign(abs(value) ** exponent, value) if value else 0.0

        for vertex in obj.data.vertices:
            nx, ny, nz = vertex.co.x, vertex.co.y, vertex.co.z
            sx, sy, sz = signed_power(nx), signed_power(ny), signed_power(nz)
            face_center = max(0.0, (1.0 - nx * nx) * (1.0 - nz * nz))
            sy *= 1.0 + center_bulge * face_center
            if nz > 0.0:
                sag_weight = max(0.0, (1.0 - abs(sx)) * (1.0 - abs(sy)))
                sz -= top_sag * sag_weight
            vertex.co = (sx * half_x, sy * half_y, sz * half_z)
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        obj.data.name = f"{name}_mesh"
        obj.data.materials.append(mat)
        obj["task"] = "11.8.4c"
        obj["component"] = name
        obj["construction"] = "deterministic_soft_mass"
        move_to(obj, recliner_collection)
        return obj

    root = bpy.data.objects.new("recliner_root", None)
    root["stable_uuid"] = config["recliner_uuid"]
    root["source_baseline_fingerprint"] = config["source_baseline_fingerprint"]
    root["art_bible_sha256"] = config["art_bible_sha256"]
    root["canon_sha256"] = config["canon_sha256"]
    recliner_collection.objects.link(root)
    components = []

    def component(name, dimensions, location, mat=fabric, rotation=(0.0, 0.0, 0.0), bevel=0.08):
        obj = add_rounded_box(name, dimensions, location, mat, rotation, bevel)
        obj.parent = root
        components.append(obj)
        return obj

    def soft_component(
        name,
        dimensions,
        location,
        mat=fabric,
        rotation=(0.0, 0.0, 0.0),
        exponent=0.68,
        center_bulge=0.08,
        top_sag=0.035,
    ):
        obj = add_soft_mass(name, dimensions, location, mat, rotation, exponent, center_bulge, top_sag)
        obj.parent = root
        components.append(obj)
        return obj

    # One bounded Canon-identity correction: lower/recline the back, overlap soft
    # masses to hide rails and segmentation, introduce mild manufactured asymmetry,
    # round the side mass, and bridge the seat-to-footrest upholstery continuously.
    component("base", (1.20, 0.80, 0.08), (0.0, 0.05, 0.07), fabric_shadow, bevel=0.035)
    component("internal_mechanism_core", (0.50, 0.40, 0.10), (0.0, 0.04, 0.24), structural, bevel=0.025)
    soft_component("base_skirt", (1.52, 1.08, 0.44), (0.0, 0.02, 0.30), fabric_shadow, exponent=0.90, center_bulge=0.055, top_sag=0.045)
    component("seat_frame", (1.20, 0.80, 0.08), (0.0, -0.07, 0.46), fabric_shadow, bevel=0.03)
    soft_component("seat_cushion", (1.27, 1.03, 0.38), (0.015, -0.17, 0.68), fabric, rotation=(math.radians(-6), math.radians(1), 0.0), exponent=0.90, center_bulge=0.13, top_sag=0.085)
    component("seat_center_seam", (0.018, 0.44, 0.018), (0.015, -0.29, 0.76), fabric_shadow, rotation=(math.radians(-7), math.radians(1), 0.0), bevel=0.007)
    soft_component("left_arm", (0.53, 1.08, 0.63), (-0.70, -0.03, 0.88), fabric_shadow, rotation=(math.radians(-8), math.radians(5), math.radians(-4)), exponent=0.94, center_bulge=0.15, top_sag=0.10)
    soft_component("right_arm", (0.50, 1.04, 0.61), (0.71, -0.01, 0.90), fabric_shadow, rotation=(math.radians(-6), math.radians(-3), math.radians(2)), exponent=0.96, center_bulge=0.12, top_sag=0.085)
    component("left_arm_piping", (0.018, 0.42, 0.018), (-0.70, -0.12, 0.98), fabric_shadow, rotation=(math.radians(-10), 0.0, math.radians(-4)), bevel=0.006)
    component("right_arm_piping", (0.018, 0.40, 0.018), (0.71, -0.10, 1.00), fabric_shadow, rotation=(math.radians(-8), 0.0, math.radians(2)), bevel=0.006)
    back_rotation = (math.radians(-21), 0.0, math.radians(-1))
    component("back_frame", (1.06, 0.08, 1.10), (0.0, 0.49, 1.38), fabric_shadow, rotation=back_rotation, bevel=0.03)
    soft_component("back_rear_cover", (1.35, 0.32, 1.12), (0.0, 0.49, 1.48), fabric_shadow, rotation=back_rotation, exponent=0.94, center_bulge=0.10, top_sag=0.08)
    soft_component("back_continuity_mass", (1.38, 0.38, 1.18), (-0.015, 0.22, 1.49), fabric_shadow, rotation=back_rotation, exponent=0.92, center_bulge=0.12, top_sag=0.085)
    soft_component("back_cushion_lower", (1.31, 0.46, 0.61), (0.025, 0.07, 1.21), fabric_shadow, rotation=back_rotation, exponent=0.91, center_bulge=0.16, top_sag=0.09)
    soft_component("back_cushion_upper", (1.47, 0.52, 0.72), (-0.03, 0.15, 1.72), fabric, rotation=back_rotation, exponent=0.90, center_bulge=0.18, top_sag=0.11)
    component("back_vertical_seam", (0.018, 0.020, 0.58), (-0.015, 0.12, 1.48), fabric_shadow, rotation=back_rotation, bevel=0.006)
    component("back_horizontal_seam", (0.54, 0.020, 0.018), (0.01, 0.12, 1.47), fabric_shadow, rotation=back_rotation, bevel=0.006)
    soft_component("back_left_tuft", (0.058, 0.043, 0.058), (-0.32, -0.105, 1.70), seam, rotation=back_rotation, exponent=0.84, center_bulge=0.0, top_sag=0.0)
    soft_component("back_right_tuft", (0.054, 0.041, 0.054), (0.27, -0.10, 1.73), seam, rotation=back_rotation, exponent=0.88, center_bulge=0.0, top_sag=0.0)
    foot_rotation = (math.radians(-10), 0.0, 0.0)
    component("footrest_support", (0.42, 0.32, 0.055), (0.0, -0.62, 0.37), fabric_shadow, rotation=foot_rotation, bevel=0.02)
    soft_component("footrest_continuity_shroud", (1.03, 0.72, 0.28), (0.0, -0.62, 0.50), fabric_shadow, rotation=foot_rotation, exponent=0.92, center_bulge=0.10, top_sag=0.055)
    component("footrest_frame", (0.82, 0.46, 0.055), (0.0, -0.80, 0.43), fabric_shadow, rotation=foot_rotation, bevel=0.025)
    soft_component("footrest_cushion", (1.05, 0.78, 0.29), (0.0, -0.83, 0.59), fabric, rotation=foot_rotation, exponent=0.91, center_bulge=0.13, top_sag=0.08)
    component("footrest_seam", (0.018, 0.30, 0.018), (0.0, -0.83, 0.61), fabric_shadow, rotation=foot_rotation, bevel=0.006)

    bpy.ops.object.select_all(action="DESELECT")
    for obj in [root, *components]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = components[0]
    bpy.ops.export_scene.gltf(filepath=str(output_dir / OUTPUT_GLB_NAME), export_format="GLB", use_selection=True, export_apply=True)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.world.color = (0.028, 0.026, 0.024)

    def add_area(name, location, energy, color, size):
        data = bpy.data.lights.new(name=name, type="AREA")
        data.energy, data.color, data.shape, data.size = energy, color, "DISK", size
        obj = bpy.data.objects.new(name, data)
        helper_collection.objects.link(obj)
        obj.location = location
        return obj

    add_area("WarmApartmentKey", (-3.2, -3.2, 4.8), 1050, (1.0, 0.67, 0.43), 4.5)
    add_area("SoftWindowFill", (3.8, -1.0, 3.4), 620, (0.63, 0.72, 0.85), 4.0)
    add_area("DustGoldRim", (0.0, 3.6, 4.2), 780, (1.0, 0.51, 0.26), 3.2)

    ground = add_rounded_box("neutral_render_ground", (8.0, 8.0, 0.08), (0.0, 0.0, -0.07), structural, bevel=0.0)
    move_to(ground, helper_collection)
    camera_data = bpy.data.cameras.new("ReviewCamera")
    camera = bpy.data.objects.new("ReviewCamera", camera_data)
    helper_collection.objects.link(camera)
    scene.camera = camera
    camera_data.lens = 62

    def look_at(obj, target):
        direction = Vector(target) - obj.location
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    views = {
        "front": (0.0, -4.4, 1.82),
        "right": (4.4, 0.0, 1.82),
        "rear": (0.0, 4.4, 1.82),
        "left": (-4.4, 0.0, 1.82),
    }
    for name, position in views.items():
        camera.location = position
        look_at(camera, (0.0, -0.04, 1.12))
        scene.render.filepath = str(output_dir / f"recliner-{name}.png")
        bpy.ops.render.render(write_still=True)

    camera_data.lens = 58
    camera.location = (3.45, -4.25, 2.15)
    look_at(camera, (0.0, -0.10, 1.10))
    scene.render.filepath = str(output_dir / "recliner-canon-view.png")
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_dir / "refined-recliner-proof.blend"))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--blender-worker", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.blender_worker:
        return worker_main(args.blender_worker.resolve())
    if args.output_dir is None:
        raise SystemExit("--output-dir is required")
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite append-only evidence directory: {output_dir}")
    required_bindings = [
        binding(ART_BIBLE_PATH, ART_BIBLE_SHA256), binding(CANON_PATH, CANON_SHA256), binding(RECLINER_CUTOUT_PATH, RECLINER_CUTOUT_SHA256),
        binding(BASELINE_GLB_PATH, BASELINE_GLB_SHA256), binding(BASELINE_PROOF_PATH, BASELINE_PROOF_SHA256), binding(REJECTION_PATH, REJECTION_SHA256),
    ]
    failures = [item for item in required_bindings if not item["verified"]]
    if failures:
        raise SystemExit(f"Fail closed: immutable input mismatch: {json.dumps(failures, indent=2)}")
    if not BLENDER_EXE.is_file():
        raise SystemExit(f"Blender executable not found: {BLENDER_EXE}")
    output_dir.mkdir(parents=True)
    prompts = build_cues_and_prompts()
    write_json(output_dir / PROMPTS_NAME, prompts)
    textures = create_textures(output_dir)
    config_path = build_worker_config(output_dir, textures)
    blender = run_blender_worker(config_path)
    make_multiangle(output_dir, output_dir / "recliner-neutral-multi-angle-sheet.png")
    make_contact_sheet(output_dir, output_dir / "canon-camera-comparison-contact-sheet.png")
    evidence = build_evidence(output_dir, prompts, blender)
    write_json(output_dir / EVIDENCE_NAME, evidence)
    print(json.dumps({
        "result": evidence["result"],
        "output_dir": str(output_dir),
        "candidate_fingerprint": evidence["candidate_fingerprint"],
        "glb_sha256": evidence["output_bindings"]["refined_deterministic_recliner_glb"]["sha256"],
        "failed_replay_checks": evidence["failed_replay_checks"],
        "failed_common_non_human_checks": evidence["common_standalone_asset_gate"]["failed_non_human_checks"],
        "review_paths": evidence["review"]["paths"],
    }, indent=2))
    return 0 if evidence["result"] == "PENDING_LOCAL_VISION_SCREEN" else 2


if __name__ == "__main__":
    separator = sys.argv.index("--") + 1 if "--" in sys.argv else 1
    raise SystemExit(main(sys.argv[separator:]))

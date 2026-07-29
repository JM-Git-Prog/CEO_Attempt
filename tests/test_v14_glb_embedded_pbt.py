"""Property-based tests for GLB Embedded Textures (No External References).

# Feature: photo-to-real-3d-world-v14

## Property 15: GLB Embedded Textures (No External References)

**Validates: Requirements 11.1**

For any GLB file produced by the pipeline, parsing the glTF JSON chunk SHALL
reveal zero image entries with external `uri` fields — all textures SHALL
reference `bufferView` indices (embedded).

This test creates GLB files via the MaterialProcessor (both Pass 1 and Pass 2),
then structurally verifies that:
1. The glTF JSON chunk contains zero images with external `uri` fields
2. All image entries reference `bufferView` indices (embedded)
3. No external file references are present when loaded via trimesh
"""

from __future__ import annotations

import json
import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from src.photo_pipeline.stages.material_processor import MaterialProcessor


# ---------------------------------------------------------------------------
# GLB Binary Format Parsing Utilities
# ---------------------------------------------------------------------------

# GLB magic number (ASCII "glTF")
_GLB_MAGIC = 0x46546C67
# GLB version 2
_GLB_VERSION = 2
# JSON chunk type
_CHUNK_TYPE_JSON = 0x4E4F534A  # "JSON" in little-endian
# BIN chunk type
_CHUNK_TYPE_BIN = 0x004E4942  # "BIN\0" in little-endian


def parse_glb_json_chunk(glb_path: Path) -> dict:
    """Parse a GLB file and extract the JSON chunk as a dictionary.

    GLB binary format:
    - 12-byte header: magic (4), version (4), total_length (4)
    - Chunks: each has length (4), type (4), data (length bytes)
    - First chunk is always JSON (type 0x4E4F534A)

    Args:
        glb_path: Path to the GLB file.

    Returns:
        Parsed JSON chunk as a dictionary.

    Raises:
        ValueError: If the file is not a valid GLB or has no JSON chunk.
    """
    with open(glb_path, "rb") as f:
        # Read 12-byte header
        header = f.read(12)
        if len(header) < 12:
            raise ValueError(f"File too small to be GLB: {glb_path}")

        magic, version, total_length = struct.unpack("<III", header)

        if magic != _GLB_MAGIC:
            raise ValueError(
                f"Not a GLB file (magic=0x{magic:08X}, expected 0x{_GLB_MAGIC:08X}): "
                f"{glb_path}"
            )
        if version != _GLB_VERSION:
            raise ValueError(
                f"Unsupported GLB version {version} (expected {_GLB_VERSION}): "
                f"{glb_path}"
            )

        # Read chunks until we find the JSON chunk
        while f.tell() < total_length:
            chunk_header = f.read(8)
            if len(chunk_header) < 8:
                break

            chunk_length, chunk_type = struct.unpack("<II", chunk_header)

            if chunk_type == _CHUNK_TYPE_JSON:
                json_data = f.read(chunk_length)
                # JSON chunk may be padded with spaces (0x20)
                json_str = json_data.decode("utf-8").rstrip()
                return json.loads(json_str)
            else:
                # Skip this chunk
                f.seek(chunk_length, 1)

    raise ValueError(f"No JSON chunk found in GLB: {glb_path}")


def check_glb_no_external_references(glb_path: Path) -> list[str]:
    """Check a GLB file for external URI references in its images.

    Returns a list of violation descriptions. Empty list means all images
    are properly embedded via bufferView.

    Args:
        glb_path: Path to the GLB file.

    Returns:
        List of violation strings (empty = pass).
    """
    violations = []

    gltf_json = parse_glb_json_chunk(glb_path)

    images = gltf_json.get("images", [])
    for idx, image_entry in enumerate(images):
        # Check for external URI (violation)
        if "uri" in image_entry:
            violations.append(
                f"Image[{idx}] has external uri: '{image_entry['uri']}'"
            )

        # Check for bufferView (required for embedding)
        if "bufferView" not in image_entry:
            violations.append(
                f"Image[{idx}] missing bufferView (not embedded)"
            )

    return violations


# ---------------------------------------------------------------------------
# Test Fixtures — create test assets
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    return tmp_path


@pytest.fixture
def object_png(tmp_workspace: Path) -> Path:
    """Create a test RGBA object PNG image."""
    png_path = tmp_workspace / "test_object.png"
    # Create a simple 64x64 RGBA image with some content
    img_array = np.random.randint(0, 255, (64, 64, 4), dtype=np.uint8)
    img_array[:, :, 3] = 255  # Full alpha
    img = Image.fromarray(img_array, mode="RGBA")
    img.save(str(png_path))
    return png_path


@pytest.fixture
def placeholder_glb(tmp_workspace: Path) -> Path:
    """Create a placeholder GLB mesh (box geometry, no textures)."""
    glb_path = tmp_workspace / "placeholder_object.glb"
    # Create a simple box mesh (placeholder geometry)
    mesh = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    # Generate UV coordinates for texturing
    uv = np.random.rand(len(mesh.vertices), 2).astype(np.float32)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv)
    mesh.export(str(glb_path), file_type="glb")
    return glb_path


@pytest.fixture
def neural_glb(tmp_workspace: Path) -> Path:
    """Create a GLB simulating neural generator output (textured icosphere).

    Simulates what Hunyuan3D or Trellis2 would produce: a mesh with
    embedded base color texture.
    """
    glb_path = tmp_workspace / "neural_object.glb"
    # Create an icosphere with sufficient geometry
    mesh = trimesh.creation.icosphere(subdivisions=3)

    # Apply a texture (simulating neural generator output)
    texture_array = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    texture_img = Image.fromarray(texture_array, mode="RGB")
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=texture_img,
        metallicFactor=0.0,
        roughnessFactor=0.5,
    )
    uv = np.random.rand(len(mesh.vertices), 2).astype(np.float32)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    mesh.export(str(glb_path), file_type="glb")
    return glb_path


@pytest.fixture
def material_processor() -> MaterialProcessor:
    """Create a MaterialProcessor instance."""
    return MaterialProcessor()


# ---------------------------------------------------------------------------
# Property 15: GLB Embedded Textures (No External References)
# ---------------------------------------------------------------------------


class TestGLBEmbeddedTexturesProperty:
    """Property 15: GLB Embedded Textures (No External References).

    **Validates: Requirements 11.1**

    For any GLB file produced by the pipeline, parsing the glTF JSON chunk
    SHALL reveal zero image entries with external `uri` fields — all textures
    SHALL reference `bufferView` indices (embedded).
    """

    def test_pass1_placeholder_photo_projection_embeds_textures(
        self,
        material_processor: MaterialProcessor,
        placeholder_glb: Path,
        object_png: Path,
    ) -> None:
        """Pass 1 photo-projection on placeholder produces embedded textures.

        **Validates: Requirements 11.1**

        After Pass 1 applies photo-projected texture to a placeholder mesh,
        the resulting GLB SHALL have all textures embedded (no external URIs).
        """
        # Apply Pass 1 to placeholder geometry
        result = material_processor.apply_pass1(
            glb_path=placeholder_glb,
            object_png=object_png,
            generation_method="placeholder",
            image_area_pct=0.05,  # medium tier
        )

        assert result.has_base_color, "Pass 1 should apply base color texture"

        # Parse GLB and check for external references
        violations = check_glb_no_external_references(placeholder_glb)
        assert violations == [], (
            f"GLB has external references after Pass 1 photo-projection: "
            f"{violations}"
        )

    def test_pass1_neural_mesh_retains_embedded_textures(
        self,
        material_processor: MaterialProcessor,
        neural_glb: Path,
        object_png: Path,
    ) -> None:
        """Pass 1 on neural mesh (Hunyuan3D/Trellis2) retains embedded textures.

        **Validates: Requirements 11.1**

        Neural generator GLBs already have embedded textures; Pass 1 should
        confirm they remain embedded (no conversion to external URIs).
        """
        # Apply Pass 1 to neural-generated mesh (hunyuan3d method)
        result = material_processor.apply_pass1(
            glb_path=neural_glb,
            object_png=object_png,
            generation_method="hunyuan3d_v2.1",
            image_area_pct=0.15,  # large tier
        )

        assert result.has_base_color, "Neural mesh should have base color"

        # Neural mesh retains its textures — verify they're still embedded
        violations = check_glb_no_external_references(neural_glb)
        assert violations == [], (
            f"Neural GLB has external references after Pass 1 confirmation: "
            f"{violations}"
        )

    def test_pass1_trellis2_mesh_retains_embedded_textures(
        self,
        material_processor: MaterialProcessor,
        neural_glb: Path,
        object_png: Path,
    ) -> None:
        """Pass 1 on Trellis2 mesh retains embedded textures.

        **Validates: Requirements 11.1**
        """
        result = material_processor.apply_pass1(
            glb_path=neural_glb,
            object_png=object_png,
            generation_method="trellis2",
            image_area_pct=0.08,
        )

        assert result.has_base_color
        violations = check_glb_no_external_references(neural_glb)
        assert violations == [], (
            f"Trellis2 GLB has external references: {violations}"
        )

    @pytest.mark.asyncio
    async def test_pass2_pbr_update_embeds_all_textures(
        self,
        material_processor: MaterialProcessor,
        placeholder_glb: Path,
        object_png: Path,
    ) -> None:
        """Pass 2 PBR update produces GLB with all textures embedded.

        **Validates: Requirements 11.1**

        After Pass 2 applies metallic-roughness and normal map textures,
        the resulting GLB SHALL have ALL textures (base color, metallic-roughness,
        normal) embedded via bufferView, with zero external URI references.
        """
        # First apply Pass 1 to get a textured mesh
        material_processor.apply_pass1(
            glb_path=placeholder_glb,
            object_png=object_png,
            generation_method="placeholder",
            image_area_pct=0.05,
        )

        # Apply Pass 2 PBR estimation
        result = await material_processor.apply_pass2(
            glb_path=placeholder_glb,
            object_png=object_png,
            material_type="wood",
        )

        assert result.has_metallic_roughness, "Pass 2 should add metallic-roughness"
        assert result.has_normal_map, "Pass 2 should add normal map"

        # Parse GLB and verify ALL textures are embedded
        violations = check_glb_no_external_references(placeholder_glb)
        assert violations == [], (
            f"GLB has external references after Pass 2 PBR update: {violations}"
        )

    @pytest.mark.asyncio
    async def test_pass2_on_neural_mesh_embeds_all_textures(
        self,
        material_processor: MaterialProcessor,
        neural_glb: Path,
        object_png: Path,
    ) -> None:
        """Pass 2 on neural mesh (with existing base color) embeds all PBR textures.

        **Validates: Requirements 11.1**
        """
        # Apply Pass 2 to neural mesh that already has base color
        result = await material_processor.apply_pass2(
            glb_path=neural_glb,
            object_png=object_png,
            material_type="metal",
        )

        assert result.has_metallic_roughness
        assert result.has_normal_map

        violations = check_glb_no_external_references(neural_glb)
        assert violations == [], (
            f"Neural GLB has external references after Pass 2: {violations}"
        )

    @pytest.mark.parametrize(
        "material_type",
        ["metal", "wood", "glass", "fabric", "ceramic", "plastic"],
    )
    @pytest.mark.asyncio
    async def test_pass2_all_material_types_embed_textures(
        self,
        material_processor: MaterialProcessor,
        tmp_path: Path,
        material_type: str,
    ) -> None:
        """All material type heuristics produce GLBs with embedded textures.

        **Validates: Requirements 11.1**

        For every supported material type, the resulting GLB SHALL have
        textures embedded as buffer views.
        """
        # Create a fresh placeholder for each material type
        glb_path = tmp_path / f"object_{material_type}.glb"
        mesh = trimesh.creation.icosphere(subdivisions=2)
        uv = np.random.rand(len(mesh.vertices), 2).astype(np.float32)
        texture_img = Image.fromarray(
            np.random.randint(0, 255, (32, 32, 3), dtype=np.uint8), mode="RGB"
        )
        material = trimesh.visual.material.PBRMaterial(
            baseColorTexture=texture_img,
        )
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
        mesh.export(str(glb_path), file_type="glb")

        # Create object PNG
        png_path = tmp_path / f"object_{material_type}.png"
        img = Image.fromarray(
            np.random.randint(0, 255, (32, 32, 4), dtype=np.uint8), mode="RGBA"
        )
        img.save(str(png_path))

        # Apply Pass 2 with this material type
        result = await material_processor.apply_pass2(
            glb_path=glb_path,
            object_png=png_path,
            material_type=material_type,
        )

        assert result.has_metallic_roughness
        violations = check_glb_no_external_references(glb_path)
        assert violations == [], (
            f"Material type '{material_type}' produced external refs: {violations}"
        )

    def test_trimesh_load_no_external_references_pass1(
        self,
        material_processor: MaterialProcessor,
        placeholder_glb: Path,
        object_png: Path,
    ) -> None:
        """Trimesh validation: loading Pass 1 GLB reveals no external file refs.

        **Validates: Requirements 11.1**

        Verify via trimesh that loading the GLB does not produce any external
        file resolver requests or unresolved texture paths.
        """
        # Apply Pass 1
        material_processor.apply_pass1(
            glb_path=placeholder_glb,
            object_png=object_png,
            generation_method="placeholder",
            image_area_pct=0.05,
        )

        # Load via trimesh and verify materials are self-contained
        scene = trimesh.load(str(placeholder_glb), force="scene")
        assert isinstance(scene, trimesh.Scene)

        for name, geom in scene.geometry.items():
            if hasattr(geom, "visual") and hasattr(geom.visual, "material"):
                mat = geom.visual.material
                # PBR materials should have textures loaded (not paths)
                if hasattr(mat, "baseColorTexture") and mat.baseColorTexture is not None:
                    tex = mat.baseColorTexture
                    # Texture should be a PIL Image (in-memory), not a file path
                    assert isinstance(tex, Image.Image), (
                        f"Geometry '{name}' has baseColorTexture that is not "
                        f"an in-memory image: {type(tex)}"
                    )

    @pytest.mark.asyncio
    async def test_trimesh_load_no_external_references_pass2(
        self,
        material_processor: MaterialProcessor,
        placeholder_glb: Path,
        object_png: Path,
    ) -> None:
        """Trimesh validation: loading Pass 2 GLB reveals no external file refs.

        **Validates: Requirements 11.1**
        """
        # Apply Pass 1 then Pass 2
        material_processor.apply_pass1(
            glb_path=placeholder_glb,
            object_png=object_png,
            generation_method="placeholder",
            image_area_pct=0.05,
        )
        await material_processor.apply_pass2(
            glb_path=placeholder_glb,
            object_png=object_png,
            material_type="ceramic",
        )

        # Load via trimesh — no external file references
        scene = trimesh.load(str(placeholder_glb), force="scene")
        assert isinstance(scene, trimesh.Scene)

        for name, geom in scene.geometry.items():
            if hasattr(geom, "visual") and hasattr(geom.visual, "material"):
                mat = geom.visual.material
                if hasattr(mat, "baseColorTexture") and mat.baseColorTexture is not None:
                    assert isinstance(mat.baseColorTexture, Image.Image), (
                        f"Geometry '{name}' baseColorTexture not in-memory after Pass 2"
                    )
                if hasattr(mat, "metallicRoughnessTexture") and mat.metallicRoughnessTexture is not None:
                    assert isinstance(mat.metallicRoughnessTexture, Image.Image), (
                        f"Geometry '{name}' metallicRoughnessTexture not in-memory"
                    )
                if hasattr(mat, "normalTexture") and mat.normalTexture is not None:
                    assert isinstance(mat.normalTexture, Image.Image), (
                        f"Geometry '{name}' normalTexture not in-memory"
                    )

    def test_glb_json_chunk_parseable(
        self,
        neural_glb: Path,
    ) -> None:
        """GLB binary format is correctly structured with valid JSON chunk.

        **Validates: Requirements 11.1**

        Verify the GLB file follows the binary format spec:
        - 12-byte header with correct magic and version
        - First chunk is JSON type (0x4E4F534A)
        - JSON chunk parses to a valid glTF structure
        """
        gltf_json = parse_glb_json_chunk(neural_glb)

        # Must have asset field (required by glTF spec)
        assert "asset" in gltf_json, "glTF JSON must have 'asset' field"
        assert gltf_json["asset"].get("version") == "2.0", (
            "glTF version must be 2.0"
        )

        # If images exist, all must be embedded
        if "images" in gltf_json:
            for idx, img_entry in enumerate(gltf_json["images"]):
                assert "uri" not in img_entry, (
                    f"Image[{idx}] has external uri (should use bufferView)"
                )
                assert "bufferView" in img_entry, (
                    f"Image[{idx}] missing bufferView (not embedded)"
                )

    @pytest.mark.parametrize("area_pct", [0.01, 0.05, 0.15])
    def test_all_texture_size_tiers_produce_embedded_glb(
        self,
        material_processor: MaterialProcessor,
        tmp_path: Path,
        area_pct: float,
    ) -> None:
        """All texture size tiers (256, 512, 1024) produce embedded GLBs.

        **Validates: Requirements 11.1**

        Regardless of which texture size tier is selected (based on area_pct),
        the output GLB SHALL always embed textures as buffer views.
        """
        # Create placeholder mesh
        glb_path = tmp_path / f"object_area_{int(area_pct * 100)}.glb"
        mesh = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
        uv = np.random.rand(len(mesh.vertices), 2).astype(np.float32)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv)
        mesh.export(str(glb_path), file_type="glb")

        # Create object PNG
        png_path = tmp_path / f"object_area_{int(area_pct * 100)}.png"
        img = Image.fromarray(
            np.random.randint(0, 255, (64, 64, 4), dtype=np.uint8), mode="RGBA"
        )
        img.save(str(png_path))

        # Apply Pass 1
        result = material_processor.apply_pass1(
            glb_path=glb_path,
            object_png=png_path,
            generation_method="placeholder",
            image_area_pct=area_pct,
        )

        assert result.has_base_color
        violations = check_glb_no_external_references(glb_path)
        assert violations == [], (
            f"area_pct={area_pct} produced GLB with external refs: {violations}"
        )

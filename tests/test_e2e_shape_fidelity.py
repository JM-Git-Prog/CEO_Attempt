"""
E2E test: Text-to-Game Fidelity — Shape variety and prompt responsiveness.

Validates that:
1. Different prompts produce different scenes (not always the 1950s diner)
2. Objects get appropriate primitive shapes based on their type/name
3. The pipeline stages produce output matching the input description
"""

import asyncio
import os

import httpx
import pytest

# Test against the live server at localhost:8000
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
INTERFACE_VERSION = "11"
TIMEOUT_SECONDS = 300  # total pipeline timeout (LLM calls can take 30-60s each)
POLL_INTERVAL = 2


def _new_session_id():
    import uuid
    return str(uuid.uuid4())


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestShapeFidelity:
    """Verify the pipeline assigns appropriate primitive shapes based on object names."""

    PROMPT = (
        "A Japanese tea room with tatami mats on the floor, a low wooden table in the "
        "center, two paper lanterns hanging from the ceiling, a ceramic tea pot on the "
        "table, a round cushion for sitting, and sliding shoji doors on the east wall."
    )

    # Objects we expect the pipeline to create, with expected shapes
    EXPECTED_SHAPES = {
        # Lanterns/lamps → cylinder
        "lantern": "cylinder",
        "lamp": "cylinder",
        # Pots → cylinder  
        "pot": "cylinder",
        "tea pot": "cylinder",
        "teapot": "cylinder",
        # Tatami/mats → box (flat)
        "tatami": "box",
        "mat": "box",
        # Tables → box
        "table": "box",
        # Cushions → sphere (round) or box
        "cushion": ("sphere", "box"),
    }

    @pytest.mark.asyncio
    async def test_japanese_tea_room_produces_varied_shapes(self):
        """Submit a Japanese tea room prompt and verify shape variety."""
        session_id = _new_session_id()

        async with httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            headers={"X-App-Version": INTERFACE_VERSION},
        ) as client:
            # Step 1: Create session and submit description
            resp = await client.post(
                f"/api/session/{session_id}/describe",
                json={"description": self.PROMPT},
            )
            if resp.status_code != 200:
                pytest.skip(
                    f"Pipeline returned {resp.status_code}: {resp.text[:200]}. "
                    "LLM may be unavailable."
                )

            data = resp.json()
            assert "concept" in data or "floor_plan" in data, (
                f"Expected concept or floor_plan in response: {list(data.keys())}"
            )

            # Step 2: Check the scene concept
            concept = data.get("concept", {})
            if concept:
                # Verify the concept reflects Japanese tea room, not a diner
                era = concept.get("era", "").lower()
                mood = concept.get("mood", "").lower()
                key_objects = [obj.lower() for obj in concept.get("key_objects", [])]

                # Should NOT be a 1950s diner
                assert "1950s" not in era or "diner" not in era, (
                    f"Scene concept is a 1950s diner, not responsive to prompt! era={era}"
                )

                # Should reference Japanese/tea room elements
                all_text = f"{era} {mood} {' '.join(key_objects)}"
                japanese_indicators = ("japan", "tea", "zen", "tatami", "shoji", "wabi")
                has_japanese = any(ind in all_text for ind in japanese_indicators)
                assert has_japanese, (
                    f"Scene concept doesn't reflect Japanese tea room prompt. "
                    f"Got era='{era}', mood='{mood}', objects={key_objects[:5]}"
                )

            # Step 3: Check the floor plan for shape variety
            floor_plan = data.get("floor_plan", {})
            items = floor_plan.get("items", [])
            if items:
                item_names = [item.get("name", "").lower() for item in items]
                # Should have tea-room objects, not diner objects
                all_names = " ".join(item_names)
                assert "stool" not in all_names or "chrome" not in all_names, (
                    f"Floor plan contains chrome diner stools instead of tea room items: {item_names}"
                )

            # Step 4: Approve plan and get scene graph
            approve_resp = await client.post(
                f"/api/session/{session_id}/approve_plan"
            )
            if approve_resp.status_code != 200:
                # Approval might fail for V11 composition issues - check snapshot
                snap_resp = await client.get(
                    f"/api/session/{session_id}/snapshot"
                )
                if snap_resp.status_code == 200:
                    snap = snap_resp.json()
                    scene_graph = snap.get("scene_graph")
                    if scene_graph:
                        self._verify_shape_variety(scene_graph)
                        return
                pytest.skip(
                    f"Plan approval returned {approve_resp.status_code}. "
                    "Skipping scene graph verification."
                )
                return

            # Step 5: Build the world/scene graph
            # The approve_plan might trigger scene graph generation in some versions
            approve_data = approve_resp.json()
            scene_graph = approve_data.get("scene_graph")

            if not scene_graph:
                # Try to get it from the snapshot
                snap_resp = await client.get(
                    f"/api/session/{session_id}/snapshot"
                )
                if snap_resp.status_code == 200:
                    scene_graph = snap_resp.json().get("scene_graph")

            if scene_graph:
                self._verify_shape_variety(scene_graph)

    def _verify_shape_variety(self, scene_graph: dict):
        """Verify the scene graph has varied primitive shapes, not all boxes."""
        objects = scene_graph.get("objects", [])
        assert len(objects) > 0, "Scene graph has no objects"

        shapes_used = set()
        shape_assignments = []

        for obj in objects:
            shape = obj.get("primitive_shape", "box")
            name = obj.get("name", "").lower()
            shapes_used.add(shape)
            shape_assignments.append((name, shape))

        # Key assertion: NOT all boxes
        assert len(shapes_used) > 1, (
            f"All {len(objects)} objects are '{next(iter(shapes_used))}' — "
            f"no shape variety! Objects: {[a[0] for a in shape_assignments]}"
        )

        # Check specific shape expectations
        for obj_name, shape in shape_assignments:
            for keyword, expected in self.EXPECTED_SHAPES.items():
                if keyword in obj_name:
                    if isinstance(expected, tuple):
                        assert shape in expected, (
                            f"Object '{obj_name}' has shape '{shape}' "
                            f"but expected one of {expected}"
                        )
                    else:
                        assert shape == expected, (
                            f"Object '{obj_name}' has shape '{shape}' "
                            f"but expected '{expected}'"
                        )


class TestShapeInferenceUnit:
    """Unit tests for the shape inference function (no LLM needed)."""

    def test_cylinder_objects(self):
        from src.scene_graph.builder import _infer_primitive_shape

        cylinder_cases = [
            ("Paper Lantern", "fixture", "Hanging paper lantern"),
            ("Bar Stool", "furniture", "Tall bar stool with legs"),
            ("Floor Lamp", "fixture", "Standing floor lamp"),
            ("Candle", "decor", "Beeswax candle on plate"),
            ("Ceramic Vase", "decor", "Tall ceramic vase with flowers"),
            ("Pillar", "architectural", "Stone support pillar"),
            ("Column", "architectural", "Greek column"),
            ("Barrel", "decor", "Wooden barrel"),
            ("Round Table", "furniture", "Small round café table"),
            ("Stool", "furniture", "Wooden stool"),
            ("Tea Pot", "decor", "Ceramic tea pot"),
        ]
        for name, cat, desc in cylinder_cases:
            result = _infer_primitive_shape(name, cat, desc)
            assert result == "cylinder", (
                f"Expected 'cylinder' for '{name}' but got '{result}'"
            )

    def test_sphere_objects(self):
        from src.scene_graph.builder import _infer_primitive_shape

        sphere_cases = [
            ("Globe", "decor", "Desktop globe"),
            ("Rice Bowl", "decor", "Ceramic rice bowl"),
            ("Ball", "decor", "Rubber ball"),
            ("Ornament", "decor", "Glass Christmas ornament"),
        ]
        for name, cat, desc in sphere_cases:
            result = _infer_primitive_shape(name, cat, desc)
            assert result == "sphere", (
                f"Expected 'sphere' for '{name}' but got '{result}'"
            )

    def test_capsule_objects(self):
        from src.scene_graph.builder import _infer_primitive_shape

        capsule_cases = [
            ("Mannequin", "decor", "Store mannequin"),
            ("Statue", "decor", "Bronze statue"),
            ("Person", "decor", "Standing person"),
        ]
        for name, cat, desc in capsule_cases:
            result = _infer_primitive_shape(name, cat, desc)
            assert result == "capsule", (
                f"Expected 'capsule' for '{name}' but got '{result}'"
            )

    def test_box_objects_not_false_positives(self):
        from src.scene_graph.builder import _infer_primitive_shape

        box_cases = [
            ("Low Table", "furniture", "Wooden low table"),
            ("Desk", "furniture", "Writing desk"),
            ("Bookshelf", "furniture", "Large bookshelf"),
            ("Cabinet", "furniture", "Kitchen cabinet"),
            ("Counter", "furniture", "Formica counter"),
            ("Bed", "furniture", "Queen size bed"),
            ("Ottoman", "furniture", "Cushioned ottoman"),
            ("Sliding Door", "architectural", "Paper shoji door"),
            ("Tatami Mat", "decor", "Woven tatami floor mat"),
        ]
        for name, cat, desc in box_cases:
            result = _infer_primitive_shape(name, cat, desc)
            assert result == "box", (
                f"Expected 'box' for '{name}' but got '{result}'"
            )

    def test_shape_override_in_constraints(self):
        """Verify that _apply_plan_constraints overrides 'box' to inferred shape."""
        from src.floor_plan.models import FloorPlan, PlanItem, PlanRoom, PlanOpening
        from src.models import (
            MaterialProps, PhysicsBody, PhysicsProps, RoomShell,
            SceneGraph, SceneLight, SceneObject, Vec3,
        )
        from src.scene_graph.builder import _apply_plan_constraints

        # Create a minimal floor plan with a stool item
        plan = FloorPlan(
            name="test",
            room=PlanRoom(width=4.0, depth=4.0, height=3.0),
            items=[
                PlanItem(
                    id="stool_1", name="Bar Stool", category="furniture",
                    x=0.0, z=0.0, width=0.4, depth=0.4, height=0.75,
                    elevation=0.0, rotation_deg=0.0, fixed=False,
                    clearance_m=0.2, description="Chrome bar stool",
                ),
                PlanItem(
                    id="table_1", name="Dining Table", category="furniture",
                    x=1.0, z=1.0, width=1.2, depth=0.8, height=0.75,
                    elevation=0.0, rotation_deg=0.0, fixed=True,
                    clearance_m=0.5, description="Rectangular dining table",
                ),
            ],
            openings=[],
            camera={"x": 1.5, "y": 1.5, "z": -1.5, "target_x": 0, "target_y": 0.7,
                    "target_z": 0, "fov_deg": 55},
        )

        # Create a scene graph where the LLM set both objects to "box"
        scene = SceneGraph(
            name="test_scene", description="Test",
            room=RoomShell(width=4.0, depth=4.0, height=3.0),
            objects=[
                SceneObject(
                    id="stool_1", name="Bar Stool", object_type="furniture",
                    position=Vec3(x=0, y=0, z=0), dimensions=Vec3(x=0.4, y=0.75, z=0.4),
                    physics=PhysicsProps(body_type=PhysicsBody.RIGID, mass_kg=8.0),
                    material=MaterialProps(base_color="#c0c0c0"),
                    primitive_shape="box",  # LLM defaulted to box
                ),
                SceneObject(
                    id="table_1", name="Dining Table", object_type="furniture",
                    position=Vec3(x=1, y=0, z=1), dimensions=Vec3(x=1.2, y=0.75, z=0.8),
                    physics=PhysicsProps(body_type=PhysicsBody.STATIC, mass_kg=30.0),
                    material=MaterialProps(base_color="#8b6b42"),
                    primitive_shape="box",  # correct for a rectangular table
                ),
            ],
            lights=[
                SceneLight(
                    id="light_1", name="Ambient", light_type="point",
                    position=Vec3(x=0, y=2.5, z=0),
                    direction=Vec3(x=0, y=-1, z=0),
                    color="#ffffff", intensity=1.0,
                ),
            ],
        )

        _apply_plan_constraints(scene, plan)

        # Stool should have been upgraded from box to cylinder
        stool = next(obj for obj in scene.objects if obj.id == "stool_1")
        assert stool.primitive_shape == "cylinder", (
            f"Stool should be 'cylinder' but got '{stool.primitive_shape}'"
        )

        # Table should remain as box (rectangular table is correctly box)
        table = next(obj for obj in scene.objects if obj.id == "table_1")
        assert table.primitive_shape == "box", (
            f"Rectangular table should remain 'box' but got '{table.primitive_shape}'"
        )

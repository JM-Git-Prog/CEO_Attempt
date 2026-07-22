from __future__ import annotations

import json
from pathlib import Path

from src.camera_contract import camera_contract_for_plan
from src.floor_plan.models import FloorPlan
from src.models import SceneGraph
from src.world_contract import ExportPolicy, WorldContract, build_world_contract

FIXTURE = Path(__file__).parent / "fixtures" / "current_runtime_characterization.json"


def build_test_contract(*, interactions=(), targets=("upbge_blend",)) -> WorldContract:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plan = FloorPlan.model_validate(payload["plan"])
    scene = SceneGraph.model_validate(payload["scene_graph"])
    return build_world_contract(
        plan,
        scene,
        camera_contract_for_plan(plan),
        session_id="upbge-test",
        interface_version=11,
        profile_id="upbge-isolated-r1",
        plan_revision=1,
        appearance_intent={"mood": "neutral"},
        export_policy=ExportPolicy(targets=targets),
        interactions=interactions,
    )

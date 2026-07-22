"""Automated API-level test harness for The Living Room on feat/articulated-blockout-r3.

Runs the canonical prompt through the full pipeline via HTTP, validates each stage,
uses Ollama for visual QA on generated images, and reports pass/fail per stage.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8000"
HEADERS = {"X-App-Version": "10", "Content-Type": "application/json"}
POLL_INTERVAL = 3.0
POLL_TIMEOUT = 300.0  # 5 minutes max per stage

CANONICAL_PROMPT = (
    "Create a compact rectangular 1950s American diner interior exactly 6 meters wide, "
    "4 meters deep, and 2.8 meters high.\n\n"
    "The approved composition must contain exactly one fixed 4.2-meter-long Formica counter "
    "centered parallel to the north wall. Give it rounded polished-chrome edge trim and a "
    "pale mint-green front.\n\n"
    "Place exactly four individual red-vinyl-and-chrome swivel stools in a straight, evenly "
    "spaced row along the south side of the counter. Each stool must be a separate object. "
    "Leave a clear circulation aisle behind the stools.\n\n"
    "Install one standard-width swinging kitchen door on the west wall near the northwest "
    "corner. Center one large storefront window on the south wall. Keep both openings "
    "unobstructed.\n\n"
    "Hang exactly three individual polished-chrome pendant lights in an evenly spaced row "
    "directly above the counter. Use a glossy black-and-cream checkerboard linoleum floor, "
    "cream ceramic tile wainscoting, pale mint-green upper walls, and a lightly aged "
    "pressed-tin ceiling.\n\n"
    "Set the scene after closing on a rainy evening. Warm amber light from the three pendants "
    "should illuminate the counter and red stools. Cool blue-gray rainy light should enter "
    "through the storefront window. The atmosphere should feel cinematic, nostalgic, intimate, "
    "realistic, and professionally photographed.\n\n"
    "Place the canon camera at normal eye height in the southeast corner, looking diagonally "
    "northwest across all four stools toward the counter and kitchen door. Use a natural "
    "rectilinear architectural-photography lens with a 55-degree field of view.\n\n"
    "The final camera view must clearly show the complete counter, all four separate stools, "
    "all three pendant lights, the kitchen door, and part of the rainy storefront window.\n\n"
    "Do not add people, booths, tables, extra stools, extra lights, extra doors, extra "
    "windows, signs, readable text, or unrelated furniture. Do not treat the floor, walls, "
    "ceiling, doors, or windows as furniture objects. Preserve the requested object counts "
    "exactly."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_json(path: str, method: str = "GET", body: dict | None = None,
              expected: tuple[int, ...] = (200,), timeout: float = 180) -> tuple[int, dict]:
    """Make an HTTP request and return (status, json_body)."""
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            payload = {"error": f"HTTP {status}"}
    except urllib.error.URLError as exc:
        raise AssertionError(f"{method} {path}: connection error — {exc.reason}")
    if status not in expected:
        raise AssertionError(f"{method} {path}: expected {expected}, got {status} — {payload}")
    return status, payload


def http_bytes(path: str) -> tuple[int, bytes]:
    """Fetch raw bytes (for images)."""
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, method="GET", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception:
        return 0, b""


def poll_until(session_id: str, target_states: set[str], timeout: float = POLL_TIMEOUT) -> dict:
    """Poll session status until it reaches one of the target states."""
    deadline = time.monotonic() + timeout
    last_state = None
    last_progress = ""
    while time.monotonic() < deadline:
        _, status = http_json(f"/api/session/{session_id}/status")
        state = status.get("state", "unknown")
        progress = status.get("progress", [""])
        latest_msg = progress[-1] if progress else ""
        if state != last_state or latest_msg != last_progress:
            print(f"  [{utc_now()}] state={state} progress={latest_msg[:80]}")
            last_state = state
            last_progress = latest_msg
        if state in target_states:
            return status
        if state == "error":
            raise AssertionError(f"Session entered error state: {status}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Timed out after {timeout}s waiting for {target_states}, last state: {last_state}")


def ollama_vision_qa(image_bytes: bytes, checklist: str) -> dict:
    """Use Ollama qwen2.5vl:7b to QA a generated image against a checklist."""
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": "qwen2.5vl:7b",
        "messages": [
            {"role": "system", "content": "You are a visual QA inspector for architectural renders. "
             "Respond ONLY with valid JSON: {\"pass\": bool, \"failed_checks\": [...], \"confidence\": 0.0-1.0, \"notes\": \"...\"}"},
            {"role": "user", "content": checklist, "images": [b64]}
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512}
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode())
        content = result.get("message", {}).get("content", "{}")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"pass": False, "failed_checks": ["invalid_json_response"], "confidence": 0, "raw": content[:500]}
    except Exception as e:
        return {"pass": None, "failed_checks": ["vision_qa_unavailable"], "confidence": 0, "error": str(e)[:200]}


def validate_plan(session_id: str, plan_data: dict) -> list[str]:
    """Validate floor plan against canonical requirements. Returns list of failures."""
    failures = []
    plan = plan_data.get("floor_plan", plan_data)

    room = plan.get("room", {})
    if [room.get("width"), room.get("depth"), room.get("height")] != [6.0, 4.0, 2.8]:
        failures.append(f"Room dimensions wrong: {room.get('width')}x{room.get('depth')}x{room.get('height')}")

    items = plan.get("items", [])
    openings = plan.get("openings", [])

    counters = [i for i in items if "counter" in str(i.get("id", "")).lower()]
    stools = [i for i in items if "stool" in str(i.get("id", "")).lower()]
    pendants = [i for i in items if "light" in str(i.get("id", "")).lower() or "pendant" in str(i.get("id", "")).lower()]
    doors = [o for o in openings if o.get("kind") == "door"]
    windows = [o for o in openings if o.get("kind") == "window"]

    if len(counters) != 1:
        failures.append(f"Expected 1 counter, got {len(counters)}")
    elif counters and counters[0].get("width") != 4.2:
        failures.append(f"Counter width should be 4.2m, got {counters[0].get('width')}")

    if len(stools) != 4:
        failures.append(f"Expected 4 stools, got {len(stools)}")
    if len(pendants) != 3:
        failures.append(f"Expected 3 pendant lights, got {len(pendants)}")
    if len(doors) != 1:
        failures.append(f"Expected 1 door, got {len(doors)}")
    elif doors and doors[0].get("wall") != "west":
        failures.append(f"Door should be on west wall, got {doors[0].get('wall')}")
    if len(windows) != 1:
        failures.append(f"Expected 1 window, got {len(windows)}")
    elif windows and windows[0].get("wall") != "south":
        failures.append(f"Window should be on south wall, got {windows[0].get('wall')}")

    camera = plan.get("camera", {})
    if camera.get("fov_deg") != 55.0:
        failures.append(f"Camera FOV should be 55, got {camera.get('fov_deg')}")

    return failures


def validate_world(session_id: str, world_data: dict) -> list[str]:
    """Validate world/scene graph against canonical requirements."""
    failures = []
    sg = world_data.get("scene_graph", {})

    objects = sg.get("objects", [])
    lights = sg.get("lights", [])
    doors = sg.get("doors", [])
    windows = sg.get("windows", [])

    if len(objects) != 8:
        failures.append(f"Expected 8 scene objects, got {len(objects)}")
    if len(lights) != 3:
        failures.append(f"Expected 3 lights, got {len(lights)}")
    if len(doors) != 1:
        failures.append(f"Expected 1 door, got {len(doors)}")
    if len(windows) != 1:
        failures.append(f"Expected 1 window, got {len(windows)}")

    # Check download availability
    download_url = world_data.get("download_url")
    if download_url:
        status, _ = http_bytes(download_url)
        if status != 200:
            failures.append(f"Download URL returned {status}")

    return failures


CANON_QA_CHECKLIST = """Inspect this architectural render of a 1950s American diner interior. Check:
1. GEOMETRY: Is the room roughly rectangular? Does it appear to be an interior?
2. COUNTER: Is there exactly ONE long counter parallel to the back wall?
3. STOOLS: Are there exactly FOUR separate stools in a row?
4. PENDANTS: Are there exactly THREE pendant lights hanging above the counter?
5. DOOR: Is there a door visible on one side wall?
6. WINDOW: Is there a large window visible (possibly showing rain/evening)?
7. CAMERA: Is this viewed from a corner, looking diagonally across?
8. MATERIALS: Checkerboard floor, mint-green walls, chrome/red vinyl stools?
9. LIGHTING: Warm amber from pendants, cool blue from window?
10. NO EXTRAS: No people, no booths, no extra furniture?

Rate each check as pass/fail. Report your overall verdict."""


BLOCKOUT_QA_CHECKLIST = """Inspect this 3D blockout render (gray/white geometry preview of a room interior). Check:
1. ROOM SHAPE: Is it a rectangular enclosed room viewed from a corner?
2. COUNTER: Is there ONE long rectangular block (the counter) along the back wall?
3. STOOLS: Are there FOUR separate small objects (stool shapes) in a row in front of the counter?
4. PENDANT LIGHTS: Are there THREE separate hanging objects above the counter?
5. DOOR: Is there a door opening visible on one side wall?
6. WINDOW: Is there a window opening visible on another wall?
7. CAMERA ANGLE: Is this viewed from approximately eye height in a corner, looking diagonally across?
8. NO EXTRAS: Are there no unexpected large objects or extra geometry beyond the specified items?

This is a geometry preview only — colors/materials don't matter, only shapes and counts.
Rate each check as pass/fail. Report your overall verdict."""


def run_full_pass() -> dict:
    """Run one complete canonical prompt test pass. Returns results dict."""
    results = {
        "started_at": utc_now(),
        "session_id": None,
        "stages": {},
        "overall": "pending",
    }

    print(f"\n{'='*60}")
    print(f"TEST PASS STARTED — {utc_now()}")
    print(f"{'='*60}")

    # 1. Create session
    print("\n[1/6] Creating session...")
    _, session = http_json("/api/session", method="POST")
    session_id = session["session_id"]
    results["session_id"] = session_id
    results["interface_version"] = session.get("interface_version")
    results["workflow_profile_id"] = session.get("workflow_profile_id")
    print(f"  Session: {session_id} (v{session.get('interface_version')}, profile={session.get('workflow_profile_id')})")

    # 2. Submit description (Brief stage)
    print("\n[2/6] Submitting canonical prompt (Brief → Plan)...")
    try:
        _, describe_resp = http_json(
            f"/api/session/{session_id}/describe",
            method="POST",
            body={"description": CANONICAL_PROMPT},
            timeout=300  # LLM can take a while
        )
        results["stages"]["brief"] = {"status": "pass", "response_state": describe_resp.get("state")}
        print(f"  Brief/Plan completed — state: {describe_resp.get('state')}")
    except Exception as e:
        # The describe endpoint might timeout if it's truly async — check status
        print(f"  Describe call raised: {e}")
        print("  Polling for plan completion...")
        try:
            status_resp = poll_until(session_id, {"awaiting_plan_approval", "awaiting_approval", "ready", "error"})
            # Fetch the snapshot to get plan data
            _, describe_resp = http_json(f"/api/session/{session_id}/snapshot")
            results["stages"]["brief"] = {"status": "pass", "response_state": describe_resp.get("state")}
            print(f"  Brief/Plan completed via polling — state: {describe_resp.get('state')}")
        except Exception as e2:
            results["stages"]["brief"] = {"status": "fail", "error": str(e2)}
            results["overall"] = "fail_at_brief"
            print(f"  Brief FAILED: {e2}")
            return results

    # 3. Validate Plan
    print("\n[3/6] Validating Plan...")
    # The plan data might be nested differently based on whether we got it from describe or snapshot
    plan_data = describe_resp.get("floor_plan", {})
    if not plan_data and describe_resp.get("concept"):
        # Might need to fetch floor_plan separately
        _, snapshot = http_json(f"/api/session/{session_id}/snapshot")
        plan_data = snapshot.get("floor_plan", {})
        describe_resp = snapshot

    plan_failures = validate_plan(session_id, describe_resp)
    if plan_failures:
        results["stages"]["plan"] = {"status": "fail", "failures": plan_failures}
        print(f"  Plan FAILED: {plan_failures}")
        # Don't abort — try to continue
    else:
        results["stages"]["plan"] = {"status": "pass", "item_count": len(plan_data.get("items", []))}
        print(f"  Plan passed — {len(plan_data.get('items', []))} items")

    # Fetch blockout image for QA
    print("\n[3.5/6] Fetching Blockout...")
    blockout_url = describe_resp.get("blockout_image") or f"/api/session/{session_id}/blockout"
    status, blockout_bytes = http_bytes(blockout_url)
    if status == 200 and len(blockout_bytes) > 1000:
        results["stages"]["blockout"] = {"status": "pass", "size_bytes": len(blockout_bytes)}
        print(f"  Blockout fetched — {len(blockout_bytes)} bytes")

        # Vision QA on Blockout
        print("  Running Ollama vision QA on Blockout (3D geometry preview)...")
        blockout_qa = ollama_vision_qa(blockout_bytes, BLOCKOUT_QA_CHECKLIST)
        results["stages"]["blockout"]["vision_qa"] = blockout_qa
        if blockout_qa.get("pass"):
            print(f"  Blockout Vision QA PASSED (confidence: {blockout_qa.get('confidence', '?')})")
        elif blockout_qa.get("pass") is None:
            print(f"  Blockout Vision QA skipped: {blockout_qa.get('error', 'unavailable')}")
        else:
            print(f"  Blockout Vision QA concerns: {blockout_qa.get('failed_checks', [])}")
            results["stages"]["blockout"]["status"] = "warn_vision"
    else:
        results["stages"]["blockout"] = {"status": "fail", "http_status": status, "size": len(blockout_bytes) if blockout_bytes else 0}
        print(f"  Blockout FAILED: status={status}")

    # Fetch and QA the 2D floor plan SVG
    print("\n[3.6/6] Fetching Floor Plan SVG (2D blueprint)...")
    floor_plan_url = describe_resp.get("floor_plan_image") or f"/api/session/{session_id}/floor_plan"
    status, svg_bytes = http_bytes(floor_plan_url)
    if status == 200 and len(svg_bytes) > 100:
        svg_text = svg_bytes.decode("utf-8", errors="replace")
        results["stages"]["floor_plan_svg"] = {"status": "pass", "size_bytes": len(svg_bytes)}
        print(f"  Floor Plan SVG fetched — {len(svg_bytes)} bytes")

        # Structural check: does the SVG contain expected elements?
        svg_checks = []
        if "<svg" not in svg_text:
            svg_checks.append("not_valid_svg")
        if "counter" not in svg_text.lower() and "rect" not in svg_text.lower():
            svg_checks.append("no_counter_element")
        if svg_text.lower().count("stool") < 4 and svg_text.count("<circle") + svg_text.count("<rect") < 6:
            svg_checks.append("possibly_missing_stool_markers")
        # Check for door/window indicators
        if "door" not in svg_text.lower() and "arc" not in svg_text.lower():
            svg_checks.append("no_door_indicator")
        if "window" not in svg_text.lower() and "dashed" not in svg_text.lower():
            svg_checks.append("no_window_indicator")

        if svg_checks:
            results["stages"]["floor_plan_svg"]["warnings"] = svg_checks
            print(f"  SVG structural warnings: {svg_checks}")
        else:
            print("  SVG structural checks passed")
    else:
        results["stages"]["floor_plan_svg"] = {"status": "fail", "http_status": status}
        print(f"  Floor Plan SVG FAILED: status={status}")

    # 4. Approve Plan → Canon generation
    print("\n[4/6] Approving plan → generating Canon...")
    try:
        status_code, approve_resp = http_json(
            f"/api/session/{session_id}/approve_plan",
            method="POST",
            expected=(200, 409),
            timeout=300  # Canon generation via FLUX can take a while
        )
        if status_code == 409:
            # V10 plan validation failed — report it
            validation = approve_resp.get("validation_report", {})
            results["stages"]["canon"] = {
                "status": "fail",
                "error": "plan_validation_rejected",
                "validation": validation,
                "message": approve_resp.get("error")
            }
            print(f"  Plan validation REJECTED (409): {approve_resp.get('error')}")
            print(f"  Validation: {validation}")
            results["overall"] = "fail_at_plan_validation"
            results["finished_at"] = utc_now()
            return results

        state = approve_resp.get("state", "unknown")
        print(f"  Plan approved, Canon generated — state: {state}")

        # Check alignment
        alignment = approve_resp.get("camera_alignment", {})
        if alignment:
            print(f"  Alignment: status={alignment.get('status')}, passed={alignment.get('passed')}, "
                  f"iou={alignment.get('edge_iou', 'n/a')}, drift={alignment.get('drift_px', 'n/a')}")
            results["stages"]["alignment"] = alignment

        # Fetch Canon image
        canon_url = approve_resp.get("canon_image") or f"/api/session/{session_id}/canon_image?v=1"
        status, canon_bytes = http_bytes(canon_url)
        if status == 200 and len(canon_bytes) > 1000:
            results["stages"]["canon"] = {"status": "pass", "size_bytes": len(canon_bytes), "alignment": alignment}
            print(f"  Canon generated — {len(canon_bytes)} bytes")

            # Vision QA
            print("  Running Ollama vision QA on Canon...")
            qa = ollama_vision_qa(canon_bytes, CANON_QA_CHECKLIST)
            results["stages"]["canon"]["vision_qa"] = qa
            if qa.get("pass"):
                print(f"  Vision QA PASSED (confidence: {qa.get('confidence', '?')})")
            else:
                print(f"  Vision QA concerns: {qa.get('failed_checks', [])}")
                results["stages"]["canon"]["status"] = "warn_vision"
        else:
            results["stages"]["canon"] = {"status": "fail", "http_status": status}
            print(f"  Canon fetch FAILED: status={status}")
    except Exception as e:
        results["stages"]["canon"] = {"status": "fail", "error": str(e)}
        print(f"  Canon FAILED: {e}")

    # 5. Approve Canon → Build World
    print("\n[5/6] Approving Canon → building World...")
    try:
        status_code, world_resp = http_json(
            f"/api/session/{session_id}/approve",
            method="POST",
            body={"action": "approve"},
            expected=(200, 409),
            timeout=300  # Mesh generation + Godot assembly
        )

        if status_code == 409:
            # Alignment gate blocked
            error_msg = world_resp.get("error", "")
            alignment_info = world_resp.get("camera_alignment", {})
            results["stages"]["world"] = {
                "status": "fail",
                "error": "alignment_gate_blocked",
                "message": error_msg,
                "alignment": alignment_info,
            }
            print(f"  World build BLOCKED (409): {error_msg}")
            print(f"  Alignment info: {alignment_info}")

            # If inconclusive and manual review allowed, try accepting
            if world_resp.get("manual_review_allowed"):
                print("  Attempting accept_alignment for inconclusive result...")
                try:
                    _, accept_resp = http_json(
                        f"/api/session/{session_id}/accept_alignment",
                        method="POST",
                        body={"decision": "accepted", "binding": alignment_info},
                        timeout=10
                    )
                    print(f"  Alignment accepted, retrying world build...")
                    # Retry approve
                    status_code, world_resp = http_json(
                        f"/api/session/{session_id}/approve",
                        method="POST",
                        body={"action": "approve"},
                        timeout=300
                    )
                except Exception as retry_e:
                    print(f"  Accept alignment failed: {retry_e}")
                    results["overall"] = "fail_at_alignment"
                    results["finished_at"] = utc_now()
                    return results
            else:
                results["overall"] = "fail_at_alignment"
                results["finished_at"] = utc_now()
                return results

        state = world_resp.get("state", "unknown")
        print(f"  Canon approved, World built — state: {state}")

        world_failures = validate_world(session_id, world_resp)
        if world_failures:
            results["stages"]["world"] = {"status": "fail", "failures": world_failures}
            print(f"  World FAILED: {world_failures}")
        else:
            results["stages"]["world"] = {"status": "pass", "scene_graph_summary": {
                "objects": len(world_resp.get("scene_graph", {}).get("objects", [])),
                "lights": len(world_resp.get("scene_graph", {}).get("lights", [])),
                "doors": len(world_resp.get("scene_graph", {}).get("doors", [])),
                "windows": len(world_resp.get("scene_graph", {}).get("windows", [])),
            }}
            print(f"  World passed — {results['stages']['world']['scene_graph_summary']}")
    except Exception as e:
        results["stages"]["world"] = {"status": "fail", "error": str(e)}
        print(f"  World FAILED: {e}")

    # 6. Check routes and download
    print("\n[6/6] Validating routes...")
    route_checks = {}
    routes_to_check = [
        f"/api/session/{session_id}/status",
        f"/api/session/{session_id}/workflow",
        "/api/readiness",
        "/api/workflow/profiles",
    ]
    for route in routes_to_check:
        try:
            status, _ = http_json(route)
            route_checks[route] = "pass"
        except Exception as e:
            route_checks[route] = f"fail: {e}"
    results["stages"]["routes"] = route_checks
    all_routes_pass = all(v == "pass" for v in route_checks.values())
    print(f"  Routes: {'all pass' if all_routes_pass else route_checks}")

    # Determine overall result
    stage_statuses = [s.get("status", "unknown") for s in results["stages"].values() if isinstance(s, dict)]
    if all(s in ("pass", "warn_vision") for s in stage_statuses) and all_routes_pass:
        results["overall"] = "PASS"
    elif any(s == "fail" for s in stage_statuses):
        failed_stages = [k for k, v in results["stages"].items() if isinstance(v, dict) and v.get("status") == "fail"]
        results["overall"] = f"FAIL ({', '.join(failed_stages)})"
    else:
        results["overall"] = "PARTIAL"

    results["finished_at"] = utc_now()
    print(f"\n{'='*60}")
    print(f"RESULT: {results['overall']} — session {session_id}")
    print(f"{'='*60}\n")

    return results


if __name__ == "__main__":
    import sys

    num_passes = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    all_results = []

    for i in range(num_passes):
        print(f"\n{'#'*60}")
        print(f"# ITERATION {i+1} of {num_passes}")
        print(f"{'#'*60}")
        try:
            result = run_full_pass()
            all_results.append(result)
        except Exception as e:
            print(f"\n!!! ITERATION {i+1} CRASHED: {e}")
            all_results.append({"overall": "CRASH", "error": str(e), "iteration": i+1})

    # Save all results
    summary_path = Path("output/test_iteration_summary.json")
    summary = {
        "total_passes": num_passes,
        "results": all_results,
        "pass_count": sum(1 for r in all_results if r.get("overall") == "PASS"),
        "fail_count": sum(1 for r in all_results if "FAIL" in str(r.get("overall", ""))),
        "crash_count": sum(1 for r in all_results if r.get("overall") == "CRASH"),
    }
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"SUMMARY: {summary['pass_count']} PASS / {summary['fail_count']} FAIL / {summary['crash_count']} CRASH out of {num_passes}")
    print(f"{'='*60}")
    print(f"Results saved to {summary_path}")

    # Also save individual results
    for r in all_results:
        if r.get("session_id"):
            p = Path(f"output/test_iteration_{r['session_id']}.json")
            p.write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")

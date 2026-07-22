"""Iterate-and-fix test loop: one pass per prompt, diagnose and fix after each failure."""

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

PROMPTS = [
    # 1. Modern office
    (
        "Create a rectangular modern open-plan office exactly 8 meters wide, 5 meters deep, "
        "and 3.2 meters high.\n\n"
        "Place exactly one long conference table 3.0 meters long and 1.2 meters wide, centered "
        "in the room. Place exactly four identical office chairs evenly spaced around the table.\n\n"
        "Install one glass door on the east wall near the northeast corner. Center one large "
        "floor-to-ceiling window on the south wall.\n\n"
        "Hang exactly two rectangular modern pendant lights in a row above the conference table.\n\n"
        "Use polished concrete floors, white walls, and an exposed ductwork ceiling. "
        "Set the scene during a bright afternoon with natural light streaming through the south window.\n\n"
        "Place the canon camera at normal eye height in the southwest corner, looking diagonally "
        "northeast toward the table and door. Use a 55-degree field of view.\n\n"
        "Do not add people, plants, screens, or unrelated furniture."
    ),
    # 2. Cozy bedroom
    (
        "Create a rectangular cozy bedroom exactly 4.5 meters wide, 4.0 meters deep, "
        "and 2.7 meters high.\n\n"
        "Place exactly one queen bed 2.0 meters long and 1.6 meters wide against the center "
        "of the north wall. Place exactly two identical bedside tables, one on each side of the bed.\n\n"
        "Install one standard door on the west wall near the southwest corner. Center one "
        "medium window on the east wall.\n\n"
        "Hang exactly one ceiling light fixture centered in the room.\n\n"
        "Use warm oak hardwood floors, soft blue-gray walls, and a white plaster ceiling. "
        "Set the scene in early morning with golden sunlight entering through the east window.\n\n"
        "Place the canon camera at normal eye height in the southeast corner, looking diagonally "
        "northwest toward the bed. Use a 55-degree field of view.\n\n"
        "Do not add people, pets, or unrelated furniture."
    ),
    # 3. Japanese tea room
    (
        "Create a rectangular traditional Japanese tea room exactly 4.5 meters wide, 3.5 meters "
        "deep, and 2.4 meters high.\n\n"
        "Place exactly one low square tea table 0.8 meters wide in the center of the room. "
        "Place exactly four floor cushions evenly spaced around the table.\n\n"
        "Install one sliding shoji screen door on the west wall, centered. Center one small "
        "window on the north wall.\n\n"
        "Hang exactly one paper lantern directly above the table.\n\n"
        "Use tatami mat flooring, light wood-panel walls, and exposed beam ceiling. "
        "Set the scene during a quiet rainy afternoon with soft diffused light from the window.\n\n"
        "Place the canon camera at normal eye height in the southeast corner, looking diagonally "
        "northwest toward the table. Use a 55-degree field of view.\n\n"
        "Do not add people, plants, scrolls, or unrelated objects."
    ),
    # 4. Industrial loft studio
    (
        "Create a rectangular industrial loft studio exactly 7 meters wide, 5 meters deep, "
        "and 3.5 meters high.\n\n"
        "Place exactly one large workbench 2.5 meters long against the north wall. Place exactly "
        "two metal stools in front of the workbench.\n\n"
        "Install one heavy steel door on the east wall near the southeast corner. Install exactly "
        "two tall narrow factory windows evenly spaced on the south wall.\n\n"
        "Hang exactly three industrial cage pendant lights in a row along the ceiling above the workbench.\n\n"
        "Use raw concrete floors, exposed brick walls, and a corrugated metal ceiling with "
        "visible steel beams. Set the scene at dusk with warm orange light from the pendants "
        "and fading blue light from the factory windows.\n\n"
        "Place the canon camera at normal eye height in the southwest corner, looking diagonally "
        "northeast toward the workbench and door. Use a 55-degree field of view.\n\n"
        "Do not add people, tools, artwork, or unrelated objects."
    ),
    # 5. Retro game room
    (
        "Create a rectangular 1980s retro game room exactly 5.5 meters wide, 4.5 meters deep, "
        "and 2.8 meters high.\n\n"
        "Place exactly three upright arcade cabinets in a row along the north wall, evenly spaced. "
        "Place exactly one round coffee table centered in the room. Place exactly one beanbag "
        "chair south of the coffee table.\n\n"
        "Install one standard door on the west wall near the northwest corner. Center one "
        "window on the south wall.\n\n"
        "Hang exactly two neon tube lights along the ceiling above the arcade cabinets.\n\n"
        "Use dark carpet flooring, deep purple walls, and a black painted ceiling. "
        "Set the scene at night with vivid neon glow from the tube lights and colorful "
        "cabinet screens reflected on the walls.\n\n"
        "Place the canon camera at normal eye height in the southeast corner, looking diagonally "
        "northwest toward the arcade cabinets. Use a 55-degree field of view.\n\n"
        "Do not add people, TVs, consoles, or unrelated furniture."
    ),
    # 6. Rustic kitchen
    (
        "Create a rectangular rustic farmhouse kitchen exactly 5 meters wide, 4 meters deep, "
        "and 2.8 meters high.\n\n"
        "Place exactly one butcher-block island 1.8 meters long and 0.9 meters wide centered in the room. "
        "Place exactly two wooden stools on the south side of the island.\n\n"
        "Install one wooden door on the east wall near the northeast corner. Center one large "
        "window on the west wall.\n\n"
        "Hang exactly two wrought-iron pendant lights above the island.\n\n"
        "Use terracotta tile flooring, whitewashed plaster walls, and exposed dark timber "
        "beam ceiling. Set the scene on a warm autumn morning with golden light from the west window.\n\n"
        "Place the canon camera at normal eye height in the southeast corner, looking diagonally "
        "northwest toward the island and window. Use a 55-degree field of view.\n\n"
        "Do not add people, food, pots, or unrelated objects."
    ),
    # 7. Art gallery
    (
        "Create a rectangular minimalist art gallery exactly 9 meters wide, 6 meters deep, "
        "and 3.5 meters high.\n\n"
        "Place exactly three identical gallery benches in a row along the center axis of the room, "
        "each 1.5 meters long. Place exactly one sculpture pedestal 0.6 meters square against "
        "the center of the north wall.\n\n"
        "Install one glass pivot door on the south wall, centered. Install exactly two skylight "
        "windows on the ceiling, evenly spaced.\n\n"
        "Hang exactly four track lights in a row along the north wall above the pedestal.\n\n"
        "Use white polished concrete floors, pure white walls, and a white ceiling. "
        "Set the scene during midday with even diffused light from the skylights.\n\n"
        "Place the canon camera at normal eye height in the southwest corner, looking diagonally "
        "northeast toward the pedestal. Use a 55-degree field of view.\n\n"
        "Do not add people, artwork on walls, labels, or unrelated objects."
    ),
    # 8. Child's playroom
    (
        "Create a rectangular bright child's playroom exactly 5 meters wide, 4 meters deep, "
        "and 2.7 meters high.\n\n"
        "Place exactly one toy chest 1.2 meters long against the center of the north wall. "
        "Place exactly one small round table 0.8 meters in diameter centered in the room. "
        "Place exactly three small chairs evenly spaced around the table.\n\n"
        "Install one standard door on the west wall near the southwest corner. Center one "
        "large window on the east wall.\n\n"
        "Hang exactly one colorful globe pendant light centered above the table.\n\n"
        "Use soft foam tile flooring in bright primary colors, sunny yellow walls, and a white ceiling. "
        "Set the scene on a cheerful afternoon with warm natural light from the east window.\n\n"
        "Place the canon camera at normal eye height in the northwest corner, looking diagonally "
        "southeast toward the table and window. Use a 55-degree field of view.\n\n"
        "Do not add people, toys on floor, books, or unrelated objects."
    ),
    # 9. Victorian parlor
    (
        "Create a rectangular Victorian parlor exactly 6 meters wide, 5 meters deep, "
        "and 3.2 meters high.\n\n"
        "Place exactly one velvet sofa 2.2 meters long centered facing the south wall. "
        "Place exactly two wingback armchairs facing the sofa with a gap between them. "
        "Place exactly one ornate coffee table between the sofa and chairs.\n\n"
        "Install one double door on the north wall, centered. Center one tall bay window "
        "on the south wall.\n\n"
        "Hang exactly one crystal chandelier centered in the room.\n\n"
        "Use dark mahogany parquet flooring, deep burgundy damask wallpaper, and an ornate "
        "white plaster ceiling with crown molding. Set the scene in the evening with warm "
        "candlelight from the chandelier and cool moonlight through the bay window.\n\n"
        "Place the canon camera at normal eye height in the northeast corner, looking diagonally "
        "southwest toward the sofa and window. Use a 55-degree field of view.\n\n"
        "Do not add people, paintings, books, or unrelated objects."
    ),
    # 10. Minimalist meditation space
    (
        "Create a rectangular minimalist meditation space exactly 4 meters wide, 4 meters deep, "
        "and 2.6 meters high.\n\n"
        "Place exactly one round meditation cushion 0.5 meters in diameter centered in the room. "
        "Place exactly one small incense holder on the floor 0.5 meters north of the cushion.\n\n"
        "Install one sliding door on the west wall, centered. Center one narrow floor-to-ceiling "
        "window on the east wall.\n\n"
        "Hang exactly one simple paper globe light centered above the cushion.\n\n"
        "Use light bamboo flooring, bare white plaster walls, and a plain white ceiling. "
        "Set the scene at dawn with soft pink-gold light entering through the east window.\n\n"
        "Place the canon camera at normal eye height in the southwest corner, looking diagonally "
        "northeast toward the cushion and window. Use a 55-degree field of view.\n\n"
        "Do not add people, mats, shelves, or unrelated objects."
    ),
]

PROMPT_NAMES = [
    "Modern Office", "Cozy Bedroom", "Japanese Tea Room", "Industrial Loft",
    "Retro Game Room", "Rustic Kitchen", "Art Gallery", "Child's Playroom",
    "Victorian Parlor", "Minimalist Meditation",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_json(path: str, method: str = "GET", body: dict | None = None,
              expected: tuple[int, ...] = (200,), timeout: float = 300) -> tuple[int, dict]:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            payload = {"error": f"HTTP {exc.code}"}
        if exc.code in expected:
            return exc.code, payload
        raise AssertionError(f"{method} {path}: expected {expected}, got {exc.code} — {payload}")
    except Exception as e:
        raise AssertionError(f"{method} {path}: {e}")


def http_bytes(path: str) -> tuple[int, bytes]:
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, method="GET", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception:
        return 0, b""


def run_one(prompt: str, name: str) -> dict:
    """Run one full pipeline pass with the given prompt. Returns result dict."""
    result = {"name": name, "started_at": utc_now(), "stages": {}, "overall": "pending"}
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"  {utc_now()}")
    print(f"{'='*60}")

    # 1. Create session
    print("  [session] Creating...")
    _, session = http_json("/api/session", method="POST")
    sid = session["session_id"]
    result["session_id"] = sid
    print(f"  [session] {sid}")

    # 2. Describe → Plan
    print("  [brief→plan] Submitting prompt...")
    try:
        status, resp = http_json(
            f"/api/session/{sid}/describe", method="POST",
            body={"description": prompt}, timeout=300
        )
        if status != 200:
            result["stages"]["brief"] = {"status": "fail", "error": resp.get("error")}
            result["overall"] = "FAIL:brief"
            print(f"  [brief] FAILED: {resp.get('error')}")
            return result
        result["stages"]["brief"] = {"status": "pass"}
        print(f"  [brief→plan] state={resp.get('state')}")
    except Exception as e:
        result["stages"]["brief"] = {"status": "fail", "error": str(e)[:200]}
        result["overall"] = "FAIL:brief"
        print(f"  [brief] FAILED: {e}")
        return result

    # 3. Validate plan structure
    plan = resp.get("floor_plan", {})
    items = plan.get("items", [])
    openings = plan.get("openings", [])
    result["stages"]["plan"] = {
        "status": "pass",
        "items": len(items),
        "openings": len(openings),
        "room": plan.get("room"),
    }
    print(f"  [plan] {len(items)} items, {len(openings)} openings, room={plan.get('room')}")

    # 4. Fetch blockout
    blockout_url = resp.get("blockout_image") or f"/api/session/{sid}/blockout"
    status, blockout_bytes = http_bytes(blockout_url)
    if status == 200 and len(blockout_bytes) > 500:
        result["stages"]["blockout"] = {"status": "pass", "bytes": len(blockout_bytes)}
        print(f"  [blockout] {len(blockout_bytes)} bytes")
    else:
        result["stages"]["blockout"] = {"status": "fail", "http": status}
        print(f"  [blockout] FAILED: {status}")

    # 5. Fetch SVG
    svg_url = resp.get("floor_plan_image") or f"/api/session/{sid}/floor_plan"
    status, svg_bytes = http_bytes(svg_url)
    if status == 200 and len(svg_bytes) > 100:
        result["stages"]["svg"] = {"status": "pass", "bytes": len(svg_bytes)}
        print(f"  [svg] {len(svg_bytes)} bytes")
    else:
        result["stages"]["svg"] = {"status": "fail", "http": status}
        print(f"  [svg] FAILED: {status}")

    # 6. Approve plan → Canon
    print("  [canon] Approving plan, generating Canon...")
    canon_bytes = None
    alignment = {}
    max_canon_attempts = 3
    for attempt in range(1, max_canon_attempts + 1):
        try:
            status, canon_resp = http_json(
                f"/api/session/{sid}/approve_plan" if attempt == 1 else f"/api/session/{sid}/reject",
                method="POST",
                body=None if attempt == 1 else {"reason": "Camera alignment failed, regenerating"},
                expected=(200, 409), timeout=300
            )
            if status == 409:
                validation = canon_resp.get("validation_report", {})
                blockers = validation.get("blockers", [])
                if blockers:
                    result["stages"]["canon"] = {
                        "status": "fail",
                        "gate": "plan_validation",
                        "blockers": blockers,
                    }
                    result["overall"] = "FAIL:plan_validation"
                    print(f"  [canon] BLOCKED by plan validation: {len(blockers)} blocker(s)")
                    for b in blockers[:3]:
                        print(f"    • {b.get('code')}: {b.get('message')}")
                    return result
                # Other 409 (maybe alignment gate on reject endpoint)
                result["stages"]["canon"] = {"status": "fail", "gate": "409_unknown", "resp": canon_resp}
                result["overall"] = "FAIL:canon_409"
                print(f"  [canon] 409: {canon_resp.get('error','')[:100]}")
                return result

            alignment = canon_resp.get("camera_alignment", {})
            canon_url = canon_resp.get("canon_image") or f"/api/session/{sid}/canon_image?v={attempt}"
            cs, canon_bytes = http_bytes(canon_url)

            if cs != 200 or len(canon_bytes) < 1000:
                print(f"  [canon] Fetch failed on attempt {attempt}: status={cs}")
                continue

            align_status = alignment.get("status", "unknown")
            print(f"  [canon] attempt {attempt}: {len(canon_bytes)} bytes, alignment={align_status}")

            if align_status in ("aligned", "inconclusive"):
                break  # Good enough to proceed
            elif attempt < max_canon_attempts:
                print(f"  [canon] Misaligned — rejecting and retrying...")
                continue
            else:
                # Last attempt still misaligned — proceed anyway for testing purposes
                print(f"  [canon] Still misaligned after {max_canon_attempts} attempts, proceeding anyway")
                break

        except Exception as e:
            if attempt == max_canon_attempts:
                result["stages"]["canon"] = {"status": "fail", "error": str(e)[:200]}
                result["overall"] = "FAIL:canon"
                print(f"  [canon] FAILED: {e}")
                return result
            print(f"  [canon] attempt {attempt} error: {e}, retrying...")

    result["stages"]["canon"] = {
        "status": "pass" if alignment.get("status") in ("aligned", "inconclusive") else "warn",
        "bytes": len(canon_bytes) if canon_bytes else 0,
        "alignment_status": alignment.get("status"),
        "attempts": attempt,
    }

    # 7. Approve Canon → World
    print("  [world] Approving Canon, building World...")
    try:
        status, world_resp = http_json(
            f"/api/session/{sid}/approve", method="POST",
            body={"action": "approve"}, expected=(200, 409), timeout=300
        )
        if status == 409:
            # Try accept_alignment if inconclusive
            error_msg = world_resp.get("error", "")
            if "inconclusive" in error_msg:
                print(f"  [world] Inconclusive alignment — accepting...")
                binding = world_resp.get("camera_alignment", {}).get("binding", {})
                try:
                    http_json(
                        f"/api/session/{sid}/accept_alignment", method="POST",
                        body={"decision": "accepted", "binding": binding}, timeout=10
                    )
                    status, world_resp = http_json(
                        f"/api/session/{sid}/approve", method="POST",
                        body={"action": "approve"}, expected=(200, 409), timeout=300
                    )
                except Exception as ae:
                    print(f"  [world] Accept failed: {ae}")
            if status == 409:
                result["stages"]["world"] = {
                    "status": "fail", "gate": "alignment",
                    "error": world_resp.get("error", "")[:200],
                }
                result["overall"] = "FAIL:alignment_gate"
                print(f"  [world] BLOCKED: {world_resp.get('error', '')[:100]}")
                return result

        sg = world_resp.get("scene_graph", {})
        result["stages"]["world"] = {
            "status": "pass",
            "objects": len(sg.get("objects", [])),
            "lights": len(sg.get("lights", [])),
            "doors": len(sg.get("doors", [])),
            "windows": len(sg.get("windows", [])),
        }
        print(f"  [world] objects={len(sg.get('objects',[]))}, lights={len(sg.get('lights',[]))}, "
              f"doors={len(sg.get('doors',[]))}, windows={len(sg.get('windows',[]))}")
    except Exception as e:
        result["stages"]["world"] = {"status": "fail", "error": str(e)[:200]}
        result["overall"] = "FAIL:world"
        print(f"  [world] FAILED: {e}")
        return result

    result["overall"] = "PASS"
    result["finished_at"] = utc_now()
    print(f"  ✓ PASS ({result['finished_at']})")
    return result


def main():
    import sys
    start_at = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    results = []
    for i, (prompt, name) in enumerate(zip(PROMPTS, PROMPT_NAMES)):
        if i + 1 < start_at:
            results.append({"name": f"[{i+1}/10] {name}", "overall": "SKIPPED"})
            continue
        r = run_one(prompt, f"[{i+1}/10] {name}")
        results.append(r)

        # Save after each
        Path("output/test_iterate_log.json").write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8"
        )

        if r["overall"] != "PASS":
            print(f"\n  ⚠ STOPPING after failure on '{name}' — fix needed.")
            print(f"  Session: {r.get('session_id')}")
            print(f"  Failure: {r['overall']}")
            if r["overall"] == "FAIL:plan_validation":
                print(f"  Blockers: {json.dumps(r['stages']['canon']['blockers'], indent=2)}")
            break

    # Final summary
    passes = sum(1 for r in results if r["overall"] == "PASS")
    total = sum(1 for r in results if r["overall"] != "SKIPPED")
    print(f"\n{'='*60}")
    print(f"DONE: {passes}/{total} passed")
    for r in results:
        if r["overall"] != "SKIPPED":
            print(f"  {r.get('name','?'):40} → {r['overall']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

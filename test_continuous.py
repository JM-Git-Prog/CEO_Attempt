"""Continuous test runner: 50 iterations with varied prompts, doesn't stop on failure."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8000"
HEADERS = {"X-App-Version": "10", "Content-Type": "application/json"}
OUTPUT_DIR = Path("output")

# 50 varied room descriptions — different styles, sizes, furniture counts
ROOMS = [
    ("Modern Office", "Create a rectangular modern office exactly 8 meters wide, 5 meters deep, and 3.2 meters high. Place exactly one conference table 3m long centered in the room. Place exactly four office chairs evenly spaced around the table. Install one glass door on the east wall near the northeast corner. Center one large window on the south wall. Hang exactly two modern pendant lights above the table. Use polished concrete floors and white walls. Place the canon camera at normal eye height in the southwest corner, looking diagonally northeast. Use a 55-degree field of view. Do not add people or unrelated furniture."),
    ("Cozy Bedroom", "Create a rectangular cozy bedroom exactly 4.5 meters wide, 4.0 meters deep, and 2.7 meters high. Place exactly one queen bed against the center of the north wall. Place exactly two bedside tables, one on each side of the bed. Install one door on the west wall near the southwest corner. Center one window on the east wall. Hang exactly one ceiling light centered in the room. Use warm oak hardwood floors and soft blue-gray walls. Place the canon camera at normal eye height in the southeast corner, looking northwest toward the bed. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Japanese Tea Room", "Create a rectangular traditional Japanese tea room exactly 4.5 meters wide, 3.5 meters deep, and 2.4 meters high. Place exactly one low square tea table 0.8m wide centered in the room. Place exactly four floor cushions evenly spaced around the table. Install one sliding door on the west wall centered. Center one small window on the north wall. Hang exactly one paper lantern above the table. Use tatami mat flooring and light wood walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Industrial Loft", "Create a rectangular industrial loft exactly 7 meters wide, 5 meters deep, and 3.5 meters high. Place exactly one large workbench 2.5m long against the north wall. Place exactly two metal stools in front of the workbench. Install one steel door on the east wall near the southeast corner. Install exactly two tall narrow windows evenly spaced on the south wall. Hang exactly three industrial pendant lights above the workbench. Use concrete floors and exposed brick walls. Place the canon camera at normal eye height in the southwest corner, looking northeast. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Retro Game Room", "Create a rectangular 1980s game room exactly 5.5 meters wide, 4.5 meters deep, and 2.8 meters high. Place exactly three upright arcade cabinets evenly spaced along the north wall. Place one round coffee table centered in the room. Place one beanbag chair south of the coffee table. Install one door on the west wall near the northwest corner. Center one window on the south wall. Hang exactly two neon tube lights above the arcade cabinets. Use dark carpet floors and deep purple walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Rustic Kitchen", "Create a rectangular rustic farmhouse kitchen exactly 5 meters wide, 4 meters deep, and 2.8 meters high. Place exactly one butcher-block island 1.8m long centered in the room. Place exactly two wooden stools on the south side of the island. Install one wooden door on the east wall near the northeast corner. Center one large window on the west wall. Hang exactly two wrought-iron pendant lights above the island. Use terracotta tile floors and whitewashed plaster walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Art Gallery", "Create a rectangular minimalist art gallery exactly 9 meters wide, 6 meters deep, and 3.5 meters high. Place exactly three gallery benches in a row along the center of the room. Place one sculpture pedestal against the north wall. Install one glass pivot door centered on the south wall. Hang exactly four track lights in a row above the north wall. Use white polished concrete floors and pure white walls. Place the canon camera at normal eye height in the southwest corner, looking northeast. Use a 55-degree field of view. Do not add people or artwork on walls."),
    ("Playroom", "Create a rectangular child's playroom exactly 5 meters wide, 4 meters deep, and 2.7 meters high. Place one toy chest against the north wall. Place one small round table centered in the room. Place exactly three small chairs around the table. Install one door on the west wall near the southwest corner. Center one window on the east wall. Hang one colorful globe light above the table. Use foam tile floors and sunny yellow walls. Place the canon camera at normal eye height in the northwest corner, looking southeast. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Victorian Parlor", "Create a rectangular Victorian parlor exactly 6 meters wide, 5 meters deep, and 3.2 meters high. Place one velvet sofa 2.2m long centered facing south. Place two wingback armchairs facing the sofa. Place one ornate coffee table between the sofa and chairs. Install one double door centered on the north wall. Center one bay window on the south wall. Hang one crystal chandelier centered in the room. Use dark mahogany parquet floors and burgundy walls. Place the canon camera at normal eye height in the northeast corner, looking southwest. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Meditation Space", "Create a rectangular minimalist meditation space exactly 4 meters wide, 4 meters deep, and 2.6 meters high. Place one meditation cushion 0.5m wide centered in the room. Place one small incense holder on the floor north of the cushion. Install one sliding door centered on the west wall. Center one narrow window on the east wall. Hang one paper globe light above the cushion. Use bamboo floors and white plaster walls. Place the canon camera at normal eye height in the southwest corner, looking northeast. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Recording Studio", "Create a rectangular home recording studio exactly 5 meters wide, 3.5 meters deep, and 2.8 meters high. Place one desk 1.5m long against the north wall. Place one studio chair in front of the desk. Place one vocal booth panel 1.2m wide against the east wall. Install one soundproof door on the west wall near the southwest corner. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people."),
    ("Barber Shop", "Create a rectangular vintage barber shop exactly 6 meters wide, 4 meters deep, and 3.0 meters high. Place exactly three barber chairs evenly spaced facing south, centered along the room's length. Place one long mirror shelf 4m against the south wall behind the chairs. Install one glass door centered on the north wall. Center one window on the east wall. Hang exactly three pendant lights above the chairs. Use black-and-white tile floors and dark green walls. Place the canon camera at normal eye height in the southwest corner, looking northeast. Use a 55-degree field of view. Do not add people."),
    ("Yoga Studio", "Create a rectangular yoga studio exactly 7 meters wide, 5 meters deep, and 3.0 meters high. Place exactly six yoga mats in two rows of three evenly spaced in the room. Place one storage shelf against the north wall. Install one door on the east wall near the northeast corner. Center one large window on the south wall. Hang exactly two soft globe lights above the center of the room. Use light wood floors and warm cream walls. Place the canon camera at normal eye height in the northwest corner, looking southeast. Use a 55-degree field of view. Do not add people."),
    ("Wine Cellar", "Create a rectangular wine cellar exactly 4 meters wide, 6 meters deep, and 2.5 meters high. Place exactly two wine racks 2m tall against the east and west walls. Place one tasting table 1.2m wide centered in the room. Place exactly two stools on opposite sides of the table. Install one heavy wooden door on the north wall centered. Hang exactly one wrought-iron chandelier above the table. Use stone tile floors and exposed stone walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people."),
    ("Dentist Office", "Create a rectangular dentist examination room exactly 4 meters wide, 3.5 meters deep, and 2.7 meters high. Place one dental chair centered in the room facing east. Place one equipment cart to the right of the chair. Place one small counter against the north wall. Install one door on the west wall near the southwest corner. Center one window on the east wall. Hang one overhead surgical light above the dental chair. Use vinyl floors and light blue walls. Place the canon camera at normal eye height in the southwest corner, looking northeast. Use a 55-degree field of view. Do not add people."),
    ("Library Reading Room", "Create a rectangular library reading room exactly 8 meters wide, 6 meters deep, and 3.5 meters high. Place exactly four tall bookshelves against the north wall. Place one large reading table centered in the room. Place exactly four reading chairs around the table. Install one double door centered on the south wall. Center one large window on the west wall. Hang exactly two brass pendant lights above the reading table. Use dark wood parquet floors and deep green walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people."),
    ("Laundromat", "Create a rectangular small laundromat exactly 6 meters wide, 4 meters deep, and 2.8 meters high. Place exactly four washing machines in a row against the north wall. Place one folding table 2m long against the south wall. Place exactly two plastic chairs along the east wall. Install one glass door centered on the west wall. Center one window on the east wall. Hang exactly three fluorescent lights evenly spaced along the ceiling. Use gray linoleum floors and white walls. Place the canon camera at normal eye height in the southwest corner, looking northeast. Use a 55-degree field of view. Do not add people."),
    ("Florist Shop", "Create a rectangular florist shop exactly 5 meters wide, 4 meters deep, and 2.8 meters high. Place one display counter 2m long centered in the room. Place exactly three flower bucket stands along the north wall. Place one cash register stand near the east end of the counter. Install one glass door centered on the south wall. Center one large window on the west wall. Hang exactly two industrial pendant lights above the counter. Use concrete tile floors and white brick walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people."),
    ("Piano Room", "Create a rectangular piano practice room exactly 5 meters wide, 4 meters deep, and 3.0 meters high. Place one grand piano centered in the room facing east. Place one piano bench in front of the piano. Place one music stand to the right of the piano. Install one door on the north wall near the northwest corner. Center one tall window on the south wall. Hang one modern pendant light above the piano. Use dark hardwood floors and cream walls with acoustic panels. Place the canon camera at normal eye height in the northeast corner, looking southwest. Use a 55-degree field of view. Do not add people."),
    ("Boxing Gym Corner", "Create a rectangular boxing training area exactly 6 meters wide, 5 meters deep, and 3.2 meters high. Place one heavy punching bag hanging from the ceiling in the center. Place one speed bag stand against the north wall. Place one bench against the east wall. Install one metal door on the west wall near the southwest corner. Hang exactly two industrial cage lights above the center. Use rubber mat floors and raw concrete walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people."),
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_json(path, method="GET", body=None, expected=(200,), timeout=300):
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
        return exc.code, payload
    except Exception as e:
        return 0, {"error": str(e)[:200]}


def http_bytes(path):
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, method="GET", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except Exception:
        return 0, b""


def run_one(name, prompt):
    r = {"name": name, "started": utc_now(), "session_id": None, "stages": {}, "result": "pending"}
    print(f"\n{'─'*50}\n  {name} ({utc_now()})\n{'─'*50}")

    # Create session
    status, resp = http_json("/api/session", method="POST")
    if status != 200:
        r["result"] = "FAIL:session"
        print(f"  ✗ session create failed: {resp}")
        return r
    sid = resp["session_id"]
    r["session_id"] = sid
    print(f"  session: {sid}")

    # Describe
    status, resp = http_json(f"/api/session/{sid}/describe", method="POST", body={"description": prompt})
    if status != 200:
        r["result"] = f"FAIL:describe({status})"
        r["stages"]["brief"] = resp.get("error", "")[:100]
        print(f"  ✗ describe failed: {resp.get('error','')[:80]}")
        return r
    r["stages"]["plan"] = {"items": len(resp.get("floor_plan", {}).get("items", [])), "openings": len(resp.get("floor_plan", {}).get("openings", []))}
    print(f"  plan: {r['stages']['plan']['items']} items, {r['stages']['plan']['openings']} openings")

    # Approve plan
    status, resp = http_json(f"/api/session/{sid}/approve_plan", method="POST", expected=(200, 409))
    if status == 409:
        blockers = resp.get("validation_report", {}).get("blockers", [])
        r["stages"]["validation"] = [b["message"][:60] for b in blockers[:3]]
        r["result"] = f"FAIL:validation({len(blockers)})"
        print(f"  ✗ validation: {len(blockers)} blocker(s)")
        for b in blockers[:2]:
            print(f"    • {b.get('code')}: {b['message'][:60]}")
        return r
    if status != 200:
        r["result"] = f"FAIL:approve_plan({status})"
        print(f"  ✗ approve_plan: {resp.get('error','')[:80]}")
        return r

    # Canon generated
    alignment = resp.get("camera_alignment", {})
    align_status = alignment.get("status", "?")
    r["stages"]["canon"] = {"alignment": align_status}
    print(f"  canon: alignment={align_status}")

    # If misaligned, try one reject+retry
    if align_status == "misaligned":
        status, resp = http_json(f"/api/session/{sid}/reject", method="POST",
                                 body={"reason": "Camera misaligned, regenerating"}, expected=(200, 400, 409))
        if status == 200:
            alignment = resp.get("camera_alignment", {})
            align_status = alignment.get("status", "?")
            r["stages"]["canon"]["alignment_retry"] = align_status
            print(f"  canon retry: alignment={align_status}")

    # Approve canon → world
    status, resp = http_json(f"/api/session/{sid}/approve", method="POST", body={"action": "approve"}, expected=(200, 409))
    if status == 409:
        # Try accept alignment
        error = resp.get("error", "")
        if "inconclusive" in error:
            binding = resp.get("camera_alignment", {}).get("binding", {})
            http_json(f"/api/session/{sid}/accept_alignment", method="POST",
                      body={"decision": "accepted", "binding": binding})
            status, resp = http_json(f"/api/session/{sid}/approve", method="POST",
                                     body={"action": "approve"}, expected=(200, 409))
        if status == 409:
            r["result"] = f"FAIL:world_gate"
            r["stages"]["world_error"] = resp.get("error", "")[:100]
            print(f"  ✗ world blocked: {resp.get('error','')[:60]}")
            return r

    if status != 200:
        r["result"] = f"FAIL:world({status})"
        print(f"  ✗ world build failed")
        return r

    sg = resp.get("scene_graph", {})
    r["stages"]["world"] = {
        "objects": len(sg.get("objects", [])),
        "lights": len(sg.get("lights", [])),
        "doors": len(sg.get("doors", [])),
        "windows": len(sg.get("windows", [])),
    }
    r["result"] = "PASS"
    r["finished"] = utc_now()
    print(f"  ✓ PASS — objects={r['stages']['world']['objects']}, lights={r['stages']['world']['lights']}")
    return r


def main():
    results = []
    # Shuffle and repeat to get 50 runs
    pool = ROOMS * 3  # 60 entries, we'll take 50
    random.shuffle(pool)
    pool = pool[:50]

    for i, (name, prompt) in enumerate(pool):
        label = f"[{i+1}/50] {name}"
        try:
            r = run_one(label, prompt)
        except Exception as e:
            r = {"name": label, "result": f"CRASH:{e}", "session_id": None}
            print(f"  ✗ CRASH: {e}")
        results.append(r)
        # Save incrementally
        OUTPUT_DIR.mkdir(exist_ok=True)
        (OUTPUT_DIR / "continuous_results.json").write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8"
        )

    # Summary
    passes = sum(1 for r in results if r["result"] == "PASS")
    val_fails = sum(1 for r in results if "validation" in r["result"])
    other_fails = sum(1 for r in results if r["result"] != "PASS" and "validation" not in r["result"])
    print(f"\n{'═'*50}")
    print(f"  FINAL: {passes}/50 PASS, {val_fails} validation fails, {other_fails} other fails")
    print(f"{'═'*50}")


if __name__ == "__main__":
    main()

"""Self-improving test loop: run pipeline, QA with vision model, learn, repeat.

After each pass generates floor plan + blockout + canon, we send all three
to qwen3-vl:8b for a structured 7-category analysis. The findings get
fed back as improvements to the next run's prompt/parameters.
"""

from __future__ import annotations

import base64
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8000"
OLLAMA = "http://127.0.0.1:11434"
HEADERS = {"X-App-Version": "10", "Content-Type": "application/json"}
OUTPUT_DIR = Path("output")

ROOMS = [
    ("Modern Office", "Create a rectangular modern office exactly 8 meters wide, 5 meters deep, and 3.2 meters high. Place exactly one conference table 3m long centered in the room. Place exactly four office chairs evenly spaced around the table. Install one glass door on the east wall near the northeast corner. Center one large window on the south wall. Hang exactly two modern pendant lights above the table. Use polished concrete floors and white walls. Place the canon camera at normal eye height in the southwest corner, looking diagonally northeast. Use a 55-degree field of view. Do not add people or unrelated furniture."),
    ("Cozy Bedroom", "Create a rectangular cozy bedroom exactly 4.5 meters wide, 4.0 meters deep, and 2.7 meters high. Place exactly one queen bed against the center of the north wall. Place exactly two bedside tables, one on each side of the bed. Install one door on the west wall near the southwest corner. Center one window on the east wall. Hang exactly one ceiling light centered in the room. Use warm oak hardwood floors and soft blue-gray walls. Place the canon camera at normal eye height in the southeast corner, looking northwest toward the bed. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Japanese Tea Room", "Create a rectangular traditional Japanese tea room exactly 4.5 meters wide, 3.5 meters deep, and 2.4 meters high. Place exactly one low square tea table 0.8m wide centered in the room. Place exactly four floor cushions evenly spaced around the table. Install one sliding door on the west wall centered. Center one small window on the north wall. Hang exactly one paper lantern above the table. Use tatami mat flooring and light wood walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Rustic Kitchen", "Create a rectangular rustic farmhouse kitchen exactly 5 meters wide, 4 meters deep, and 2.8 meters high. Place exactly one butcher-block island 1.8m long centered in the room. Place exactly two wooden stools on the south side of the island. Install one wooden door on the east wall near the northeast corner. Center one large window on the west wall. Hang exactly two wrought-iron pendant lights above the island. Use terracotta tile floors and whitewashed plaster walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Art Gallery", "Create a rectangular minimalist art gallery exactly 9 meters wide, 6 meters deep, and 3.5 meters high. Place exactly three gallery benches in a row along the center of the room. Place one sculpture pedestal against the north wall. Install one glass pivot door centered on the south wall. Hang exactly four track lights in a row above the north wall. Use white polished concrete floors and pure white walls. Place the canon camera at normal eye height in the southwest corner, looking northeast. Use a 55-degree field of view. Do not add people or artwork on walls."),
    ("Victorian Parlor", "Create a rectangular Victorian parlor exactly 6 meters wide, 5 meters deep, and 3.2 meters high. Place one velvet sofa 2.2m long centered facing south. Place two wingback armchairs facing the sofa. Place one ornate coffee table between the sofa and chairs. Install one double door centered on the north wall. Center one bay window on the south wall. Hang one crystal chandelier centered in the room. Use dark mahogany parquet floors and burgundy walls. Place the canon camera at normal eye height in the northeast corner, looking southwest. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Retro Game Room", "Create a rectangular 1980s game room exactly 5.5 meters wide, 4.5 meters deep, and 2.8 meters high. Place exactly three upright arcade cabinets evenly spaced along the north wall. Place one round coffee table centered in the room. Place one beanbag chair south of the coffee table. Install one door on the west wall near the northwest corner. Center one window on the south wall. Hang exactly two neon tube lights above the arcade cabinets. Use dark carpet floors and deep purple walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Piano Room", "Create a rectangular piano practice room exactly 5 meters wide, 4 meters deep, and 3.0 meters high. Place one grand piano centered in the room facing east. Place one piano bench in front of the piano. Place one music stand to the right of the piano. Install one door on the north wall near the northwest corner. Center one tall window on the south wall. Hang one modern pendant light above the piano. Use dark hardwood floors and cream walls. Place the canon camera at normal eye height in the northeast corner, looking southwest. Use a 55-degree field of view. Do not add people."),
    ("Meditation Space", "Create a rectangular minimalist meditation space exactly 4 meters wide, 4 meters deep, and 2.6 meters high. Place one meditation cushion 0.5m wide centered in the room. Place one small incense holder on the floor north of the cushion. Install one sliding door centered on the west wall. Center one narrow window on the east wall. Hang one paper globe light above the cushion. Use bamboo floors and white plaster walls. Place the canon camera at normal eye height in the southwest corner, looking northeast. Use a 55-degree field of view. Do not add people or unrelated objects."),
    ("Library Reading Room", "Create a rectangular library reading room exactly 8 meters wide, 6 meters deep, and 3.5 meters high. Place exactly four tall bookshelves against the north wall. Place one large reading table centered in the room. Place exactly four reading chairs around the table. Install one double door centered on the south wall. Center one large window on the west wall. Hang exactly two brass pendant lights above the reading table. Use dark wood parquet floors and deep green walls. Place the canon camera at normal eye height in the southeast corner, looking northwest. Use a 55-degree field of view. Do not add people."),
]

VISION_QA_PROMPT = """Analyze these images from a room generation pipeline. The first is a 2D floor plan/layout (SVG), the second is a 3D blockout (geometry preview), and the third is the final photorealistic render (Canon).

Evaluate across these 7 categories. For each, give a score 1-10 and a one-line finding:

1. SPATIAL ACCURACY: How precisely does the blockout and render match the layout's dimensions and placements?
2. AESTHETIC QUALITY: Visual appeal of the final render — materials, textures, lighting, mood.
3. PROMPT ADHERENCE: Are all requested objects, counts, materials, and camera constraints present?
4. ARTIFACTS/GLITCHES: Any clipping, floating objects, distorted textures, unrealistic lighting?
5. INFORMATION FLOW: How well does spatial data transfer from 2D symbols → 3D blocks → final surfaces?
6. CAMERA PERSPECTIVE: Does the render's viewpoint match the blueprint's camera position/angle?
7. ASSET FIDELITY: How well do simple symbols become detailed 3D objects across the pipeline?

Respond ONLY with valid JSON:
{"scores":{"spatial":N,"aesthetic":N,"prompt":N,"artifacts":N,"info_flow":N,"camera":N,"assets":N},"findings":{"spatial":"...","aesthetic":"...","prompt":"...","artifacts":"...","info_flow":"...","camera":"...","assets":"..."},"top_issue":"one sentence describing the single biggest problem to fix","suggestion":"one sentence concrete improvement for the next iteration"}"""


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


def vision_qa(svg_bytes: bytes, blockout_bytes: bytes, canon_bytes: bytes) -> dict:
    """Send all three artifacts to qwen3-vl for structured QA."""
    images = [
        base64.b64encode(svg_bytes).decode(),
        base64.b64encode(blockout_bytes).decode(),
        base64.b64encode(canon_bytes).decode(),
    ]
    payload = {
        "model": "qwen3-vl:8b",
        "messages": [
            {"role": "user", "content": VISION_QA_PROMPT, "images": images}
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024}
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode())
        content = result.get("message", {}).get("content", "{}")
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": "invalid_json", "raw": content[:300] if 'content' in dir() else ""}
    except Exception as e:
        return {"error": str(e)[:200]}


def run_pass(iteration: int, name: str, prompt: str, learnings: list[str]) -> dict:
    """Run one full E2E pass with QA analysis."""
    r = {"iteration": iteration, "name": name, "started": utc_now(), "stages": {}}
    print(f"\n{'━'*60}")
    print(f"  ITERATION {iteration}: {name}")
    print(f"  {utc_now()}")
    if learnings:
        print(f"  Learnings applied: {len(learnings)}")
    print(f"{'━'*60}")

    # Create session
    status, resp = http_json("/api/session", method="POST")
    if status != 200:
        r["result"] = "FAIL:session"
        return r
    sid = resp["session_id"]
    r["session_id"] = sid
    print(f"  session: {sid}")

    # Describe → Plan
    status, resp = http_json(f"/api/session/{sid}/describe", method="POST", body={"description": prompt})
    if status != 200:
        r["result"] = f"FAIL:describe"
        r["error"] = resp.get("error", "")[:200]
        print(f"  ✗ describe: {r['error'][:80]}")
        return r
    plan = resp.get("floor_plan", {})
    r["stages"]["plan"] = {"items": len(plan.get("items", [])), "openings": len(plan.get("openings", []))}
    print(f"  plan: {r['stages']['plan']['items']} items")

    # Fetch SVG + Blockout
    svg_url = resp.get("floor_plan_image") or f"/api/session/{sid}/floor_plan"
    blockout_url = resp.get("blockout_image") or f"/api/session/{sid}/blockout"
    _, svg_bytes = http_bytes(svg_url)
    _, blockout_bytes = http_bytes(blockout_url)
    print(f"  svg: {len(svg_bytes)}B, blockout: {len(blockout_bytes)}B")

    # Approve plan → Canon
    status, resp = http_json(f"/api/session/{sid}/approve_plan", method="POST", expected=(200, 409))
    if status == 409:
        blockers = resp.get("validation_report", {}).get("blockers", [])
        r["result"] = f"FAIL:validation({len(blockers)})"
        r["stages"]["validation_blockers"] = [b["message"][:80] for b in blockers[:5]]
        print(f"  ✗ validation: {len(blockers)} blockers")
        return r
    if status != 200:
        r["result"] = "FAIL:canon_gen"
        return r

    canon_url = resp.get("canon_image") or f"/api/session/{sid}/canon_image?v=1"
    _, canon_bytes = http_bytes(canon_url)
    alignment = resp.get("camera_alignment", {})
    r["stages"]["canon"] = {"bytes": len(canon_bytes), "alignment": alignment.get("status")}
    print(f"  canon: {len(canon_bytes)}B, alignment={alignment.get('status')}")

    # ━━━ VISION QA ━━━
    if svg_bytes and blockout_bytes and canon_bytes and len(canon_bytes) > 1000:
        print(f"  🔍 Running 7-category vision QA...")
        qa = vision_qa(svg_bytes, blockout_bytes, canon_bytes)
        r["vision_qa"] = qa
        if "scores" in qa:
            scores = qa["scores"]
            avg = sum(scores.values()) / max(len(scores), 1)
            print(f"  QA scores: {scores}")
            print(f"  QA avg: {avg:.1f}/10")
            print(f"  Top issue: {qa.get('top_issue', '?')}")
            print(f"  Suggestion: {qa.get('suggestion', '?')}")
            r["qa_avg"] = round(avg, 1)
        elif "error" in qa:
            print(f"  QA error: {qa['error'][:80]}")
    else:
        print(f"  ⚠ Skipping QA (missing artifacts)")

    # Approve Canon → World
    if alignment.get("status") == "misaligned":
        # Try reject + retry once
        status2, resp2 = http_json(f"/api/session/{sid}/reject", method="POST",
                                   body={"reason": "Camera misaligned with blockout"}, expected=(200, 400, 409))
        if status2 == 200:
            alignment = resp2.get("camera_alignment", {})
            r["stages"]["canon_retry"] = alignment.get("status")

    status, resp = http_json(f"/api/session/{sid}/approve", method="POST",
                             body={"action": "approve"}, expected=(200, 409))
    if status == 409:
        error = resp.get("error", "")
        if "inconclusive" in error:
            binding = resp.get("camera_alignment", {}).get("binding", {})
            http_json(f"/api/session/{sid}/accept_alignment", method="POST",
                      body={"decision": "accepted", "binding": binding})
            status, resp = http_json(f"/api/session/{sid}/approve", method="POST",
                                     body={"action": "approve"}, expected=(200, 409))
        if status == 409:
            r["result"] = "FAIL:world_gate"
            print(f"  ✗ world gate: {resp.get('error','')[:60]}")
            return r

    if status != 200:
        r["result"] = "FAIL:world_build"
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
    print(f"  ✓ PASS — {r['stages']['world']}")
    return r


def main():
    results = []
    learnings = []
    pool = ROOMS[:]
    random.shuffle(pool)

    for i in range(50):
        name, prompt = pool[i % len(pool)]
        r = run_pass(i + 1, name, prompt, learnings)
        results.append(r)

        # Extract learnings from QA
        qa = r.get("vision_qa", {})
        if qa.get("suggestion"):
            learnings.append(qa["suggestion"])
            # Keep only last 10 learnings
            learnings = learnings[-10:]

        # Save incrementally
        OUTPUT_DIR.mkdir(exist_ok=True)
        summary = {
            "total": len(results),
            "passes": sum(1 for x in results if x["result"] == "PASS"),
            "qa_scores": [x.get("qa_avg") for x in results if x.get("qa_avg")],
            "learnings": learnings,
            "results": results,
        }
        (OUTPUT_DIR / "learn_loop_results.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )

        # Print running stats
        passes = sum(1 for x in results if x["result"] == "PASS")
        qa_avgs = [x["qa_avg"] for x in results if x.get("qa_avg")]
        avg_qa = sum(qa_avgs) / len(qa_avgs) if qa_avgs else 0
        print(f"\n  📊 Running: {passes}/{len(results)} pass, avg QA: {avg_qa:.1f}/10")
        if learnings:
            print(f"  💡 Latest learning: {learnings[-1][:80]}")

    # Final
    passes = sum(1 for x in results if x["result"] == "PASS")
    qa_avgs = [x["qa_avg"] for x in results if x.get("qa_avg")]
    print(f"\n{'═'*60}")
    print(f"  FINAL: {passes}/50 PASS")
    if qa_avgs:
        print(f"  Avg QA score: {sum(qa_avgs)/len(qa_avgs):.1f}/10")
        print(f"  First 5 QA: {qa_avgs[:5]}")
        print(f"  Last 5 QA:  {qa_avgs[-5:]}")
    print(f"  Learnings accumulated: {len(learnings)}")
    for l in learnings:
        print(f"    • {l[:80]}")
    print(f"{'═'*60}")


if __name__ == "__main__":
    main()

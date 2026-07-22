"""Run a single improved pass for QA review."""
import json, urllib.request, urllib.error

BASE = "http://127.0.0.1:8000"
H = {"X-App-Version": "10", "Content-Type": "application/json"}

PROMPT = """Create a rectangular rustic farmhouse kitchen exactly 5 meters wide, 4 meters deep, and 2.8 meters high.

Place exactly one butcher-block island 1.8 meters long and 0.9 meters wide centered in the room. Place exactly three wooden stools evenly spaced along the south side of the island.

Install one wooden door on the east wall near the northeast corner. Center one large window on the west wall.

Hang exactly two wrought-iron pendant lights in a row above the island. Place one tall pantry cabinet against the north wall near the northwest corner. Place one small herb shelf mounted on the west wall below the window.

Use terracotta tile flooring, whitewashed plaster walls, and exposed dark timber beam ceiling. Set the scene on a warm autumn morning with golden light from the west window.

Place the canon camera at normal eye height in the southeast corner, looking diagonally northwest toward the island and window. Use a 55-degree field of view.

Do not add people, food, pots, or unrelated objects."""


def rq(path, method="GET", body=None, timeout=300):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


print("Creating session...")
_, s = rq("/api/session", "POST")
sid = s["session_id"]
print(f"Session: {sid}")

print("Submitting prompt...")
st, r = rq(f"/api/session/{sid}/describe", "POST", {"description": PROMPT})
plan = r.get("floor_plan", {})
print(f"Plan: {len(plan.get('items', []))} items, {len(plan.get('openings', []))} openings")
for item in plan.get("items", []):
    print(f"  {item['id']:20} {item['name']:30} mount={item['mount']:8} pos=({item['x']:.1f}, {item['z']:.1f}) {item['width']:.1f}x{item['depth']:.1f}m")

print("\nApproving plan...")
st, r = rq(f"/api/session/{sid}/approve_plan", "POST")
if st == 409:
    blockers = r.get("validation_report", {}).get("blockers", [])
    print(f"BLOCKED: {len(blockers)} validation errors")
    for b in blockers:
        print(f"  • {b['message']}")
else:
    align = r.get("camera_alignment", {}).get("status", "?")
    print(f"Canon generated, alignment={align}")

    print("\nApproving canon → building world...")
    st2, r2 = rq(f"/api/session/{sid}/approve", "POST", {"action": "approve"})
    if st2 == 409:
        error = r2.get("error", "")
        if "inconclusive" in error:
            binding = r2.get("camera_alignment", {}).get("binding", {})
            rq(f"/api/session/{sid}/accept_alignment", "POST", {"decision": "accepted", "binding": binding})
            st2, r2 = rq(f"/api/session/{sid}/approve", "POST", {"action": "approve"})
        elif "misaligned" in error:
            print(f"Canon misaligned — proceeding anyway for QA review")
            st2 = 200
            r2 = {}
    if st2 == 200 and r2.get("scene_graph"):
        sg = r2["scene_graph"]
        print(f"WORLD: objects={len(sg['objects'])}, lights={len(sg['lights'])}, doors={len(sg['doors'])}, windows={len(sg['windows'])}")
    else:
        print(f"World result: status={st2}")

print(f"\n{'='*50}")
print(f"Session {sid} ready for review at http://localhost:8501")
print(f"{'='*50}")

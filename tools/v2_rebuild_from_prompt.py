"""Rebuild a V2.0 session's hero Canon from an explicit prompt (bypasses chat flow).

Use when the describe step captured the wrong text (e.g. 'yes' fallback).
Extracts a Brief via the conversation engine, generates the hero Canon, and
leaves the session in awaiting_approval so the normal approve->build flow continues.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SESSION_ID = "f63607f2-665f-476b-8183-f7fbefe9ebb6"
PROMPT = (
    "A cramped one-bedroom apartment belonging to a washed-up former minor-league "
    "baseball player in his late 40s. Dim afternoon light through half-closed blinds. "
    "A sagging brown corduroy couch with a faded team blanket over the back. A dented "
    "mini-fridge next to a card table holding empty beer cans and a takeout container. "
    "On the wall a cracked framed jersey and a dusty trophy shelf with tarnished "
    "little-league cups and a yellowed newspaper clipping. A cheap TV on a milk crate. "
    "A worn recliner with duct tape on the armrest. Scuffed hardwood floors, a pizza "
    "box on the floor, a baseball bat leaning in the corner, a glove and scuffed ball "
    "on the windowsill. Peeling beige paint, water stains on the ceiling, a bare bulb "
    "fixture. Melancholy, lived-in, faded-glory mood, warm dim tungsten lighting, "
    "cluttered, nostalgic, run-down."
)


async def main():
    from src.web.v2_routes import _generate_hero_canon
    from src.unified_pipeline.conversation import ConversationEngine, ConversationTurn

    session_dir = Path(f"output/{SESSION_ID}")
    artifacts = session_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    print(f"Rebuilding {SESSION_ID[:8]} from explicit prompt...")

    # Build a fresh conversation engine and inject the real prompt
    engine = ConversationEngine()
    engine._state.session_id = SESSION_ID
    engine._state.steering_stable = True
    engine._state.turns.append(ConversationTurn(role="user", content=PROMPT))
    engine._state.turn_count += 1

    print("Extracting Brief from prompt...")
    brief = await engine.extract_brief()
    brief_doc = brief.to_dict()
    provenance = brief_doc.get("provenance", {}).get("source", "?")
    objects = [o["name"] for o in brief_doc.get("object_manifest", [])]
    print(f"  Brief provenance: {provenance}")
    print(f"  Objects: {objects}")

    (artifacts / "brief.json").write_text(json.dumps(brief_doc, indent=2), encoding="utf-8")

    print("Generating hero Canon from the correct brief...")
    hero_path = await _generate_hero_canon(SESSION_ID, session_dir, brief_doc, PROMPT)
    print(f"  Hero Canon: {hero_path}")

    # Update meta
    meta_path = session_dir / "session_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    meta["user_prompt"] = PROMPT
    meta["state"] = "awaiting_approval"
    meta["hero_canon"] = str(hero_path)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\nDone. Review the new Canon:")
    print(f"  http://127.0.0.1:8000/api/v2/session/{SESSION_ID}/artifact/hero_canon")


if __name__ == "__main__":
    asyncio.run(main())

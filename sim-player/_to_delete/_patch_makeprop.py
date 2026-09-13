"""Root-cause fixes for the 21 lots John marked "none of these" on the Prop Bench, 2026-09-11.
Byte-exact, exact-once, refuses the file if any anchor is not unique."""
import sys
from pathlib import Path

P = Path(sys.argv[1]) / "make-prop.mjs"

EDITS = [
# ── A. 'trim' catches furniture. 'flagpole' catches nothing. ───────────────────────────────
('''// Deliberately conservative. Words that also appear in furniture subjects are left
// OUT: "step" (step stool), "panel" (control panel), "arch", "wall". A wrong
// category is worse than none, and MAKE_PROP_CATEGORY overrides it either way.
const BUILDING_WORDS = new RegExp(
  "\\\\b(door|doors|doorway|window|sash|casement|mullion|roof|shingle|shingles|gable|hipped|" +
  "dormer|chimney|column|columns|pillar|portico|pediment|porch|veranda|decking|facade|" +
  "soffit|cornice|moulding|molding|skirting|balustrade|banister|staircase|threshold|" +
  "sill|lintel|siding|clapboard|shutter|shutters|awning|gutter|eaves|wainscot|fence|" +
  "gate|balcony|trim)\\\\b", "i");''',
'''// Deliberately conservative. Words that also appear in furniture subjects are left
// OUT: "step" (step stool), "panel" (control panel), "arch", "wall". A wrong
// category is worse than none, and MAKE_PROP_CATEGORY overrides it either way.
//
// 2026-09-11, from the 21 lots John marked "none of these" on the Prop Bench:
//   REMOVED "trim" — it broke its own rule. "oxblood leather high back executive chair
//   with brass nailhead TRIM" was classified building-part, so a chair was rendered
//   without the office palette and came back wrong; its twin without the word ("high
//   back executive office chair tufted") classified prop, rendered right, and John
//   approved it. One word, two lots, opposite verdicts. Nailhead trim, chrome trim and
//   piping are furniture words.
//   ADDED words that name a building part and nothing else. "flagpole" is the one that
//   cost the most: factory-laws.json has carried THREE open flags on "tall white
//   flagpole, steel pole, plain" since 2026-09-05 — it read as a prop, took the
//   executive-office palette, and John denied every take of it twice before today.
const BUILDING_WORDS = new RegExp(
  "\\\\b(door|doors|doorway|window|sash|casement|mullion|roof|shingle|shingles|gable|hipped|" +
  "dormer|chimney|column|columns|pillar|portico|pediment|porch|veranda|decking|facade|" +
  "soffit|cornice|moulding|molding|skirting|balustrade|banister|staircase|threshold|" +
  "sill|lintel|siding|clapboard|shutter|shutters|awning|gutter|eaves|wainscot|fence|" +
  "gate|balcony|flagpole|stoop|transom|fanlight|newel|cupola|turret|parapet|downspout|" +
  "weatherboard|quoin|architrave|entablature|rafter|truss|joist|lath|flashing|" +
  "doorframe|windowsill|frontage)\\\\b", "i");'''),

# ── B. the house clause carried the whole building into a prompt for one part ───────────────
('''export function houseLook(name) {
  const want = String(name || process.env.MAKE_PROP_HOUSE || "").trim();
  try {
    const doc = JSON.parse(readFileSync(HOUSES_FILE, "utf8"));
    const key = want || doc.default;
    if (!key) return null;
    const h = (doc.houses || {})[key];
    if (!h || !h.look) return null;
    return { key, look: String(h.look), name: h.name || key };
  } catch { return null; }
}''',
'''export function houseLook(name) {
  const want = String(name || process.env.MAKE_PROP_HOUSE || "").trim();
  try {
    const doc = JSON.parse(readFileSync(HOUSES_FILE, "utf8"));
    const key = want || doc.default;
    if (!key) return null;
    const h = (doc.houses || {})[key];
    if (!h || !h.look) return null;
    return { key, look: String(h.look), name: h.name || key,
             materials: Array.isArray(h.materials) ? h.materials.map(String) : [] };
  } catch { return null; }
}

// WHAT A COMPONENT MAY INHERIT FROM ITS HOUSE (2026-09-11) ───────────────────────────────
// The belongs-clause was `look` verbatim: "red brick walls, four tall white columns across
// the front, white painted trim and joinery, hipped shingle roof, neoclassical presidential
// style, three storeys". That is a complete instruction for a BUILDING, and an image model
// reads it as the subject rather than as context — so a prompt for one door returned four
// whole houses. John, as the end user, on the Prop Bench: "what am I judging, because there
// is a whole house."
//
// A part may inherit MATERIAL AND FINISH. It may never inherit massing — storeys, style
// period, elevation composition, or how many of anything there are across the front.
// HOUSES.json already carries `materials` for exactly this; `look` is for the BUILDER.
//
// The filter is here rather than in the data file on purpose: a house added later must not
// be able to reintroduce the fault by putting "three storeys" in its materials list.
const MASSING = new RegExp(
  "\\\\b(storey|storeys|story|stories|floor|floors|style|presidential|colonial|victorian|" +
  "neoclassical|georgian|craftsman|ranch|across the front|elevation|facade|massing|" +
  "\\\\d+\\\\s*(?:bed|bath|car)\\\\w*)\\\\b", "i");

export function houseMaterials(h) {
  if (!h) return "";
  const clean = (h.materials || []).map((m) => String(m).trim()).filter((m) => m && !MASSING.test(m));
  if (!clean.length) return "";
  const last = clean.pop();
  return clean.length ? clean.join(", ") + " and " + last : last;
}'''),

('''    const h = houseLook();
    const belongs = h ? ", part of a house that is " + h.look : "";''',
'''    const h = houseLook();
    // materials and finish only — never the building (see houseMaterials above)
    const mats = houseMaterials(h);
    const belongs = mats ? ", finished to match a house of " + mats : "";'''),

# ── C. the ledger recorded the wrong style for every building part ever made ───────────────
('''  const styleUsed = currentStyle();''',
'''  // 2026-09-11: this was currentStyle() with no argument, so it defaulted to "prop" and
  // every building part ever made was recorded in the ledger as having been rendered under
  // art/PROP-STYLE.txt. The whole point of this block, by its own comment above, is to make
  // "which style made this?" answerable — and for building parts the answer it gave was wrong.
  const styleUsed = currentStyle(category);'''),
]


def apply(path, edits):
    data = path.read_bytes()
    before = len(data)
    for old, new in edits:
        ob, nb = old.encode("utf-8"), new.encode("utf-8")
        n = data.count(ob)
        if n != 1:
            print("REFUSED %s: %d matches for %r" % (path.name, n, old[:70]))
            return False
        data = data.replace(ob, nb)
    path.write_bytes(data)
    a = path.read_bytes()
    print("OK %s: %d -> %d bytes, %d edits, CR %d" % (path.name, before, len(a), len(edits), a.count(b"\x0d")))
    return True


sys.exit(0 if apply(P, EDITS) else 1)

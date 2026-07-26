# LLM → 3D scene / Blender tools — core engineering primitives

Researched 2026-07-26, for the flywheel's room-layout problem (turning a room
description into a correct blueprint: room size, furniture placement, doors,
windows, camera). Four tools, what each one actually does under the hood, and
whether it's open source.

---

## 1. SceneCraft (Google DeepMind / Caltech, arXiv:2403.01248, March 2024)

**License / open source: NO usable code release.** The paper is CC-BY-4.0
(free to read/cite), but there is no confirmed public GitHub repo with working
code. Several "SceneCraft" repos exist on GitHub under that name but are
unrelated projects (mostly Minecraft-adjacent). Treat this as **research to
learn from, not a tool you can install.**

**The core primitive: scene graph → numerical constraints → render → GPT-V critique → repeat.**

1. **Scene graph blueprint.** Given a text description, an LLM first writes a
   scene graph: nodes are assets, edges are spatial relationships ("lamp is
   on the desk," "chair faces the window"). This is the same idea your
   flywheel's own `relationships` JSON field is already doing — SceneCraft
   just makes that step the explicit, separate first stage instead of asking
   the model to jump straight to coordinates.
2. **Relationships → Python/Blender constraints.** The graph is translated
   into a Blender Python script where each relationship becomes a numerical
   constraint on asset layout (position, rotation, scale) — not free-form
   coordinates guessed by the model, but math it derives from the graph
   (e.g., "on top of" → stacked bounding boxes touching at one face).
3. **Vision-critique refinement loop.** The script is rendered, and a
   vision-language model (GPT-V) looks at the rendered image and critiques
   it against the original description, feeding corrections back into another
   round of script-writing. This is iterative visual self-correction — the
   loop your flywheel does NOT have (yours checks math validity, not "does
   this look right").
4. **Library learning (the actual novel bit).** Every time SceneCraft solves
   a layout pattern (say, "place N books on a shelf without overlap"), it
   compiles the working code into a reusable function and adds it to a
   growing library. Future scenes call these learned functions instead of
   re-deriving the same geometry from scratch. This is how it "self-improves"
   without ever touching model weights — the improvement lives in an
   external code library, not in fine-tuning.

**Why it matters for you:** the library-learning idea is the most directly
reusable concept, independent of Blender — you could have your own model
accumulate a library of "solved" spatial-relationship-to-constraint
functions (e.g., a proven `place_against_wall()` or `align_row()` snippet)
that gets reused across training examples, rather than re-deriving the same
math in every generated blueprint. The vision-critique loop is the other
big idea, but it requires a rendering step + a vision model in the loop,
which is a heavier pipeline than what you're running now.

---

## 2. BlenderLLM (FreedomIntelligence, GitHub, Apache-2.0)

**License / open source: YES — Apache-2.0, full code + weights + dataset released.**
Repo: `github.com/FreedomIntelligence/BlenderLLM`

**The core primitive: fine-tune a 7B code model specifically on Blender-script pairs, then benchmark it against general models.**

1. **Fine-tuned backbone, not a prompting trick.** BlenderLLM is Qwen2.5-Coder-7B-Instruct,
   actually fine-tuned (weights updated) on a purpose-built dataset called
   **BlendNet** — roughly 12,000 (instruction → Blender Python script) pairs.
   This is the opposite approach from SceneCraft: instead of a frozen big
   model doing agentic reasoning at inference time, the model itself learns
   the mapping directly. This is architecturally the closest analog to what
   your flywheel is already doing (fine-tuning a small local model on
   accepted examples) — BlenderLLM is proof the same recipe works for
   Blender-script generation specifically.
2. **CAD-focused, not room-layout-focused.** Its target domain is parametric/CAD-style
   object modeling (build this specific mechanical or geometric shape as a
   script), not multi-object room composition with spatial relationships.
   It does one object well; it isn't solving "where does the couch go
   relative to the door."
3. **CADBench — their own benchmark.** They built a companion benchmark
   (CADBench) to score generated scripts, and report BlenderLLM beating
   larger general-purpose models on CAD-script generation despite being much
   smaller — the argument being that domain-specific fine-tuning on a
   focused dataset beats raw model size. This is the same bet your flywheel
   is making.
4. **Stated limitations (from their own README):** basic-modeling only, no
   multimodal input (text only, no reference images), no multi-turn
   conversation/iterative refinement — a single one-shot script per prompt.

**Why it matters for you:** BlenderLLM is the strongest existing evidence
that "fine-tune a small open model on a narrow, well-defined script/JSON
generation task" works and beats bigger models — which is exactly your
flywheel's bet. It's not directly reusable for room layout (wrong domain),
but its recipe (build a focused pair dataset → fine-tune a 7B coder model →
benchmark against baselines) is structurally identical to what you're
already running.

---

## 3. LL3M (Threedle Lab / University of Chicago, GitHub)

**License / open source: Code released**, but with a **custom Academic and
Evaluation License Agreement** alongside the repo's LICENSE file — read that
license before any commercial use; it isn't a plain MIT/Apache grant.
Repo: `github.com/threedle/ll3m`
**Caveat:** their hosted live-demo server is discontinued because it depended
on Claude Sonnet 3.7, which has since been retired — the code still exists,
but you'd need to point it at a current model yourself.

**The core primitive: a multi-agent pipeline (plan → retrieve → write → debug → refine), not a single model call.**

1. **Multi-agent architecture.** Instead of one model producing one script,
   LL3M splits the job across specialized agent roles: a **planner** (breaks
   the request into steps), a **retriever** (pulls relevant Blender API
   knowledge), a **writer** (generates the actual script), and a **debugger**
   (catches and fixes script errors) — each a separate LLM call with a
   narrow job, chained together.
2. **BlenderRAG — retrieval-augmented Blender API knowledge.** Rather than
   relying on the model's memorized knowledge of the (large, changing)
   Blender Python API, LL3M maintains a retrieval index of real API
   documentation/examples and pulls the relevant snippets into context
   before writing code. This directly reduces hallucinated API calls —
   arguably the most transferable idea here if you ever have a model
   generating against any API/schema that's too large to memorize reliably
   (your JSON blueprint schema, for instance).
3. **Client-server via a Blender addon.** LL3M runs as an actual Blender
   addon that opens a local server (port 8888); the LLM pipeline talks to
   Blender over that connection to execute scripts and get real feedback
   (errors, state) back, rather than generating a script blind and hoping
   it runs.
4. **Three-phase pipeline with session resumption:** Initial Creation →
   Auto Refinement (the debug loop runs automatically until the script
   executes cleanly) → User-Guided Refinement (a human can then ask for
   specific changes, and the session/state persists so those changes build
   on the existing scene rather than starting over).

**Why it matters for you:** the debugger-agent-in-the-loop pattern (keep
retrying with real execution feedback until it actually runs, before ever
showing it to a human or banking it as training data) is the most directly
useful idea for your flywheel's math-validity gate — right now your
strict checker either passes or rejects a blueprint outright; LL3M's
architecture suggests a middle step where a cheap local pass could try to
auto-repair a near-miss (e.g., one small overlap) before throwing the whole
generation away.

---

## 4. Tiny-LLM-3D (Shaurya-34, GitHub)

**License / open source: YES — MIT license.** Repo: `github.com/Shaurya-34/Tiny-LLM-3D`
**Caveat:** this is a small, early-stage personal project (effectively 0
stars/adoption at time of research) — treat it as "here's one indie
implementation of the idea," not a proven, battle-tested tool.

**The core primitive: text → JSON intermediate representation → a separate, deterministic Blender executor — with a rule-based fallback when no model is available.**

1. **Strict separation of "understand the request" from "build the scene."**
   The LLM's only job is to turn a text prompt into a structured JSON
   description (objects, positions, sizes). A completely separate,
   deterministic Python script then reads that JSON and drives Blender to
   build it. The model never touches Blender's API directly — this is
   architecturally the closest match to what your flywheel already does
   (model outputs JSON blueprint; a separate math checker/executor consumes
   it), just applied to actually rendering the result in Blender rather than
   only validating it.
2. **Rule-based fallback mode.** If no LLM is configured/available, the
   system falls back to simple deterministic rules for basic prompts (e.g.,
   keyword-matching "a red cube" into a hardcoded JSON template) — a cheap
   guaranteed-to-work path when the model isn't present, rather than the
   whole pipeline failing.
3. **Async inbox/watcher job pattern.** Prompts get dropped into a watched
   "inbox" folder/queue; a background watcher process picks them up, runs
   them through the pipeline, and writes results out — decoupling "someone
   asks for a scene" from "the (possibly slow) generation actually happens,"
   similar in spirit to your own harvester/flywheel loop structure.

**Why it matters for you:** this is the simplest, most structurally similar
project to what you've already built — it's really a proof-of-concept of
the exact same "LLM writes JSON, deterministic code executes it" pattern,
just with a Blender executor bolted on instead of your math validator. If
you ever want to go from "validated JSON blueprint" to "an actual rendered
Blender/3D scene" as a demo step, this is the shortest, most directly
comparable existing example to crib from — though given its early/unproven
state, you'd be learning from its architecture, not depending on its code.

---

## Side note: UPBGE (context, not one of the four above)

UPBGE (Uchronia Project Blender Game Engine) is a separate, actively
maintained fork of Blender's old game engine — GPL-licensed (inherits
Blender's license), currently at v0.50, tracking Blender 5 as of 2026, used
for games/architectural walkthroughs/robotics sims. It is **not** an
LLM-scene-generation tool itself — it's a runtime/engine that any of the
above tools' *output* could theoretically be loaded into and made walkable.
It only becomes relevant to your project if Blender/UPBGE were the target
engine your generated scenes get built into — separate from your existing
Three.js web world at `localhost:5173`. I flagged this open question
earlier and haven't heard back: would a Blender-based approach be a
**content-authoring step** that exports into your existing web world
(e.g., via glTF), or a **second, competing engine**? Worth settling before
any of this goes further, since UPBGE's whole value proposition (its own
game runtime) only applies under the second reading.

---

## The one-line comparison

| Tool | Core trick | Domain | Open source |
|---|---|---|---|
| SceneCraft | scene graph → constraints → render → GPT-V critique loop → reusable function library | multi-object scene composition | No (paper only) |
| BlenderLLM | fine-tune a 7B coder model on 12k instruction→script pairs | single-object CAD scripting | Yes (Apache-2.0) |
| LL3M | multi-agent plan/retrieve/write/debug/refine, RAG over the Blender API, live Blender connection | general Blender scene building, iterative | Yes (custom academic license) |
| Tiny-LLM-3D | text → JSON → deterministic executor, rule-based fallback | simple object placement | Yes (MIT) |

The two ideas most worth stealing for your flywheel specifically: **library
learning** (SceneCraft — bank solved spatial-constraint patterns as reusable
functions instead of re-deriving them every time) and **debug-loop
auto-repair before rejection** (LL3M — give a near-miss blueprint one cheap
local repair attempt before throwing the whole generation away).

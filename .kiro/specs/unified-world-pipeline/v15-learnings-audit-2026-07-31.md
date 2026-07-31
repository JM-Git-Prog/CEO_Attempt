# V15 Learnings Audit for Unified World Pipeline

**Snapshot:** 2026-07-31. **Mode:** read-only scan of V15; Claude Desktop was actively editing V15 during collection. This report is advisory evidence, not V15 release evidence, and intentionally does not modify `requirements.md`, `design.md`, or `tasks.md`.

## Evidence reviewed
- Corrective authority: `../photo-to-real-3d-world-v14/requirements.md` Requirements 16–22.
- As-built record: `../../../THE-LINE-ARCHITECTURE.md`.
- Live implementation: `../../../src/v15_fable.py`, V15 template/routing, and `../../../v15-variations/var-001..004/` notes.
- Target comparison: this spec's `requirements.md`, `design.md`, and `tasks.md`; current `src/unified_pipeline/**`; KiroGraph memory and repository history/status.
- Working-tree caveat: V15 and Unified files were concurrently modified; re-check exact code before adopting changes.

## Critical lessons Unified should absorb
1. **One spatial authority:** approved normalized Metric Plan owns architecture, openings, navigation, collision, and transforms. Canon, segmentation, depth, and neural meshes are evidence/candidates only.
2. **Remove dual room authority:** Unified Requirement 16 currently promotes a depth-displaced shell to environment geometry. Keep a parametric room authoritative; depth may be optional aligned appearance/reference with collision disabled.
3. **Fail-closed solve chain:** evidence → provenance-bearing intent → solve → normalize → validate → immutable CameraContract → constrained SceneGraph → WorldContract → relationship solve → canonical hash. Any mutation creates a new nonzero revision and revalidation.
4. **No consumer reinterpretation:** browser/Godot/UPBGE must not independently default, clamp, rotate, rescale, offset, normalize, or infer camera/geometry. Normalize approved assets exactly once.
5. **Restore all publication gates to MVP:** provenance, containment, overlap/openings/circulation, camera validity, asset digest/triangles, material honesty, and browser/compiler parity. V15 learned these are correctness gates, not polish.
6. **Compile before parity:** run structural gates before compilation, then compiler parity as a post-compile/pre-publication gate. Current `Gates → Compile` wording cannot prove parity at gate time.
7. **GREEN must mean spatial honesty:** presence alone is insufficient. Validate every requested object, photo placement, rotation-aware full extents, height/dimensions, zero forbidden overlaps, opening/shell truth, palette/material intent, and prompt fidelity.
8. **Three-view identity:** Blockout/blueprint, Canon, and first-person world must derive from one geometry and camera; add a mandatory cross-authority identity report before publication.
9. **Similarity only, never min-max:** measured image evidence may use one camera-anchored uniform similarity transform plus translation-to-fit. Independent-axis/min-max normalization amplified a 0.35 m depth band by 13.6×.
10. **Stable identity:** bind objects/assets by UUID and explicit category, not list index or fuzzy noun matching. Preserve evidence-to-object lineage through approval, replacement, compilation, and replay.
11. **Durable resumability:** persist stage checkpoints, input/output hashes, pending external job IDs, approval revision, and branch lineage. Resume idempotently; stale responses must not overwrite newer revisions.
12. **Artifact invalidation:** changing Plan, Canon, Object_Canon, mesh, or material must invalidate all dependent approvals/artifacts and preserve superseded artifacts rather than silently overwrite/delete.
13. **One approval writer:** define ownership for approval state, unresolved-flag blocking, rejection/remake lifecycle, stale approval invalidation, and explicit flag resolution. Make Object_Canon an actual mandatory gate or remove it consistently.
14. **Resource arbiter, not a partial list:** include Ollama, Dream/Canon FLUX, SAM, Qwen edit/inpaint, DA3, Hunyuan, Trellis, painting, and every Comfy instance. One GPU user at a time includes the planner; define unload, OOM, stall, and host-RAM policy.
15. **Windows process ownership:** detached child process groups, single-worker lease/lock, watched-reload safety, mtime/hash freshness checks, and external-job reconciliation are architecture requirements.
16. **Event finality:** pre-contract events are provisional. Final SSE/WS/replay/sidecar/compiler records require the exact revision, transforms, asset/material bindings, gate report, and canonical hash; reconnect/replay must preserve ordering.
17. **Qualification durability:** distinguish mocked tests from live qualification; use fresh zero-state sessions, exact artifact hashes/source fingerprints, isolated browser ownership, append-only evidence, and restart after every failure. Consider retaining V15's smoke + 5 headless + 5 human-like rounds instead of one pass.
18. **Warehouse policy must be explicit:** always-fresh generation makes the warehouse catalog-only. V15 proved approved reuse can save GPU work; keep reuse opt-in/post-MVP if originality remains the default.

## Do not port from V15
- Canon-first reconciliation that lets photo evidence rewrite authoritative geometry.
- Weak presence/order-only GREEN logic, free-form coordinate planning, index-based identity, fuzzy warehouse pre-match, first-installed-model selection, or BAT/in-memory ownership of durable orchestration.
- Depth/neural room meshes as collision or architectural truth, stale cache-by-existence, or final events emitted before a gated hash-bound contract.

## Ranked spec edits
- **Critical:** rewrite Requirements 16/20; add the mandatory solve/revision chain, exactly-once asset normalization, full MVP gates, three-view identity, durable checkpoint/replay semantics, and an explicit Object_Canon gate.
- **Important:** reconcile design/task stage order and gate count; replace fixed VRAM order with a complete arbiter; add approval/process ownership and property tests for no-min-max, no consumer drift, hash/revision rejection, and replay ordering.
- **Cleanup:** fix Requirement 12.3's “V14 interface” wording; define positive-forward coordinate convention across Three.js/Godot/UPBGE; reconcile qualification count and release-title policy.

## Verification still required
No tests were run for this read-only audit. V15 has no defensible clean release baseline in the scanned working tree, and current Unified completion marks are provisional until concurrent edits settle and tests/qualification produce durable evidence. Re-scan the V15 diff and resolve conflicts before directly editing the three governing spec files.
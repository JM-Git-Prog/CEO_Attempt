# Self-Learning Flywheel — Photo-to-2D-CAD Floor Plan SLM

## North Star

Train an ultra-efficient, near-perfect small language model (SLM) that excels at ONE task:
converting a photograph of a room with objects into a precise 2D CAD floor plan drawing
(including all furniture positions, dimensions, and identifiers).

This leverages V14's existing infrastructure — segmentation, depth estimation, scale
calibration, and layout estimation — as both a data generator and an objective labeler.
The V14 pipeline mass-produces structured outputs (depth maps, object positions, real-world
dimensions) that can be converted into ground-truth 2D CAD representations without manual
annotation.

## Why This Is Credible

1. **Free labeler exists:** V14's depth-to-layout pipeline produces metric 3D positions and
   real-world dimensions for every object. Projecting these onto the floor plane gives
   a ground-truth 2D CAD layout — no human labeling needed.
2. **Data factory exists:** every photo submission through V14 generates a complete labeled
   example (photo → segmentation → depth → layout → floor plan projection).
3. **Task is narrow and well-defined:** photo → structured JSON/DXF describing a top-down
   floor plan with walls, doors, windows, and furniture footprints with dimensions.
4. **Small models fine-tune well on narrow tasks:** the vision-to-structured-output pattern
   (image → JSON schema) is exactly what 1-3B parameter vision-language models handle.

## Architecture

```
V14 Pipeline (data factory)
    │
    ├── Source Photo ─────────────────────────┐
    ├── Segmented Objects + Masks             │
    ├── Depth Map (metric, meters)            │
    ├── Scale Calibrator (real-world dims)    │
    ├── Layout Estimator (3D positions)       │
    └── Physics Classification               │
         │                                    │
         v                                    v
    Floor Plan Projector              Training Pair
    (3D→2D top-down projection)       (photo, floor_plan_json)
         │                                    │
         v                                    v
    Ground Truth CAD JSON             Corpus (append-only)
                                              │
                                              v
                                    SLM Fine-Tune (LoRA)
                                              │
                                              v
                                    Eval: photo → predicted CAD
                                    vs. V14 ground truth
```

## Phases

### F0 · Corpus Capture (passive, runs alongside V14)

Every V14 session produces a training example:
- **Input:** source photo (resized to model input resolution)
- **Label:** 2D CAD floor plan JSON containing:
  - Room boundary polygon (walls projected to floor plane)
  - Door/window positions and widths
  - Furniture footprints (bounding rectangles on floor plane with ID, category, dimensions)
  - Scale bar / room dimensions in meters

The projector converts V14's 3D layout to a 2D top-down representation:
- Object (x, z) positions become CAD (x, y) coordinates
- Object width/depth from ScaleResult become footprint rectangles
- Room shell depth map → wall boundary polygon
- Openings from scene parse → door/window markers

**Storage:** `data/flywheel/corpus.jsonl` — append-only, one record per session.

### F1 · Diversity Expansion (idle-GPU, after V14 stabilizes)

- Run V14 on diverse room photos (sourced from public datasets: 3D-FRONT renders,
  ScanNet, HyperSim, or user submissions)
- Cycle through varied room types: bedrooms, living rooms, kitchens, offices
- Each successful V14 run → one training example added to corpus
- Target: 500+ labeled pairs before training

### F2 · SLM Fine-Tune (gate: ≥500 labeled pairs)

- Base model: small vision-language model (e.g., Qwen2-VL-2B, PaliGemma-3B, or similar)
- Task: photo → CAD floor plan JSON
- Method: LoRA fine-tune on RTX 4090 (fits in 24GB for 2-3B models)
- Eval metric: IoU of predicted furniture footprints vs. V14 ground truth
  - Per-object position error (meters)
  - Per-object dimension error (%)
  - Room boundary IoU
  - Object count accuracy

### F3 · Continuous Improvement Loop

Once the SLM is trained:
1. Run SLM on new photos → predicted CAD
2. Run V14 on same photos → ground truth CAD
3. Compare: where SLM disagrees with V14, that's a hard example
4. Add hard examples to training corpus (curriculum learning)
5. Retrain periodically as corpus grows
6. Track eval metrics on held-out test set

## Output Format: CAD Floor Plan JSON

```json
{
  "version": "cad-floor-plan/v1",
  "room": {
    "boundary_m": [[0,0], [4.2,0], [4.2,3.8], [0,3.8]],
    "ceiling_height_m": 2.7
  },
  "openings": [
    {"type": "door", "wall": "south", "center_m": [2.1, 0], "width_m": 0.9},
    {"type": "window", "wall": "east", "center_m": [4.2, 1.9], "width_m": 1.2}
  ],
  "furniture": [
    {
      "id": "sofa_1",
      "category": "props",
      "label": "three-seat sofa",
      "footprint_m": {"center": [2.1, 3.2], "width": 2.0, "depth": 0.9},
      "rotation_deg": 0
    },
    {
      "id": "table_1",
      "category": "props",
      "label": "coffee table",
      "footprint_m": {"center": [2.1, 2.4], "width": 1.0, "depth": 0.5},
      "rotation_deg": 0
    }
  ],
  "source_photo_hash": "sha256:..."
}
```

## Relationship to Other Specs

- **photo-to-real-3d-world-v14:** The DATA FACTORY — produces labeled training examples
- **llm-driven-upbge-runtime:** The SLM's output (2D CAD) can feed the WorldContract
  builder, which can then compile to UPBGE or export to Godot/GLB
- **text-to-playable-world-mvp:** A trained SLM replaces the text LLM for photo inputs

## Guardrails

- V14 implementation takes absolute priority — flywheel is passive data collection only
  until V14 is stable and producing reliable outputs
- No training runs that block the GPU during V14 pipeline execution
- Corpus is append-only; no deletion of validated examples
- The SLM is evaluated against V14 ground truth, never self-evaluated
- No cloud data uploads without explicit approval

## Success Criteria

The SLM is "near-perfect" when:
- Object position error < 0.15m mean on held-out test set
- Object dimension error < 15% mean
- Room boundary IoU > 0.85
- Object count accuracy > 90%
- Inference time < 3 seconds per photo on RTX 4090
- Model size < 4B parameters (fits alongside V14 pipeline in VRAM)

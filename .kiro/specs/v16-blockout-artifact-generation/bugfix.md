# Bugfix Requirements Document

## Introduction

The V16 unified pipeline's `blockout` and `canon_honesty` stage handlers are stubs that return status dicts without producing any artifact file on disk. When `unified_artifact_response()` looks for the expected image file, it finds nothing and returns 404. This causes the frontend to render a broken `<img>` tag (blank area), and the pipeline stalls at `blockout_approval` waiting for user approval of a non-existent image — permanently blocking the canon stage from executing.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the `blockout` stage handler executes THEN the system returns `{"status": "blockout_rendered"}` without writing any image file to the session directory

1.2 WHEN the frontend requests `/api/session/{id}/blockout` after the blockout stage completes THEN the system returns HTTP 404 because no `blockout*.png` file exists on disk

1.3 WHEN the `canon_honesty` stage handler executes THEN the system returns a result dict with `"image_path": ""` without generating any canon image file

1.4 WHEN the pipeline reaches `blockout_approval` THEN the system parks indefinitely because the user cannot approve a non-existent blockout image

1.5 WHEN ComfyUI is unavailable and the blockout stage is triggered THEN the system still returns only the stub dict with no fallback artifact and no indication of degraded state

### Expected Behavior (Correct)

2.1 WHEN the `blockout` stage handler executes THEN the system SHALL invoke the blockout renderer (ComfyUI SDXL workflow or Three.js plan render) and write a `blockout.png` file to the session output directory

2.2 WHEN the frontend requests `/api/session/{id}/blockout` after the blockout stage completes THEN the system SHALL return the generated blockout image with HTTP 200

2.3 WHEN the `canon_honesty` stage handler executes THEN the system SHALL invoke the canon image generator (FLUX via ComfyUI with the plan prompt) and write a `canon.png` file to the session output directory

2.4 WHEN the blockout stage completes successfully THEN the system SHALL store the output file path in the stage result dict so that `unified_artifact_response()` can locate and serve the file

2.5 WHEN ComfyUI is unavailable and the blockout stage is triggered THEN the system SHALL generate a labeled placeholder image (containing text indicating degraded mode), write it to disk, store the path in the result dict, and mark the checkpoint status as `"degraded"`

2.6 WHEN the `canon_honesty` stage handler completes THEN the system SHALL store the canon image output path in the stage result dict under `"image_path"`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the pipeline executes stages other than `blockout` and `canon_honesty` (e.g., `brief`, `plan`, `dream_preview`) THEN the system SHALL CONTINUE TO handle those stages with their existing logic unchanged

3.2 WHEN `unified_artifact_response()` is called for artifact types other than `blockout` or `canon` THEN the system SHALL CONTINUE TO resolve and serve those artifacts using the existing file-lookup logic

3.3 WHEN a session has already completed the blockout stage with a valid artifact on disk THEN the system SHALL CONTINUE TO serve that existing artifact on subsequent requests without re-rendering

3.4 WHEN the pipeline checkpoint state machine transitions between stages THEN the system SHALL CONTINUE TO follow the existing stage ordering and approval gates

3.5 WHEN ComfyUI is available and the blockout stage is triggered THEN the system SHALL CONTINUE TO prefer the full-quality ComfyUI render over any placeholder fallback

---

## Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type StageExecution where X.stage IN {"blockout", "canon_honesty"}
  OUTPUT: boolean

  // The bug triggers when a stage handler completes but no artifact file
  // exists at the expected output path in the session directory
  RETURN X.stage_completed = TRUE
     AND file_exists(X.session_dir / expected_artifact_filename(X.stage)) = FALSE
END FUNCTION
```

## Property: Fix Checking

```pascal
// For all sessions where the blockout or canon stage executes,
// the fixed handler must produce a file on disk and reference it in the result.
FOR ALL X WHERE isBugCondition(X) DO
  result ← F'(X)
  ASSERT file_exists(result.output_path)
     AND result.output_path != ""
     AND http_status(GET /api/session/{X.session_id}/{X.stage}) = 200
END FOR
```

## Property: Preservation Checking

```pascal
// For all sessions where stages OTHER than blockout/canon execute,
// behavior is identical before and after the fix.
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

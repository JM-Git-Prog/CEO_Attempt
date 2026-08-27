---
inclusion: manual
description: "Runs the world_test_kit e2e test with a kitchen prompt, logs output, diagnoses and fixes root-cause errors (offloading to GLM-5.2 for heavy analysis), then reruns until clean."
---

Run the following test command and capture output:

python -m tests.e2e.world_test_kit run --prompt "a small warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain" 2>&1 | Tee-Object tests\e2e\artifacts\playtest\latest_run.log

After the run:
1. If there are errors, diagnose the root cause. For long-running analysis or large log triage, offload to Ollama GLM-5.2 (use ollama_chat or ollama_generate with model "glm-5.2:cloud" and format "markdown").
2. Fix the root cause in the source code.
3. Rerun the same test command to confirm the fix.
4. Repeat until the test passes cleanly.

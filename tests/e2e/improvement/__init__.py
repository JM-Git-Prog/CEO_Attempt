"""Self-improving loop modules for the E2E testing framework.

This package contains cloud model integration for:
- Failure analysis and triage (failure_analyzer.py)
- Test coverage gap discovery (coverage_discoverer.py)
- Perceptual threshold calibration (threshold_calibrator.py)
- Vision QA checklist evolution (checklist_evolver.py)

All modules communicate with cloud models via Ollama MCP tools and
produce ADVISORY outputs only — no changes are auto-applied.

Requirements: 24–27
"""

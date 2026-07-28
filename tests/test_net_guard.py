"""The endpoint host allowlist (src/orchestrator/net_guard.py)."""

import pytest

from src.orchestrator.net_guard import UnsafeEndpointError, checked_url


def test_local_hosts_pass(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    assert checked_url("OLLAMA_URL") == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434/")
    assert checked_url("OLLAMA_URL") == "http://127.0.0.1:11434"


def test_mock_e2e_sinkhole_still_passes(monkeypatch):
    # MOCK_E2E_ENV points OLLAMA_URL at 127.0.0.1:9 on purpose; the guard
    # must not break the qualification loop's own mock mode.
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    assert checked_url("OLLAMA_URL") == "http://127.0.0.1:9"


def test_remote_host_is_rejected(monkeypatch):
    monkeypatch.delenv("ALLOWED_API_HOSTS", raising=False)
    monkeypatch.setenv("OPENAI_API_URL", "https://evil.example.com")
    with pytest.raises(UnsafeEndpointError):
        checked_url("OPENAI_API_URL")


def test_empty_value_means_backend_is_off(monkeypatch):
    monkeypatch.delenv("IMAGE_API_URL", raising=False)
    assert checked_url("IMAGE_API_URL") == ""


def test_allowlist_widens_only_when_asked(monkeypatch):
    monkeypatch.setenv("IMAGE_API_URL", "https://api.example.com")
    monkeypatch.delenv("ALLOWED_API_HOSTS", raising=False)
    with pytest.raises(UnsafeEndpointError):
        checked_url("IMAGE_API_URL")
    monkeypatch.setenv("ALLOWED_API_HOSTS", "api.example.com")
    assert checked_url("IMAGE_API_URL") == "https://api.example.com"


def test_value_is_resolved_fresh_on_every_call(monkeypatch):
    # Guards the 2026-07-25 defect: a URL resolved once and frozen into a
    # module-level constant silently ignores a later os.environ change, so a
    # mid-run redirect would sail past a check done only at import time.
    monkeypatch.delenv("ALLOWED_API_HOSTS", raising=False)
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    assert checked_url("OLLAMA_URL") == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_URL", "http://attacker.test:11434")
    with pytest.raises(UnsafeEndpointError):
        checked_url("OLLAMA_URL")

"""Host allowlist for outbound API endpoints that carry a credential.

Mirrors the control already applied to COMFYUI_URL in tools/e2e_qualification.py
(`canon_comfyui_must_be_local`, lines 852-859). OLLAMA_URL, OPENAI_API_URL and
IMAGE_API_URL never got the same treatment, yet two of them attach a Bearer
token to every request — so a changed environment variable would have sent the
key to an arbitrary host, unattended, with nothing to notice.

Fails closed and loud: an unapproved host raises rather than falling through to
the next backend. A silent fallback would hide exactly the event this guards.

Resolved fresh on every call and never frozen into a module-level constant — a
value read once at import silently ignores later os.environ changes (see the
2026-07-25 constitution entry on per-call env mutation).
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class UnsafeEndpointError(RuntimeError):
    """An endpoint was pointed at a host that is not on the allowlist."""


def allowed_hosts() -> frozenset[str]:
    """Local hosts, plus anything deliberately listed in ALLOWED_API_HOSTS."""
    extra = os.getenv("ALLOWED_API_HOSTS", "")
    return LOCAL_HOSTS | frozenset(
        host.strip().lower() for host in extra.split(",") if host.strip()
    )


def checked_url(env_var: str, default: str = "") -> str:
    """Return the URL held in `env_var`, or raise if its host is not allowed.

    An empty value returns "" — an unconfigured backend is not an error, it is
    simply off, and the callers already treat "" as "skip this backend".
    """
    url = os.getenv(env_var, default).rstrip("/")
    if not url:
        return ""
    host = (urlparse(url).hostname or "").lower()
    permitted = allowed_hosts()
    if host not in permitted:
        raise UnsafeEndpointError(
            f"{env_var} points at {host!r}, which is not an allowed host. "
            f"Allowed: {sorted(permitted)}. If this is deliberate, add the host "
            f"to ALLOWED_API_HOSTS — do not widen this check in code."
        )
    return url

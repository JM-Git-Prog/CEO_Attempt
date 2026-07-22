# Unsupported-Feature and Fallback Policy

Status: normative pre-routing decision record  
Schema: `fallback-policy/v1`  
Scope: task 1.3; no pipeline, adapter, profile, or UI routing is activated here.

## Authority and representation

`World_Contract` remains the read-only semantic authority for every adapter attempt. A fallback consumes the same canonical contract bytes and profile configuration as the primary attempt; it never consumes, repairs, or reverse-engineers a failed `.blend`, GLB, runtime package, or other engine artifact.

For every requested feature, an adapter must report exactly one disposition:

1. `native`: represented by the target contract without semantic loss.
2. `sidecar_metadata`: preserved in a named, versioned metadata contract where the portable artifact cannot carry it.
3. `target_specific`: implemented by an explicitly named, versioned first-party target implementation.
4. `unsupported`: not representable without changing semantics.

Sidecar and target-specific dispositions require an explicit declaration version. Empty nodes, baked animation, replacement materials, placeholder geometry, generated source, or other approximations are not implicit fallbacks. An adapter must report `unsupported` rather than silently substituting semantics.

## Truthful outcomes

Terminal status is one of:

- `native_success`: all requested artifacts passed their applicable gates using the profile's primary adapter.
- `fallback_success`: all requested artifacts passed using the profile-declared fallback adapter.
- `partial_export`: at least one independently requested portable artifact passed all of its own gates, but the complete requested set did not. Partial output is never described as playable.
- `failure`: no independently valid requested artifact remains, or a fail-closed condition invalidates acceptance.

A fallback result can never become `native_success`. Regular Blender can never be identified as UPBGE. It may be used only as an explicitly profile-authorized compile-only development adapter and cannot establish playable-runtime success.

## Fallback eligibility

Fallback is allowed only when all of the following are true:

- the immutable Workflow_Profile declares a distinct fallback adapter;
- the profile allowlists the exact trigger;
- the failure stage is valid for that trigger;
- any profile retry budget has been exhausted; and
- the fallback starts from the same canonical read-only `World_Contract`.

Eligible triggers are:

| Trigger | Eligible stage | Additional rule |
|---|---|---|
| `unavailable` | capability probe | Must be profile-declared. |
| `incompatible` | capability probe | Must be profile-declared. |
| `timeout` | capability probe, compile, export | Retry budget must be exhausted. |
| `process_failure` | capability probe, compile, export | Retry budget must be exhausted. |
| `unsupported_required_feature` | capability probe, compile, export | Only an explicit profile declaration permits target change. |

Contract, command-validation, constraint-solving, security/resource, traversal, parity, QA, provenance, and fallback-attempt failures are fail-closed and cannot invoke another adapter. Runtime-smoke failure rejects the playable artifact; independently requested portable artifacts may remain `partial_export` only after passing their own parity and content gates.

Fallback cannot authorize model-generated Python, shell, shader source, driver expressions, executable substitutions, or filesystem paths. The same security and resource limits apply to every attempt.

## Routing and history

Routing is selected from the persisted immutable Workflow_Profile, never from currently installed engines. Capability discovery may determine whether the selected attempt can execute, but it cannot rewrite routing policy. Retained V9/V10 profiles and historical sessions therefore remain unchanged when UPBGE or another engine is installed or removed.

This record does not add a new profile, modify V9/V10, choose a packaged UPBGE build, or expose controls. Those actions remain owned by later tasks and require their own versioning, licensing, provenance, QA, and release gates.

## Evidence requirements

Every primary and fallback attempt must eventually receive a separate append-only prepared and terminal manifest bound to profile identity, canonical contract hash, adapter identity, configuration, diagnostics, and artifacts. A failed later attempt cannot overwrite prior accepted artifacts or evidence. Provenance write or binding failure is fail-closed.

Release classification remains prohibited until the complete fresh zero-state process in Requirement 12 succeeds on the exact target commit. This policy-only task creates no user-visible interface change and therefore does not advance an interface query version.

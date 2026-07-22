# UPBGE Exact-Build License and Redistribution Decision

**Decision ID:** `upbge-redistribution/v1`  
**Decision date:** 2026-07-22  
**Status:** **BLOCKED — no exact UPBGE build is approved or pinned**  
**Approval owner:** Not supplied; a named release/compliance owner must approve a future revision.  
**Scope:** Task 1.4; Requirements 1, 7, 8, 9, and 12.

## Decision

The approved/pinned UPBGE build is **none**. The repository and this machine do not contain enough evidence to identify or approve a specific UPBGE binary. A product-version string used by a test double is not a release pin, and general project licensing information is not evidence for the contents or obligations of an exact binary archive.

Until a future decision satisfies every gate below, the project SHALL NOT bundle, copy, mirror, install, auto-download, containerize, redistribute, or publish an UPBGE executable, Blender Player, UPBGE standalone runtime, or package containing those components. Packaging work that would include UPBGE software is prohibited. This blocked decision completes the required pre-packaging review without inventing an approval.

A candidate may be located without being accepted. Product routing SHALL NOT automatically launch a candidate from `PATH`, a known location, or `UPBGE_PATH` until its exact artifact hash is on an approved allowlist. A manually initiated, non-release engineering evaluation may record candidate evidence, but its outputs are diagnostic only and are ineligible for publication or release evidence.

Engine-neutral World Contracts, Godot fallback output, and portable GLB/metadata that do not contain UPBGE software may continue under their own license, parity, provenance, QA, and release gates. They must never be labeled native UPBGE output.

## Evidence reviewed

### Repository and environment evidence

- `src/workflow_provenance.py` selects `upbge` for profile `v11-upbge-contract-r1`, but records no release tag, source commit, platform archive, download URL, executable SHA-256, signing identity, or license bundle.
- `src/upbge_capabilities.py::discover_upbge` supports optional `UPBGE_PRODUCT_VERSION` and `UPBGE_BLENDER_API_VERSION` comparisons, but those values are not mandatory and no executable hash is checked.
- `src/pipeline.py` calls discovery with only `UPBGE_PATH`; it does not supply an approved product/API pin or binary digest. Current capability success therefore cannot establish build approval.
- The `0.36` and Blender API `3.6` values in `tests/test_upbge_capabilities.py` are synthetic monkeypatched payloads written around fake temporary executables. They are test examples, not provenance or approval evidence.
- No checked-in UPBGE binary, release archive, checksum, signature, corresponding-source snapshot, exact-build `COPYING` file, third-party notice set, SBOM, or packaging manifest was found.
- At review time, `UPBGE_PATH` was unset and neither `upbge` nor `blender` resolved from `PATH`. This machine observation is not a portable release guarantee.
- Evidence was reviewed against repository HEAD `580fb347401d871d1920e96b7e7b39263bd48121`; the working tree was not a clean release target, so this is not Requirement 12 release qualification.

### External licensing sources

- The [official UPBGE repository COPYING notice](https://github.com/UPBGE/upbge/blob/master/COPYING) identifies the codebase as GNU GPL and points to the repository's full license text.
- The [official UPBGE licensing guidance](https://upbge.org/docs/latest/manual/manual/deployment/licensing.html) explains that bundles containing UPBGE/Blender software must comply with the GNU GPL and that a standalone package can include the player and blend data.
- The [Blender Foundation license page](https://www.blender.org/about/license/) describes GPL obligations for Blender binary distributions and notes that bundled components can carry additional compatible licenses.

These sources establish material compliance risk but do not identify the license composition of an unselected UPBGE build. External source descriptions above are paraphrased for licensing compliance; this record is an engineering gate, not legal advice.

## Mandatory gates for a future approval

A future revision may change the status only when all items are attached to the decision:

1. **Exact identity:** UPBGE release/version, upstream tag, immutable source commit, Blender API version, Python version, target OS, architecture, archive filename, executable path within the archive, and intended distribution channel.
2. **Artifact provenance:** official HTTPS source URL, archive byte size and SHA-256, executable SHA-256 after extraction, and available publisher signature/attestation with verification result. Rebuilt or repackaged artifacts need their own identity and hashes.
3. **License set:** the exact archive's license files, third-party notices, component/dependency inventory, and an SBOM retained with the review. Generic `master` or `latest` pages are supporting context only.
4. **Compliance plan:** written treatment of binary notices, corresponding source and build information, local modifications, first-party scripts using the Blender API, redistribution of dependencies, trademark/branding, and the offer or delivery mechanism required for the chosen channel.
5. **Runtime-content review:** a determination for the exact standalone packaging method, including whether player software, `.blend` data, Python/runtime templates, assets, or libraries are combined and whether every included element is distributable under the proposed terms.
6. **Named approval:** dated sign-off by the product/release owner and the person responsible for license compliance. Legal review is required where the owner cannot confidently approve the GPL distribution plan.
7. **Enforced immutable pin:** the new Workflow Profile must record the approved product/API versions, platform artifact identity, archive and executable SHA-256 values, and compiler/runtime template hashes. Hash verification must occur before any candidate is launched; an unpinned `PATH` result cannot be accepted.
8. **No silent acquisition:** no automatic download or upgrade. Any installer or acquisition flow requires separate explicit approval, integrity verification, user disclosure, and failure-closed behavior.
9. **Package inventory and disclosure:** the proposed package layout, bundled notices/source materials, third-party-runtime disclosure, artifact roles, media types, byte counts, and hashes must be reviewed before publication.
10. **Technical qualification:** the exact approved build must pass identity/capability probing, isolation checks, structural parity, GLB reload validation, applicable runtime smoke checks, and immutable prepared/terminal manifests.
11. **Release qualification:** Requirement 12 must pass from a brand-new zero-state session on the exact target commit, recording the workflow profile, UPBGE version/build hashes, package hashes, canonical prompt, URLs, and retained-interface/fallback checks.
12. **Superseding record:** approval must be a new dated decision revision that names the exact build and evidence; capability detection or a passing test cannot implicitly change this blocked status.

## Failure and fallback rule

If any approval field or gate is absent, mismatched, or unverifiable, the result is `unapproved_build`: do not launch for product routing, do not package, do not publish a playable UPBGE artifact, preserve diagnostics, and use only the immutable profile's explicitly permitted Godot fallback. The user-visible and provenance status must remain `fallback_success`, `partial_export`, or `failure` as applicable—never `native_success`.

# UI Versioning and Commit Policy

For every user-visible page or interface change:

1. Increment the interface query version (`?v=N`).
2. Keep the preceding version accessible and behaviorally stable.
3. Make the newest version the default when no `v` is supplied.
4. Show clear links for switching between retained versions.
5. Validate the page, relevant API routes, and static JavaScript before completion.
6. Before committing, create a brand-new empty session ID and run the canonical demo prompt from Step 1.
7. Inspect every affected stage (Brief, Plan, Blockout, Canon, World, and Compare as applicable).
8. If any bug appears, record it, fix it, discard that test session, and restart with another new empty session ID.
9. Never use a restored or previous-version session as evidence for a release pass.
10. Commit only after one complete clean zero-state pass.
11. Stage only relevant files and use commit titles in the form `feat(web): release vN interface` unless the change is strictly a fix.
12. After the commit, provide the clean-version URL, fresh session URL, exact canonical prompt, and commit hash.

Never silently overwrite the latest released interface without advancing its version. Never commit a UI version before its zero-state loop passes.

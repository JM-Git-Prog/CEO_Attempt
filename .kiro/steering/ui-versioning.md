# UI Versioning and Commit Policy

For every user-visible page or interface change:

1. Increment the interface query version (`?v=N`).
2. Keep the preceding version accessible and behaviorally stable.
3. Make the newest version the default when no `v` is supplied.
4. Show clear links for switching between retained versions.
5. Validate the page, relevant API routes, and static JavaScript before completion.
6. Create a Git commit for the completed version, staging only relevant files.
7. Use commit titles in the form `feat(web): release vN interface` unless the change is strictly a fix.

Never silently overwrite the latest released interface without advancing its version.

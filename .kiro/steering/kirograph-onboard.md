---
inclusion: manual
---

# KiroGraph: Onboarding Workflow

Follow these steps to quickly understand a new codebase.

## Steps

1. **Project overview**
   ```
   kirograph_status()
   ```

2. **File structure**
   ```
   kirograph_files(format: "tree", maxDepth: 2)
   ```

3. **Key entry points**
   ```
   kirograph_hotspots(limit: 15)
   ```

4. **Architecture layers**
   ```
   kirograph_architecture()
   ```

5. **Explore a specific area**
   ```
   kirograph_context(task: "<area you want to understand>")
   ```

6. **Understand a key symbol**
   ```
   kirograph_node(symbol: "<symbol name>", includeCode: true)
   ```

## Tips
- Start broad (status, files, hotspots) then narrow down
- Use `kirograph_type_hierarchy` to understand inheritance patterns
- Use `kirograph_callees` on entry points to trace execution flow

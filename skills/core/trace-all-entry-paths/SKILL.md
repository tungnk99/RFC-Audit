---
name: trace-all-entry-paths
description: Enumerates every code path that reaches a protocol check and says which paths pass through it. Use when the RFC sentence says every received record or message, when a requirement of type D must hold on all paths, or when the verifier reported a missing path.
metadata:
  rfcv-task-types: TRACE_PATHS LOCATE
  version: "1"
---

# Trace all entry paths

A check found on one path proves nothing about the others.

1. Start from the target symbol and call `code__find_references` on it.
2. For each caller, record whether the check is inside the caller, before it, or absent on that route.
3. Function-pointer tables and dispatch arrays hide callers. When a reference has kind `fn_pointer`, or the
   caller is a table, use `code__explore` with `rg -n <function_name>` to find textual uses.
4. Walk upward until you reach an entry point of the adapter scope (for example the function that reads
   bytes from the socket). Keep the chain in `call_path`.
5. Every route that reaches the target without the check goes to `unexplored` or yields `MISMATCH`.
   Routes you did not finish before the budget ran low must be listed in `unexplored`; never imply
   completeness.
6. Report one `LocationClaim` per route class, not one claim that summarises all routes.

Stop when all entry points inside the scope are classified, or when about 20% of the budget remains.

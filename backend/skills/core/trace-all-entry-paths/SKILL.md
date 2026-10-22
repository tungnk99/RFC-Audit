---
name: trace-all-entry-paths
description: Enumerates the code paths along which the triggering input can reach the code that must enforce a requirement, and finds any path that bypasses the check. Use for TRACE_PATHS tasks, when the RFC sentence says every, all or any record or message, or when a location claim still has unexplored routes.
metadata:
  rfcv-task-types: TRACE_PATHS LOCATE
  version: "2"
---

# Trace all entry paths

A check found on one path proves nothing about the others. The question is narrow: can the triggering input (for example a
record from the network) reach further processing without passing the check?

## Procedure

1. **Fix the target**: the function and line of the check (from `task.recheck_location`, an earlier claim, or your own LOCATE).
2. **Find the entry points**: functions that receive the triggering input from outside. Start from `adapter.locator_hints`
   entry points (for example `ProcessReply`), or search for the read/receive calls of the protocol layer.
3. **Walk from each entry point downward** with `code__callees` and by reading the bodies, until you reach either the check or the
   code that consumes the input (decrypts, parses, hands it upward). Record each distinct route as a chain of function names.
4. **Watch for hidden routes**: function-pointer tables and dispatch arrays (a reference of kind `fn_pointer`, or a table name);
   early-return fast paths (for example a separate path for already-buffered data); version-specific branches (DTLS, TLS 1.2, TLS 1.3
   in different functions); `#if` alternatives (see `check-ifdef-compiled-lines`).
5. **Classify each route**: passes the check, or bypasses it (the input is consumed without the check), or not finished.

## Report

Return ONE `LocationClaim` (the output schema has room for one):
- `symbol`, lines and `call_path`: the check on the main route the trigger takes.
- the aspect the route question is about (usually `CONDITION`): `MATCH` if every finished route passes the check, `MISMATCH` if
  any finished route bypasses it; name the bypassing route in `note`.
- `unexplored`: every route you did not finish, by name, for example `"DoDtlsRecord → ProcessDtls (not read)"`. Never imply
  completeness: an empty `unexplored` means you classified every route you found.

Stop when every entry point in scope is classified, or when about 20% of the tool budget remains.

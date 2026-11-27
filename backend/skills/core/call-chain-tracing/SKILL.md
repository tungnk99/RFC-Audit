---
name: call-chain-tracing
description: Traces callers and callees of a function across several hops and shows the lines that use a given identifier. Use when a field check and its error reaction live in different functions, or when a call path must be confirmed.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS
  version: "1"
---

# Call-chain tracing (`code__call_chain`)

A check and the reaction to its failure often sit in different functions: a helper validates a field and returns an error
code, and a caller two or three hops up turns that code into the externally visible reaction. One `code__call_chain` call
shows these links together.

## Procedure

1. **Pick the anchor**: the function that holds the check, or the one that holds the reaction.
2. **Trace once**: `code__call_chain(symbol=<anchor>, direction="both", depth=2, filter_identifier=<name>)`.
   `filter_identifier` is a literal, case-sensitive substring: the field, variable, constant or error code under study.
   It returns up to 4 lines per function, preferring `if` / `switch` / `return` / comparison lines.
3. **Follow the value**:
   - the check returns an error code: use `direction="callers"` with that code as `filter_identifier` to find where it is
     tested or mapped to a reaction;
   - the anchor only dispatches: use `direction="callees"` to reach the function that tests the field.
   If the code is renamed or translated on the way, trace again with the new name. Raise `depth` to 3 only when the chain
   is still open at 2.
4. **Read before you conclude**: the matching lines are excerpts. Use `code__read` around the deciding branch to see the
   surrounding control flow and whether the lines are `[DISABLED]` under the build flags.
5. **Report**: build `call_path` (caller first) only from `caller -> callee` edges that were printed or that you saw in
   code you read. Cite only line numbers that a tool displayed.

## Limits

- The trace holds only calls recorded in the code index. Calls through function pointers or dispatch tables, and calls
  built by macros, can be missing: no edge does not prove there is no path. Search for them with `code__grep`.
- When several functions share a name, their edges may be merged, and only one definition is scanned for lines. Confirm
  which one applies.
- If the output reports a cut or that only some functions were scanned, narrow the direction or choose a closer anchor.
  Record any route you did not finish in `unexplored`.

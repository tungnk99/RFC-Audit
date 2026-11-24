---
name: locate-alert-sites
description: Globally scans and ranks all protocol error/alert/response-code emitting sites across multi-file network libraries without grep head_limit truncation. Use first whenever T3 reports WRONG_ALERT or REACTION_ABSENT on a large or multi-file codebase.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS
  version: "3"
---

# Global Protocol Reaction-Site Localization (`code__find_alert_sites`)

In large or multi-file C/C++ network protocol codebases, plain `code__grep` can truncate before reaching the active error-handling site or return noisy matches from `tests/` and `examples/`.

## Procedure

1. **Invoke `code__find_alert_sites` as your first step** when `behavior.diagnosis` reports a violation:
   - On `WRONG_ALERT` (wrong error/alert/response code): pass `alert` = the **observed wrong code** from `behavior.diagnosis.observed_alerts`, and `keywords` = the key terms from `requirement.structured` (e.g., field names, message/frame types, parameter names).
   - On `REACTION_ABSENT`: pass `alert` = the **expected code** from `requirement.structured.expect`, and `keywords` = the trigger/where terms, then read 80–100 lines above the earliest active site if the reaction was deleted or `#ifdef`-disabled.
2. **Inspect the ranked `#1..#8` slices** returned by `code__find_alert_sites`:
   - Every slice already includes its exact enclosing `[symbol: <name> (a–b)]`, `[DISABLED]` build-flag annotations, and counts as **already read** for SchemaGate.
   - **Syntax vs Negotiation/Finalization**: Under `WRONG_ALERT`, distinguish syntactic wire-length parsers from post-negotiation / finalization checks or internal error-to-reaction `switch` mappers.
   - **Initial vs Post-Handshake/Encrypted Stage**: When `requirement.structured.state == "initial"` (pre-handshake / plaintext input), **skip** header validators that only execute after session keys or handshake completion. Inspect the initial frame/record reader and its unknown-type or pre-negotiation branch.
   - **Early-Return Missing Reaction (`REACTION_ABSENT`)**: When `T3` observes no error code (`none`/`noerror`), do **not** submit a later `default:` branch that still emits the expected code (`REACTION = MATCH`). Inspect earlier `if` / pre-negotiation / early-return paths (e.g. `return -1` without invoking the reaction emitter) in the same function, and submit that exact early-return block with `REACTION = MISMATCH`.
   - Verify the top matching candidate with 1–2 short `code__read` calls (40–60 lines) if you need surrounding `if`/`switch` context, then submit `LocationClaim@1` immediately with `REACTION = MISMATCH`.

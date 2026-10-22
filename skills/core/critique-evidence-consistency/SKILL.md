---
name: critique-evidence-consistency
description: Checks the structured evidence of one requirement for gaps and contradictions and turns each finding into a typed critique issue. Use on every CRITIQUE task, especially before a COMPLIANT label is accepted or when the sufficiency report lists a conflict.
metadata:
  rfcv-task-types: CRITIQUE
  version: "1"
---

# Critique the evidence

You never decide a label and never dispatch work. You list problems; the planner turns each `kind` into the next task.
An empty `issues` list on a provisional `COMPLIANT` ends the investigation, so check every item below before returning it.
A false issue only costs budget; a missed one can let a wrong `COMPLIANT` through.

## What you can see

- `evidence.summary`: one row per evidence item.
  - T1 (code location): `finding`, `aspects[]` (`aspect`, `value` MATCH/MISMATCH/UNCLEAR, `observed`), `symbol`,
    `call_path`, `unexplored_count`.
  - T2 (static query): `validated`, `paths_examined`, `violating_paths`.
  - T3 (test run): `variant`, `variant_class`, `outcome`, `alert`, `closed`, `linked`.
- `verdict.sufficiency`: `provisional`, `missing[]` (`need`, `variant`), `conflicts[]`, `feasible`.
- `requirement.structured` (its type A–D), `rfc.sentence`, `rfc.paragraph`.

## Checks, in this order

| # | Signal | `kind` | `evidence_id` | `suggested_task` |
|---|---|---|---|---|
| 1 | An entry in `conflicts`, or a T3 with `outcome: PASS` while a T1 aspect is `MISMATCH`, or T3 `alert` differs from the T1 `REACTION.observed` (for example `send_alert(decode_error)` against alert `record_overflow`) | `CONTRADICTION` | the T1 | `RECHECK` |
| 2 | A T1 with `unexplored_count > 0`, or the RFC sentence says every / all / any received message or record and only one route is covered | `MISSING_PATH` | the T1 | `TRACE_PATHS` |
| 3 | `missing` has an item with `need: T3` | `MISSING_VARIANT` | none | `SELECT_TESTS` |
| 4 | No T1 at all; or a T1 lacks an aspect its type needs (A: CONDITION, THRESHOLD; B: + REACTION; C: ORDER_STATE, REACTION; D: EFFECT); or that aspect is `UNCLEAR`; or type D has no validated T2 | `MISSING_EVIDENCE` | the T1 if there is one | `LOCATE` (type D without T2: `STATIC_QUERY`) |
| 5 | The T1 symbol or call path clearly belongs to another protocol layer than the RFC section (for example a record-layer requirement located in a handshake message handler) | `WRONG_LOCATION` | the T1 | `LOCATE` |

Raise check 5 only when the names make it obvious. There is no component map yet, so a guess here sends the code
reader in the wrong direction.

## Rules for the output

- One issue per distinct problem. Do not repeat an issue for every T3 row of the same variant.
- `kind` and `suggested_task` are exact upper-case codes from the tables above; any other spelling is rejected.
- `evidence_id` is copied from `evidence.summary`. Never invent one; leave it empty when no single item is at fault.
- Skip an item whose `feasible` is `false`: the adapter cannot produce that evidence, asking again only burns budget.
- Return `issues: []` only after all five checks pass.

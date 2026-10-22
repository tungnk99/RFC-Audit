---
name: critique-evidence-consistency
description: A worked procedure for criticising the evidence of one requirement before a conclusion is accepted - how to read folded test rows and code locations, how to tell a real contradiction from noise, and when an issue has already been dealt with and must not be raised again. Use on every CRITIQUE task, especially before a COMPLIANT label is accepted or when the sufficiency report lists a conflict.
metadata:
  rfcv-task-types: CRITIQUE
  version: "3"
---

# Critique the evidence

You never decide a label and never dispatch work. You list problems; the planner turns each `kind` into the next task. An empty
`issues` list on a provisional `COMPLIANT` ends the investigation. A missed problem can let a wrong `COMPLIANT` through; a problem
raised without grounds, or raised again after it was handled, costs a whole investigation round and can loop.

## Reading the evidence

- `evidence.summary` has one row per evidence item, except that passing test runs differing only by `variant` are folded into one
  row (`count`, `evidence_ids[]`, `variant[]`). Failed, errored, inconsistent or linked runs, and anything the provisional label or a
  conflict cites, keep their own row. Use `evidence__read_summary` with `fold=false` to see every run when a fold hides something.
- A code location (T1) row has `finding`, `aspects[]` (`aspect`, `value` MATCH/MISMATCH/UNCLEAR, `observed`), `symbol`,
  `call_path`, `unexplored_count`.
- A test run (T3) row has `variant`, `variant_class` (required, control, random, valid_random), `outcome`, `alert`, `closed`, `linked`.
- `tasks.history` lists every dispatched task with its round, `new_evidence` and `failure`. The last `CRITIQUE` entry marks your
  previous review; anything after it was done in response to it.

## Checks, in this order

| # | Raise when | Do not raise when | `kind` | `evidence_id` | `suggested_task` |
|---|---|---|---|---|---|
| 1 | an entry in `conflicts`; or T3 on the violating side has `alert` different from the T1 `REACTION.observed`; or a T1 aspect is `MISMATCH` while every T3 passes | the differing alert is on a `control` or `valid` run (those must be accepted, no alert expected) | `CONTRADICTION` | the T1 | `RECHECK` |
| 2 | the T1 symbol or call path clearly belongs to another protocol layer than the RFC section, or the checked quantity differs from the `where` field | the names are ambiguous; there is no component map to settle it | `WRONG_LOCATION` | the T1 | `LOCATE` |
| 3 | the latest T1 has `unexplored_count > 0`; or the RFC sentence says every/all/any and no `TRACE_PATHS` has run | a `TRACE_PATHS` after the last `CRITIQUE` finished with `new_evidence > 0` and the latest T1 has `unexplored_count = 0` | `MISSING_PATH` | the T1 | `TRACE_PATHS` |
| 4 | `missing` has an item with `need: T3`; or no violating-side run near the limit exists while the label is COMPLIANT | `feasible.T3` is false | `MISSING_VARIANT` | none | `SELECT_TESTS` |
| 5 | no T1; or a T1 lacks an aspect its type needs (A: CONDITION, THRESHOLD; B: + REACTION; C: ORDER_STATE, REACTION; D: EFFECT); or that aspect is `UNCLEAR`; type D without validated T2 | `feasible.T1` is false | `MISSING_EVIDENCE` | the T1 if any | `LOCATE` (type D without T2: `STATIC_QUERY`) |

## Rules for the output

- One issue per distinct problem. Do not repeat an issue for every T3 row of the same variant.
- `kind` and `suggested_task` are exact upper-case codes from the table; any other spelling is rejected.
- `evidence_id` is copied from `evidence.summary` (for a folded row pick one of its `evidence_ids`). Never invent one; leave it
  empty when no single item is at fault.
- Return `issues: []` only after all five checks are done and none applies.

## Example

Provisional COMPLIANT (V5). T1 `ParseRecordHeader`, CONDITION and REACTION MATCH, THRESHOLD MATCH 16640, `unexplored_count = 0`.
T3: one folded PASS row (`count = 18`), boundary 16641 and max 65535 rows with `alert = record_overflow`, `closed = true`, linked.
`tasks.history`: round 1 SELECT_TESTS, LOCATE; round 2 CRITIQUE (you, raised MISSING_PATH); round 3 TRACE_PATHS with
`new_evidence = 1`. Check 3 does not apply any more (the route issue was handled and nothing is unexplored); checks 1, 2, 4, 5 find
nothing. Result: `issues: []`.

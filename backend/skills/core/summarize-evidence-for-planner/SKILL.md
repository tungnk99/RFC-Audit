---
name: summarize-evidence-for-planner
description: How to turn the verdict engine's sufficiency report, the task history and the last critique into the next dispatch - diagnosing what blocks a decisive label, why earlier tasks failed, and when to deviate from the playbook. Use at the start of every planning round.
metadata:
  version: "3"
---

# Plan from the evidence

The verdict engine, not you, decides whether evidence is enough and which label it supports. You decide what work would move the
investigation toward a decisive label most cheaply. The hub stops by itself when a label is decisive (and, for `COMPLIANT`, a
critique found nothing new), so you are only called while more work is needed.

## 1. Diagnose what blocks a decision

Read `verdict.sufficiency` and classify the situation. Use `verdict__read` for the rule catalogue if unsure.

| Situation | What it means | Work that resolves it |
|---|---|---|
| `missing` has `need: T3` items | required variants have not passed yet, or too few random samples | `SELECT_TESTS` with `missing_variants` from those items |
| `missing` has `need: T1` | no code location yet; the best label reachable is behavioral (V6) | `LOCATE` with the aspects of the requirement type |
| provisional `COMPLIANT`, no critique yet | hub requires one clean critique | `CRITIQUE` |
| `conflicts` not empty | code reading and test behaviour disagree | `CRITIQUE` first, then `RECHECK` on the aspect it names |
| tests pass but a T1 refutes (MISMATCH/ABSENT) | either the reading or the test is off | `CRITIQUE`, then `RECHECK` that aspect |
| tests pass, T1 exists, label is not V5 | the passing tests do not run through the cited lines (coverage not linked): the location is wrong or too narrow | `RECHECK` or a new `LOCATE`, not more tests |
| critique raised issues | the verifier found a concrete gap | the issue's suggested task (`FOLLOW_CRITIQUE`) |

## 2. Learn from the history

Read every entry of `tasks.history`:
- `failure` set (for example `UsageLimitExceeded`) or `new_evidence = 0`: the same task with the same parameters will very likely
  fail again. Change the approach: `start_hints = locator`, a `target_symbol`, fewer aspects, `RECHECK` instead of `LOCATE`.
- a task that ran after the last `CRITIQUE` addressed what that critique raised: critique again instead of repeating the task.
- the same task three times with no new evidence stops the run with `LOOP`.

## 3. Choose by value and cost

Typical cost per task: code reading (`LOCATE`, `TRACE_PATHS`, `RECHECK`) 100–300k tokens; `CRITIQUE` about 40k; `SELECT_TESTS`
about 10k. At most two tasks per round, and only independent ones together (find code + select tests). Check `budget.left`: with
little left, prefer the single task most likely to make the label decisive.

## 4. Compare with the playbook

Your prompt lists the playbook, generated from the domain's data. Follow it when it agrees with your diagnosis. Deviate when the
evidence or the history gives a concrete reason, and then set `rationale_code = DEVIATE_PLAYBOOK`.

## 5. Parameters and stopping

- Parameters come from data, never free text: `missing_variants` from `missing`, `evidence_id` and `aspect` from the critique or
  `conflicts`, `aspects` from the requirement type.
- Stop with `INFEASIBLE` only when, for every item in `missing`, `feasible[need]` is false. The hub rejects any other stop.
- Every dispatch carries a `rationale_code` from the fixed list.

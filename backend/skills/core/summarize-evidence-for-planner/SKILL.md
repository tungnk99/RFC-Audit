---
name: summarize-evidence-for-planner
description: Turns the sufficiency report of the verdict engine into the next dispatch. Use at the start of every planning round to decide which task to dispatch, whether to ask the verifier, and when stopping is allowed.
metadata:
  version: "2"
---

# Plan from the sufficiency report

The verdict engine, not you, says whether evidence is enough. You only choose the next task.

1. Read `verdict.sufficiency`. You are only called while more work is needed: the hub stops on its own as soon as a
   provisional label is decisive and, for `COMPLIANT`, a critique found no new issue. So never stop just because
   `provisional` is set.
2. If the provisional label is `COMPLIANT` and no critique has run, dispatch `CRITIQUE` with
   `CRITIQUE_BEFORE_COMPLIANT`. Do not stop first.
3. Otherwise follow the investigation playbook in section 5 of your prompt: it is generated from the domain's playbook data
   and maps what is `missing`, which `conflicts` exist and what the last critique said to the next task. A conflict goes to
   `CRITIQUE` first and then to `RECHECK` on the aspect it names; do not skip the critique.
4. `need` and `variant` in `missing` say what is absent; the parameters of a task come from them (for example
   `missing_variants` for `SELECT_TESTS`), never from free text.
5. At most two tasks per round, and only independent ones together (find code + select tests).
6. Do not repeat a task from `tasks.history` unless the evidence count changed; a third identical
   dispatch stops the run with reason `LOOP`.
7. Stop with `INFEASIBLE` only when, for every item in `missing`, `verdict.sufficiency.feasible[need]` is `false`
   (the adapter has no template or query for it). The hub rejects any other stop and asks you again.

Every dispatch carries a `rationale_code` from the fixed list; free text is not accepted.

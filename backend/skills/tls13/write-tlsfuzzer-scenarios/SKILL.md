---
name: write-tlsfuzzer-scenarios
description: How to build and debug a TLS 1.3 test scenario in the rfcv scenario DSL - reaching the precondition state, sending the trigger with a variant-bound value, checking it on the reference implementation with tester__run_scenario, and reading the probe result. Use for every SELECT_TESTS task on a TLS requirement of type A, B or C.
metadata:
  rfcv-task-types: SELECT_TESTS
  version: "3"
---

# Write and debug a TLS scenario

You choose structure; the harness computes the values from the variants and the compiled oracle judges each run. A scenario is
good when it reaches the trigger and exercises exactly the condition of the requirement, so that a correct implementation passes
and a faulty one fails for the right reason.

## Build

1. `tester__list_examples` for the requirement type; start from the closest template and set `example_id`.
2. Precondition: for state `connected` use `connect` then `complete_handshake`; for a trigger before or during the handshake use
   `connect` and the handshake messages up to that point.
3. Trigger: send exactly the thing named in `trigger` with the field from `where` bound to the variant, for example
   `{"op": "send_raw_record", "args": {"content_type": "application_data", "length": "$record.length", "body": "zeros", "encrypted": true}}`
   and `"bindings": {"record.length": "from_variant"}`. For the TLS 1.3 ciphertext limit the record must be a protected record
   (`encrypted: true`) after the handshake; an unprotected record tests something else.
4. End with one `expect` step using the `within_ms` of the requirement.

## Debug with the probe

`tester__run_scenario(scenario, variant)` runs one variant on a reference implementation and writes no evidence.

| Probe result | Meaning | Fix |
|---|---|---|
| `stage: validate` | DSL error | fix the step or argument named in `errors` |
| `reason: trigger_not_reached` | the steps before the trigger did not reach the state | fix the precondition steps; never drop the trigger |
| control variant `outcome: FAIL` | the reference rejects valid input: the scenario changes something besides the variant value | make the trigger well-formed except for the bound field |
| boundary variant, reference shows no expected alert | the trigger is not the condition the requirement is about | check record type, protection, and that the length really reaches the header |
| `reason: sanity_failed` or `environment_error` | environment problem, not your scenario | submit and say so |

Run the control variant first, then one violating-side variant. Then submit. Do not tune the scenario to make anything pass: the
probe is for debugging on the reference, not for predicting the result on the system under test.

## Coverage

Cover the missing variants first: `task.focus.missing_variants` when the planner names them, otherwise the `verdict.missing` items
with `need: T3`. You do not see code evidence or the provisional label; that is deliberate, so the test result stays independent of
the code reading.

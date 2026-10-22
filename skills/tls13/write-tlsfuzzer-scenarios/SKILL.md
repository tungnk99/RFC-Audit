---
name: write-tlsfuzzer-scenarios
description: Builds a scenario in the rfcv scenario DSL for a TLS requirement, reaching the connected state and then sending the trigger with a variant value. Use when selecting tests for a TLS 1.3 requirement of type A, B or C.
metadata:
  rfcv-roles: test
  rfcv-task-types: SELECT_TESTS
  version: "1"
---

# Write TLS scenarios

You only choose structure. The harness computes parameter values from the variant and the oracle judges
the outcome; never state expected pass or fail.

1. Reach the precondition from `requirement.rbs` `state`. For `connected` start with `connect` and
   `complete_handshake`; for a pre-handshake trigger use `connect` only.
2. Send the trigger with `send_raw_record`, `send_msg` or `mutate`. Put variant values behind a binding such
   as `$record.length` and declare it in `bindings` as `from_variant`.
3. End with exactly one `expect` step. Use the `within_ms` of the requirement.
4. Allowed operations are `connect`, `complete_handshake`, `send_msg`, `send_raw_record`, `mutate`,
   `reorder`, `repeat`, `expect`. Nothing else exists.
5. Start from the closest entry of `examples.similar_scenarios` and change as little as possible.
6. If a run reports `TRIGGER_NOT_REACHED`, fix the steps that lead to the state; do not remove the trigger.

Cover the missing variants first (`verdict.missing_variants`), including the control value equal to the limit,
which must be accepted.

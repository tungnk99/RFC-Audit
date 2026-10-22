---
name: write-ssh-scenarios
description: How to build and debug an SSH test scenario in the rfcv scenario DSL with the asyncssh backend - reaching the identification, key exchange or authenticated phase, sending a raw binary packet whose message number comes from the variant, shaping KEXINIT with mutate, and reading the probe result. Use for every SELECT_TESTS task on an SSH requirement.
metadata:
  rfcv-task-types: SELECT_TESTS
  version: "1"
---

# Write and debug an SSH scenario

There is no existing SSH conformance suite to wrap, so every scenario is written in the DSL.

## Build

1. `test__list_examples`: start from the closest DSL template and set `example_id`; read the `DSL` block for operations and values.
2. Reach the state of the requirement:
   - `version_exchanged`: `connect` only (TCP and identification strings).
   - `authenticating`: `connect`, then `complete_handshake` with `until: kex` (key exchange done, NEWKEYS exchanged).
   - `authenticated`: `connect`, then `complete_handshake` with `until: userauth`.
3. A message number from the variant: `{"op": "send_raw_record", "args": {"msg_number": "$msg.number", "body": "zeros",
   "encrypted": true}}` with `"bindings": {"msg.number": "from_variant"}`. After key exchange every packet is encrypted, so use
   `encrypted: true` from state `authenticating` on.
4. A shaped KEXINIT: `mutate` the field right before `{"op": "send_msg", "args": {"type": "kexinit"}}`, for example
   `kexinit.common_kex_count` bound to the variant (the runner fills the kex name-list with that many algorithms the server
   supports, and unknown names otherwise).
5. End with one `expect` using the `within_ms` of the requirement.

## Debug with the probe

| Probe result | Meaning | Fix |
|---|---|---|
| `stage: validate` | DSL error | fix the operation or argument named in `errors` |
| `reason: trigger_not_reached` | key exchange or authentication failed before the trigger | check the `until` phase and the server's algorithms |
| control variant closes the connection | the packet is invalid for another reason (unencrypted after kex, bad padding) | keep the packet valid apart from the bound field |
| boundary variant answered UNIMPLEMENTED, connection open | the server treats the number as unknown instead of out of phase | that is the observation; do not change the scenario to hide it |
| `reason: sanity_failed` or `environment_error` | environment problem | submit and say so |

Run the control variant first, then one violating-side variant, then submit.

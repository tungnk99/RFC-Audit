---
name: write-quic-scenarios
description: How to build and debug a QUIC test scenario in the rfcv scenario DSL with the aioquic backend - sending a raw Initial packet in a datagram whose size comes from the variant, completing the handshake before sending a frame, changing one frame field with mutate, and reading the probe result. Use for every SELECT_TESTS task on a QUIC requirement.
metadata:
  rfcv-task-types: SELECT_TESTS
  version: "1"
---

# Write and debug a QUIC scenario

## Build

1. `test__list_examples`: start from the closest DSL template and set `example_id`; read the `DSL` block for the packet types,
   frame types and arguments this backend accepts. Packet types (`packet_type`) and frame types (`type`) are different lists.
2. State `initial` (nothing established yet): only `connect`, then the trigger. State `connected`: `connect`, then
   `complete_handshake` (with the ALPN the server expects).
3. Datagram-size requirements: send one Initial with a valid ClientHello and pad the datagram to the variant size:
   `{"op": "send_raw_record", "args": {"packet_type": "initial", "datagram_length": "$datagram.payload_length", "body": "valid"}}`.
   The Initial must be valid apart from the size, otherwise the server drops it for another reason and every variant looks
   compliant.
4. Frame-field requirements: `mutate` the field right before the frame, then `send_msg` with the frame type:
   `{"op": "mutate", "args": {"field": "new_connection_id.length", "op": "set", "value": "$new_connection_id.length"}}`,
   `{"op": "send_msg", "args": {"type": "new_connection_id"}}`.
5. End with one `expect` using the `within_ms` of the requirement.

## Debug with the probe

| Probe result | Meaning | Fix |
|---|---|---|
| `stage: validate` | DSL error | fix the operation, argument or type named in `errors` |
| control variant (1200 bytes) gets no answer | the Initial is not valid (version, connection ID, ClientHello) | fix the base Initial before touching the size |
| `reason: trigger_not_reached` | handshake did not complete | check ALPN and version; never drop the trigger |
| frame variant answered with PROTOCOL_VIOLATION | the frame is invalid for another reason (for example a sequence number or an unused field) | keep every other field valid |
| `reason: sanity_failed` or `environment_error` | environment problem | submit and say so |

"No response within the window" is observed as `discard`; for a discard requirement that is the expected reaction, and the
control variant must get a response. Run the control first, then one violating-side variant, then submit.

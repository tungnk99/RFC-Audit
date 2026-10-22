---
name: write-http2-scenarios
description: How to build and debug an HTTP/2 test scenario in the rfcv scenario DSL with the h2spec backend - reaching the connected state with the connection preface and SETTINGS, opening a stream when a frame needs one, sending a raw frame whose header Length comes from the variant, and reading the probe result. Use for every SELECT_TESTS task on an HTTP/2 requirement.
metadata:
  rfcv-task-types: SELECT_TESTS
  version: "1"
---

# Write and debug an HTTP/2 scenario

## Build

1. `test__list_examples`: prefer a wrapped h2spec case whose limit matches the requirement; otherwise start from a DSL template.
   Read the `DSL` block for the operations and frame type names this backend accepts.
2. `connect` (cleartext h2c unless the SUT only serves TLS), then `complete_handshake`: the connection preface and SETTINGS
   exchange; after it the state is `connected`.
3. A DATA frame needs an open stream: send `{"op": "send_msg", "args": {"type": "headers", "stream_id": 1}}` first. Frames of the
   connection (SETTINGS, PING, GOAWAY, WINDOW_UPDATE on stream 0) do not.
4. Send the trigger as a raw frame with the header Length bound to the variant:
   `{"op": "send_raw_record", "args": {"type": "data", "stream_id": 1, "length": "$frame.length", "body": "zeros"}}` and
   `"bindings": {"frame.length": "from_variant"}`. The payload sent matches the length, so the frame is well formed except for
   its size.
5. End with one `expect` using the `within_ms` of the requirement.

## Debug with the probe

| Probe result | Meaning | Fix |
|---|---|---|
| `stage: validate` | DSL error | fix the operation, argument or frame type named in `errors` |
| `reason: trigger_not_reached` | preface or SETTINGS exchange failed | check `connect` (h2c or TLS) before changing the trigger |
| control variant gets PROTOCOL_ERROR or STREAM_CLOSED | the frame is invalid for another reason (no open stream, wrong stream id) | open the stream, use stream 0 only for connection frames |
| boundary variant accepted | the SUT advertised a larger SETTINGS_MAX_FRAME_SIZE, or the length did not reach the header | compare with the advertised setting, check the bound field |
| `reason: sanity_failed` or `environment_error` | environment problem | submit and say so |

A large DATA frame can also hit flow control (initial window 65535): a FLOW_CONTROL_ERROR on a big variant means the window, not
the frame size, was exceeded; say so when you submit. Run the control variant first, then one violating-side variant, then submit.

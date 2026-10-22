---
name: write-dns-scenarios
description: How to build and debug a DNS test scenario in the rfcv scenario DSL with the dnspython backend - choosing the transport, building a valid query and changing exactly one field with mutate, binding the variant value, and reading the probe result. Use for every SELECT_TESTS task on a DNS requirement.
metadata:
  rfcv-task-types: SELECT_TESTS
  version: "1"
---

# Write and debug a DNS scenario

DNS has no handshake: the server is in state `ready` as soon as the transport is chosen. A good scenario sends one well-formed
query that differs from a normal query only in the field the requirement is about, so the response code reflects that field.

## Build

1. `tester__list_examples`: start from the closest template (wrapped genreport case or DSL template) and set `example_id`. Read the
   `DSL` block of the result for the exact operations and argument values this backend accepts.
2. `connect` with `transport`: `udp` by default; `tcp` when the query can exceed 512 bytes (many OPT RRs, large options).
3. Change the field with `mutate` placed right before the message it applies to, binding the variant value:
   `{"op": "mutate", "args": {"field": "opt.version", "op": "set", "value": "$opt.version"}}` with
   `"bindings": {"opt.version": "from_variant"}`. For a count of records use `set` on the count field (for example `opt.count`).
4. `send_msg` with `type: query`, a name inside the test zone (`qname`) and a common type (`qtype`, for example SOA). A query for a
   name outside the zone can be answered REFUSED for an unrelated reason.
5. End with one `expect` using the `within_ms` of the requirement.

## Debug with the probe

| Probe result | Meaning | Fix |
|---|---|---|
| `stage: validate` | DSL error | fix the operation or argument named in `errors` |
| control variant answered with an error code | the query itself is wrong (zone, name, type) | make the base query one the server answers NOERROR |
| boundary variant answered NOERROR | the mutation did not reach the wire field | check the field name and that `mutate` precedes `send_msg` |
| `alert` is `refused` or `notimp` | the server rejected the query for a different reason | fix opcode, recursion flag or zone |
| `reason: sanity_failed` or `environment_error` | environment problem | submit and say so |

Run the control variant first, then one violating-side variant, then submit. The probe is for debugging on the reference, not for
predicting the result on the system under test.

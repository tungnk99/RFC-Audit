---
name: dns-edns-message-checks
description: Domain knowledge for EDNS(0) and DNS message validation in RFC 6891 (with RFC 1035 message format) - the OPT pseudo-RR layout, the extended RCODE that BADVERS needs, which malformed queries must get FORMERR, and where name servers implement parsing and the response code. Use when a requirement is about OPT RRs, EDNS version, FORMERR, BADVERS, or the response code a server returns to a malformed query.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS CRITIQUE
  version: "1"
---

# DNS EDNS(0) and message checks

## The OPT pseudo-RR (RFC 6891 §6.1)

| Field | Where it sits | Meaning |
|---|---|---|
| NAME | owner name | must be the root (empty name) |
| TYPE | RR type | 41 (OPT) |
| CLASS | the class field | requestor's UDP payload size; values below 512 are treated as 512 (§6.2.3) |
| TTL, upper 8 bits | the TTL field | EXTENDED-RCODE: upper 8 bits of the 12-bit response code |
| TTL, next 8 bits | the TTL field | VERSION; only version 0 is defined |
| TTL, low 16 bits | the TTL field | DO bit and Z (must be zero when sent) |
| RDATA | | options as {code, length, data} |

The full response code is `(EXTENDED-RCODE << 4) | header RCODE`. BADVERS is 16: header RCODE 0 and EXTENDED-RCODE 1, so it can
only be expressed in a response that carries an OPT RR. A server that sets only the 4-bit header field cannot answer BADVERS.

## The requirements and their reaction

| Sentence | Condition | Required reaction |
|---|---|---|
| 6891 §6.1.1 | a query with more than one OPT RR | FORMERR (RCODE 1) |
| 6891 §6.1.3 | VERSION higher than any level the server implements | BADVERS, in a response with an OPT RR |
| 6891 §7 | a badly formatted OPT RR (bad option layout, out-of-range values) | FORMERR |
| 6891 §7 | a server without EDNS receives an OPT RR | FORMERR and no OPT RR in the response |

RFC 1034, 1035 and 2181 predate BCP 14 and write "must" in lowercase. They define the message format and are context, not
normative sentences for this adapter.

## How servers implement it

- **Parse** first: the packet parser walks the four sections and usually remembers the OPT RR in a dedicated slot. A second OPT RR
  is typically rejected there with a generic "malformed" error code, not with an RCODE. Find where that error code is turned into
  FORMERR: the query processing layer maps parse failures to a response code, or drops the query. Dropping a malformed query is not
  "returning FORMERR": the REACTION is MISMATCH.
- **Version** is checked after parsing, in query processing: compare the VERSION field with the implemented level (a constant
  that is normally 0) and set the extended RCODE. Check that the response path then adds an OPT RR; otherwise BADVERS cannot
  reach the wire.
- **Transports**: UDP, TCP and, if compiled, encrypted transports (DoT, DoH, DoQ) can have separate receive entry points that
  share the parser. A check reached only from one transport covers only that transport.

## Judging the aspects

- CONDITION: counts OPT RRs in the additional section of a query (not every RR of type 41 anywhere), or reads the VERSION byte
  from the OPT TTL.
- THRESHOLD: more than one OPT RR; VERSION greater than the implemented level. A server that rejects exactly one OPT RR rejects
  valid queries: MISMATCH, stricter.
- REACTION: `respond(formerr)` or `respond(badvers)` is MATCH only if a response is built and sent with that code. A silent drop,
  SERVFAIL, or REFUSED is MISMATCH.

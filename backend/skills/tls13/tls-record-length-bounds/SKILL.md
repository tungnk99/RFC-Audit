---
name: tls-record-length-bounds
description: Domain knowledge for the TLS record length limits of RFC 8446 sections 5.1 and 5.2 (and their RFC 9846 successors) - which quantity is limited, the exact numbers, the required reaction, and where libraries implement the check and the alert. Use when a requirement is about record length, record_overflow, plaintext or ciphertext size, or when a threshold in TLS record code must be compared with the RFC.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS CRITIQUE
  version: "2"
---

# TLS record length bounds

## The limits

| Quantity | RFC limit | Where | Required reaction |
|---|---|---|---|
| TLSPlaintext.length (record before protection, and the inner plaintext after decryption) | 2^14 = 16384 | 8446 §5.1 | `record_overflow`, terminate |
| TLSCiphertext.length (length field of a protected record) | 2^14 + 256 = 16640 | 8446 §5.2 | `record_overflow`, terminate |
| TLS 1.2 TLSCiphertext.length (for comparison) | 2^14 + 2048 = 18432 | 5246 §6.2.3 | `record_overflow` |

The two TLS 1.3 limits are different requirements. A check on one is never evidence for the other: the header length check
covers 5.2; a check after decryption on the inner plaintext covers 5.1.

## How libraries implement it

- **Check**: in the record header parser, right after reading the 5-byte header and before allocating or decrypting. Often one
  shared constant for all versions, built as a base size plus "extra" room for MAC, padding and AEAD expansion. Compute it with
  `resolve-c-macro-thresholds`; a shared constant may be above 16640 (accepts over-long TLS 1.3 records) or below it (rejects
  valid ones).
- **Reaction**: usually NOT next to the check. The parser returns an error code (for example `LENGTH_ERROR`), and a caller maps
  error codes to alerts in a `switch` or a helper. Follow the code with `code__find_references` to that mapping, and check it with
  `check-ifdef-compiled-lines`: a mapping compiled out by a build flag means no alert at all.
- **Close**: `REACTION` is `MATCH` only if the alert is `record_overflow` AND processing of the connection stops (the error is
  returned up, the connection is marked closed or freed). An alert followed by continued processing is not enough.

## Record receive paths to trace

"An endpoint that receives a record" covers every route a record can arrive by. Typical routes in one library: the TLS stream
path (header parser, then decryption), the DTLS datagram path (separate header format and parser), early data (0-RTT) before the
handshake completes, and buffered or partially read records. A check on the TLS stream path says nothing about the DTLS parser.

## Judging the aspects for the 5.2 requirement

- CONDITION: the comparison reads the length field of the protected record (TLSCiphertext), and rejects when it is larger.
- THRESHOLD: computed limit equals 16640. Above: violation candidate. Below: stricter than the RFC (the control test at 16640
  fails); report `MISMATCH` and say "stricter" in `note`.
- REACTION: `send_alert(record_overflow)` reached on the error path, compiled, followed by termination.

Worked example with real-library numbers: [the reference](references/worked-example.md).

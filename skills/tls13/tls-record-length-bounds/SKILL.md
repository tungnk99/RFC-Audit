---
name: tls-record-length-bounds
description: Explains the TLS 1.3 record length limits of RFC 8446 sections 5.1 and 5.2 and how libraries usually implement them. Use when a requirement is about record length, record_overflow, plaintext or ciphertext size limits, or when a threshold in TLS record code needs to be compared with the RFC.
metadata:
  rfcv-roles: code_reader verifier
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS CRITIQUE
  version: "1"
---

# TLS record length bounds

There are two different limits. Never use one as evidence for the other.

| Record kind | RFC limit | Section | Required reaction |
|---|---|---|---|
| TLSPlaintext (before protection) | 2^14 = 16384 bytes | 5.1 | `record_overflow` |
| TLSCiphertext (protected) | 2^14 + 256 = 16640 bytes | 5.2 | `record_overflow`, then close |

Practical notes:
- Libraries often use one shared constant for all versions, built from a base size plus extra room for MAC,
  padding and AEAD expansion. Compute it (see `resolve-c-macro-thresholds`); a shared constant may sit above
  16384 and still satisfy 5.2 while violating 5.1.
- Check the reaction as well as the threshold. A correct limit that sends `decode_error` instead of
  `record_overflow` is a `REACTION` mismatch.
- The check normally lives in the record header parser, before any decryption. Look there first, then at the
  callers that read the header.
- Alert and close are two steps. `REACTION` is `MATCH` only when the code sends the alert and ends the
  connection.

Details and a worked example are in [the reference](references/worked-example.md).

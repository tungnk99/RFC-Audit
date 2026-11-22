---
name: locate-alert-sites
description: Globally scans and ranks all alert-emitting code sites across multi-file TLS libraries (OpenSSL, wolfSSL, GnuTLS, mbedTLS) without grep head_limit truncation. Use first whenever T3 reports WRONG_ALERT or REACTION_ABSENT on a large or multi-file codebase.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS
  version: "1"
---

# Global Alert-Site Localization (`code__find_alert_sites`)

In large or polymorphic TLS codebases (such as OpenSSL 3.x with 15+ files under `ssl/record/` and `ssl/statem/`, or wolfSSL's 48k-line `src/internal.c`), plain `code__grep` can truncate before reaching the active alert site or return noisy matches from `tests/` and `examples/`.

## Procedure

1. **Invoke `code__find_alert_sites` as your first step** when `behavior.diagnosis` reports a violation:
   - On `WRONG_ALERT`: pass `alert` = the **observed wrong alert** from `behavior.diagnosis.observed_alerts` (e.g. `"illegal_parameter"`, `"decode_error"`, `"handshake_failure"`), and `keywords` = the key terms from `requirement.structured` (e.g. `["key_share", "group", "client_hello"]`, `["content_type", "record"]`, `["record", "length", "tls13"]`).
   - On `REACTION_ABSENT`: pass `alert` = the **expected alert** from `requirement.structured.expect`, and `keywords` = the trigger/where terms, then read 80–100 lines above the earliest active site if the alert was deleted or `#ifdef`-disabled.
2. **Inspect the ranked `#1..#8` slices** returned by `code__find_alert_sites`:
   - Every slice already includes its exact enclosing `[symbol: <name> (a–b)]`, `[DISABLED]` build-flag annotations, and counts as **already read** for SchemaGate.
   - When localizing `client_hello.groups` (`no shared group`) under `WRONG_ALERT` (e.g. `decode_error`), distinguish syntactic extension parsers (which legitimately raise `decode_error` on malformed wire length) from post-negotiation / finalization checks (e.g. `final_key_share`, `TranslateErrorToAlert`, where `handshake_failure` is expected).
   - **Plaintext vs Encrypted Record Stage**: When `requirement.structured.state == "initial"` and the test varies `record.content_type` (plaintext record sent before handshake/encryption), **skip** encrypted TLS 1.3 record header validators (such as `tls13_validate_record_header`), which only run after handshake keys are installed. Inspect the plaintext record-layer reader (e.g. `rec_layer` / `ssl3_read_bytes` / `DoProcessReplyEx`) and check the branch handling unknown record types before version negotiation.
   - **Early-Return Missing Alert (`REACTION_ABSENT`)**: When `T3` observes `alert=none`, do **not** submit a later `default:` branch that still sends the expected alert (`REACTION = MATCH`). Inspect all earlier `if` / pre-version / `first_packet` error-return paths (e.g. `return -1` without calling `SSLfatal`/`SendAlert`) in the same function, and submit that exact early-return block with `REACTION = MISMATCH`.
   - Verify the top matching candidate with 1–2 short `code__read` calls (40–60 lines) if you need surrounding `if`/`switch` context, then submit `LocationClaim@1` immediately with `REACTION = MISMATCH`.

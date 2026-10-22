---
name: resolve-c-macro-thresholds
description: Computes the numeric value of a size or length limit in C code that is written with macros, enum constants, sizeof or build-dependent terms, and decides whether it matches, exceeds or falls short of the RFC limit. Use when judging the THRESHOLD aspect, or whenever a comparison uses names like MAX_RECORD_SIZE, MAX_MSG_EXTRA or RECORD_EXTRA.
metadata:
  rfcv-task-types: LOCATE RECHECK
  version: "2"
---

# Resolve a threshold to a number

A limit written as `MAX_RECORD_SIZE + MAX_MSG_EXTRA` tells you nothing until every name is a number. Libraries routinely build
limits from a base size plus "extra room" that depends on the build, so the name is the least reliable thing on the line.

## Procedure

1. **Isolate the comparison** that rejects the input, e.g. `if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA + (comp ? MAX_COMP_EXTRA : 0))`.
   Note the operator: `>` rejects values above the limit, `>=` rejects the limit itself (limit is effectively one lower).
2. **List every identifier** in the expression that is not a local variable.
3. **Resolve each one** with `code__get_definition`. Expect four shapes:
   - `#define NAME 16384` → a literal.
   - enum member `NAME = 38 + WC_MAX_DIGEST_SIZE,` → an expression; resolve its terms too.
   - definition inside `#if`/`#ifdef` with several alternatives → pick the branch the build flags select
     (see `check-ifdef-compiled-lines`). If the flags do not decide it, the value is unknown.
   - `sizeof(struct X)` or a size macro of a primitive (`MAX_DIGEST_SIZE`) → resolve from the definition; if it depends on which
     algorithms are compiled in, take the largest enabled one and say so in `note`.
4. **Handle conditional terms.** A term like `(usingCompression ? MAX_COMP_EXTRA : 0)` is 0 in the normal case when compression is
   off (TLS 1.3 has no compression). Use the value for the case the test exercises and mention the other in `note`.
5. **Write the arithmetic out** before concluding, e.g. `16384 + (38 + 64) + 0 = 16486`. Do not round, do not stop at a name.
6. **Compare with the RFC limit L** from the requirement's `where` clause. With rejection on `> T`:
   - `T == L` → `MATCH`.
   - `T > L` → `MISMATCH`: inputs between L+1 and T are accepted although the RFC requires rejecting them (candidate violation).
   - `T < L` → `MISMATCH`: valid inputs between T+1 and L are rejected (the implementation is stricter than the RFC; the control
     test at the limit will fail). Say "stricter" in `note`.
   - any term unknown → `UNCLEAR`, name the term in `unexplored`.
7. **Report** `observed` as the computed integer and cite the lines of the comparison (and of the definitions you displayed if they
   are in the same function). Never put a macro name in `observed`.

## Pitfalls

- The same constant often serves several protocol versions. Compare with the limit for the version and the quantity in scope:
  TLS 1.3 ciphertext 16640, TLS 1.3 plaintext 16384, TLS 1.2 ciphertext 2^14 + 2048 = 18432.
- A check on a *different* quantity (plaintext after decryption instead of the ciphertext length in the header) is a `CONDITION`
  problem, not a threshold problem. Settle CONDITION first.
- Two checks in sequence (a coarse one in the header parser, a precise one after decryption): the one that runs first for the
  triggering input decides the observed behaviour; report that one and mention the other in `note`.

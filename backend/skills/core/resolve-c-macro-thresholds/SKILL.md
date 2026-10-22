---
name: resolve-c-macro-thresholds
description: Computes the numeric value of a size, length or count limit in C code that is written with macros, enum constants, sizeof or build-dependent terms, and decides whether it matches, exceeds or falls short of the limit in the requirement. Use when judging the THRESHOLD aspect, or whenever a comparison uses named constants instead of literals.
metadata:
  rfcv-task-types: LOCATE RECHECK
  version: "3"
---

# Resolve a threshold to a number

A limit written as `MAX_PAYLOAD + EXTRA_ROOM` tells you nothing until every name is a number. Implementations routinely build
limits from a base size plus "extra room" that depends on the build, so the name is the least reliable thing on the line.

## Procedure

1. **Isolate the comparison** that rejects the input, e.g. `if (len > MAX_PAYLOAD + EXTRA_ROOM + (opt ? OPT_EXTRA : 0))`.
   Note the operator: `>` rejects values above the limit, `>=` rejects the limit itself (the limit is effectively one lower).
2. **List every identifier** in the expression that is not a local variable.
3. **Resolve each one** with `code__get_definition`. Expect four shapes:
   - `#define NAME 4096` → a literal.
   - enum member `NAME = 38 + MAX_DIGEST,` → an expression; resolve its terms too.
   - definition inside `#if`/`#ifdef` with several alternatives → pick the branch the build flags select
     (see `check-ifdef-compiled-lines`). If the flags do not decide it, the value is unknown.
   - `sizeof(struct X)` or a size that depends on which algorithms or features are compiled in → resolve from the definition; if it
     depends on the build, take the value for the build in scope and say so in `note`.
4. **Handle conditional terms.** A term like `(opt ? OPT_EXTRA : 0)` takes the value for the case the test exercises; mention the
   other case in `note`.
5. **Write the arithmetic out** before concluding, e.g. `4096 + (38 + 64) + 0 = 4198`. Do not round, do not stop at a name.
6. **Compare with the limit L** from the requirement's `where` clause. With rejection on `> T`:
   - `T == L` → `MATCH`.
   - `T > L` → `MISMATCH`: inputs between L+1 and T are accepted although the requirement says they must be rejected (candidate violation).
   - `T < L` → `MISMATCH`: valid inputs between T+1 and L are rejected (the implementation is stricter than the specification; the
     control test at the limit will fail). Say "stricter" in `note`.
   - any term unknown → `UNCLEAR`, name the term in `unexplored`.
7. **Report** `observed` as the computed integer and cite the lines of the comparison (and of the definitions you displayed if they
   are in the same function). Never put a macro name in `observed`.

## Pitfalls

- The same constant often serves several protocol versions or message kinds. Compare with the limit for the version and the
  quantity in scope; the adapter's protocol skill lists the exact numbers.
- A check on a *different* quantity (a length after decoding or decryption instead of the length field on the wire, a total size
  instead of a per-item size) is a `CONDITION` problem, not a threshold problem. Settle CONDITION first.
- Two checks in sequence (a coarse one early, a precise one later): the one that runs first for the triggering input decides the
  observed behaviour; report that one and mention the other in `note`.
- Units: bytes against octets is the same; bytes against elements, or bits against bytes, is not.

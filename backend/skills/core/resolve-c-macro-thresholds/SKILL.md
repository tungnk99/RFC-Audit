---
name: resolve-c-macro-thresholds
description: Resolves a numeric threshold in C code that is written with macros or constants before comparing it with the RFC value. Use when a length or size check uses names like MAX_RECORD_SIZE, MAX_MSG_EXTRA or sizeof expressions, or when judging the THRESHOLD aspect.
metadata:
  rfcv-task-types: LOCATE RECHECK
  version: "1"
---

# Resolve macro thresholds

Never judge `THRESHOLD` from the name of a constant. Compute the number.

1. Find the comparison (`if (size > A + B + C)`).
2. For every uppercase identifier in the expression call `code__get_definition`.
3. Expand nested definitions until only integer literals, `sizeof(...)` of fixed types, or build-flag
   dependent values remain. Write the arithmetic out, for example `16384 + 102 = 16486`.
4. If a term depends on a build flag (`#ifdef`, `#if defined`), look up the flag in `adapter.build_flags`.
   If the flag is not listed, report that aspect as `UNCLEAR`, not `MATCH`.
5. Compare the final number with the RFC value from the requirement. Report `MATCH` only on equality.
   A larger threshold than the RFC allows is `MISMATCH`, even when the code does reject larger inputs.
6. Put the computed number in `observed` (an integer), and cite only lines you displayed.

Edge cases:
- One threshold may serve several protocol versions. The RFC limit for the version in scope is the one to compare.
- Do not round. `16486` is not `16384`.

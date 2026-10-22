---
name: check-ifdef-compiled-lines
description: Decides whether a line of C code is really compiled under the build flags of the system under test. Use before citing a line that sits inside #ifdef, #if or #ifndef blocks, especially an alert or error reaction, because dead code gives a false MATCH.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS
  version: "1"
---

# Check that a cited line is compiled

A reaction such as `SendAlert(ssl, alert_fatal, record_overflow)` can exist in the source and still be
absent from the binary. Reading code without the build flags produces a wrong `MATCH`.

1. Before you cite a line, call `code__read_range` on the 30 lines above it and look for `#if`, `#ifdef`,
   `#ifndef`, `#elif`, `#else`, `#endif`.
2. List every enclosing condition, innermost first.
3. Evaluate each condition against `adapter.build_flags`. A macro that is neither defined by a flag nor
   visible as `#define` in a displayed file is unknown.
4. Outcomes:
   - all enclosing conditions are true: the line is compiled; cite it;
   - any condition is false: the line is not compiled; do not cite it, look for the `#else` branch instead;
   - any condition is unknown: report the aspect as `UNCLEAR` and name the macro in `unexplored`.
5. The deterministic gate rejects lines that coverage data shows were not compiled, so a wrong citation is
   discarded and costs you a retry.

Do not assume a flag is enabled because the feature name sounds standard.

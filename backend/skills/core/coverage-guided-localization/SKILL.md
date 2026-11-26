---
name: coverage-guided-localization
description: Uses real execution line-coverage hotspots (SBFL Ochiai via coverage__hotspots) to separate actually executed functions from unexecuted duplicate checks when localizing protocol defects.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS
  version: "1"
---

# Coverage-Guided Causal Localization (`coverage__hotspots`)

Large protocol codebases often contain multiple functions that check the same length limit, macro, or header field (for example, an early pre-accept entry point vs a later post-handshake handler). Static search alone cannot tell which function actually ran during the failing test.

## Procedure

1. **Check `code.coverage_hotspots` in context or call `coverage__hotspots(top_k=12)`** whenever:
   - Static search (`code__find_alert_sites` or `code__grep`) returns two or more plausible functions checking the same condition/macro, OR
   - The expected error/reaction call was deleted (`REACTION_ABSENT`) inside a long function.
2. **Prioritize functions that actually executed on failing runs (`fail > 0`)**:
   - Lines with high Ochiai score (`fail > 0, pass == 0` or `fail > 0`) are directly on the failing execution path.
   - **Never submit a function whose lines have 0 execution hits** when `coverage__hotspots` shows another candidate function actually executed on the failing test.
3. **Read 20–40 lines around the top executed hotspot** with `code__read` to confirm the exact `if`/`switch` condition and missing/wrong reaction, then submit `LocationClaim@1` with `MISMATCH`.
4. **If a threshold or length check was deleted** (so no wrong constant appears in the executed function), set `CONDITION` or `REACTION` to `MISMATCH` and keep `THRESHOLD` as `UNCLEAR` (`observed: null`) — never copy the expected threshold into `observed` with `MISMATCH`.

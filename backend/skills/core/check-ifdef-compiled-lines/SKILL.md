---
name: check-ifdef-compiled-lines
description: Decides whether a line of C code is part of the binary under the build flags of the system under test, so that dead code is never cited as a MATCH. Use before citing any check or reaction that sits inside #if, #ifdef, #ifndef or #elif blocks, and when a definition has alternatives under different flags.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS
  version: "2"
---

# Check that a cited line is compiled

`SendAlert(ssl, alert_fatal, record_overflow);` can sit in the source and be absent from the binary. A real wolfSSL bug was
exactly this: the alert for an over-long record was inside `#ifdef HAVE_MAX_FRAGMENT`, so default builds sent nothing.
Reading code without the build flags turns that into a false `MATCH`.

## Procedure

1. **Find every enclosing directive.** Read upward from the line until you reach the start of the function and, if needed,
   further. `code__read_function` page 1 lists first-level blocks of long functions; `code__explore` with
   `sed -n 'A,Bp' <file>` or `rg -n '^\s*#\s*(if|ifdef|ifndef|elif|else|endif)' <file>` shows directives between two lines.
   Track nesting: each `#endif` closes the most recent open `#if`; an `#else` flips the branch you are in.
2. **List the conditions innermost first**, as they apply to your line (inside an `#else`, the condition is the negation).
3. **Evaluate each one against `adapter.build_flags`**:
   - `-DNAME` or `--enable-x` that the project maps to `NAME` defines it; `--disable-x` undefines it.
   - `defined(A) && !defined(B)`, `#if A >= 3`: evaluate with the same rules; a macro set by a `#define` you displayed counts.
   - A macro not set by any flag and not defined in a displayed file is **unknown**, not "probably on".
4. **Decide:**
   - all conditions true → compiled; cite the line.
   - any condition false → not compiled; do not cite it. Look for the `#else` branch or another place that really runs. If no
     compiled code implements the reaction, that aspect is `MISMATCH` (the binary does not do it) and the dead line goes in `note`.
   - any condition unknown → `UNCLEAR`, put the macro name in `unexplored`.
5. The Schema gate also rejects cited lines that the index knows are not compiled (`LINES_NOT_COMPILED`); treat that as a hint to
   repeat steps 1–4, not as an error to work around.

## Example

```c
switch (ret) {
#ifdef HAVE_MAX_FRAGMENT
    case LENGTH_ERROR:
        SendAlert(ssl, alert_fatal, record_overflow);
        break;
#endif
    default:
        break;
}
```
Build flags `--enable-tls13 --disable-shared` do not define `HAVE_MAX_FRAGMENT`, and no displayed file defines it. The
`case LENGTH_ERROR` branch is not compiled; `LENGTH_ERROR` falls into `default`, which sends nothing. `REACTION` is `MISMATCH`, cite the
`switch` and `default` lines, and note the dead branch.

Do not assume a flag is enabled because the feature name sounds standard.

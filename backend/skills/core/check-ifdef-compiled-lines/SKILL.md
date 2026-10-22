---
name: check-ifdef-compiled-lines
description: Decides whether a line of C code is part of the binary under the build flags of the system under test, so that dead code is never cited as a MATCH. Use before citing any check or reaction that sits inside #if, #ifdef, #ifndef or #elif blocks, and when a definition has alternatives under different flags.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS
  version: "3"
---

# Check that a cited line is compiled

A reaction such as `send_error(conn, ERR_TOO_LONG)` can sit in the source and be absent from the binary. Feature flags guard
whole branches of protocol code, and a reaction compiled out by a flag the build does not set means the binary does not react
at all. Reading code without the build flags turns that into a false `MATCH`.

## Procedure

1. **Find every enclosing directive.** Read upward from the line until you reach the start of the function and, if needed,
   further. `code__read_function` page 1 lists first-level blocks of long functions; `code__explore` with
   `sed -n 'A,Bp' <file>` or `rg -n '^\s*#\s*(if|ifdef|ifndef|elif|else|endif)' <file>` shows directives between two lines.
   Track nesting: each `#endif` closes the most recent open `#if`; an `#else` flips the branch you are in.
2. **List the conditions innermost first**, as they apply to your line (inside an `#else`, the condition is the negation).
3. **Evaluate each one against `adapter.build_flags`**:
   - `-DNAME` defines `NAME`; a configure option such as `--enable-x` or `--disable-x` defines or undefines the macro the project
     maps it to (check the project's configure or CMake mapping when it matters).
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
#ifdef HAVE_LARGE_MESSAGES
    case ERR_TOO_LONG:
        send_error(conn, ERR_CODE_TOO_LONG);
        break;
#endif
    default:
        break;
}
return ret;
```
The build flags do not define `HAVE_LARGE_MESSAGES` and no displayed file defines it. The `case ERR_TOO_LONG` branch is not
compiled; the error falls into `default`, which sends nothing. The reaction aspect is `MISMATCH`: cite the `switch` and `default`
lines and name the dead branch in `note`.

Do not assume a flag is enabled because the feature name sounds standard.

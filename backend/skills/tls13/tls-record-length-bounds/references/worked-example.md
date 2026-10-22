# Worked example: threshold and reaction

Setting: a library whose header parser contains

```c
if (*size > (MAX_RECORD_SIZE + MAX_MSG_EXTRA)) { ... return LENGTH_ERROR; }
```

with `MAX_RECORD_SIZE = 16384` and `MAX_MSG_EXTRA = 38 + WC_MAX_DIGEST_SIZE`, where the digest size is 64.

1. `MAX_MSG_EXTRA = 38 + 64 = 102`.
2. Threshold in code: `16384 + 102 = 16486`.
3. Requirement 5.2 (ciphertext): limit 16640. The code rejects at 16486, which is below 16640. `THRESHOLD` is
   `MISMATCH` for 5.2 in the strict reading, but the behaviour is stricter than the RFC, so report it and
   let the oracle decide. The test result, not this reading, sets the label.
4. Requirement 5.1 (plaintext): limit 16384. The code accepts 16385 through 16486, so `THRESHOLD` is
   `MISMATCH` and this is a candidate violation.
5. Reaction: find where `LENGTH_ERROR` is handled and what alert it maps to. If the alert call sits inside
   an `#ifdef` that the build flags disable, the reaction is not present in the tested binary (see
   `check-ifdef-compiled-lines`).

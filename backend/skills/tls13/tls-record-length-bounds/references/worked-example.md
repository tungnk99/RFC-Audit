# Worked example: a real library, two releases

Setting: a TLS library whose record header parser contains

```c
#ifdef HAVE_MAX_FRAGMENT
    if (*size > (ssl->max_fragment + MAX_MSG_EXTRA + (ssl->options.usingCompression ? MAX_COMP_EXTRA : 0)))
        return LENGTH_ERROR;
#else
    if (*size > (MAX_RECORD_SIZE + MAX_MSG_EXTRA + (ssl->options.usingCompression ? MAX_COMP_EXTRA : 0)))
        return LENGTH_ERROR;
#endif
```

with `#define MAX_RECORD_SIZE 16384` and the enum member `MAX_MSG_EXTRA = 38 + WC_MAX_DIGEST_SIZE`.

## Threshold

1. Build flags do not define `HAVE_MAX_FRAGMENT`, so the `#else` branch is compiled.
2. Compression is off in TLS 1.3, so the conditional term is 0.
3. `WC_MAX_DIGEST_SIZE` is the largest enabled digest: 64 if SHA-512 is compiled in, 48 for SHA-384, 32 for SHA-256 only. With 64:
   `MAX_MSG_EXTRA = 38 + 64 = 102`, threshold `16384 + 102 + 0 = 16486`.
4. Requirement 5.2 (ciphertext, limit 16640): the code rejects from 16487, below the limit. `THRESHOLD` is `MISMATCH`, stricter
   than the RFC: valid records of 16487–16640 bytes are refused. `observed = 16486`, `note` says "stricter".
5. Requirement 5.1 (plaintext, limit 16384): this header check does not test the plaintext; look for the check after decryption.

## Reaction, before and after a fix

Release A, in the caller that maps error codes:
```c
switch (ret) {
#ifdef HAVE_MAX_FRAGMENT
    case LENGTH_ERROR: SendAlert(ssl, alert_fatal, record_overflow); break;
#endif
    default: break;
}
return ret;
```
`HAVE_MAX_FRAGMENT` is not defined, so `LENGTH_ERROR` reaches `default`: no alert is sent, the error is returned. `REACTION` is
`MISMATCH` (the binary does not send `record_overflow`).

Release B (the fix): the `#ifdef` around `case LENGTH_ERROR` is removed. The alert is compiled and the error is returned, so the
connection stops. `REACTION` is `MATCH`, `observed = send_alert(record_overflow)`.

The test results, not this reading, decide the label; this reading tells the investigation where to look and lets coverage link
the passing test to the right lines.

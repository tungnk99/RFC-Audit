---
name: ssh-transport-and-auth-errors
description: Domain knowledge for the SSH transport and authentication protocols (RFC 4253, RFC 4252) - message number ranges and which messages are allowed in which phase, key exchange negotiation failure, SSH_MSG_UNIMPLEMENTED and SSH_MSG_DISCONNECT with its reason codes, packet size limits, and where servers implement message dispatch. Use when a requirement is about disconnecting, unexpected or unrecognized messages, algorithm negotiation, or packet and identification string format.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS CRITIQUE
  version: "1"
---

# SSH transport and authentication errors

## Message numbers (RFC 4250 allocation, used by RFC 4252/4253)

| Range | Used by |
|---|---|
| 1-19 | transport generic (DISCONNECT 1, IGNORE 2, UNIMPLEMENTED 3, DEBUG 4, SERVICE_REQUEST 5, SERVICE_ACCEPT 6) |
| 20-29 | algorithm negotiation (KEXINIT 20, NEWKEYS 21) |
| 30-49 | key exchange method specific |
| 50-79 | user authentication (50-59 generic, 60-79 method specific) |
| 80-127 | connection protocol |
| 128-191 | reserved for client protocols |
| 192-255 | local extensions |

Rules that use these ranges:
- Before authentication completes, a message number of 80 or higher is an error and the server MUST disconnect, preferably with
  a proper SSH_MSG_DISCONNECT (RFC 4252 §6). The MUST is the disconnect; the message is recommended.
- An implementation MUST answer every unrecognized message with SSH_MSG_UNIMPLEMENTED, in order (RFC 4253 §11.4). "Unrecognized"
  depends on what the implementation supports and on the phase, so a requirement on it needs care with the valid side.

## Key exchange negotiation (RFC 4253 §7.1)

Each name-list in KEXINIT is matched by taking the first algorithm on the client's list that the server also supports. If no
algorithm can be chosen for kex, host key, cipher, MAC or compression, the connection fails and both sides MUST disconnect.

## Disconnect (RFC 4253 §11.1)

SSH_MSG_DISCONNECT carries a reason code: 1 HOST_NOT_ALLOWED_TO_CONNECT, 2 PROTOCOL_ERROR, 3 KEY_EXCHANGE_FAILED, 4 RESERVED,
5 MAC_ERROR, 6 COMPRESSION_ERROR, 7 SERVICE_NOT_AVAILABLE, 8 PROTOCOL_VERSION_NOT_SUPPORTED, 9 HOST_KEY_NOT_VERIFIABLE,
10 CONNECTION_LOST, 11 BY_APPLICATION, 12 TOO_MANY_CONNECTIONS, 13 AUTH_CANCELLED_BY_USER, 14 NO_MORE_AUTH_METHODS_AVAILABLE,
15 ILLEGAL_USER_NAME.

## Packets (RFC 4253 §6)

`packet_length` (uint32), `padding_length` (byte), payload, random padding of at least 4 bytes, MAC. Implementations MUST accept an
uncompressed payload of 32768 bytes and a total packet of 35000 bytes; they SHOULD check that the packet length is reasonable.

## How servers implement it

- A dispatch table maps message numbers to handlers and is replaced per phase (key exchange, authentication, connection). Numbers
  without a handler go to a default handler: either "send UNIMPLEMENTED" or "protocol error, disconnect". Find which default is
  installed in the pre-authentication phase, and whether a range check rejects numbers >= 80 before dispatch.
- Negotiation failure is detected in the function that matches name-lists; it returns an error that the caller turns into a
  disconnect (often with KEY_EXCHANGE_FAILED) or a plain close.

## Judging the aspects

- CONDITION / ORDER_STATE: the check must depend on the phase (authenticated or not), not only on the number.
- THRESHOLD: 80 for the pre-authentication rule.
- REACTION: `close` is the required part; `send_disconnect(<reason>)` before it is recommended. A handler that answers
  UNIMPLEMENTED and keeps the connection open does not meet the 80-or-higher rule.

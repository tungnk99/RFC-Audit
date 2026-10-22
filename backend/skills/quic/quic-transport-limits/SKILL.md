---
name: quic-transport-limits
description: Domain knowledge for QUIC v1 transport limits and error handling in RFC 9000 - the 1200-byte rule for datagrams carrying Initial packets and what a server must do with smaller ones, frame field limits such as the connection ID length in NEW_CONNECTION_ID, how a connection error is signalled with CONNECTION_CLOSE, and where implementations check them. Use when a requirement is about datagram size, Initial packets, frame encoding errors, transport error codes, or closing a connection.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS CRITIQUE
  version: "1"
---

# QUIC transport limits

## Datagram size and Initial packets (RFC 9000 §8.1, §14.1)

- A client must pad every UDP datagram that carries an Initial packet to a payload of at least 1200 bytes.
- A server must discard an Initial packet carried in a datagram whose UDP payload is smaller than 1200 bytes (§14.1). Discard means
  no response of any kind to that datagram: no Initial, Handshake, Retry or Version Negotiation packet. Responding would break the
  anti-amplification limit (a server sends at most three times what it received before the client address is validated).
- The quantity is the UDP payload length of the whole datagram, not the length of one QUIC packet inside it (a datagram may
  coalesce several packets). A check on the packet length is a different, weaker condition.

## Frame field limits (examples)

| Frame | Field | Valid | Error |
|---|---|---|---|
| NEW_CONNECTION_ID | Length | 1 to 20 | FRAME_ENCODING_ERROR (§19.15) |
| NEW_CONNECTION_ID | Retire Prior To | not greater than Sequence Number | FRAME_ENCODING_ERROR |
| MAX_STREAMS | Maximum Streams | at most 2^60 | FRAME_ENCODING_ERROR (§19.11) |
| any | unknown frame type | | FRAME_ENCODING_ERROR (§12.4) |

Field limits are often checked while decoding the frame (the decoder returns a generic decode error) and translated into a
transport error code later. Follow the decoder's return value to the place that picks the error code.

## Signalling a connection error (§10.2, §11.1)

An error that makes the connection unusable is signalled with a CONNECTION_CLOSE frame of type 0x1c carrying the transport error
code, after which the endpoint enters the closing state and stops processing. Closing silently (idle timeout, dropping state) does
not signal the code. Some errors allow a choice of codes ("FRAME_ENCODING_ERROR or FLOW_CONTROL_ERROR"); the RBS then lists the
alternatives.

## Judging the aspects

- CONDITION: for the 1200-byte rule, the comparison reads the received datagram size on the server's Initial path (often in the
  function that accepts a new connection); for a frame field, the decoded field value.
- THRESHOLD: `< 1200` for datagrams; `> 20` and `< 1` for the connection ID length. The constant is often a shared minimum
  datagram size; compute it.
- REACTION: for the datagram rule, `discard`: the function returns without building any packet and without creating connection
  state that later sends. For frame errors, `send_connection_close(<code>)` with the right code, followed by the closing state.

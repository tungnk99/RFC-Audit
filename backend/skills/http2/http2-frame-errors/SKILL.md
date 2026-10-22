---
name: http2-frame-errors
description: Domain knowledge for HTTP/2 frame validation and error handling in RFC 9113 - frame size limits and SETTINGS_MAX_FRAME_SIZE, frame types with a fixed length, the difference between stream and connection errors, what GOAWAY and closing the connection require, and where implementations check frames. Use when a requirement is about frame length, FRAME_SIZE_ERROR, PROTOCOL_ERROR, GOAWAY, RST_STREAM, or how a frame error must be reported.
metadata:
  rfcv-task-types: LOCATE RECHECK TRACE_PATHS CRITIQUE
  version: "1"
---

# HTTP/2 frame errors

## Frame size

Every frame starts with a 9-octet header: Length (24 bits, payload only), Type (8), Flags (8), reserved bit, Stream Identifier
(31). The payload limit is the receiver's SETTINGS_MAX_FRAME_SIZE: initially 2^14 = 16384; an endpoint may advertise any value
from 16384 to 2^24 - 1 = 16777215 (§6.5.2). Until the server has advertised a larger value AND the peer has seen it, the limit is
16384. A frame larger than the limit, larger than a limit of its frame type, or too small for its mandatory fields gets
FRAME_SIZE_ERROR (§4.2).

Frame types with a fixed payload length (each a FRAME_SIZE_ERROR otherwise):

| Type | Length | Error kind |
|---|---|---|
| PRIORITY | 5 | stream error |
| RST_STREAM | 4 | connection error |
| SETTINGS | multiple of 6; 0 with ACK | connection error |
| PING | 8 | connection error |
| WINDOW_UPDATE | 4 | connection error |

## Stream error or connection error

- Stream error (§5.4.2): send RST_STREAM with the error code; the connection stays open.
- Connection error (§5.4.1): SHOULD send GOAWAY with the error code and the last processed stream id, then MUST close the TCP
  connection. GOAWAY is recommended, closing is mandatory. An implementation that closes without GOAWAY still meets the MUST.
- A frame size error in a frame that can change connection state (HEADERS, PUSH_PROMISE, CONTINUATION, SETTINGS, any frame on
  stream 0) must be a connection error (§4.2). Any stream error may be escalated to a connection error.

## How implementations check frames

- The frame reader parses the header, then compares Length with the local max frame size before reading the payload. Look for the
  constant and the setting variable: they differ (a constant default and a negotiated value). Check which one the comparison
  reads and when the negotiated value starts applying.
- Per-type length checks live in the frame unpacking code or in the per-type receive handler.
- The reaction is usually a function that terminates the session with an error code (writes GOAWAY, marks the session to close)
  or a function that submits RST_STREAM. Follow the error code returned by the check to that call.

## Judging the aspects

- CONDITION: the comparison reads the Length field of the frame header (or the payload length of a fixed-length type).
- THRESHOLD: compare with the setting actually in force; 16384 unless the server advertised more. A constant above that accepts
  over-long frames; a smaller one rejects valid frames.
- REACTION: `send_goaway(frame_size_error)` or `send_rst_stream(frame_size_error)` with the right code. For a connection error the
  connection must also be closed; for a frame that must be ignored or answered (PING ACK), check that the error path skips it.

# Decision: Connect Streaming Frame Parser

Status: proposed

## Problem
envd API uses Connect protocol with Server-Streaming responses in NDJSON format. Need a parser that handles streaming frames efficiently.

## Decision
`ConnectStreamReader` in `transport/streaming.py`:
- Parse `application/connect+json` streaming responses
- Yield typed frames via `AsyncIterator`
- Backpressure via `asyncio.Queue(maxsize)` to prevent memory overflow
- Handle incomplete frames at chunk boundaries
- Support both data frames and end-of-stream frames with optional error/trailer

Frame format: newline-delimited JSON objects, each containing `result` or `error` field.

## Alternatives considered
- **Read entire response** — Cannot handle long-running processes with streaming output
- **SSE (Server-Sent Events)** — E2B protocol uses Connect, not SSE

## Dependencies
- `transport/http.py` for underlying HTTP streaming
- `transport/codec.py` for JSON encoding/decoding (orjson optional)

## Test Strategy
- Frame parsing with known payloads
- Incomplete frame handling at chunk boundaries
- Backpressure behavior when consumer is slow
- Error frame propagation

## Acceptance criteria
- Can parse streaming process output in real-time
- Memory-bounded via queue maxsize
- Correctly handles split frames across HTTP chunks

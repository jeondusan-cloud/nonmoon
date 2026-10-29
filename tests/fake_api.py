"""A stand-in for the Claude API that speaks the real wire format.

The Anthropic SDK sends its real HTTP requests to ``httpx2.MockTransport``;
``FakeAPI`` records each request body and answers with a server-sent-event
stream holding a JSON reply chosen by the request's output schema. This
checks that the pipeline's request parameters survive the SDK unchanged.
"""

from __future__ import annotations

import json

import anthropic
import httpx2


def _sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in events).encode()


def stream_body(text: str, stop_reason: str = "end_turn", usage: dict | None = None) -> bytes:
    usage = usage or {"input_tokens": 1200, "output_tokens": 800, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {**usage, "output_tokens": 1},
    }
    return _sse(
        [
            ("message_start", {"type": "message_start", "message": message}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": usage},
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


class FakeAPI:
    def __init__(self, replies):
        """``replies(schema_keys, body) -> (json_text, stop_reason)``."""
        self.replies = replies
        self.requests: list[dict] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.requests.append({"headers": dict(request.headers), "body": body})
        schema = body["output_config"]["format"]["schema"]
        text, stop = self.replies(tuple(sorted(schema["properties"])), body)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=stream_body(text, stop))

    def client(self) -> anthropic.Anthropic:
        transport = httpx2.MockTransport(self.handler)
        return anthropic.Anthropic(api_key="test-key", http_client=anthropic.DefaultHttpxClient(transport=transport))

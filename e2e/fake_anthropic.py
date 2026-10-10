"""A tiny stand-in for the Anthropic Messages API, for end-to-end tests only.

Run:  python e2e/fake_anthropic.py 8901   then start Locuvi with ANTHROPIC_BASE_URL=http://127.0.0.1:8901
It never calls the real API. Booking requests (structured output) get a fixed proposal;
agent requests (tools) first call get_overview + find_uninvoiced_sessions, then answer.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def message(content, stop="end_turn"):
    return {"id": "msg_fake", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": stop, "stop_sequence": None, "content": content,
            "usage": {"input_tokens": 1, "output_tokens": 1}}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802  (model list: "Check key" in Settings)
        assert self.headers.get("x-api-key"), "API key header expected"
        out = {"data": [{"type": "model", "id": m, "display_name": m, "created_at": "2026-01-01T00:00:00Z"}
                        for m in ("claude-opus-5-5", "claude-sonnet-5-5")],
               "has_more": False, "first_id": None, "last_id": None}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        assert self.headers.get("x-api-key"), "API key header expected"
        assert body.get("fallbacks") == "default"
        if "tools" not in body:  # booking reader
            booking = {"summary": "Two sessions at Example Medical Practice.", "questions": [],
                       "items": [{"date": d, "unit": u, "hours": None, "practice_id": None,
                                  "practice_name": "Example Medical Practice", "rate": "640.00",
                                  "action": "add", "note": None}
                                 for d, u in (("2026-12-01", "am"), ("2026-12-02", "pm"))]}
            out = message([{"type": "text", "text": json.dumps(booking)}])
        elif isinstance(body["messages"][-1]["content"], str):  # new question
            out = message([
                {"type": "thinking", "thinking": "", "signature": "fake-signature"},
                {"type": "tool_use", "id": "tu_1", "name": "get_overview", "input": {}},
                {"type": "tool_use", "id": "tu_2", "name": "find_uninvoiced_sessions", "input": {}},
            ], stop="tool_use")
        else:  # tool results came back
            results = body["messages"][-1]["content"]
            assert all(r["type"] == "tool_result" for r in results)
            assert body["messages"][-2]["content"][0]["signature"] == "fake-signature"
            out = message([{"type": "text", "text":
                            "Here's where things stand:\n- Nothing is overdue.\n- Your records look up to date."}])
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()

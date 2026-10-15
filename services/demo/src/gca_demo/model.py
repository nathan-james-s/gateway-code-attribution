"""demo-model: a keyless stand-in for model providers (T056; FR-038).

Serves the four provider APIs in their real streaming formats, writing the body in small chunks (default 7
bytes) so gateways see SSE lines and UTF-8 sequences split across writes. Requests marked by `gca demo run`
get that session step's tool call; requests marked by `--inject-faults` get a broken stream (T092); anything
else gets a short text reply. Request bodies are not logged.
"""

from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .sessions import FAULTS, fault_call, parse_fault, parse_marker, sessions, tool_calls
from .streams import render, render_fault

CHUNK = int(os.environ.get("GCA_DEMO_CHUNK", "7"))
_GEMINI = re.compile(r"^/v1beta/models/([^/:]+):(streamGenerateContent|generateContent)")


def route(path: str) -> str | None:
    p = path.split("?", 1)[0]
    if p.endswith("/chat/completions"):
        return "openai_chat"
    if p.endswith("/responses"):
        return "openai_responses"
    if p.endswith("/messages"):
        return "anthropic_messages"
    if _GEMINI.search(p) or ":streamGenerateContent" in p or ":generateContent" in p:
        return "gemini_native"
    return None


def _wants_stream(api_format: str, path: str, body: str) -> bool:
    if api_format == "gemini_native":
        return ":streamGenerateContent" in path
    try:
        return bool(json.loads(body).get("stream"))
    except (ValueError, AttributeError):
        return False


def respond(api_format: str, path: str, body: str) -> tuple[str, bytes, bool]:
    fault = parse_fault(body)
    if fault is not None and FAULTS[fault[0]] == api_format and _wants_stream(api_format, path, body):
        ctype, data = render_fault(fault[0], fault_call(fault[1]))
        return ctype, data, True
    mark = parse_marker(body)
    calls = []
    if mark is not None:
        session = sessions().get(mark[0])
        if session is not None and 0 <= mark[1] < len(session.steps):
            calls = tool_calls(session.steps[mark[1]], f"call_{mark[0]}_{mark[1]}")
    stream = _wants_stream(api_format, path, body)
    ctype, data = render(api_format, calls, stream=stream)
    return ctype, data, stream


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:
        return

    def do_GET(self) -> None:
        data = b'{"status":"ok"}'
        self.send_response(200 if self.path in ("/healthz", "/") else 404)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        api_format = route(self.path)
        if api_format is None:
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        ctype, data, stream = respond(api_format, self.path, body)
        self.send_response(200)
        self.send_header("content-type", ctype)
        if not stream:
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_header("cache-control", "no-cache")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        for i in range(0, len(data), CHUNK):
            c = data[i : i + CHUNK]
            self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
            self.wfile.flush()
            time.sleep(0.0005)
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


def main() -> None:
    port = int(os.environ.get("GCA_DEMO_PORT", "8080"))
    sessions()  # fail fast on a bad session file
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Record a real-traffic corpus (T111; FR-045, SC-011). A standalone developer tool, never part of a deployed
service: the stack itself must never persist model output (Constitution II), and no image or chart contains this
file (scripts/check-no-recorder.sh checks both).

Run it on your own machine, between your coding tool and the gateway, while you do the scripted tasks in
eval/corpus/tasks.md. It forwards every request and response unchanged and, for model responses (HTTP 2xx on a
model route), also writes the raw response body as the tool received it to

    eval/corpus/<tool>/<api_format>/<n>.sse

Requests are never written. Recording refuses to start without eval/corpus/<tool>/consent.yaml naming you as
the owner who consents; `--owner NAME --i-consent` writes it. Only synthetic tasks belong in the corpus.

    python eval/corpus/record.py --tool claude-code --owner "Your Name" --i-consent   # once
    python eval/corpus/record.py --tool claude-code                                    # then point the tool at :4100

Standard library only, so it runs with any Python 3.12.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import http.client
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
TOOLS = ("claude-code", "codex-cli", "gemini-cli", "opencode")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host", "content-length"}  # fmt: skip


def api_format(path: str) -> str | None:
    p = path.split("?", 1)[0]
    if p.endswith("/chat/completions"):
        return "openai_chat"
    if p.endswith("/responses"):
        return "openai_responses"
    if p.endswith("/messages"):
        return "anthropic_messages"
    if ":streamGenerateContent" in p or ":generateContent" in p:
        return "gemini_native"
    return None


def consent_file(tool: str) -> Path:
    return HERE / tool / "consent.yaml"


def write_consent(tool: str, owner: str) -> Path:
    path = consent_file(tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"tool: {tool}\n"
        f"owner: {owner!r}\n"
        "consent: true\n"
        f"date: {dt.date.today().isoformat()}\n"
        "statement: >-\n"
        "  I ran the scripted synthetic tasks in eval/corpus/tasks.md with this tool, through the gateway, and\n"
        "  consent to the recorded model responses being published in this repository's test corpus.\n"
    )
    return path


def has_consent(tool: str) -> bool:
    path = consent_file(tool)
    return path.is_file() and "consent: true" in path.read_text()


class Recorder:
    def __init__(self, tool: str, upstream: str) -> None:
        self.tool = tool
        u = urlsplit(upstream)
        self.scheme, self.host, self.port = u.scheme, u.hostname or "localhost", u.port
        self.lock = threading.Lock()

    def next_path(self, fmt: str) -> Path:
        d = HERE / self.tool / fmt
        with self.lock:
            d.mkdir(parents=True, exist_ok=True)
            n = 1 + max((int(p.stem) for p in d.glob("*.sse") if p.stem.isdigit()), default=0)
            path = d / f"{n:03d}.sse"
            path.touch()
        return path


def handler_for(rec: Recorder) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            return  # no request lines, no headers: they carry credentials

        def _forward(self) -> None:
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            conn_cls = http.client.HTTPSConnection if rec.scheme == "https" else http.client.HTTPConnection
            conn = conn_cls(rec.host, rec.port, timeout=600)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            conn.request(self.command, self.path, body=body or None, headers=headers)
            resp = conn.getresponse()
            fmt = api_format(self.path)
            out = rec.next_path(fmt).open("wb") if fmt and 200 <= resp.status < 300 else None
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            if self.command == "HEAD":
                self.send_header("content-length", "0")
                self.end_headers()
                conn.close()
                return
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            try:
                while chunk := resp.read1(65536):
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                    if out:
                        out.write(chunk)
                self.wfile.write(b"0\r\n\r\n")
            finally:
                if out:
                    out.close()
                    print(f"recorded {Path(out.name).relative_to(HERE)}", file=sys.stderr)
                conn.close()

        do_GET = do_POST = do_HEAD = _forward

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tool", required=True, choices=TOOLS)
    ap.add_argument("--upstream", default="http://localhost:4000", help="the gateway (default: the demo's)")
    ap.add_argument("--port", type=int, default=4100, help="where your tool connects (default 4100)")
    ap.add_argument("--owner", help="your name, for consent.yaml")
    ap.add_argument("--i-consent", action="store_true", help="write consent.yaml for this tool and exit")
    args = ap.parse_args(argv)
    if args.i_consent:
        if not args.owner:
            ap.error("--i-consent needs --owner")
        print(f"wrote {write_consent(args.tool, args.owner).relative_to(HERE)}")
        return 0
    if not has_consent(args.tool):
        print(
            f"no consent: run once with --owner NAME --i-consent (see {consent_file(args.tool)})",
            file=sys.stderr,
        )
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(Recorder(args.tool, args.upstream)))
    print(
        f"recording {args.tool}: point the tool at http://localhost:{args.port} (forwarding to {args.upstream})"
    )
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

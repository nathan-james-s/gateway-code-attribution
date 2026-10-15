"""Mock model provider. Streams fixtures in tiny byte writes (splits SSE lines and UTF-8 sequences).

Routes:
  POST /v1/chat/completions  -> openai_chat
  POST /v1/responses         -> openai_responses
  POST /v1/messages          -> anthropic (or anthropic_truncated if body contains "TRUNCATE")
  POST /v1beta/models/<m>:streamGenerateContent -> gemini
Every request body is appended to requests.log for inspection.
"""
import sys, time, json, os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from fixtures import FIXTURES

CHUNK = int(os.environ.get("CHUNK", "7"))
HERE = os.path.dirname(os.path.abspath(__file__))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        with open(os.path.join(HERE, "requests.log"), "a") as f:
            f.write(json.dumps({"path": self.path, "body": body[:2000]}) + "\n")
        p = self.path
        if p.startswith("/v1/chat/completions"):
            name = "openai_chat"
        elif p.startswith("/v1/responses"):
            name = "openai_responses"
        elif p.startswith("/v1/messages"):
            name = "anthropic_truncated" if "TRUNCATE" in body else "anthropic"
        elif ":streamGenerateContent" in p:
            name = "gemini"
        else:
            self.send_response(404); self.send_header("content-length", "0"); self.end_headers(); return
        stream, _ = FIXTURES[name]()
        if name != "gemini" and ('"stream":false' in body.replace(" ", "") or '"stream"' not in body):
            return self.non_stream(name, stream)
        data = stream.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        for i in range(0, len(data), CHUNK):
            c = data[i:i + CHUNK]
            self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
            self.wfile.flush()
            time.sleep(0.0005)
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


    def non_stream(self, name, stream):
        """Return the final non-streamed object, derived from the same fixture."""
        from reassemble import reassemble
        evs = []
        for block in stream.split("\n\n"):
            for line in block.split("\n"):
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    evs.append(json.loads(line[6:]))
        if name == "openai_responses":
            obj = [e for e in evs if e.get("type") == "response.completed"][0]["response"]
        elif name.startswith("anthropic"):
            calls = reassemble(name, [stream.encode()])
            obj = {"id": "msg_1", "type": "message", "role": "assistant", "model": "mock", "stop_reason": "tool_use",
                   "content": [{"type": "text", "text": "Writing the file."}] +
                              [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["parsed"]} for c in calls],
                   "usage": {"input_tokens": 10, "output_tokens": 50}}
        else:
            calls = reassemble(name, [stream.encode()])
            obj = {"id": "chatcmpl-1", "object": "chat.completion", "model": "mock", "choices": [{"index": 0, "finish_reason": "tool_calls",
                   "message": {"role": "assistant", "content": "Writing the file.", "tool_calls": [
                       {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["raw"]}} for c in calls]}}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60}}
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

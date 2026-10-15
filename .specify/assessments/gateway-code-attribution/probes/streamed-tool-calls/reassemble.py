"""Reference reassembler: raw response bytes in, completed tool calls out. Stdlib only.

This is the logic a gateway-side capture component would need, independent of gateway.
"""
import codecs, json


class SSEParser:
    """Incremental SSE parser over arbitrary byte chunks (handles split UTF-8 and split lines)."""

    def __init__(self):
        self.dec = codecs.getincrementaldecoder("utf-8")()
        self.buf = ""

    def feed(self, b):
        self.buf += self.dec.decode(b)
        self.buf = self.buf.replace("\r\n", "\n")
        while "\n\n" in self.buf:
            block, self.buf = self.buf.split("\n\n", 1)
            ev, data = None, []
            for line in block.split("\n"):
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
            if data and "\n".join(data) != "[DONE]":
                yield ev, "\n".join(data)


class Calls:
    def __init__(self):
        self.calls = {}  # key -> dict
        self.order = []

    def get(self, key, **init):
        if key not in self.calls:
            self.calls[key] = {"id": None, "name": None, "kind": "json", "raw": "", "done": False, **init}
            self.order.append(key)
        return self.calls[key]

    def result(self):
        out = []
        for k in self.order:
            c = dict(self.calls[k])
            if c["kind"] == "json":
                try:
                    c["parsed"] = json.loads(c["raw"]) if c["raw"] else {}
                except json.JSONDecodeError as e:
                    c["parsed"], c["error"] = None, f"invalid JSON: {e.msg}"
            else:
                c["parsed"] = {"__freeform__": c["raw"]}
            out.append(c)
        return out


def openai_chat(events):
    cs = Calls()
    for _, d in events:
        j = json.loads(d)
        for ch in j.get("choices", []):
            for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                c = cs.get((ch.get("index", 0), tc.get("index", 0)))
                c["id"] = tc.get("id") or c["id"]
                fn = tc.get("function") or {}
                c["name"] = fn.get("name") or c["name"]
                c["raw"] += fn.get("arguments") or ""
            if ch.get("finish_reason"):
                for c in cs.calls.values():
                    c["done"] = True
    return cs.result()


def openai_responses(events):
    cs = Calls()
    for ev, d in events:
        j = json.loads(d)
        t = j.get("type", ev)
        if t == "response.output_item.added" and j["item"]["type"] in ("function_call", "custom_tool_call"):
            it = j["item"]
            c = cs.get(it["id"], kind="json" if it["type"] == "function_call" else "freeform")
            c["id"], c["name"] = it.get("call_id"), it.get("name")
        elif t in ("response.function_call_arguments.delta", "response.custom_tool_call_input.delta"):
            cs.get(j["item_id"])["raw"] += j["delta"]
        elif t == "response.function_call_arguments.done":
            c = cs.get(j["item_id"]); c["raw_done"] = j["arguments"]; c["done"] = True
        elif t == "response.custom_tool_call_input.done":
            c = cs.get(j["item_id"]); c["raw_done"] = j["input"]; c["done"] = True
    res = cs.result()
    for c in res:  # the .done events carry the full value: cross-check against the deltas
        c["delta_matches_done"] = c.get("raw_done") == c["raw"]
    return res


def anthropic(events):
    cs = Calls()
    stop = None
    for ev, d in events:
        j = json.loads(d)
        t = j.get("type", ev)
        if t == "content_block_start" and j["content_block"]["type"] in ("tool_use", "server_tool_use"):
            c = cs.get(j["index"]); c["id"], c["name"] = j["content_block"]["id"], j["content_block"]["name"]
        elif t == "content_block_delta" and j["delta"]["type"] == "input_json_delta":
            cs.get(j["index"])["raw"] += j["delta"]["partial_json"]
        elif t == "content_block_stop" and j["index"] in cs.calls:
            cs.calls[j["index"]]["done"] = True
        elif t == "message_delta":
            stop = j["delta"].get("stop_reason")
    res = cs.result()
    for c in res:
        c["stop_reason"] = stop
    return res


def gemini(events):
    cs = Calls()
    n = 0
    for _, d in events:
        j = json.loads(d)
        for cand in j.get("candidates", []):
            for part in (cand.get("content") or {}).get("parts", []):
                if "functionCall" in part:
                    fc = part["functionCall"]
                    c = cs.get(n); n += 1
                    c["name"], c["raw"], c["done"] = fc["name"], json.dumps(fc.get("args", {})), True
                    c["id"] = fc.get("id") or fc["name"]
    return cs.result()


PARSERS = {"openai_chat": openai_chat, "openai_responses": openai_responses,
           "anthropic": anthropic, "anthropic_truncated": anthropic, "gemini": gemini}


def reassemble(fmt, byte_chunks):
    p = SSEParser()
    events = [e for b in byte_chunks for e in p.feed(b)]
    return PARSERS[fmt](events)

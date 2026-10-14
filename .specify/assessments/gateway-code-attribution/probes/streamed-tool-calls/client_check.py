"""Stream each fixture from a base URL (mock directly, or through a gateway), reassemble the
raw bytes the client received, and compare with ground truth. Usage:
  python client_check.py <base_url> [fmt ...]
"""
import sys, json, hmac, hashlib, unicodedata, urllib.request
from fixtures import FIXTURES
from reassemble import reassemble

KEY = b"probe-key"
REQ = {
    "openai_chat": ("/v1/chat/completions", {"model": "mock-openai", "stream": True, "messages": [{"role": "user", "content": "hi"}],
                                            "tools": [{"type": "function", "function": {"name": "write_file", "parameters": {"type": "object"}}},
                                                      {"type": "function", "function": {"name": "edit_file", "parameters": {"type": "object"}}}]}),
    "openai_responses": ("/v1/responses", {"model": "mock-openai", "stream": True, "input": "hi",
                                          "tools": [{"type": "function", "name": "write_file", "parameters": {"type": "object"}},
                                                    {"type": "custom", "name": "apply_patch"}]}),
    "anthropic": ("/v1/messages", {"model": "mock-anthropic", "stream": True, "max_tokens": 1000, "messages": [{"role": "user", "content": "hi"}],
                                   "tools": [{"name": "Write", "input_schema": {"type": "object"}}, {"name": "Edit", "input_schema": {"type": "object"}}]}),
    "anthropic_truncated": ("/v1/messages", {"model": "mock-anthropic", "stream": True, "max_tokens": 1000, "messages": [{"role": "user", "content": "TRUNCATE"}],
                                             "tools": [{"name": "Write", "input_schema": {"type": "object"}}, {"name": "Edit", "input_schema": {"type": "object"}}]}),
    "gemini": ("/v1beta/models/mock-gemini:streamGenerateContent?alt=sse", {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}),
}


def fp_lines(text):
    """Tiny stand-in for the shared normaliser + HMAC: NFC, strip, skip blanks."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        n = unicodedata.normalize("NFC", line).strip()
        if n:
            out.append(hmac.new(KEY, n.encode(), hashlib.sha256).hexdigest()[:16])
    return out


def code_fields(args):
    return {k: v for k, v in (args or {}).items() if k in ("content", "new_string", "__freeform__")}


def run(base, fmt, headers=None):
    path, body = REQ[fmt]
    req = urllib.request.Request(base.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "authorization": "Bearer sk-probe",
                                          "x-api-key": "sk-probe", "anthropic-version": "2023-06-01", **(headers or {})})
    chunks = []
    with urllib.request.urlopen(req, timeout=30) as r:
        while True:
            b = r.read1(4096) if hasattr(r, "read1") else r.read(4096)
            if not b:
                break
            chunks.append(b)
    raw = b"".join(chunks)
    calls = reassemble(fmt, chunks)
    _, truth = FIXTURES[fmt]()
    truth_list = list(truth.values())
    report = {"fmt": fmt, "bytes": len(raw), "calls": []}
    for i, c in enumerate(calls):
        exp = truth_list[i] if i < len(truth_list) else "MISSING"
        ok = c["parsed"] == exp
        fp_ok = None
        if exp not in (None, "MISSING") and c["parsed"]:
            fp_ok = all(fp_lines(v) == fp_lines(exp[k]) for k, v in code_fields(c["parsed"]).items())
        report["calls"].append({"name": c["name"], "id": c["id"], "kind": c["kind"], "done": c["done"],
                                "args_equal_truth": ok, "fingerprints_equal_truth": fp_ok,
                                **{k: c[k] for k in ("error", "stop_reason", "delta_matches_done") if k in c}})
    report["n_calls"], report["n_truth"] = len(calls), len(truth_list)
    return report, raw


if __name__ == "__main__":
    base = sys.argv[1]
    fmts = sys.argv[2:] or list(REQ)
    for f in fmts:
        try:
            rep, _ = run(base, f)
            print(json.dumps(rep))
        except Exception as e:
            print(json.dumps({"fmt": f, "error": f"{type(e).__name__}: {e}"}))

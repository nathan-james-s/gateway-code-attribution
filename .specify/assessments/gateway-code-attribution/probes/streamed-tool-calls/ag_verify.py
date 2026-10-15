"""Send each fixture through agentgateway (streamed and non-streamed), then compare the
llm.toolCalls it logged against ground truth."""
import json, time, urllib.request
from fixtures import FIXTURES
from client_check import REQ, run, fp_lines, code_fields

BASE = "http://127.0.0.1:13000"
LOG = "ag.log"


def log_lines():
    out = []
    for l in open(LOG):
        try:
            j = json.loads(l)
        except Exception:
            continue
        if "probe.streaming" in j or "http.path" in j:
            out.append(j)
    return out


def nonstream(fmt):
    path, body = REQ[fmt]
    body = {**body, "stream": False}
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "authorization": "Bearer x",
                                          "x-api-key": "x", "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def compare(fmt, entry):
    _, truth = FIXTURES[fmt]()
    tl = list(truth.values())
    tcs = entry.get("probe.tool_calls")
    res = {"fmt": fmt, "path": entry.get("http.path"), "status": entry.get("http.status"),
           "streaming": entry.get("probe.streaming"), "n_logged": None if tcs is None else len(tcs), "n_truth": len(tl),
           "completion": entry.get("probe.completion"), "calls": []}
    for i, t in enumerate(tcs or []):
        a = t.get("arguments")
        if isinstance(a, str):
            try:
                a = json.loads(a)
            except json.JSONDecodeError:
                a = {"__freeform__": a} if "Begin Patch" in a else {"__unparsed__": a[:80]}
        exp = tl[i] if i < len(tl) else "MISSING"
        fp = None
        if isinstance(a, dict) and exp not in (None, "MISSING"):
            fp = all(fp_lines(v) == fp_lines(exp[k]) for k, v in code_fields(a).items()) if code_fields(a) else False
        res["calls"].append({"id": t.get("id"), "name": t.get("name"), "arg_type": type(t.get("arguments")).__name__,
                             "equal": a == exp, "fp_equal": fp,
                             "arg_preview": json.dumps(t.get("arguments"), ensure_ascii=False)[:70]})
    return res


if __name__ == "__main__":
    time.sleep(1)
    for mode in ("stream", "nonstream"):
        for fmt in ("openai_chat", "openai_responses", "anthropic", "anthropic_truncated"):
            if mode == "nonstream" and fmt == "anthropic_truncated":
                continue
            before = len(log_lines())
            client = None
            try:
                if mode == "stream":
                    rep, _ = run(BASE, fmt)
                    client = all(c["args_equal_truth"] for c in rep["calls"]) and rep["n_calls"] == rep["n_truth"]
                else:
                    nonstream(fmt)
            except Exception as e:
                client = f"{type(e).__name__}: {e}"
            time.sleep(0.7)
            new = log_lines()[before:]
            entry = new[-1] if new else {}
            r = compare(fmt, entry)
            r["mode"], r["client_side_reassembly_ok"] = mode, client
            print(json.dumps(r, ensure_ascii=False))

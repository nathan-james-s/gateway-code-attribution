"""Compare the tool calls the LiteLLM callback received against fixture ground truth."""
import json
from fixtures import FIXTURES
from client_check import fp_lines, code_fields

TRUTH = {"acompletion": "openai_chat", "aresponses": "openai_responses"}


def calls_of(r):
    o = r["response_obj"]
    out = []
    if "choices" in o:
        for ch in o["choices"]:
            for tc in ch["message"].get("tool_calls") or []:
                out.append((tc["id"], tc["function"]["name"], "json", tc["function"]["arguments"], ch.get("finish_reason")))
    elif "output" in o:
        for it in o["output"]:
            if it.get("type") == "function_call":
                out.append((it["call_id"], it["name"], "json", it["arguments"], o.get("status")))
            elif it.get("type") == "custom_tool_call":
                out.append((it["call_id"], it["name"], "freeform", it["input"], o.get("status")))
    return out


seen_anthropic = 0
for line in open("litellm_capture.jsonl"):
    r = json.loads(line)
    if r["event"] != "success":
        print("FAILURE", r); continue
    ct = r["call_type"]
    if ct == "anthropic_messages":
        fmt = "anthropic" if seen_anthropic == 0 else "anthropic_truncated"; seen_anthropic += 1
    elif ct == "acompletion" and "gemini" in json.dumps(r["response_obj"]).lower():
        fmt = "gemini"
    else:
        fmt = TRUTH.get(ct)
    _, truth = FIXTURES[fmt]()
    tl = list(truth.values())
    res = []
    for i, (cid, name, kind, raw, fin) in enumerate(calls_of(r)):
        try:
            parsed = json.loads(raw) if kind == "json" else {"__freeform__": raw}
            err = None
        except json.JSONDecodeError as e:
            parsed, err = None, e.msg
        exp = tl[i] if i < len(tl) else "MISSING"
        fp = None
        if parsed and exp not in (None, "MISSING"):
            fp = all(fp_lines(v) == fp_lines(exp[k]) for k, v in code_fields(parsed).items())
        res.append({"id": cid, "name": name, "equal": parsed == exp, "fp_equal": fp, "json_error": err, "finish": fin})
    print(json.dumps({"call_type": ct, "fixture": fmt, "n": len(res), "n_truth": len(tl), "calls": res}))

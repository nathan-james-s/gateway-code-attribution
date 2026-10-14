"""Synthetic streaming responses that mimic each provider's documented SSE format.

Each fixture carries tool calls whose arguments contain code. Arguments are split into
small fragments so a fragment boundary lands inside JSON escapes (\\n, \\", \\u00e9) and the
server additionally writes the byte stream in tiny TCP writes so UTF-8 sequences and SSE
lines are split mid-way. Ground truth is the code each tool call carries.
"""
import json

# Code that exercises normalisation-sensitive content.
PY_FILE = (
    "def total(items):\n"
    "\tsubtotal = sum(i.price for i in items)  # café\n"
    '    print("a\\nb", \'quote\')\n'
    "    return round(subtotal * 1.0825, 2)\r\n"
    "\n"
    "émoji = \"🚀\"\n"
)
OLD_STR = "    return round(subtotal * 1.0825, 2)"
NEW_STR = "    tax = 1.0825\n    return round(subtotal * tax, 2)"
TS_FILE = "export const add = (a: number, b: number): number => a + b;\nconsole.log(`sum=${add(1, 2)}`);\n"
PATCH = (
    "*** Begin Patch\n"
    "*** Update File: src/app.py\n"
    "@@ def total(items):\n"
    "-    return round(subtotal * 1.0825, 2)\n"
    "+    tax = 1.0825\n"
    "+    return round(subtotal * tax, 2)\n"
    "*** End Patch\n"
)


def frags(s, n=5):
    return [s[i:i + n] for i in range(0, len(s), n)]


def sse(data, event=None):
    out = ""
    if event:
        out += f"event: {event}\n"
    out += "data: " + (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)) + "\n\n"
    return out


# ---------------- OpenAI Chat Completions: two parallel tool calls, interleaved ----------
def openai_chat():
    calls = [
        ("call_w", "write_file", {"path": "src/app.py", "content": PY_FILE}),
        ("call_e", "edit_file", {"path": "src/app.py", "old_string": OLD_STR, "new_string": NEW_STR}),
    ]
    base = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "mock"}
    out = [sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Writing the file."}, "finish_reason": None}]})]
    pieces = []
    for idx, (cid, name, args) in enumerate(calls):
        out.append(sse({**base, "choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": idx, "id": cid, "type": "function", "function": {"name": name, "arguments": ""}}]}, "finish_reason": None}]}))
        pieces.append([(idx, f) for f in frags(json.dumps(args, ensure_ascii=(idx == 1)))])
    # interleave fragments of both calls (parallel tool calls)
    while any(pieces):
        for p in pieces:
            if p:
                idx, f = p.pop(0)
                out.append(sse({**base, "choices": [{"index": 0, "delta": {"tool_calls": [
                    {"index": idx, "function": {"arguments": f}}]}, "finish_reason": None}]}))
    out.append(sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60}}))
    out.append(sse("[DONE]"))
    truth = {cid: args for cid, _, args in calls}
    return "".join(out), truth


# ---------------- OpenAI Responses API: function_call + freeform custom tool (apply_patch) ----
def openai_responses():
    args = {"path": "src/util.ts", "content": TS_FILE}
    a = json.dumps(args, ensure_ascii=False)
    fc = {"type": "function_call", "id": "fc_1", "call_id": "call_r1", "name": "write_file", "arguments": "", "status": "in_progress"}
    ct = {"type": "custom_tool_call", "id": "ctc_1", "call_id": "call_r2", "name": "apply_patch", "input": "", "status": "in_progress"}
    resp = {"id": "resp_1", "object": "response", "created_at": 1, "model": "mock", "status": "in_progress", "output": []}
    out = [sse({"type": "response.created", "sequence_number": 0, "response": resp}, "response.created")]
    seq = 1

    def ev(t, body):
        nonlocal seq
        body = {"type": t, "sequence_number": seq, **body}
        seq += 1
        return sse(body, t)

    out.append(ev("response.output_item.added", {"output_index": 0, "item": fc}))
    for f in frags(a):
        out.append(ev("response.function_call_arguments.delta", {"item_id": "fc_1", "output_index": 0, "delta": f}))
    out.append(ev("response.function_call_arguments.done", {"item_id": "fc_1", "output_index": 0, "arguments": a}))
    fc_done = {**fc, "arguments": a, "status": "completed"}
    out.append(ev("response.output_item.done", {"output_index": 0, "item": fc_done}))
    out.append(ev("response.output_item.added", {"output_index": 1, "item": ct}))
    for f in frags(PATCH, 7):
        out.append(ev("response.custom_tool_call_input.delta", {"item_id": "ctc_1", "output_index": 1, "delta": f}))
    out.append(ev("response.custom_tool_call_input.done", {"item_id": "ctc_1", "output_index": 1, "input": PATCH}))
    ct_done = {**ct, "input": PATCH, "status": "completed"}
    out.append(ev("response.output_item.done", {"output_index": 1, "item": ct_done}))
    out.append(ev("response.completed", {"response": {**resp, "status": "completed", "output": [fc_done, ct_done],
                                                      "usage": {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 50, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 60}}}))
    return "".join(out), {"call_r1": args, "call_r2": {"__freeform__": PATCH}}


# ---------------- Anthropic Messages: text block + Write + Edit tool_use (input_json_delta) ----
def anthropic(truncate=False):
    calls = [
        ("toolu_w", "Write", {"file_path": "/repo/src/app.py", "content": PY_FILE}),
        ("toolu_e", "Edit", {"file_path": "/repo/src/app.py", "old_string": OLD_STR, "new_string": NEW_STR}),
    ]
    out = [sse({"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "mock",
                                                    "content": [], "stop_reason": None, "stop_sequence": None,
                                                    "usage": {"input_tokens": 10, "output_tokens": 1}}}, "message_start")]
    out.append(sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}, "content_block_start"))
    out.append(sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Writing the file."}}, "content_block_delta"))
    out.append(sse({"type": "content_block_stop", "index": 0}, "content_block_stop"))
    truth = {}
    for i, (tid, name, args) in enumerate(calls, start=1):
        out.append(sse({"type": "content_block_start", "index": i, "content_block": {"type": "tool_use", "id": tid, "name": name, "input": {}}}, "content_block_start"))
        s = json.dumps(args, ensure_ascii=False)
        fs = frags(s, 6)
        if truncate and i == 2:
            fs = fs[: len(fs) // 2]  # max_tokens mid-value
        for k, f in enumerate(fs):
            out.append(sse({"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": f}}, "content_block_delta"))
            if k == 3:
                out.append(sse({"type": "ping"}, "ping"))
        out.append(sse({"type": "content_block_stop", "index": i}, "content_block_stop"))
        truth[tid] = None if (truncate and i == 2) else args
    stop = "max_tokens" if truncate else "tool_use"
    out.append(sse({"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 50}}, "message_delta"))
    out.append(sse({"type": "message_stop"}, "message_stop"))
    return "".join(out), truth


# ---------------- Gemini streamGenerateContent (alt=sse): functionCall arrives whole ----------
def gemini():
    args = {"path": "src/app.py", "content": PY_FILE}
    out = [sse({"candidates": [{"content": {"role": "model", "parts": [{"text": "Writing the file."}]}, "index": 0}]}),
           sse({"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": "write_file", "args": args}}]},
                                "finishReason": "STOP", "index": 0}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 50, "totalTokenCount": 60}})]
    return "".join(out), {"write_file": args}


FIXTURES = {
    "openai_chat": openai_chat,
    "openai_responses": openai_responses,
    "anthropic": anthropic,
    "anthropic_truncated": lambda: anthropic(truncate=True),
    "gemini": gemini,
}

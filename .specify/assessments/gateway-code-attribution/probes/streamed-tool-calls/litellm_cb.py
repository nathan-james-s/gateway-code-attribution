"""LiteLLM proxy callback: record what a capture plug-in can see for each streamed request."""
import json, os
from litellm.integrations.custom_logger import CustomLogger

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "litellm_capture.jsonl")


def dump(o):
    if o is None:
        return None
    for m in ("model_dump", "dict", "json"):
        if hasattr(o, m):
            try:
                v = getattr(o, m)()
                return json.loads(v) if isinstance(v, str) else v
            except Exception:
                pass
    return str(o)[:5000]


class Probe(CustomLogger):
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        slo = kwargs.get("standard_logging_object") or {}
        rec = {
            "event": "success",
            "call_type": kwargs.get("call_type"),
            "route": (kwargs.get("litellm_params") or {}).get("proxy_server_request", {}).get("url"),
            "stream": kwargs.get("stream"),
            "has_complete_streaming_response": "complete_streaming_response" in kwargs,
            "complete_streaming_response": dump(kwargs.get("complete_streaming_response")),
            "response_obj": dump(response_obj),
            "slo_response": slo.get("response"),
        }
        with open(OUT, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        with open(OUT, "a") as f:
            f.write(json.dumps({"event": "failure", "call_type": kwargs.get("call_type"),
                                "exception": str(kwargs.get("exception"))[:2000]}) + "\n")


probe = Probe()

"""Developers using coding tools through a gateway (T114; SC-010, SC-013). Each simulated developer sends a
streamed request whose response holds tool calls (a demo-session step, answered by the demo model), reads the
whole stream, then thinks. tests/perf/gateway_overhead.py starts the gateway and runs this with:

    GCA_PERF_GATEWAY      agentgateway | litellm
    GCA_PERF_CREDENTIALS  a JSON list of {key, credential_id}, one per developer
    GCA_PERF_THINK        "min,max" seconds between a developer's requests (default "10,60")
    GCA_PERF_TIMES        a file to append each request's exact completion time to (ms, one per line)

Locust reads each response to the end, so its response time is the completion time SC-010 is about. Locust's
own percentiles round times over a second to two significant figures (100 ms steps at 2 s, about 4%), too
coarse for a 5% bar, so every request's time is also written to GCA_PERF_TIMES.
"""

from __future__ import annotations

import itertools
import json
import os
import random
from pathlib import Path

from locust import HttpUser, between, events, task

from gca_demo.agent import request_parts
from gca_demo.sessions import marker, sessions
from gca_eval.gateways import CREDENTIAL_HEADER, LITELLM_MASTER

GATEWAY = os.environ.get("GCA_PERF_GATEWAY", "agentgateway")
CREDENTIALS = json.loads(Path(os.environ["GCA_PERF_CREDENTIALS"]).read_text())
THINK = tuple(float(x) for x in os.environ.get("GCA_PERF_THINK", "10,60").split(","))
STEPS = [(step.format, marker(s.name, i)) for s in sessions().values() for i, step in enumerate(s.steps)]
_developer = itertools.count()
_times = open(os.environ["GCA_PERF_TIMES"], "a", buffering=1) if os.environ.get("GCA_PERF_TIMES") else None  # noqa: SIM115


@events.request.add_listener
def _record(response_time: float, exception: Exception | None, **_: object) -> None:
    if _times is not None and exception is None:
        _times.write(f"{response_time:.3f}\n")


class Developer(HttpUser):
    wait_time = between(*THINK)

    def on_start(self) -> None:
        c = CREDENTIALS[next(_developer) % len(CREDENTIALS)]
        if GATEWAY == "agentgateway":
            self.key, self.extra = c["key"], {}
        else:  # LiteLLM in the local stack: the master key, and the developer named in a header
            self.key, self.extra = LITELLM_MASTER, {CREDENTIAL_HEADER: c["credential_id"]}

    @task
    def coding_turn(self) -> None:
        api_format, text = random.choice(STEPS)
        path, headers, body = request_parts(api_format, text, self.key, self.extra)
        with self.client.post(path, json=body, headers=headers, name=api_format, catch_response=True) as r:
            if r.status_code != 200 or not r.content:
                r.failure(f"HTTP {r.status_code}")

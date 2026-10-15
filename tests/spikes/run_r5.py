"""T039 driver: does agentgateway 1.6.0 standalone reload `llm.policies.apiKey.keys` from a changed config file
without dropping in-flight streams (research R5)? Prints a JSON report.

Usage: python run_r5.py <agentgateway-binary>
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_r2 import PROBE, REQ, fetch, start, wait_port

HERE = Path(__file__).resolve().parent
NEW_KEY = "gca_spike_key_2"


def main() -> None:
    ag_bin = sys.argv[1]
    tmp = Path(tempfile.mkdtemp(prefix="r5-"))
    cfg = tmp / "config.yaml"
    base = (HERE / "r2_agentgateway.yaml").read_text()
    # No extProc here: isolate key reload behaviour.
    base = base.split("    extProc:")[0] + "  models:" + base.split("  models:")[1]
    cfg.write_text(base)
    procs: list[subprocess.Popen] = []
    report: dict = {}
    try:
        procs.append(start([sys.executable, "mock_upstream.py", "18092"], cwd=PROBE, env={"CHUNK": "1"}))
        wait_port(18092)
        cfg.write_text(cfg.read_text().replace("127.0.0.1:18090", "127.0.0.1:18092"))
        procs.append(start([ag_bin, "-f", str(cfg)], log=tmp / "ag.log"))
        wait_port(13090)
        time.sleep(0.5)
        report["new_key_before_reload"] = fetch(
            "http://127.0.0.1:13090", *REQ["openai_chat"][:2], {}, key=NEW_KEY
        )[0]

        # A long in-flight stream (1-byte chunks) while the config changes underneath it.
        result: dict = {}
        t = threading.Thread(
            target=lambda: result.update(
                via=fetch("http://127.0.0.1:13090", *REQ["anthropic"][:2], REQ["anthropic"][2])
            )
        )
        t.start()
        time.sleep(0.3)
        new_hash = hashlib.sha256(NEW_KEY.encode()).hexdigest()
        text = cfg.read_text().replace(
            "      keys:\n",
            f'      keys:\n        - keyHash: "sha256:{new_hash}"\n          metadata: {{credential_id: "new", github_id: 7}}\n',
        )
        tmp_cfg = tmp / "config.yaml.new"
        tmp_cfg.write_text(text)
        shutil.move(tmp_cfg, cfg)  # atomic replace, like a ConfigMap update
        changed_at = time.time()
        applied_after = None
        for _ in range(100):
            if fetch("http://127.0.0.1:13090", *REQ["openai_chat"][:2], {}, key=NEW_KEY)[0] == 200:
                applied_after = round(time.time() - changed_at, 2)
                break
            time.sleep(0.2)
        report["new_key_applied_after_seconds"] = applied_after
        t.join(60)
        status, via, secs = result.get("via", (None, b"", 0))
        _, direct, _ = fetch(
            "http://127.0.0.1:18092",
            REQ["anthropic"][0],
            {**REQ["anthropic"][1], "model": "mock"},
            REQ["anthropic"][2],
            key=None,
        )
        report["in_flight_stream_during_reload"] = {
            "status": status,
            "identical_to_direct": via == direct,
            "seconds": round(secs, 2),
        }
        report["old_key_still_valid"] = fetch("http://127.0.0.1:13090", *REQ["openai_chat"][:2], {})[0]
        # Revocation: remove the new key again
        cfg.write_text(
            cfg.read_text().replace(
                f'        - keyHash: "sha256:{new_hash}"\n          metadata: {{credential_id: "new", github_id: 7}}\n',
                "",
            )
        )
        revoked_after = None
        t0 = time.time()
        for _ in range(100):
            if fetch("http://127.0.0.1:13090", *REQ["openai_chat"][:2], {}, key=NEW_KEY)[0] == 401:
                revoked_after = round(time.time() - t0, 2)
                break
            time.sleep(0.2)
        report["revocation_applied_after_seconds"] = revoked_after
    finally:
        for p in procs:
            p.kill()
        report["logs_dir"] = str(tmp)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

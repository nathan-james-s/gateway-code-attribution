"""Entry point: python -m gca_capture_extproc"""

from __future__ import annotations

import asyncio
import logging

from gca_core.capture_runtime import CaptureRuntime
from gca_core.config import settings
from gca_core.nats import connect_jetstream, ensure_stream

from .server import env_int, serve


async def _main() -> None:
    cfg = settings()
    state: dict[str, object] = {}

    async def send(subject: str, payload: bytes) -> None:
        js = state.get("js")
        if js is None:
            _, js = await connect_jetstream(cfg.nats_url)
            await ensure_stream(js)
            state["js"] = js
        await js.publish(subject, payload)  # type: ignore[attr-defined]

    runtime = CaptureRuntime(
        "agentgateway", send, heartbeat_seconds=cfg.heartbeat_seconds, max_buffer=cfg.publish_buffer_max
    )
    await serve(
        runtime,
        port=env_int("GCA_EXTPROC_PORT", 9000),
        keys_dir=cfg.keys_dir,
        workers=env_int("GCA_EXTPROC_WORKERS", 2),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_main())


if __name__ == "__main__":
    main()

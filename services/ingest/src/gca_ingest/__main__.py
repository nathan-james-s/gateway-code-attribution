"""Entry point: python -m gca_ingest"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from gca_core.config import settings
from gca_core.db import engine

from .consumer import consume, maintenance

log = logging.getLogger("gca.ingest")


async def _main() -> None:
    cfg = settings()
    eng = engine()
    # Ingest runs as PID 1, which ignores SIGTERM unless it handles it. Unhandled, a pod told to stop kept
    # consuming until Kubernetes killed it after the grace period, so scaling ingest to zero didn't pause it.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    sweeper = asyncio.create_task(maintenance(eng, cfg.gateway_type))
    try:
        await consume(eng, cfg.nats_url, stop=stop)
        log.info("stopping")
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_main())


if __name__ == "__main__":
    main()

"""Entry point: python -m gca_ingest"""

from __future__ import annotations

import asyncio
import logging

from gca_core.config import settings
from gca_core.db import engine

from .consumer import consume, maintenance


async def _main() -> None:
    cfg = settings()
    eng = engine()
    await asyncio.gather(consume(eng, cfg.nats_url), maintenance(eng, cfg.gateway_type))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_main())


if __name__ == "__main__":
    main()

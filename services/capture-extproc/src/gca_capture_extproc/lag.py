"""Event-loop lag monitor: the processor's self-deadline (docs/validation/R2-extproc.md mitigation 2)."""

from __future__ import annotations

import asyncio
import time


class LagMonitor:
    """Marks the processor *degraded* while the event loop lags more than ``deadline`` seconds.

    While degraded, streams stop copying chunks for capture (counted as loss) but keep echoing, so a slow
    processor never stalls developers on its own account.
    """

    def __init__(self, deadline: float = 0.25, interval: float = 0.05) -> None:
        self.deadline = deadline
        self.interval = interval
        self.degraded = False
        self.max_lag = 0.0
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        while True:
            start = time.monotonic()
            await asyncio.sleep(self.interval)
            lag = time.monotonic() - start - self.interval
            self.max_lag = max(self.max_lag, lag)
            self.degraded = lag > self.deadline

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

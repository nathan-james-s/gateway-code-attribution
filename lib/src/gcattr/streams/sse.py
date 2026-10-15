"""Incremental Server-Sent Events parser over arbitrary byte chunks (split UTF-8 and split lines are fine)."""

from __future__ import annotations

import codecs
from collections.abc import Iterable, Iterator
from typing import NamedTuple

__all__ = ["SSEEvent", "SSEParser", "iter_events"]


class SSEEvent(NamedTuple):
    event: str | None
    data: str


class SSEParser:
    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf = ""

    def feed(self, chunk: bytes) -> Iterator[SSEEvent]:
        self._buf += self._decoder.decode(chunk)
        yield from self._drain(final=False)

    def close(self) -> Iterator[SSEEvent]:
        self._buf += self._decoder.decode(b"", final=True)
        yield from self._drain(final=True)

    def _drain(self, final: bool) -> Iterator[SSEEvent]:
        self._buf = self._buf.replace("\r\n", "\n").replace("\r", "\n")
        while "\n\n" in self._buf:
            block, self._buf = self._buf.split("\n\n", 1)
            ev = _parse_block(block)
            if ev is not None:
                yield ev
        if final and self._buf.strip():
            ev = _parse_block(self._buf)
            self._buf = ""
            if ev is not None:
                yield ev


def _parse_block(block: str) -> SSEEvent | None:
    event: str | None = None
    data: list[str] = []
    for line in block.split("\n"):
        if line.startswith(":"):
            continue  # comment / keep-alive
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if not data:
        return None
    joined = "\n".join(data)
    if joined.strip() == "[DONE]":
        return None
    return SSEEvent(event, joined)


def iter_events(chunks: Iterable[bytes]) -> Iterator[SSEEvent]:
    parser = SSEParser()
    for chunk in chunks:
        yield from parser.feed(chunk)
    yield from parser.close()

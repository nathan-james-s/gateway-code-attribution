"""agentgateway ext_proc capture server (T041; research R2; docs/validation/R2-extproc.md).

Contract: echo every response body chunk unchanged, immediately. Copy chunks (up to 8 MiB per stream) for
capture; at end of stream hand the bytes to a worker process for parsing and fingerprinting, then publish
fingerprints only. Content is never logged. Every failure is counted, never raised into the stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing
import os
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Executor, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from typing import Any

import grpc
from envoy.service.ext_proc.v3 import external_processor_pb2 as pb
from envoy.service.ext_proc.v3 import external_processor_pb2_grpc as pbg
from google.protobuf.json_format import MessageToDict

from gca_core.capture_runtime import CaptureRuntime

from . import worker
from .api_format import UNSUPPORTED, classify, model_from_path, session_id, tool_hint
from .lag import LagMonitor

log = logging.getLogger("gca.capture_extproc")

MAX_STREAM_BYTES = 8 * 1024 * 1024
# Fault injection for the end-to-end test (T093d): delay each echoed chunk. Off (0) in every real install.
ECHO_DELAY_SECONDS = float(os.environ.get("GCA_CAPTURE_TEST_ECHO_DELAY_SECONDS", "0"))


def _headers(header_map: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in header_map.headers:
        value = h.raw_value.decode("utf-8", "replace") if h.raw_value else h.value
        out[h.key.lower()] = value
    return out


def _echo(body: bytes, end_of_stream: bool) -> pb.ProcessingResponse:
    return pb.ProcessingResponse(
        response_body=pb.BodyResponse(
            response=pb.CommonResponse(
                body_mutation=pb.BodyMutation(
                    streamed_response=pb.StreamedBodyResponse(body=body, end_of_stream=end_of_stream)
                )
            )
        )
    )


def make_executor(workers: int, keys_dir: str) -> ProcessPoolExecutor:
    # spawn, never fork: forking while gRPC's threads run crashes the child inside gRPC's poller and wedges
    # the parent (seen on the first kind install: grpc fork_posix "skipping fork() handlers").
    return ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=worker.init,
        initargs=(keys_dir,),
    )


class CaptureProcessor(pbg.ExternalProcessorServicer):
    def __init__(
        self,
        runtime: CaptureRuntime,
        executor: Executor,
        lag: LagMonitor,
        fingerprint: Callable[..., Any] = worker.fingerprint,
        executor_factory: Callable[[], Executor] | None = None,
    ) -> None:
        self.runtime = runtime
        self.executor = executor
        self.executor_factory = executor_factory
        self.pool_restarts = 0
        self.lag = lag
        self.fingerprint = fingerprint
        self.accepting = True
        self.active_streams = 0

    async def Process(
        self, request_iterator: AsyncIterator[pb.ProcessingRequest], context: grpc.aio.ServicerContext
    ) -> AsyncIterator[pb.ProcessingResponse]:
        self.active_streams += 1
        buf = bytearray()
        capture = self.accepting
        overflow = False
        path: str | None = None
        req_headers: dict[str, str] = {}
        status: str | None = None
        meta: dict[str, Any] = {}
        try:
            async for req in request_iterator:
                which = req.WhichOneof("request")
                if not meta and req.HasField("metadata_context"):
                    meta = MessageToDict(req.metadata_context).get("filterMetadata", {}).get("gca", {})
                if which == "request_headers":
                    req_headers = _headers(req.request_headers.headers)
                    path = req_headers.get(":path")
                    yield pb.ProcessingResponse(request_headers=pb.HeadersResponse())
                elif which == "response_headers":
                    status = _headers(req.response_headers.headers).get(":status")
                    yield pb.ProcessingResponse(response_headers=pb.HeadersResponse())
                elif which == "response_body":
                    body = req.response_body.body
                    eos = req.response_body.end_of_stream
                    # Echo first, unchanged. Nothing below may delay it.
                    if ECHO_DELAY_SECONDS:
                        await asyncio.sleep(ECHO_DELAY_SECONDS)
                    yield _echo(body, eos)
                    if capture and not overflow:
                        if self.lag.degraded or len(buf) + len(body) > MAX_STREAM_BYTES:
                            overflow = True
                            buf = bytearray()
                        else:
                            buf += body
                    if eos:
                        self._finish(path, req_headers, status, meta, bytes(buf), overflow, capture)
                        buf = bytearray()
                elif which == "request_body":
                    yield pb.ProcessingResponse(request_body=pb.BodyResponse())
                elif which == "request_trailers":
                    yield pb.ProcessingResponse(request_trailers=pb.TrailersResponse())
                elif which == "response_trailers":
                    yield pb.ProcessingResponse(response_trailers=pb.TrailersResponse())
        finally:
            self.active_streams -= 1

    # ---------------------------------------------------------------------------------------------- capture
    def _finish(
        self,
        path: str | None,
        headers: dict[str, str],
        status: str | None,
        meta: dict[str, Any],
        data: bytes,
        overflow: bool,
        capture: bool,
    ) -> None:
        api_format = classify(path)
        if api_format is None or not capture:
            return  # a route that never carries code (or draining): nothing to attribute
        if status is not None and not status.startswith("2"):
            return  # provider error bodies carry no model output
        credential = meta.get("credential_id")
        hint = tool_hint(headers)
        known = None if api_format == UNSUPPORTED else api_format
        if not credential:
            self.runtime.emit_failure("unknown_credential", api_format=known, tool_hint=hint)
            return
        if known is None:
            # A model route capture can't read: counted against the developer, never dropped silently (FR-007).
            self.runtime.emit_failure("unsupported_combination", credential_id=credential, tool_hint=hint)
            return
        if overflow:
            self.runtime.emit_failure(
                "buffer_overflow", credential_id=credential, api_format=api_format, tool_hint=hint
            )
            return
        asyncio.get_running_loop().create_task(
            self._fingerprint_and_emit(
                api_format, data, credential, hint, session_id(headers), model_from_path(path)
            )
        )

    async def _fingerprint_and_emit(
        self,
        api_format: str,
        data: bytes,
        credential: str,
        hint: str | None,
        session: str | None,
        path_model: str | None = None,
    ) -> None:
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                self.executor, partial(self.fingerprint, api_format, data)
            )
        except BrokenProcessPool:
            # A worker died. Count this response as lost and replace the pool so later responses are captured.
            log.error("fingerprint worker pool broke; replacing it")
            self._replace_executor()
            self.runtime.emit_failure(
                "unparsable", credential_id=credential, api_format=api_format, tool_hint=hint
            )
            return
        except Exception:
            log.exception("fingerprinting failed")  # the exception never carries content
            self.runtime.emit_failure(
                "unparsable", credential_id=credential, api_format=api_format, tool_hint=hint
            )
            return
        failures: list[str] = result["failures"]
        lines = result["lines"]
        status = (
            "captured" if not failures else ("partial" if lines or result["tool_call_count"] else "failed")
        )
        if status != "failed":
            self.runtime.emit_event(
                api_format=api_format,
                model=result["model"] if result["model"] != "unknown" else (path_model or "unknown"),
                lines=lines,
                tool_call_count=result["tool_call_count"],
                alg=result["alg"],
                key_gen=result["key_gen"],
                status=status,
                failure_cause=failures[0] if failures else None,
                credential_id=credential,
                tool_hint=hint,
                session_id=session,
            )
        for i, cause in enumerate(failures):  # every failure is counted as loss (FR-005)
            # A fully failed response emits no event, so its first failure stands for the response itself.
            self.runtime.emit_failure(
                cause,
                credential_id=credential,
                api_format=api_format,
                tool_hint=hint,
                count_as_response=status == "failed" and i == 0,
            )

    def _replace_executor(self) -> None:
        if self.executor_factory is None:
            return
        old = self.executor
        self.executor = self.executor_factory()
        self.pool_restarts += 1
        with contextlib.suppress(Exception):
            old.shutdown(wait=False, cancel_futures=True)

    @property
    def healthy(self) -> bool:
        return not getattr(self.executor, "_broken", False)


async def health_server(processor: CaptureProcessor, port: int) -> asyncio.Server:
    """Liveness on a plain HTTP port, answered from the event loop: if the loop is wedged, the probe fails."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(reader.readline(), timeout=2)
            ok = processor.healthy
            status = b"200 OK" if ok else b"503 Service Unavailable"
            body = b"ok" if ok else b"worker pool broken"
            writer.write(
                b"HTTP/1.1 "
                + status
                + b"\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            await writer.drain()
        writer.close()

    return await asyncio.start_server(handle, "0.0.0.0", port)  # noqa: S104


async def serve(
    runtime: CaptureRuntime,
    *,
    port: int,
    keys_dir: str,
    workers: int = 2,
    grace_seconds: float = 300.0,
    health_port: int = 9001,
) -> None:
    factory = partial(make_executor, workers, keys_dir)
    executor = factory()
    # Start the worker processes now, before gRPC creates its threads.
    await asyncio.get_running_loop().run_in_executor(executor, worker.ping)
    lag = LagMonitor()
    lag.start()
    processor = CaptureProcessor(runtime, executor, lag, executor_factory=factory)
    health = await health_server(processor, health_port)
    server = grpc.aio.server()
    pbg.add_ExternalProcessorServicer_to_server(processor, server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    runtime.start()
    log.info("capture-extproc listening on :%s (instance %s)", port, runtime.instance_id)

    stop = asyncio.Event()
    with contextlib.suppress(NotImplementedError):
        import signal

        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop.set)
    await stop.wait()
    # Graceful drain: stop new streams, let in-flight ones finish (R2 mitigation 3).
    processor.accepting = False
    await server.stop(grace=grace_seconds)
    health.close()
    await runtime.shutdown()
    processor.executor.shutdown(wait=True)


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))

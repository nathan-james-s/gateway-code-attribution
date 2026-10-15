"""T038 spike: minimal pass-through ext_proc processor for agentgateway 1.6.0 (research R2).

Echoes every response body chunk unchanged and records, per stream, the chunk count, a SHA-256 of the bytes
seen, and the metadata context. Writes one JSON line per finished stream to $SPIKE_OUT. No content is written.
Env: SPIKE_PORT (9000), SPIKE_OUT, ECHO_DELAY (seconds before each echo; simulates a slow processor).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os

import grpc
from envoy.service.ext_proc.v3 import external_processor_pb2 as pb
from envoy.service.ext_proc.v3 import external_processor_pb2_grpc as pbg
from google.protobuf.json_format import MessageToDict

OUT = os.environ.get("SPIKE_OUT", "/tmp/extproc_spike.jsonl")
DELAY = float(os.environ.get("ECHO_DELAY", "0"))


class Echo(pbg.ExternalProcessorServicer):
    async def Process(self, request_iterator, context):  # type: ignore[no-untyped-def]
        chunks, digest, meta, path, eos = 0, hashlib.sha256(), {}, None, False
        async for req in request_iterator:
            which = req.WhichOneof("request")
            if req.HasField("metadata_context") and not meta:
                meta = MessageToDict(req.metadata_context).get("filterMetadata", {})
            if which == "request_headers":
                for h in req.request_headers.headers.headers:
                    if h.key == ":path":
                        path = h.raw_value.decode() if h.raw_value else h.value
                yield pb.ProcessingResponse(request_headers=pb.HeadersResponse())
            elif which == "response_headers":
                yield pb.ProcessingResponse(response_headers=pb.HeadersResponse())
            elif which == "request_body":
                yield pb.ProcessingResponse(request_body=pb.BodyResponse())
            elif which == "response_body":
                body = req.response_body.body
                eos = req.response_body.end_of_stream
                chunks += 1
                digest.update(body)
                if DELAY:
                    await asyncio.sleep(DELAY)
                yield pb.ProcessingResponse(
                    response_body=pb.BodyResponse(
                        response=pb.CommonResponse(
                            body_mutation=pb.BodyMutation(
                                streamed_response=pb.StreamedBodyResponse(body=body, end_of_stream=eos)
                            )
                        )
                    )
                )
            elif which == "response_trailers":
                yield pb.ProcessingResponse(response_trailers=pb.TrailersResponse())
            elif which == "request_trailers":
                yield pb.ProcessingResponse(request_trailers=pb.TrailersResponse())
        with open(OUT, "a") as f:
            f.write(
                json.dumps(
                    {
                        "path": path,
                        "chunks": chunks,
                        "sha256": digest.hexdigest(),
                        "eos": eos,
                        "metadata": meta,
                    }
                )
                + "\n"
            )


async def main() -> None:
    server = grpc.aio.server()
    pbg.add_ExternalProcessorServicer_to_server(Echo(), server)
    server.add_insecure_port(f"127.0.0.1:{os.environ.get('SPIKE_PORT', '9000')}")
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(main())

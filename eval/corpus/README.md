# The real-traffic corpus

Recorded responses from real coding tools, through the gateway, while their owner does the synthetic tasks in
[tasks.md](tasks.md) (T112; FR-045). A tool is listed as supported only once its corpus exists, with consent, and
passes conformance (T113; `docs/tools/supported.md`).

The recorder is a developer tool you run on your own machine, never part of the stack: the stack never stores
model output (Constitution II), and `scripts/check-no-recorder.sh --images` checks that no image contains it.

## Recording

1. Have the demo running and your tool working through the gateway (docs/tools/).
2. Consent, once per tool. This writes `eval/corpus/<tool>/consent.yaml`:

   ```bash
   python3 eval/corpus/record.py --tool claude-code --owner "Your Name" --i-consent
   ```

3. Start the recorder. It listens on port 4100 and forwards to the gateway on 4000:

   ```bash
   python3 eval/corpus/record.py --tool claude-code
   ```

4. Point the tool at `http://localhost:4100` instead of `:4000`, with the same gateway key, and do the tasks in
   [tasks.md](tasks.md), in order, in one fresh, empty folder. Each model response lands in
   `eval/corpus/<tool>/<api_format>/<n>.sse`. Requests and keys are never written.
5. Stop it with Ctrl+C. Write `eval/corpus/<tool>/setup.md`: the tool's version, and what you changed to route it
   (the endpoint and the credential only; no install, SC-011).

Only the synthetic tasks belong here. Review the recorded files before committing them.

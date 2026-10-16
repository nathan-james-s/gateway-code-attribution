# Validation: clean-machine quickstart run (task T120)

- **Date**: 2026-10-16
- **Machine**: MacBook Pro (Apple silicon), macOS 27.0.1, on battery, OrbStack for Docker. The project, its images,
  the kind cluster, uv's Python and the Homebrew tools were removed first, then reinstalled (not timed).
- **Versions**: kind v0.33.0 (node `kindest/node:v1.34.0`), helm v4.3.1, agentgateway v1.6.0, LiteLLM 1.105.1,
  gcattr 0.1.0, algorithm version 1.
- **Account**: personal (`nathan-james-s`), so section 3 (team roles) doesn't apply.
- **Guide**: `specs/001-gateway-code-attribution/quickstart.md` at `41a62c6`, followed as written.

## Section 1: SC-001, time to the first attributed PR

| Gateway | Timed | Result |
|---|---|---|
| agentgateway (steps 1–6) | about **9 min 30 s**: App created in 37 s, `make demo` 3 min 9 s (kind cluster creation excluded) | ✅ within 30 min |
| LiteLLM (step 7) | about **2 min**: `helm upgrade` 43 s, credential 5 s, `gca demo run` 45 s, check 30 s, not counting the recovery in finding 2 | ✅ within 30 min |

Installing the App on the sample repository was missed at first (finding 1). The check started as soon as it was
installed. The owner estimates the missed step at about 10 seconds, so the run wasn't repeated.

### Check results

| PR | AI unmodified | AI modified (anchored) | AI modified (broad) | Human | Indeterminate | Coverage | alg |
|---|---|---|---|---|---|---|---|
| [#1](https://github.com/nathan-james-s/gca-sample/pull/1) agentgateway | 47 | 1 | 2 | 8 | 35 | incomplete | 1 |
| [#2](https://github.com/nathan-james-s/gca-sample/pull/2) LiteLLM | 47 | 1 | 2 | 8 | 35 | incomplete | 1 |

| Expectation | Result |
|---|---|
| Step 1: App created, values and secret written (mode 0600, git-ignored) | ✅ |
| Step 3: all pods Ready, release deployed, URLs printed | ✅ |
| Step 4: credential issued once from the portal | ✅ |
| Step 5: every API format through the gateway, PR opened, check completes (neutral) with non-zero counts for every outcome | ✅ |
| Step 5: coverage `complete` | ❌ incomplete on both PRs (findings 3 and 4) |
| Step 6: the PR reaches the reporting view | ✅ one `v_change_summary` row per PR |
| Step 7: same counts as the first PR | ✅ |
| Step 7: same outcome for every line | ✅ 0 differences across 93 lines, but not independent (finding 5) |

## Findings

1. **The App install step is easy to miss, and missing it failed silently.** `gca demo init-repo` printed "Install
   the GitHub App on it next", but the step happens in the browser. `gca demo run` opened the PR anyway, and prcheck
   kept polling an App with no installations without logging anything. No check appeared and Grafana stayed empty.
   **Fixed** in [#12](https://github.com/nathan-james-s/gateway-code-attribution/pull/12): `init-repo` prints the
   install link, `gca demo run` stops with that link when the App isn't installed, and prcheck warns while the App
   has no installations.
2. **`make demo-upgrade GATEWAY=litellm` timed out with no ingest pod.** For 30 seconds after the restart, the kind
   API server rejected the controller-manager (`service account token has expired`). The Mac had just woken from
   sleep. Ingest uses the Recreate strategy: its old pod was removed, the new ReplicaSet was never created, and the
   rollout wait timed out. Every other deployment came up. `kubectl -n gca rollout restart deploy/gca-gca-ingest`
   recovered it. **Documented** in docs/install.md section 3. This is environmental (kind after host sleep), not
   the chart.
3. **PR #1's incomplete coverage was correct.** The Mac idle-slept three times while the demo ran: 15:05–15:08,
   15:20–15:31 and 15:40–15:43 UTC (`pmset -g log`). Each sleep froze the cluster, ingest recorded a
   `heartbeat_missed` loss, and the 15:05 one fell inside PR #1's matching window. **Documented**: the quickstart's
   prerequisites now say to keep the machine awake (`caffeinate -i`). A sleep marks every PR in the next 14 days
   (the default matching window) incomplete, so a laptop demo has to stay awake from install onwards.
4. **PR #2's incomplete coverage exposed two bugs, fixed in this change:**
   - **A gateway switch left an outage open forever.** When agentgateway's capture shut down for the upgrade, the
     old ingest (still configured for agentgateway) opened a "no capture running" outage for agentgateway. The new
     ingest only checks the configured gateway, LiteLLM, so nothing ever closed it. Every later PR showed "capture
     wasn't reporting … and it still isn't". CI's end-to-end test missed this only because its new ingest usually
     starts within the 15-second stale threshold. **Fix**: the sweeper ends `heartbeat_missed` losses of other
     gateways once the configured gateway's capture is active (`gca_ingest.loss._close_switched`).
   - **LiteLLM capture started on the first request, not at startup.** Until a request arrived, a freshly started
     proxy sent no heartbeats. On this run it didn't matter, because no LiteLLM capture had run before. But after
     any later restart, including every `make demo-upgrade`, ingest would see an outage until the first request.
     **Fix**: the handler starts capture when the proxy imports it inside its event loop at startup.
   - **Verified on this cluster**: after rebuilding and upgrading, LiteLLM's capture was heartbeating about 10 s
     after its pod started, with no request sent. The stuck agentgateway outage closed at that moment.
5. **Step 7's line-by-line comparison isn't independent in a manual run.** The demo writes identical code both
   times, and the manual run doesn't clear captures in between. So 33 of PR #2's 50 AI lines matched agentgateway
   captures from step 5, and only 17 matched LiteLLM's. That attribution is correct, but it doesn't prove LiteLLM
   parity on its own. The end-to-end test (`tests/e2e/test_us1_demo.py`, CI's `clean-install-and-privacy` job)
   clears captures between the gateways and compares line by line. It passed on main at `09398a6`.
   **Documented** in quickstart step 7.
6. **The guide's golden-corpus command ran no tests** (found in the section 6 run below). `uv run pytest
   lib/tests/golden` collects nothing (exit code 5): that directory holds the corpus and its generator, while the
   test is `lib/tests/test_golden.py`. **Fixed** in the quickstart.

Not guide issues: the first LiteLLM `gca demo run` got HTTP 401 because the key was read into a misspelled variable.
The two attempts were recorded as `unknown_credential` losses, which correctly don't affect coverage.

## Automated checks (sections 6 and 7)

Run on 2026-10-16, 16:35–17:15 UTC, by a Claude Code session at `7731f62`. Same Mac as section 1, on battery,
with `caffeinate -i` running throughout. The privacy audit and the CLI comparison in section 6 ran against the
section 1 cluster (kind-gca, namespace `gca`, Helm revision 4, gateway LiteLLM, rebuilt with finding 4's fixes).
`gca eval`, conformance and `make perf` start their own local gateways and PostgreSQL, so they don't use the
cluster. The fresh checkout needed `uv sync --all-packages -p 3.12` (docs/install.md) before anything ran.

### Privacy audit (SC-006): `uv run pytest tests/privacy`

✅ **6 passed, none skipped**, in 3 s. At the time the store held 104 captured lines, 186 line results (PRs #1 and
#2) and 6 LiteLLM spend-log rows. So every scan had something to look at, including the LiteLLM spend-log check.
No demo code line was found in PostgreSQL, the JetStream file store, any pod's logs, or Grafana's database. LiteLLM's
spend logs had no request or response content.

### Section 6: library reuse and determinism (SC-008)

| Step | Result |
|---|---|
| `uv run gca version` | ✅ `library_version: 0.1.0`, `alg: 1`, `supported_algs: [1]`, `pinned_unicode_version: 15.0.0` (interpreter 15.0.0) |
| Golden corpus on macOS | ✅ `uv run pytest lib/tests/test_golden.py lib/tests/test_determinism.py`: 7 passed. Linux and macOS: CI's `test-lib` matrix is green on main at `09398a6` |
| `GCA_E2E=1 GCA_E2E_REPO=nathan-james-s/gca-sample uv run pytest tests/integration/test_cli_matches_prcheck.py` | ✅ 1 passed. PR #2 at `209fc2b`: `gca attribute` on a fresh clone matched the PR check on all 93 lines (47 / 1 / 2 / 8 / 35, as in section 1) |

### Section 7: quality gate (SC-002–SC-007, SC-009, SC-010, SC-013)

**`make eval`**: ✅ exit code 0 after 3 min 23 s, on scenario set `17-scenarios-ba2b6ff80f75`. `report.json`
validates against `contracts/quality-report.schema.json`, and its `passed` is `true`.

| Gateway | Lines | Accuracy | False AI modified (anchored / broad) | Formatter false human | Rewrite survival | Silent loss | Verdict |
|---|---|---|---|---|---|---|---|
| agentgateway 1.6.0 | 375 | 0.987 | 0.000 / 0.000 | 0.000 | 1.000 | 0 | Release bar met |
| LiteLLM 1.105.1 | 375 | 0.987 | 0.000 / 0.000 | 0.000 | 1.000 | 0 | Release bar met |

Cross-gateway agreement: 1.000.

**`uv run pytest tests/conformance`** (FR-006): ✅ 60 passed in 2 min 43 s.

**`make perf`**: ✅ exit code 0 after 28 min 6 s, with the default settings: 500 users, 300 s per run, 10–60 s
think time, 2 s streams, and `PERF_SCALE=0.05`.

| Check | Result |
|---|---|
| SC-010, agentgateway | ✅ `p95 2345 ms without capture, 2387 ms with it: overhead +1.8%; 4170 requests, 4176 captured, 0 lost, 0 failed -> PASS` |
| SC-010, LiteLLM | ✅ `p95 2387 ms without capture, 2400 ms with it: overhead +0.5%; 4159 requests, 4162 captured, 0 lost, 0 failed -> PASS` |
| SC-009 / SC-013, PR check for 1,000 added lines | ✅ matching took 12.7 s (candidate lookup 18.0 s, measured separately) against 4,671,000 captured lines, with a 120 s budget. `passed: true`. Outcomes: 600 AI unmodified, 96 AI modified, 304 human. The generator plants 600 exact copies, 200 copies with one identifier renamed, and 200 new lines. So 104 renamed lines came out human. That's expected, and the check doesn't assert outcomes. These short synthetic lines have no anchor, so only the broad tier (similarity ≥ 0.75) applies. Measured over 2,000 such renames, the median similarity is 0.75 and 50% reach it |
| Storage per captured line (T115) | 1,476 bytes |
| Ingest rate, one replica (T115) | 4,881 lines/s (1,000 events, 40,000 lines in 8.2 s) |

The perf log also holds about 60 `ConnectionResetError` tracebacks. These come from the eval harness's stub upstream
model (`gca_eval.gateways._Upstream`, Python's `http.server`). It was waiting on an idle keep-alive connection when
the gateway under test shut down after its run, and they appear after Locust's final stats. No request failed. It's
log noise, not a result.

## Not yet run

These are for the owner:

- **Section 2 (edge cases)**: `gca demo scenarios` opens about 10 PRs on the sample repository.
- **Section 4 (coverage and fail-open)**.
- **The SC-011 check**: Claude Code through the gateway with only environment variables. It needs the owner's
  gateway key.

T120 stays open until these are recorded here.

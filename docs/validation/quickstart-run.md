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

7. **`scn-pending` never showed "Waiting for capture to catch up"** (section 2 below). The scenario scales ingest
   to zero, then opens its PR. But ingest runs as PID 1 and had no SIGTERM handler, so it ignored the signal and
   kept consuming for the full 30-second grace period, until Kubernetes killed it. It stored a heartbeat sent
   after the PR was recorded, the watermark passed the PR, and prcheck completed the check at once. The demo model
   had the same missing handler. This also explains the 30 seconds every ingest restart took (finding 2).
   **Fixed**: ingest stops consuming on SIGTERM and exits (measured on this cluster: gone 3 s after scaling to
   zero, before 30 s), the demo model exits on SIGTERM, and `scn-pending` waits until the ingest pod has gone
   before it opens the PR.

8. **Fault injection crashed with LiteLLM** (section 4 below). `gca demo run --inject-faults` sends deliberately
   broken responses. LiteLLM closes the connection when an upstream stream is malformed, while agentgateway
   passes it on, so the demo client raised `httpx.RemoteProtocolError` on the first `unexpected_format` fault and
   stopped. The fault had already gone through the gateway, and capture recorded it. **Fixed**: the client treats
   a cut connection on a fault request as sent, and carries on.

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

## Section 2: real PRs and edge cases (User Story 2)

Run by the owner at 18:05 UTC with LiteLLM: `gca demo scenarios --repo nathan-james-s/gca-sample` (PRs
[#3](https://github.com/nathan-james-s/gca-sample/pull/3)–[#11](https://github.com/nathan-james-s/gca-sample/pull/11)).
Each PR's per-line results in the store were compared with its answer key, `.gca-expected.json`, at every head.

| Case | PR | Lines matching the answer key | Result |
|---|---|---|---|
| unmodified AI lines | #11 | 11/11 | ✅ |
| edited AI lines | #4 | 17/17 | ✅ |
| typed-only lines | #9 | 8/8 | ✅ |
| braces, blanks, `else {` | #8 | 7/7 | ✅ |
| rebase onto a moved base, then squash (SC-004) | #7 | 16/16 at the final head | ✅ The first head was force-pushed within seconds, before the 30 s poll saw it. That's expected with polling delivery |
| cherry-pick (SC-004) | #3 | 10/10 | ✅ |
| PR opened while ingest is paused | #6 | 12/12 | ❌ the check never showed "Waiting for capture to catch up" (finding 7) |
| the same, rerun with finding 7's fix (`--only pending`, 22:27 UTC) | [#13](https://github.com/nathan-james-s/gca-sample/pull/13) | 12/12 | ✅ the check showed "Waiting for capture to catch up" while ingest was paused, then completed after it resumed |
| commit by an account with no gateway credential | #10 | 13/13 | ✅ |
| two mapped authors | — | — | skipped by the owner: needs a second GitHub account with a credential (`--second-login`, `GCA_CREDENTIAL_2`). No automated test covers it either, so crediting each line to its commit's author is unverified |
| a new push to an open PR | #5 | 8/8 and 13/13 | ✅ both heads attributed, the first kept |

Every check showed incomplete coverage, from the Mac's earlier sleeps (finding 3). The answer keys say
`complete`, but no line outcome depends on coverage. The report labels the run `agentgateway` because
`--gateway` wasn't passed. That flag only labels the report: traffic went through `--gateway-url`, here LiteLLM.

## Section 4: coverage and fail-open (User Story 4)

| Step | Result |
|---|---|
| 1. Injected faults: `--inject-faults truncated=3,unexpected_format=2 --faults-only` | ✅ exactly 3 `truncated` (Anthropic Messages) and 2 `unexpected_format` (OpenAI Responses) losses recorded, the source of the Coverage dashboard's per-cause panel. Fault-only traffic opens no PR and captures no lines, so none counted as human. The run stopped after the first `unexpected_format` fault (finding 8); after the fix, `unexpected_format=1` sent the second |
| 2. NATS stopped (`kubectl -n gca scale statefulset/gca-nats --replicas=0`), demo run, NATS restored | ✅ every gateway request succeeded and [#12](https://github.com/nathan-james-s/gca-sample/pull/12) opened. A `heartbeat_missed` loss covers the outage (18:10:49–18:11:03 UTC), and #12 shows incomplete coverage |

## SC-011: no install for coding tools

✅ Claude Code 2.1.292, run by the owner with LiteLLM, on their usual profile (signed in to claude.ai), with only
environment variables. `ANTHROPIC_BASE_URL=http://localhost:4000`, `ANTHROPIC_AUTH_TOKEN=<sk-gca- key from the
portal>`, `ANTHROPIC_MODEL`/`ANTHROPIC_SMALL_FAST_MODEL`/`ANTHROPIC_DEFAULT_HAIKU_MODEL=demo-anthropic`, and
`ANTHROPIC_API_KEY` unset. `claude -p "hello"` got the demo model's reply. Nothing was installed: no plug-in, hook
or settings change. The key took precedence over the claude.ai sign-in (Claude Code says so in a warning), so no
separate profile is needed. Claude Code also warns that `demo-anthropic` isn't in its model catalog, which only
affects its context-window estimate.

The first attempts got HTTP 401 because the token wasn't the current LiteLLM gateway key: an older key, then the
OpenRouter provider key. The gateway only accepts the personal `sk-gca-` key from the portal, and issuing a new
one replaces the previous key for that gateway.

## Not run

- **Section 2, two mapped authors**: skipped by the owner (see above).
- **Section 3 (reporting and roles)**: needs an organization with teams; the owner's App is on a personal account.
- **Section 5 (bring your own key)**: optional, and it spends provider credit.

Every other section of the quickstart was run on this machine for both gateways and is recorded above, with
each mismatch fixed. T120 is complete.

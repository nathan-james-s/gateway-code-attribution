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

Not guide issues: the first LiteLLM `gca demo run` got HTTP 401 because the key was read into a misspelled variable.
The two attempts were recorded as `unknown_credential` losses, which correctly don't affect coverage.

## Not yet run

Sections 2 (edge cases), 4 (coverage and fail-open), 6 (library reuse) and 7 (quality gate: `gca eval`,
`make perf`), `pytest tests/privacy`, and the SC-011 check (Claude Code through the gateway with only environment
variables). T120 stays open until these are recorded here.

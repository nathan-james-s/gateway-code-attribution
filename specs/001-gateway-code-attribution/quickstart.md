# Quickstart & Validation Guide: Gateway Code Attribution Reference Stack

This guide proves the feature works from end to end. Each section maps to a user story or success criterion in
[spec.md](./spec.md). Command names refer to targets and CLIs defined in [plan.md](./plan.md) and
[contracts/](./contracts/). They're validation steps, not implementation.

## Prerequisites

- Docker (or Podman), `kind` ≥ 0.27, `helm` ≥ 3.16, `kubectl`, Python 3.12 with `uv`, and the GitHub CLI `gh`,
  signed in.
- A GitHub organization you administer, for the full roles and teams demo. A personal account works too, but team
  and team-lead features need an organization.
- No model or API key is needed for the demo. Bring-your-own keys are optional (section 5).
- Keep the machine awake from step 3 on (on macOS, leave `caffeinate -i` running in another terminal). While it
  sleeps, capture stops sending heartbeats, so ingest records a capture gap. Every PR whose matching window
  (14 days by default) overlaps that gap then shows **incomplete** coverage, which is correct but fails the
  `complete` expectation in section 1.

## 1. Install and see a sample change (User Story 1, SC-001)

Start a timer when you start step 1. SC-001 allows 30 minutes to the first attributed demonstration PR, measured
with each gateway, excluding provisioning the cluster or machine: installing the prerequisites doesn't count, and
nor does the `creating kind cluster` part of step 3.

1. `uv run gca setup github-app --org <ORG> --namespace gca`
   Confirm the App's name in the browser and click **Create**.
   **Expect:** the GitHub App exists with exactly the permissions in
   [contracts/github-app.md](./contracts/github-app.md), and `values-github.yaml` and `github-app.secret.yaml`
   are written to the checkout (git-ignored).
2. `uv run gca demo init-repo --repo <ORG>/gca-sample`, then install the App on that repository only
   (docs/install.md 2.3).
   **Expect:** the repository has the sample project on `main`.
3. `make demo GATEWAY=agentgateway`
   This creates a kind cluster and installs the chart with `demo.enabled=true` and `prcheck.delivery=polling`.
   **Expect:** all pods Ready, `helm status` shows `deployed`, and the portal, gateway and Grafana URLs printed.
4. Open the portal (http://localhost:8080), sign in with GitHub, and select **Get gateway credential**.
   **Expect:** the key is shown once, and `/me` shows an active credential (FR-016).
5. `GCA_CREDENTIAL=<key> uv run gca demo run --repo <ORG>/gca-sample`
   **Expect:**
   - demo traffic for each API format passes through the gateway;
   - a demonstration PR opens;
   - within 2 minutes the check **AI code attribution** completes (neutral). Its summary shows non-zero counts
     for AI unmodified, AI modified (anchored), AI modified (broad), human and indeterminate, plus coverage
     `complete` and the `alg` version.
   **Stop the timer** when the check completes (SC-001).
6. Open the Grafana (http://localhost:3000) **Change** and **Repository** dashboards.
   **Expect:** the demonstration PR appears in the per-change, per-repository and team totals.
7. Switch to LiteLLM and repeat: `make demo-upgrade GATEWAY=litellm`, then in the portal **Get gateway
   credential** again (credentials are per gateway), then
   `GCA_CREDENTIAL=<litellm key> uv run gca demo run --repo <ORG>/gca-sample --gateway litellm`.
   Time it from the upgrade to the completed check.
   **Expect:** the second PR's check shows the same counts as the first, and its per-line view in the portal
   gives the same outcome for every line (User Story 1 scenario 5), with coverage `complete`. The demo writes the
   same code both times, so some of the second PR's lines may match the first run's agentgateway captures. That
   attribution is correct, but it means this manual step doesn't prove LiteLLM parity on its own. The end-to-end
   test does: it clears captures between the gateways and compares the two PRs line by line.

## 2. Real PRs and edge cases (User Story 2)

Run `GCA_CREDENTIAL=<key> uv run gca demo scenarios --repo <ORG>/gca-sample`. It replays scripted cases through
the gateway and opens one PR per case (pass `--only edited trivial` to run some). **Expect**, for each PR's check:

| Case | Expected result |
|---|---|
| unmodified AI lines | AI unmodified |
| edited AI lines | AI modified (anchored, high), or broad (lower) when there's no anchor in the file |
| typed-only lines | human |
| braces, blanks, `else {` | indeterminate, left out of percentages |
| rebase onto a moved base, squash, cherry-pick | AI lines keep attribution (SC-004) |
| PR opened while ingest is paused (`gca demo pause-ingest`) | check shows "Waiting for capture to catch up", then completes after resume, or after 10 minutes with incomplete coverage |
| commit by an account with no gateway credential (the `unmapped` case) | those lines are not observed |
| two mapped authors | each line credited to its commit's author |
| a new push to an open PR | new head attributed; earlier head kept |

## 3. Reporting and roles (User Story 3)

1. With the App on an organization that has teams: sign in as an **org owner**.
   **Expect:** `/developers/<login>` works for anyone.
2. Sign in as a **team maintainer**.
   **Expect:** `/teams/<slug>/developers` works for their team, and `/developers/<someone-else>` returns 403.
3. Sign in as a plain member.
   **Expect:** per-developer routes return 403 (FR-029, FR-029a).
4. In Grafana, switch **Include broad matches** off.
   **Expect:** only the broad AI-modified counts change, and `alg` is shown (FR-028).

## 4. Coverage and fail-open (User Story 4)

1. `GCA_CREDENTIAL=<key> uv run gca demo run --repo <ORG>/gca-sample --inject-faults truncated=3,unexpected_format=2 --faults-only`
   **Expect:** the Grafana **Coverage** dashboard shows exactly 3 truncated and 2 unexpected-format losses, none
   counted as human (SC-005).
2. Stop capture's path to ingest, run demo traffic, then restore it. With agentgateway,
   `kubectl -n gca scale deploy/gca-gca-capture-extproc --replicas=0`, then back to 2. With either gateway, stop NATS:
   `kubectl -n gca scale statefulset/gca-nats --replicas=0`, then back to 1.
   **Expect:** every gateway request succeeds (FR-005a). Coverage shows a loss period with cause
   `heartbeat_missed` or `buffer_overflow`. PRs whose window overlaps it show **incomplete coverage**.

## 5. Bring your own key (FR-039)

Create a Secret with a real provider key and add `providers.existingSecret` and `providers.models` to your values
([docs/install.md](../../docs/install.md#bring-your-own-provider-keys)), then `make demo-upgrade`. Configure one
in-scope tool from `/me/setup`, make a real change, and open a PR.
**Expect:** the same check behaviour on real traffic.

## 6. Library reuse and determinism (User Story 5, SC-008)

- `uv run gca version` shows the library semver, `ALG` and the pinned Unicode version.
- `uv run pytest lib/tests/test_golden.py` passes on Linux and macOS (CI matrix). `lib/tests/golden/` holds the
  corpus and its generator, not tests.
- `GCA_E2E=1 GCA_E2E_REPO=<ORG>/gca-sample uv run pytest tests/integration/test_cli_matches_prcheck.py`: it exports
  the captures behind the latest attributed demo PR (fingerprints only), runs `gca attribute` on a fresh clone, and
  checks it gives the same per-line outcomes as the PR check.

## 7. Quality gate (User Story 6, SC-002–SC-007)

- `uv run gca eval --scenarios eval/scenarios --gateway both --out report.json`
  **Expect:**
  - exit code 0;
  - `report.json` is valid against [contracts/quality-report.schema.json](./contracts/quality-report.schema.json);
  - each gateway shows accuracy ≥ 0.95, false AI modified ≤ 0.02 (anchored) and ≤ 0.05 (broad), formatter false
    human ≤ 0.10, history-rewrite survival 1.0 and silent loss 0;
  - `cross_gateway_agreement` is 1.0.
- `uv run pytest tests/conformance` (FR-006): identical fingerprint multisets per event across gateways.
- `uv run pytest tests/privacy` (SC-006), against the demo cluster after a demo run: no fixture code strings in
  Postgres, NATS, gateway logs, service logs or traces.
- `make perf` (SC-009, SC-010, SC-013): at 500 simulated developers, PR check ≤ 2 minutes for 1,000 added lines,
  and capture overhead ≤ 5% at p95 for each gateway.

## Clean up

`make demo-down` deletes the kind cluster. Uninstall the GitHub App and delete the sample repository from GitHub
by hand.

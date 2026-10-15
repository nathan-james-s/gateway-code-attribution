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

## 1. Install and see a sample change (User Story 1, SC-001)

Start a timer. SC-001 allows 30 minutes, excluding cluster provisioning.

1. `make demo GATEWAY=agentgateway`
   This creates a kind cluster and installs the chart with `demo.enabled=true` and `prcheck.delivery=polling`.
   **Expect:** all pods Ready, and `helm status` shows `deployed`.
2. `uv run gca setup github-app --org <ORG> --out values-github.yaml`, then
   `make demo-upgrade VALUES=values-github.yaml`.
   **Expect:** the GitHub App exists with exactly the permissions in
   [contracts/github-app.md](./contracts/github-app.md).
3. Create the sample repository from the template:
   `gh repo create <ORG>/gca-sample --template <project>/gca-sample --private`. Install the App on it.
4. Open the portal (localhost URL printed by `make demo`), sign in with GitHub, and select **Get gateway
   credential**.
   **Expect:** the key is shown once, and `/me` shows an active credential (FR-016).
5. `uv run gca demo run --repo <ORG>/gca-sample`
   **Expect:**
   - demo traffic for each API format passes through the gateway;
   - a demonstration PR opens;
   - within 2 minutes the check **AI code attribution** completes (neutral). Its summary shows non-zero counts
     for AI unmodified, AI modified (anchored), AI modified (broad), human and indeterminate, plus coverage
     `complete` and the `alg` version.
6. Open the Grafana **Change** and **Repository** dashboards.
   **Expect:** the demonstration PR appears in the per-change, per-repository and team totals.
   **Stop the timer** (SC-001).
7. Repeat steps 1–6 with `GATEWAY=litellm`.
   **Expect:** identical per-line outcomes. Compare with `uv run gca demo compare --pr <url-agentgateway>
   --pr <url-litellm>` (User Story 1 scenario 5).

## 2. Real PRs and edge cases (User Story 2)

Run `uv run gca demo scenarios --repo <ORG>/gca-sample`. It replays scripted cases through the gateway and opens
one PR per case. **Expect**, for each PR's check:

| Case | Expected result |
|---|---|
| unmodified AI lines | AI unmodified |
| edited AI lines | AI modified (anchored, high), or broad (lower) when there's no anchor in the file |
| typed-only lines | human |
| braces, blanks, `else {` | indeterminate, left out of percentages |
| rebase onto a moved base, squash, cherry-pick | AI lines keep attribution (SC-004) |
| PR opened while ingest is paused (`gca demo pause-ingest`) | check shows "Waiting for capture to catch up", then completes after resume, or after 10 minutes with incomplete coverage |
| commit by an unmapped account (`--as-unmapped`) | those lines are not observed |
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

1. `uv run gca demo run --inject-faults truncated=3,unexpected_format=2`
   **Expect:** the Grafana **Coverage** dashboard shows exactly 3 truncated and 2 unexpected-format losses, none
   counted as human (SC-005).
2. `kubectl scale deploy/gca-capture-extproc --replicas=0` (or stop NATS), run demo traffic, then restore.
   **Expect:** every gateway request succeeds (FR-005a). Coverage shows a loss period with cause
   `heartbeat_missed` or `buffer_overflow`. PRs whose window overlaps it show **incomplete coverage**.

## 5. Bring your own key (FR-039)

Create a Secret with a real provider key, then
`make demo-upgrade VALUES=values-byo.yaml` (with `providers.existingSecret` and `providers.models`). Configure one
in-scope tool from `/me/setup`, make a real change, and open a PR.
**Expect:** the same check behaviour on real traffic.

## 6. Library reuse and determinism (User Story 5, SC-008)

- `uv run gca version` shows the library semver, `ALG` and the pinned Unicode version.
- `uv run pytest lib/tests/golden` passes on Linux and macOS (CI matrix).
- `uv run gca attribute --repo <local clone> --base main --head <demo-branch> --captures <export>` gives the same
  per-line outcomes as the PR check for that head.

## 7. Quality gate (User Story 6, SC-002–SC-007)

- `uv run gca eval --scenarios eval/scenarios --gateway both --out report.json`
  **Expect:**
  - exit code 0;
  - `report.json` is valid against [contracts/quality-report.schema.json](./contracts/quality-report.schema.json);
  - each gateway shows accuracy ≥ 0.95, false AI modified ≤ 0.02 (anchored) and ≤ 0.05 (broad), formatter false
    human ≤ 0.10, history-rewrite survival 1.0 and silent loss 0;
  - `cross_gateway_agreement` is 1.0.
- `uv run pytest tests/conformance` (FR-006): identical fingerprint multisets per event across gateways.
- `uv run pytest tests/privacy` (SC-006): no fixture code strings in Postgres, NATS, gateway logs, service logs
  or traces after a full demo run.
- `make perf` (SC-009, SC-010, SC-013): at 500 simulated developers, PR check ≤ 2 minutes for 1,000 added lines,
  and capture overhead ≤ 5% at p95 for each gateway.

## Clean up

`make demo-down` deletes the kind cluster. Uninstall the GitHub App and delete the sample repository from GitHub
by hand.

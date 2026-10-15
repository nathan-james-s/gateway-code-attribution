# Contract: GitHub App (PR check and sign-in)

One App per install, created with `gca setup github-app` (manifest flow, R16). It provides the PR check (FR-023 to
FR-025) and GitHub sign-in for the portal and Grafana (FR-016, FR-029a).

## Permissions (least privilege; listed in docs with these reasons)

| Permission | Access | Why it's needed |
|---|---|---|
| Checks | write | create and update the attribution check run on each PR head (FR-024) |
| Pull requests | read | list PR commits, authors and merge state; receive PR events (FR-008, FR-018) |
| Contents | read | the compare API (added lines in `merge-base...head`) and GraphQL `blame` (line credit, R11). Content is held in memory only |
| Metadata | read | required by GitHub for every App |
| Members (organization) | read | sync teams, members, maintainers and owners for team totals and viewer roles (FR-027, FR-029a) |
| Email addresses (account) | read | Grafana's GitHub sign-in needs the user's verified email |

No write access to code, issues or pull requests is requested. **User authorization (OAuth)** is enabled with no
extra scopes. It's used only to identify the signed-in user and read their organization and team membership.

## Events subscribed

`pull_request` (opened, synchronize, reopened, closed), `check_run` (rerequested), `installation` and
`installation_repositories`, `membership`, `team`, `organization` (member and owner changes).

## Delivery modes

- **Webhook** (default when `prcheck.publicUrl` is set): signature verified with the App's webhook secret.
  Deliveries are deduplicated on `X-GitHub-Delivery` (FR-020).
- **Polling** (local demo): every 30 seconds, list open PRs in installed repositories and compare head SHAs. It
  produces the same internal events.

## Check run contract (per PR head)

- **Name**: `AI code attribution`. **Conclusion**: always `neutral` (informational, FR-025).
  **Status**: `queued` → `in_progress` → `completed`, with `pending` shown as `in_progress` and the title
  "Waiting for capture to catch up" (FR-017).
- **Title**: `AI 62% · human 30% · indeterminate 14 lines · coverage: complete`. Percentages exclude broad matches
  unless the install sets `report.headlineIncludesBroad: true`. The other figure is always shown in the summary.
- **Summary (markdown)**:
  - a table of counts and percentages using the standard display labels (T067): `AI, unmodified`; `AI, modified
    (anchored)` (high confidence); `AI, modified (broad)` (lower confidence); `Human`; `Indeterminate`. Below the
    outcome rows, separate counts for `Not observed` (a state, not an outcome) and `Excluded`. Percentages are
    computed over the `AI, …` and `Human` rows only. `Indeterminate`, `Not observed` and `Excluded` show counts
    only (FR-014);
  - coverage status, with reasons (losses overlapping the window, unmapped authors, unsupported combinations);
  - `alg`, the library version and the key generations;
  - excluded paths, each with its reason (`rule`, `binary` or `too_large`);
  - a link to the portal's per-line view;
  - a note on what "human" means: "no match to observed AI output".
- **Annotations**: notice-level only. Runs of consecutive lines with the same AI outcome are grouped into one
  annotation, at most 50 per update, batched as GitHub requires. Each annotation's message holds only the outcome,
  tier and confidence, never code.
- **Rerun**: `check_run.rerequested` re-attributes the same head idempotently.

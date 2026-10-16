# The GitHub App

Each install has its own GitHub App. It does two things: it posts the **AI code attribution** check on pull
requests (FR-023 to FR-025), and it signs people in to the portal and Grafana with GitHub (FR-016, FR-029a).
`gca setup github-app` creates it for you from a manifest ([install.md](install.md#22-creating-the-app)), with exactly
the permissions below. The authoritative list is
[contracts/github-app.md](../specs/001-gateway-code-attribution/contracts/github-app.md).

## Permissions

| Permission | Access | Why it's needed |
|---|---|---|
| Checks | write | create and update the attribution check run on each PR head (FR-024) |
| Pull requests | read | list PR commits, authors and merge state; receive PR events (FR-008, FR-018) |
| Contents | read | the compare API (added lines in `merge-base...head`) and GraphQL `blame` (which commit, and so which person, each line is credited to). Content is held in memory only, never stored or logged |
| Metadata | read | required by GitHub for every App |
| Members (organization) | read | sync teams, members, maintainers and owners for team totals and viewer roles (FR-027, FR-029a) |
| Email addresses (account) | read | Grafana's GitHub sign-in needs the user's verified email |

The App asks for **no write access to code, issues or pull requests**: the check run is the only thing it writes.
**User authorization (OAuth)** is enabled with no extra scopes; it only identifies who signed in and reads their
organization and team membership.

## Events

| Event | Why |
|---|---|
| `pull_request` (opened, synchronize, reopened, closed) | attribute each new PR head; record merges and closes |
| `check_run` (rerequested) | **Re-run** on the check re-attributes the same head |
| `installation`, `installation_repositories` | know which repositories the App can see (GitHub always sends these) |
| `membership`, `team`, `organization` | keep teams, maintainers and owners current for roles and team totals |

## Webhook or polling

| | Polling (`prcheck.delivery: polling`, the default) | Webhook (`prcheck.delivery: webhook`) |
|---|---|---|
| Needs | nothing reachable from the internet | a public HTTPS URL routing `/webhooks/github` to the PR check (`prcheck.publicUrl`, `prcheck.ingress`) |
| How it works | every 30 seconds, lists open PRs in the installed repositories and compares head SHAs | GitHub calls the PR check; each delivery's signature is verified with the App's webhook secret and deduplicated on `X-GitHub-Delivery` (FR-020) |
| Delay before a check starts | up to 30 seconds | seconds |
| GitHub API use | one listing per repository per 30 s, on top of attribution | attribution only |
| App setting | **Webhook → Active: off** | **Webhook → Active: on**, with the URL and a random secret |

Both produce the same internal events, so results are the same. Polling suits a local or private install; use
webhooks once the PR check has a public URL, or when many repositories make polling's API use noticeable (each
installation token allows 5,000 requests an hour; 15,000 on Enterprise Cloud).

To switch to webhooks later: set the App's webhook URL and secret in its GitHub settings, put the same secret in
the `webhookSecret` key of the App's Kubernetes Secret, and upgrade with `prcheck.delivery: webhook` and
`prcheck.publicUrl`.

## Uninstalling

1. **Stop the stack** (optional, any order): `helm uninstall gca -n gca`. The Postgres volume is kept unless you
   delete it; it holds per-line results and fingerprints, never code.
2. **Uninstall the App from the organization**: *Organization settings → GitHub Apps → (the App) → Configure →
   Uninstall*. The App immediately loses access to every repository; check runs it already posted stay on their
   PRs as a record.
3. **Delete the App**: *Developer settings → GitHub Apps → (the App) → Advanced → Delete GitHub App*. This
   invalidates its private key, client secret and webhook secret, and every user authorization for it.
4. **Remove local copies of its credentials**: the Kubernetes Secret (`kubectl -n gca delete secret
   gca-github-app`) and the git-ignored `github-app.secret.yaml` and `values-github.yaml` written by
   `gca setup github-app`.

People who signed in can also revoke their own authorization at any time under *Settings → Applications →
Authorized GitHub Apps*; they then have to sign in again to use the portal.

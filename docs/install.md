# Install

This guide brings up the reference stack on a local Kubernetes cluster and attributes a demonstration pull
request. Plan for about 30 minutes, excluding cluster provisioning (SC-001).

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker-compatible runtime | any | **OrbStack** works as is (kind runs its node as an OrbStack container). Docker Desktop and Podman also work. |
| `kind` | ≥ 0.27 | Default local cluster. Alternatively turn on OrbStack's built-in Kubernetes and use `CLUSTER=orbstack` (step 3). |
| `helm` | ≥ 3.16 | |
| `kubectl` | any recent | |
| `uv` + Python 3.12 | | `uv sync --all-packages -p 3.12` |
| `gh` | signed in | The demo pushes a branch and opens a PR as you |

Resources: about 4 CPUs and 6 GiB of memory free for the cluster.

## 2. GitHub: what you need and why

The stack talks to GitHub through **one GitHub App** per install. The App does two jobs: it runs the PR check, and
it signs people in to the portal and Grafana. You also need **a repository** for the PRs being attributed.

### 2.1 Where the App lives: use an organization

Create the App under a **GitHub organization you administer**. Teams, team maintainers and organization owners
drive the dashboard roles (FR-027, FR-029a), and only an organization has those. A personal account works for
the basic demo, but team totals and team-lead views will be empty. A free organization is enough.

### 2.2 Creating the App

Run:

```bash
uv run gca setup github-app --org <ORG> --namespace gca
```

This uses GitHub's *App manifest* flow. Your browser opens GitHub with every setting pre-filled; you confirm the
App's name and click **Create**. GitHub redirects back to a temporary listener on `localhost`. The tool then
writes two git-ignored files, readable only by you: `values-github.yaml`, and `github-app.secret.yaml`, a
Kubernetes Secret holding the App ID, client ID, client secret, private key and webhook secret. Nothing is
shipped with default secrets (FR-035), and no secret is printed.

**Already created the App by hand?** Package its credentials the same way. On the App's settings page note the
App ID and client ID, generate a client secret, and generate and download a private key (`.pem`). Then run:

```bash
uv run gca setup github-app --existing --namespace gca \
  --app-id <APP_ID> --client-id <CLIENT_ID> --private-key-file ~/Downloads/<app>.private-key.pem
```

It prompts for the client secret (hidden), and for a webhook secret, which you can leave empty for a local
install. Secrets go into the local Secret file only; never paste them into chats, issues or shell history.

The manifest sets exactly the following. To create the App by hand, under *Settings → Developer settings →
GitHub Apps*, use the same values:

| Setting | Value | Why |
|---|---|---|
| Owner | your organization | roles and teams come from it |
| GitHub App name | for example `gca-<org>-local` | must be unique on GitHub |
| Homepage URL | `http://localhost:8080` | the portal |
| Callback URLs | `http://localhost:8080/auth/callback` and `http://localhost:3000/login/github` | GitHub sign-in for the portal and gateway credentials (FR-016). `localhost` works because only your browser follows it. |
| Expire user authorization tokens | on | default |
| Request user authorization (OAuth) during installation | off | people sign in at the portal instead |
| Webhook → Active | **off** for a local install | GitHub can't reach `localhost`, so the stack **polls** every 30 s (`prcheck.delivery: polling`) |
| Webhook URL / secret | only with a public URL: `https://<host>/webhooks/github` plus a random secret | set `prcheck.delivery: webhook` |
| **Repository permissions** | Checks: **Read and write** · Contents: **Read** · Pull requests: **Read** · Metadata: **Read** (mandatory) | write the check run; read diffs and blame (in memory only); read PR commits and authors |
| **Organization permissions** | Members: **Read** | teams, team maintainers and owners for roles and team totals |
| Account permissions | Email addresses: **Read** | Grafana sign-in needs your verified email |
| Subscribe to events (webhook mode only) | Pull request, Check run, Membership, Team, Organization | new heads, re-runs, team and role changes |
| Where can this App be installed? | Only on this account | |

The App never gets write access to code, issues or pull requests. `docs/github-app.md` explains each permission.

### 2.3 Installing the App

On the App's page choose **Install App → your organization → Only select repositories** and pick the sample
repository (2.4). You can add real repositories later; the App only ever writes check runs.

### 2.4 The sample repository

Create a private repository in the organization, for example `<ORG>/gca-sample`, with the demo's sample content:

```bash
uv run gca demo init-repo --repo <ORG>/gca-sample
```

This creates the repository if needed, and pushes the sample project to `main` from `services/demo/sample-repo/`.
Then install the App on it (2.3). No branch protection is needed; the check is informational and never blocks
merging (FR-025).

### 2.5 Your identity

Sign in to the portal with the **same GitHub account `gh` uses**. The demo commits and opens the PR as that
account. Your gateway credential is issued to that account, so the demo's AI output is matched to your commits
(FR-012, FR-016).

### 2.6 Teams, optional, for trying roles (US3)

In the organization create one or two teams, for example `platform` and `payments`. Make yourself a
**maintainer** of one, so you see the team-lead view, and add a second account if you have one. Organization
owners are admins in the portal.

### 2.7 CI only

The project's own CI uses a separate test App and test repository through the repository secrets
`GCA_E2E_APP` (App ID, private key, installation ID) and `GCA_E2E_REPO`. You don't need these to run the demo.

## 3. Install the stack

```bash
make demo GATEWAY=agentgateway        # or GATEWAY=litellm
```

`make demo` creates a kind cluster named `gca`, applies `github-app.secret.yaml`, builds and loads the images, and
installs the chart in namespace `gca` with demo mode on, using `values-github.yaml`. Pass `VALUES=` and `SECRET=`
if your files are elsewhere. It maps **http://localhost:8080** (portal), **http://localhost:4000** (gateway) and
**http://localhost:3000** (Grafana) to your machine. Re-run it, or `make demo-upgrade`, after changing code or
values.

With OrbStack's own Kubernetes (`orb config set k8s.enable true`), run `make demo CLUSTER=orbstack` instead. Images
built with OrbStack's Docker are visible to its Kubernetes without loading; reach the services with
`kubectl port-forward`.

## Bring your own provider keys

To drive real coding tools against real models (FR-039), create a Secret with any of `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY` and `GEMINI_API_KEY`, and list the model routes the gateway should offer:

```bash
kubectl -n gca create secret generic provider-keys \
  --from-literal=ANTHROPIC_API_KEY=... --from-literal=OPENAI_API_KEY=...
```

```yaml
# values-byo.yaml (git-ignored)
providers:
  existingSecret: provider-keys
  models:
    - {name: claude-sonnet-4-5, provider: anthropic, model: claude-sonnet-4-5}
    - {name: gpt-5, provider: openAI, model: gpt-5}
```

Install with `-f values-byo.yaml` as well. Demo routes stay available alongside in demo mode. Then point your tools
at the gateway: [tools/](tools/README.md).

## 4. Run the demo

1. Open http://localhost:8080, sign in with GitHub, choose **Get gateway credential**, and copy the key. It's shown
   once.
2. Run:

   ```bash
   GCA_CREDENTIAL=<key> uv run gca demo run --repo <ORG>/gca-sample   # add --gateway litellm for LiteLLM
   ```

3. Open the PR it prints. Within about 2 minutes the **AI code attribution** check shows per-line outcomes, and the
   change appears in the Grafana dashboards.

What the outcomes mean: [outcomes.md](outcomes.md).

## 5. Clean up

```bash
make demo-down
```

This deletes the cluster. Delete the GitHub App and the sample repository on GitHub by hand.

# Configuration reference

Every Helm value of the chart (`charts/gateway-code-attribution`), with its default. Generated from
`values.schema.json` and `values.yaml` by `scripts/gen-config-reference.py`; edit those, not this file.
Install and upgrade validate values against the schema. Secrets are always referenced by Secret name,
never put in values.

## `gateway`

The AI gateway developers' coding tools connect to (FR-001).

| Key | Type | Default | Description |
|---|---|---|---|
| `gateway.type` | `agentgateway` \| `litellm` | `agentgateway` | `agentgateway` (with the capture-extproc processor) or `litellm` (with the capture callback). Required. |
| `gateway.publicUrl` | string | *(empty)* | The URL developers' tools use to reach the gateway. Empty: the cluster Service, reached with port-forward or `expose`. |
| `gateway.agentgateway` | object |  | agentgateway's image. |
| `gateway.agentgateway.image` | object |  | agentgateway image. |
| `gateway.agentgateway.image.repository` | string | `cr.agentgateway.dev/agentgateway` | image repository |
| `gateway.agentgateway.image.tag` | string | `v1.6.0` | image tag |
| `gateway.agentgateway.image.digest` | string | `sha256:9d3e6044ddcdc0878b1787f77bd401252b95e22684203fb5e874c4c42d2…` | sha256 digest; pinned for every third-party image (Constitution VI, scripts/pin-digests.sh) |
| `gateway.litellm` | object |  | This project's LiteLLM image (LiteLLM plus the capture callback). |
| `gateway.litellm.image` | object |  | LiteLLM image. |
| `gateway.litellm.image.repository` | string | `ghcr.io/nathan-james-s/gca-litellm` | image repository |
| `gateway.litellm.image.tag` | string | `v1.105.1-gca0.1.0` | image tag |
| `gateway.litellm.image.digest` | string | *(empty)* | sha256 digest; pinned for every third-party image (Constitution VI, scripts/pin-digests.sh) |

## `capture`

The capture processor for agentgateway (capture-extproc).

| Key | Type | Default | Description |
|---|---|---|---|
| `capture.replicas` | integer | `2` | Replicas of capture-extproc. At least 2, so one can restart while the other serves (R2). docs/sizing.md: about one per 500 developers. |

## `providers`

Bring-your-own provider keys (FR-039). Empty in demo mode.

| Key | Type | Default | Description |
|---|---|---|---|
| `providers.existingSecret` | string | *(empty)* | Secret holding the provider API keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or the names given in `apiKeyName`. |
| `providers.models` | list of object | *(empty)* | Model routes. A tool asks for a route by `name`; the gateway calls `model` at `provider`. |
| `providers.models[].name` | string |  | The model name tools request (for example `claude-sonnet-5-5`). |
| `providers.models[].provider` | `anthropic` \| `openAI` \| `gemini` |  | The API the gateway speaks to the provider. |
| `providers.models[].model` | string |  | The provider's model ID (for OpenRouter, for example `anthropic/claude-sonnet-5.5`). |
| `providers.models[].baseUrl` | string |  | An API-compatible service instead of the provider itself, for example `https://openrouter.ai/api/v1`. |
| `providers.models[].apiKeyName` | string |  | The key in `providers.existingSecret` holding this route's API key (default: the provider's). |

## `github`

The GitHub App, from `gca setup github-app` (FR-035). Secrets are referenced, never put in values.

| Key | Type | Default | Description |
|---|---|---|---|
| `github.existingSecret` | string | *(empty)* | Secret with keys `appId`, `clientId`, `clientSecret`, `privateKey`, `webhookSecret`. |
| `github.org` | string | *(empty)* | The organization whose owners, teams and maintainers drive roles and team totals (FR-027, FR-029a). |
| `github.host` | `github.com` | `github.com` | GitHub.com (including Enterprise Cloud); the only host in v1. |

## `prcheck`

The PR check service (FR-023 to FR-025).

| Key | Type | Default | Description |
|---|---|---|---|
| `prcheck.delivery` | `polling` \| `webhook` | `polling` | `polling` (every 30 s; nothing public needed) or `webhook` (needs `publicUrl`). See docs/github-app.md. |
| `prcheck.publicUrl` | string | *(empty)* | Public HTTPS URL GitHub delivers webhooks to (`{publicUrl}/webhooks/github`). Required for `webhook`. |
| `prcheck.pendingCapMinutes` | integer | `10` | How long a head waits for capture to catch up before it's attributed anyway, with coverage marked (R12). |
| `prcheck.headlineIncludesBroad` | boolean | `false` | Count broad (lower-confidence) matches in the check run's headline percentages. Always shown in the summary. |
| `prcheck.ingress` | object |  | An Ingress for webhooks. |
| `prcheck.ingress.enabled` | boolean | `false` | Create the Ingress. |
| `prcheck.ingress.className` | string | *(empty)* | IngressClass name. |
| `prcheck.ingress.annotations` | object |  | Annotations for the Ingress (for example cert-manager's). |
| `prcheck.ingress.tlsSecret` | string | *(empty)* | TLS Secret for the Ingress host. |

## `attribution`

Matching settings. Applied at install and upgrade; admins can change them in the portal (US3).

| Key | Type | Default | Description |
|---|---|---|---|
| `attribution.matchingWindowDays` | integer | `14` | How far back from a PR head captured AI output can match its lines. |
| `attribution.retentionDays` | integer | `90` | Days captured fingerprints are kept (daily partitions are dropped after this). Storage grows with it: docs/sizing.md. |
| `attribution.exclusions` | list of string | `["**/*.lock", "**/package-lock.json", "**/vendor/**", "**/node_mod…` | Glob patterns of files never attributed (listed as excluded in the check). |

## `perDeveloper`

Per-developer views in the portal (FR-029).

| Key | Type | Default | Description |
|---|---|---|---|
| `perDeveloper.enabled` | boolean | `true` | Show per-developer results at all. |
| `perDeveloper.visibleRoles` | list of `admin` \| `team_lead` | `["admin", "team_lead"]` | Roles that see other developers' results: `admin`, and `team_lead` for their own teams. |

## `fingerprintKey`

The keyed-fingerprint secret (R8).

| Key | Type | Default | Description |
|---|---|---|---|
| `fingerprintKey.existingSecret` | string | *(empty)* | A Secret to use. Empty: generated at install and kept across upgrades; rotate in the portal. |

## `postgres`

PostgreSQL 17 (R14).

| Key | Type | Default | Description |
|---|---|---|---|
| `postgres.internal` | boolean | `true` | Run the official postgres:17 image as a StatefulSet. `false`: use `external`. |
| `postgres.storage` | string | `200Gi` | Volume size for the internal database. 200Gi holds 90 days for 500 developers (docs/sizing.md). |
| `postgres.external` | object |  | An existing PostgreSQL 17 (needs the btree_gin extension, which ships with PostgreSQL). |
| `postgres.external.host` | string | *(empty)* | Host. Required when `internal` is false. |
| `postgres.external.port` | integer | `5432` | Port. |
| `postgres.external.database` | string | *(empty)* | Database name. |
| `postgres.external.existingSecret` | string | *(empty)* | Secret with `username`, `password` and `reportingPassword` (Grafana's read-only role). Required when `internal` is false. |
| `postgres.storageClassName` | string | *(empty)* | StorageClass for the volume (empty: the cluster default). |
| `postgres.image` | object |  | The internal database image. |
| `postgres.image.repository` | string | `docker.io/library/postgres` | image repository |
| `postgres.image.tag` | string | `17` | image tag |
| `postgres.image.digest` | string | `sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddb…` | sha256 digest; pinned for every third-party image (Constitution VI, scripts/pin-digests.sh) |

## `portal`

The portal: sign-in, gateway credentials, per-developer views, admin settings.

| Key | Type | Default | Description |
|---|---|---|---|
| `portal.adminLogins` | list of string | *(empty)* | GitHub logins with the admin role besides the organization's owners (needed on a personal account). |
| `portal.publicUrl` | string | *(empty)* | The browser-reachable portal URL (GitHub sign-in returns here). |

## `demo`

Demo mode (FR-038): a deterministic model, so the stack runs with no provider key.

| Key | Type | Default | Description |
|---|---|---|---|
| `demo.enabled` | boolean | `false` | Deploy demo-model and route the demo model names (`demo-anthropic`, `demo-openai`, `demo-gemini`) to it. |
| `demo.agent` | object |  | The scripted demo agent. |
| `demo.agent.enabled` | boolean | `true` | Allow `gca demo run` against this install. |

## `images`

This project's images (built by scripts/build-images.sh, released by release.yml).

| Key | Type | Default | Description |
|---|---|---|---|
| `images.registry` | string | `ghcr.io/nathan-james-s` | Registry and owner of the `gca-*` images. |
| `images.tag` | string | `0.1.0` | Tag of the `gca-*` images. |
| `images.pullPolicy` | `Always` \| `IfNotPresent` \| `Never` | `IfNotPresent` | Image pull policy for the `gca-*` images. |
| `images.digests` | object |  | Digest per image name (`capture-extproc`, `ingest`, `prcheck`, `portal`, `demo`). A release sets them from the images it builds, so the chart pins them (T119). |

## `networkPolicies`

NetworkPolicies (T116).

| Key | Type | Default | Description |
|---|---|---|---|
| `networkPolicies.enabled` | boolean | `true` | Only the services that use them reach PostgreSQL, NATS, the capture processor and the demo model. Needs a network plugin that enforces NetworkPolicy. |

## `expose`

For local clusters: NodePorts that kind maps to localhost (scripts/demo.sh).

| Key | Type | Default | Description |
|---|---|---|---|
| `expose.nodePorts` | boolean | `false` | Expose the portal and gateway on NodePorts. |
| `expose.portal` | integer | `30080` | The portal's NodePort. |
| `expose.gateway` | integer | `30400` | The gateway's NodePort. |

## `nats`

The official NATS chart (JetStream, single node), passed through: see its documentation. Set here: JetStream on a 10Gi volume, Pod Security "restricted" security contexts, no nats-box.

| Key | Type | Default | Description |
|---|---|---|---|
| `nats.enabled` | boolean | `true` | Deploy NATS. Capture and ingest need it unless you point them at your own. |

## `grafana`

The grafana-community chart, passed through: see its documentation. Set here: GitHub sign-in, the read-only Postgres datasource, the dashboards, and `publicUrl`.

| Key | Type | Default | Description |
|---|---|---|---|
| `grafana.enabled` | boolean | `true` | Deploy Grafana with the aggregate dashboards (R15). |
| `grafana.publicUrl` | string | `http://localhost:3000` | The browser-reachable Grafana URL (GitHub sign-in returns here). |

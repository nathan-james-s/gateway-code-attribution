# Contract: Helm chart values (`charts/gateway-code-attribution`)

The adopter-facing install contract (FR-037, R17). Keys not listed here are internal and may change in a minor
release. Every image is pinned by tag and digest in `values.yaml`.

```yaml
gateway:
  type: agentgateway            # REQUIRED: agentgateway | litellm (FR-001)
  publicUrl: ""                 # URL developers' tools use; default is a cluster Service plus port-forward instructions
  agentgateway:
    image: {tag: "1.6.0", digest: "sha256:…"}
  litellm:
    image: {tag: "v1.105.1", digest: "sha256:…"}   # with the gcattr_litellm callback baked in (built by this project)

providers:                      # BYO hosted key mode (FR-039); empty in demo mode
  existingSecret: ""            # Secret with ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
  models: []                    # [{name, provider: anthropic|openAI|gemini, model}]

demo:
  enabled: false                # true → deploys demo-model and routes the demo model names to it (FR-038)
  agent: {enabled: true}        # demo-agent Job (runs on `helm test` or `gca demo run`)

github:                         # from `gca setup github-app` (never shipped with defaults; FR-035)
  existingSecret: ""            # appId, clientId, clientSecret, privateKey, webhookSecret
  org: ""                       # organization whose teams and owners drive roles (FR-027, FR-029a)
  host: github.com              # GitHub.com / Enterprise Cloud only in v1

prcheck:
  delivery: polling             # polling (local) | webhook (needs publicUrl)
  publicUrl: ""
  pendingCapMinutes: 10         # R12
  headlineIncludesBroad: false

attribution:
  matchingWindowDays: 14
  retentionDays: 90
  exclusions: ["**/*.lock", "**/package-lock.json", "**/vendor/**", "**/node_modules/**", "**/*.min.*", "**/dist/**"]

perDeveloper:
  enabled: true                 # FR-029 default
  visibleRoles: [admin, team_lead]

fingerprintKey:
  existingSecret: ""            # otherwise generated at install and kept across upgrades (lookup); rotate via the portal

postgres:
  internal: true                # official postgres:17 StatefulSet (no Bitnami)
  storage: 200Gi                # sized for SC-013; see docs/sizing.md
  external: {host: "", port: 5432, database: "", existingSecret: ""}

nats:                           # official nats-io chart dependency, JetStream single node
  enabled: true

grafana:                        # grafana-community chart dependency
  enabled: true
  githubOAuth: {allowedOrganizations: ""}   # reuses the GitHub App's OAuth client

portal:
  publicUrl: ""                 # browser-reachable URL; localhost works for the demo
```

## Validation (enforced by `values.schema.json` and a pre-install hook)

- `gateway.type` must be `agentgateway` or `litellm`.
- `github.existingSecret` is required unless `demo.enabled: true` with `prcheck.delivery: polling` and a
  `github.existingSecret` supplied by `gca setup` output. Install fails fast with a message rather than starting a
  partly configured stack.
- `prcheck.delivery: webhook` requires `prcheck.publicUrl`.
- If `postgres.internal: false`, `postgres.external.host` and `postgres.external.existingSecret` are required.
- No value may hold a secret inline. Secrets are referenced only through `existingSecret`, or generated
  (Constitution: Security & Data Handling).

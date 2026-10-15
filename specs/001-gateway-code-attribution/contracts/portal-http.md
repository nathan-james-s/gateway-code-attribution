# Contract: Portal HTTP interface

Sign-in, gateway credentials, overrides, role-checked per-developer views, and per-line PR views. Server-rendered
HTML, with JSON variants under `/api`. Every route except `/healthz` and `/auth/*` needs a GitHub sign-in session.
**Responses never contain code or prompt text.** Per-line views show positions and outcomes, with links to the
lines on GitHub.

## Roles (FR-029, FR-029a)

`admin`, `team_lead(team)` and `other`, resolved as described in [data-model.md](../data-model.md#viewerrolegrant).
**403** is returned whenever a role check fails. The response doesn't reveal whether the requested developer or
team exists.

## Routes

| Method & path | Role | Purpose | Notes |
|---|---|---|---|
| `GET /auth/login`, `GET /auth/callback` | anyone | GitHub sign-in through the App's user authorization | sets an HttpOnly, Secure, SameSite=Lax session |
| `POST /auth/logout` | signed in | end the session | |
| `GET /me` | signed in | profile, roles, credential status | |
| `POST /me/credential` | signed in | issue a personal gateway credential; **the key is shown once** | revokes the previous active credential (one active per developer); creates the gateway key (R5) |
| `DELETE /me/credential` | signed in | revoke your own credential | FR-016 |
| `GET /me/setup` | signed in | copy-paste routing instructions for each in-scope tool, with the gateway URL | per-tool table from R6 |
| `GET /changes/{repo}/{pr}` | anyone who can view the repo on GitHub (checked through the user's token) | per-line results for the latest and final heads: path, line, outcome, tier, confidence, credited login; links to GitHub | no line content |
| `GET /developers/{github_login}` | admin, or team_lead of a team containing that developer | per-developer totals over a period, with and without broad | FR-029; 403 otherwise |
| `GET /teams/{slug}/developers` | admin, or team_lead(slug) | per-developer breakdown inside a team | |
| `GET /coverage` | signed in | links to the Grafana coverage dashboard, plus the unmapped-author list | FR-030 |
| `GET /admin/overrides` / `POST` / `DELETE /admin/overrides/{id}` | admin | identity overrides | FR-016; `reason` required |
| `GET/POST /admin/roles`, `GET/POST /admin/teams` | admin | role and team overrides | FR-027, FR-029a |
| `GET/POST /admin/settings` | admin | `per_developer_enabled`, `visible_roles`, window, retention, exclusions | |
| `POST /admin/credentials/{id}/revoke` | admin | revoke any developer's credential | |
| `POST /admin/keys/rotate` | admin | start a fingerprint key rotation (new active generation; the old one retires) | FR-036 |
| `GET /healthz`, `GET /readyz` | none | probes | |

## API errors

Errors are JSON `{ "error": "<code>", "message": "<text>" }` with codes `unauthenticated` (401), `forbidden`
(403), `not_found` (404), `conflict` (409, for example a duplicate override) and `invalid` (422).

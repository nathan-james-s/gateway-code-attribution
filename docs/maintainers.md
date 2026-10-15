# Maintainers

## Required status checks

Protect `main` and require these checks (constitution "Development Workflow & Quality Gates"):

| Check | Workflow | Gate | Runs when |
|---|---|---|---|
| `lint`, `test-lib`, `test-services`, `helm-lint` | `ci.yml` | baseline | every PR |
| `golden-frozen` | `ci.yml` | golden corpora never change; a new one comes with a higher `ALG` (Principle III, FR-032) | every PR |
| `no-recorder` | `gates.yml` | no retained code or prompts (Principle II) | every PR |
| `conformance` | `gates.yml` | gateway capture changes | `lib/**`, `services/core/**`, `services/capture-*/**` |
| `clean-install-and-privacy` | `gates.yml` | stack changes (clean install of each gateway to first result, M7; identical outcomes across gateways) and data-path changes (privacy audit, same cluster) | `lib/**`, `services/**`, `charts/**` |

Jobs skipped by their path filter report success, so they can stay required.

## Repository secrets

- `GCA_E2E_APP`: JSON with `appId`, `privateKey`, `installationId`, `clientId` and `clientSecret` of a test GitHub
  App installed on the test repository.
- `GCA_E2E_REPO`: `OWNER/NAME` of the test repository, holding the sample project (`gca demo init-repo`).
- `GCA_E2E_GH_TOKEN`: a token for the GitHub account the demo commits as. It needs `repo` access to the test
  repository. The test issues that account a gateway credential with the portal's operator command
  (`python -m gca_portal.admin_cli issue-credential`), so no browser sign-in is needed.

The end-to-end test opens one PR per gateway in the test repository and closes it (deleting its branch) at the
end. To run it locally against your own demo cluster:

```bash
GCA_E2E=1 GCA_E2E_REPO=OWNER/NAME uv run pytest tests/e2e/test_us1_demo.py tests/privacy -s --gateway both
```

It reinstalls the release and clears captured fingerprints between gateways.

The other end-to-end tests run against the demo install that's already up, without reinstalling:

```bash
GCA_E2E=1 GCA_E2E_REPO=OWNER/NAME uv run pytest tests/e2e/test_us4_coverage.py -s     # coverage and fail-open
GCA_E2E=1 GCA_E2E_REPO=OWNER/NAME uv run pytest tests/integration/test_cli_matches_prcheck.py -s
```

## Releasing

A `v*` tag runs `.github/workflows/release.yml`. The tag must equal the version in `lib/pyproject.toml`,
`Chart.yaml` (`version` and `appVersion`) and `values.yaml` (`images.tag`); the first job fails otherwise. It then:

1. runs the library tests (with the golden corpus), builds the `gcattr` wheel and sdist and writes `SHA256SUMS`;
2. publishes them to PyPI through trusted publishing, with attestations;
3. builds and pushes the six service images to `ghcr.io/<owner>` for amd64 and arm64, with build provenance;
4. packages the chart with a checksum and pushes it to `oci://ghcr.io/<owner>/charts`;
5. creates the GitHub Release with the library files, the chart, and every image digest in the notes.

One-time setup:

- On PyPI, add a trusted publisher for project `gcattr`: this repository, workflow `release.yml`, environment
  `pypi`. In the repository settings, create the `pypi` environment (optionally with required reviewers).
- After the first image push, make the `ghcr.io` packages public if adopters should pull without credentials.

Version bumps: a change that alters any fingerprint or outcome raises `ALG` and is at least a minor release
(docs/library.md).

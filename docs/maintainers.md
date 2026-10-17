# Maintainers

## Required status checks

Protect `main` and require these checks (constitution "Development Workflow & Quality Gates"):

| Check | Workflow | Gate | Runs when |
|---|---|---|---|
| `lint`, `test-lib`, `test-services`, `helm-lint` | `ci.yml` | baseline | every PR |
| `golden-frozen` | `ci.yml` | golden corpora never change; a new one comes with a higher `ALG` (Principle III, FR-032) | every PR |
| `release-bar` | `gates.yml` | the spec's SC-002/SC-003 numbers equal the schema's `release_bar` constants (FR-044) | every PR |
| `no-recorder` | `gates.yml` | no retained code or prompts (Principle II) | every PR |
| `conformance` | `gates.yml` | gateway capture changes | `lib/**`, `services/core/**`, `services/capture-*/**` |
| `clean-install-and-privacy` | `gates.yml` | stack changes (clean install of each gateway to first result, M7; identical outcomes across gateways) and data-path changes (privacy audit, same cluster) | `lib/**`, `services/**`, `charts/**` |

Jobs skipped by their path filter report success, so they can stay required.

`release-gate` (`release-gate.yml`) runs the scenario set through both gateways on every PR to `main` and uploads
the quality report. `release.yml` requires it, so no release is published below the bar (Principle V). It passes
(accuracy 0.987 on both gateways, 2026-10-16), so make it a required merge check too. Branch protection is free on a
public repository.

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

**Not released, and no release is planned.** The owner deferred the first release (v0.1.0) on 2026-10-16 and on
2026-10-17 dropped the open-source release altogether: the repository is public as source-available code
([LICENSE](../LICENSE)), nothing has been tagged, and nothing is on PyPI or ghcr.io. The workflow below still
works; if a release is ever wanted, do the one-time setup first, then push the tag.

A `v*` tag runs `.github/workflows/release.yml`. The tag must equal the version in `lib/pyproject.toml`,
`Chart.yaml` (`version` and `appVersion`) and `values.yaml` (`images.tag` and `gateway.litellm.image.tag`); the
first job fails otherwise. It then:

1. runs the library tests (with the golden corpus), builds the `gcattr` wheel and sdist and writes `SHA256SUMS`;
2. publishes them to PyPI through trusted publishing, with attestations;
3. builds and pushes the six service images to `ghcr.io/<owner>` for amd64 and arm64, with build provenance;
4. packages the chart with a checksum and pushes it to `oci://ghcr.io/<owner>/charts`;
5. creates the GitHub Release with the library files, the chart, and every image digest in the notes.

One-time setup, before the first tag:

- **Repository visibility.** Make the repository public before the first release, or the release fails partway.
  The images job uses `actions/attest-build-provenance`, and GitHub stores artifact attestations only for public
  repositories (or private ones on GitHub Enterprise Cloud). The `pypi` job doesn't wait for the images, so on a
  private repository `gcattr` reaches PyPI and the images job then fails. A private repository also keeps the
  GitHub Release, its assets and (until changed) the `ghcr.io` packages private, so evaluators can't use them.
- **PyPI.** `gcattr` doesn't exist on PyPI yet, so add a *pending* trusted publisher (Account settings →
  Publishing): project `gcattr`, owner and repository of this repository, workflow `release.yml`, environment
  `pypi`. The first publish creates the project.
- **GitHub environment.** In the repository settings, create the `pypi` environment (optionally with required
  reviewers, which also gives you a last stop before PyPI).
- **ghcr.io packages.** The first release creates seven packages under the owner: the six `gca-*` images and
  `charts/gateway-code-attribution`. After the first release, check each one's visibility (a new package can
  start out private) and make it public (package settings → Change visibility) so adopters pull without
  credentials. Check with `docker logout ghcr.io` and a `docker pull`.

PyPI files can't be replaced. If a job fails after `pypi` has published, fix the cause and re-run only the failed
jobs (`gh run rerun <run-id> --failed`); re-pushing the same tag would try to publish the same version again.

Version bumps: a change that alters any fingerprint or outcome raises `ALG` and is at least a minor release
(docs/library.md).

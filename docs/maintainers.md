# Maintainers

## Required status checks

Protect `main` and require these checks (constitution "Development Workflow & Quality Gates"):

| Check | Workflow | Gate | Runs when |
|---|---|---|---|
| `lint`, `test-lib`, `test-services`, `helm-lint` | `ci.yml` | baseline | every PR |
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

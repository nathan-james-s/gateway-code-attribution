# Upgrading

## Upgrading the chart

```bash
helm upgrade gca charts/gateway-code-attribution -n gca -f values.yaml   # or: make demo-upgrade
```

Database migrations (Alembic) run in a Job **before** the new pods start (`pre-upgrade` hook), and the upgrade
waits for them. They only move forward; `helm rollback` restores the previous pods but not the previous schema, so
back up the database before an upgrade you might want to undo. Settings you changed in the portal survive an
upgrade: the chart re-applies only the values that changed since it last applied them.

Read the notes below for the versions you're crossing.

## Fingerprint key rotation

An admin rotates the fingerprint key in the portal (**Admin → Rotate the fingerprint key**). Rotation:

1. writes a new key generation to the key Secret, then records it as **active**: capture uses it within about
   two minutes (the Secret reaches the pods, and the gateway reloads, research R5);
2. marks the previous generation **retired**: it fingerprints nothing new, but the PR check still uses it to match
   lines against captures made under it;
3. **expires** the retired generation after `attribution.retentionDays`, when the last captures made with it are
   gone. Expired keys are removed from the Secret.

A PR check result names the key generations its candidates came from. Outcomes don't depend on the key:
calibration requires that a line's outcome is the same under at least 99% of keys (research R9), so a rotation
doesn't change how similar code is judged.

## Algorithm (`alg`) upgrades

The matching algorithm is versioned (`alg`, Constitution III). A change that could alter a fingerprint or an
outcome ships as a new `alg` with its own frozen golden corpus, never as a change to an existing one.

- **Captures** are fingerprinted with the newest `alg` from the moment the new capture pods run. Captures made
  under an older `alg` stay matchable while the library still supports it (`SUPPORTED_ALGS`): each candidate is
  compared using the fingerprints and thresholds of its own `alg`.
- **PR check results already stored** keep the `alg` they were computed with; it's shown on the check run and in
  the portal. Nothing is recomputed silently. A **Re-run** on a check computes the head again with the current
  library, so the new result can differ from the old one.
- **Reports** that span an upgrade mix results from both versions; each result row keeps its `alg`.

## Release notes

### Matching and storage changes (migrations 0006 and 0007)

- **Fingerprints captured before 0006 are deleted.** They came from an earlier, unreleased form of `alg 1` (3-gram
  shingles, 32-value signatures) and can't be compared with current ones. Their capture events keep their
  metadata, so coverage history is unchanged, but AI output captured before the upgrade won't match PRs after it.
- **0007 moves LSH bands into `captured_line`** and drops the `lsh_band` table, cutting storage per captured line
  by about 45% (docs/sizing.md). It creates the `btree_gin` extension, which ships with PostgreSQL and which the
  database owner can create. On an external database, make sure the chart's database user owns the database or
  has `CREATE` on it.
- **The capture message format is `gca.capture.v2`.** During the rollout, messages from capture pods still running
  the old version are rejected and counted as loss, not stored.

### Pod Security "restricted" and NetworkPolicies

- Every pod now meets Pod Security **restricted**. Label the namespace to have the cluster enforce it
  ([install.md](install.md#3-install-the-stack)). `make demo` does this for you.
- **NATS now runs as a non-root user (1000).** JetStream data written by the previous version belongs to root, and
  the new NATS can't write it. NATS only holds capture messages until ingest stores them, so the volume can be
  recreated. Before upgrading an existing install:

  ```bash
  kubectl -n gca scale deployment gca-gca-capture-extproc --replicas=0   # stop new capture messages
  kubectl -n gca logs deploy/gca-gca-ingest --tail=5                     # wait until ingest has caught up
  kubectl -n gca delete statefulset gca-nats
  kubectl -n gca delete pvc gca-nats-js-gca-nats-0
  ```

  then upgrade; the upgrade recreates NATS and capture-extproc. These names are for release `gca` in namespace
  `gca`. With LiteLLM, scale `gca-gca-gateway` instead of capture-extproc. Messages still unstored when the volume is deleted are reported as loss (sequence gaps), not
  lost silently.
- **NetworkPolicies** (`networkPolicies.enabled`, on by default) let only the services that use them reach
  PostgreSQL, NATS, the capture processor and the demo model.

### Default database volume 200Gi

The default `postgres.storage` is now 200Gi (was 100Gi), sized from measurements (docs/sizing.md). A StatefulSet's
volume size can't change through an upgrade. To grow an existing volume, if its StorageClass allows expansion:

```bash
kubectl -n gca patch pvc data-gca-gca-postgres-0 -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'
```

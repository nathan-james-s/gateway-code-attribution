# Validation R5: agentgateway 1.6.0 API-key hot reload (task T039)

- **Date**: 2026-10-14
- **Setup**: `tests/spikes/run_r5.py`. agentgateway 1.6.0 standalone with `llm.policies.apiKey` (`keyHash` +
  `metadata`) read from a config file. While a long stream (1-byte chunks, about 8 s) was in flight, the file was
  atomically replaced to add a key, and later edited to remove it.

## Results

| Check | Result |
|---|---|
| New key rejected before the change | ✅ 401 |
| New key accepted after the file change | ✅ after **13.2 s** (the gateway's file-watch and reload interval) |
| Stream in flight during the reload | ✅ completed, status 200, **byte-identical** to the upstream stream |
| Existing key unaffected | ✅ 200 |
| Revocation (key removed from the file) | ✅ 401 after **13.0 s** |

## Decision

**Research R5 holds; no fallback needed.**
- The portal renders personal-key entries (`keyHash`, `metadata: {credential_id, github_id}`) into a
  portal-managed ConfigMap mounted into agentgateway (T043, T049). agentgateway reloads it without disturbing
  traffic.
- **End-to-end delay in Kubernetes**: the kubelet's ConfigMap sync (default up to about 60–90 s) plus about 13 s of
  gateway reload. So a newly issued key works, and a revoked key stops working, **within about 2 minutes**.
  - The portal tells the developer this when issuing a key (T050).
  - Revocation meets FR-016, which requires stopping future capture but sets no deadline. Captures made in that
    window still record the revoked credential's identity, so they're attributed correctly.
- **Mount the ConfigMap as a directory, never with `subPath`.** Kubernetes doesn't update `subPath` mounts.

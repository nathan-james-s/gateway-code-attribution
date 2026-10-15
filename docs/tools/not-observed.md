# What the gateway can't observe

Attribution only sees model output that passes through the gateway. Code from anything else lands as **human**
("no match to observed AI output"), or as **not observed** when its author has no gateway credential. These are
known blind spots, not errors (FR-040, FR-041).

## Out of scope for v1

- **GitHub Copilot**: inline completions and next-edit suggestions go to GitHub's service, not through a
  configurable endpoint. Copilot Chat in some editors allows custom endpoints, but it isn't validated here.
- **Cursor**: Tab completions, Composer and inline edit use Cursor's own backend.

## Never observable

- Chat output copied from a browser tab or another app and pasted into the editor.
- Any coding tool, plug-in or agent that isn't pointed at the gateway, or that a developer runs with their own
  provider key.
- Model output produced before the developer got a gateway credential, or older than the matching window
  (14 days by default).

## Partly observable

- Formatter rewrites of AI code: lines that change shape can drop from *AI, unmodified* to *AI, modified* or
  *human* (the release bar tracks this; see SC-003).
- Responses the gateway let through while capture was down. They're recorded as capture loss and show as
  *incomplete coverage* on affected changes (US4).

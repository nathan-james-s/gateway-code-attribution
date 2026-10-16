# What the outcomes mean

Every line a pull request adds gets exactly one result. Lines whose author the gateway can attribute get one of
four **outcomes**. Lines whose author it can't see get the **state** *not observed*, which is not an outcome and
is never counted in percentages.

These display labels are used everywhere: the check run, the portal, the dashboards and these docs.

| Label | Meaning | Confidence |
|---|---|---|
| **AI, unmodified** | The line matches, exactly, a line the author's AI tool produced through the gateway within the matching window (14 days by default). | exact |
| **AI, modified (anchored)** | Not an exact match, but similar to a line from an AI response that produced at least one exact match **in the same file**. Typical: you renamed a variable in AI-written code. | high |
| **AI, modified (broad)** | Similar to a line from any of the author's AI responses in the window, with no anchor in the same file. Typical: AI-written code moved to another file and adapted. | lower |

A formatter that splits one AI line over several (a long call wrapped one argument per line, a method chain
broken up) gives lines that are each only a fragment of what the AI wrote. They're matched by joining the
consecutive lines back together, and reported as **AI, modified** (anchored or broad, as above). A short
fragment next to a line that already matched (`if missing:` split from the `raise` the AI wrote after it) is AI
modified when joining it makes the match closer. Changing quote
style alone (`'x'` to `"x"`) is not a modification.
| **Human** | **No match to observed AI output.** It does not prove a person typed it: code from tools the gateway can't see also lands here. | |
| **Indeterminate** | Too short or too common to attribute honestly: fewer than 3 tokens, no identifier, number or string, or a line on the common-lines list (`return`, `}`, `else:`, `import os`, blank lines). | |
| **Not observed** *(state)* | The commit's author has no GitHub account linked, or isn't mapped to a developer with a gateway credential. Nothing is guessed. | |

## Percentages

Percentages are computed over **AI** and **Human** lines only. *Indeterminate*, *not observed* and excluded files
are shown as counts. By default the headline excludes broad matches, counting those lines as human. The
**Include broad matches** switch, or `prcheck.headlineIncludesBroad: true` for the check title, includes them.
The check summary always shows both figures.

## Coverage

Each attributed head also gets a coverage status:

- **complete**: capture had caught up with the push, and no capture loss overlaps the matching window.
- **incomplete**: capture loss overlapped the window, or the wait for capture hit its cap. Some AI lines may show
  as human.
- **pending**: waiting for capture to catch up (shown as *in progress* on the check).
- **not observed**: none of the change's authors are mapped.

What counts as capture loss for a change: a loss in the matching window that is one of its credited authors' own
(a truncated, unreadable or unsupported response under their credential), or that could be anyone's (a sequence
gap, missed heartbeats, a capture outage, a full buffer). The check lists one reason per cause. Responses under an
unknown credential belong to nobody in the stack, so they never make a change incomplete.

Capture loss is recorded when:

- a capture instance reports it (truncated, unreadable or unexpected responses, unsupported routes or tools,
  unknown credentials, a full buffer, failed publishes);
- messages from an instance go missing (a gap in its sequence numbers; a late, out-of-order message isn't loss);
- an instance stops sending heartbeats for 15 seconds, until it resumes, shuts down or is replaced;
- no capture instance of the installed gateway is running for 15 seconds, for example scaled to zero. The gateway
  fails open, so requests keep working, but nothing captures them until capture is back.

The portal's `/coverage` page and Grafana's **Coverage** dashboard show it by cause, gateway, API format and tool.

## Excluded files

Some files are listed rather than attributed, each with a reason:

- `rule`: matched an exclusion rule (lock files, `vendor/`, `dist/`, minified files);
- `binary`: not text;
- `too_large`: more than 5,000 added lines, or GitHub wouldn't return the diff.

## Multiset counting

Each captured line counts once. If the AI wrote a line once and it appears in two places in the PR, one is
*AI, unmodified* and the other is matched on its own merits (often *human*). Copying AI output doesn't inflate
the AI share.

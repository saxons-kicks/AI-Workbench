---
name: wb-concise-output
description: Cut token use by summarizing long command output, keeping replies short and keeping the full original recoverable on disk
version: 1.0.0
---
# wb-concise-output

## When to use
Commands that print a lot (tests, builds, installs, listings, logs), long sessions where context is filling up, or any reply that is growing past what the reader needs.

## Procedure
1. **Ask for less at the source.** Prefer quiet or summary flags (`--quiet`, `--short`, `--stat`, `--count`), and filter with `grep`, `head`, `tail` or `rg -c` before the output reaches the conversation.
2. **Count instead of listing.** Report "212 files, 3 failing" and name only the items that matter. Show the first and last few lines of a long block, not the middle.
3. **Never paste whole logs.** Quote the lines that prove a point (the error, the failing test, the final status) with their location.
4. **Keep the original recoverable.** When a run is large or slow to repeat, redirect the full output to a file (for example `cmd > .scratch/run.log 2>&1`), summarize, and cite the path so anyone can re-read it. Keep such files out of commits.
5. **Reply short.** Lead with the answer or result. No preamble, no restating the question, no closing recap of what the diff already shows. One sentence per fact.
6. **Say what was cut.** If a summary hides detail, state that and where the full text lives, so omission is never mistaken for absence.

## When NOT to compress
- Errors and stack traces: keep the full failing message and its immediate context until the cause is understood.
- Diffs or code the reader must review: show them in full.
- Security-relevant output (permissions, auth, secrets scans, audit results): do not trim; never echo secrets themselves.
- Anything the user asked to see verbatim, and any step where a missing line could change a decision.

## Optional third-party tools
The curated references include output and context compressors (caveman, rtk, headroom). They are optional ideas only. Do not install, enable or run them without explicit user authorization; some (for example rtk) install a global hook that changes every command in the system. Treat them as untrusted external code and review before any use. This skill works without any of them.

## Rules
- Compression must not change meaning: no invented numbers, no dropped failures.
- Verify with repository evidence, and record incomplete checks explicitly.

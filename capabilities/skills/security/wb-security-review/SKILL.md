---
name: wb-security-review
description: Use when auditing code, dependencies, auth flows, file I/O, or agent integrations for vulnerabilities, injection, and secret exposure.
---

# Security Review

## When to apply
- Reviewing PRs touching authentication, authorization, file paths, subprocesses, deserialization, or external inputs.
- Auditing third-party skills, MCP configs, or dependency trees for supply-chain risks.

## Procedure
1. Map trust boundaries, entry points, and attacker-controlled inputs (files, URLs, CLI args, headers, LLM/tool outputs).
2. Check for path traversal/symlink escapes, command injection (`shell=True`), unsafe deserialization (`yaml.load`, `pickle`), and SSRF/XSS.
3. Verify authn/authz enforcement on every sensitive action (fail-closed defaults, constant-time token comparison, least privilege).
4. Scan for hardcoded secrets, overly broad permissions, and sensitive data written to logs, errors, or git-tracked files.
5. Provide minimal proof-of-concept reproductions, severity rationale, and targeted regression tests for each confirmed finding.

## Finding standard
- Report a finding only when it names the trust boundary crossed and a concrete attacker-reachable result; "looks risky" is a note, not a finding.
- Work source-first: cite the code path from attacker input to sink; scanner or model output alone is a lead, not evidence.
- Rate impact (priority) and confidence (certainty) separately, so a likely-but-unproven critical stays visible without being overstated.
- Recommend the smallest fix that closes the path, plus the regression test that proves it.
- Keep a coverage ledger: list areas reviewed, skipped, and why, so absence of findings is not mistaken for absence of bugs.

## Verification
- Regression tests confirm rejected malicious inputs fail closed without side effects.
- Confirmed findings include exact file/line references and remediation verification.

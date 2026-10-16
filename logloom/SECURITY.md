# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | ✅ |

## Reporting a vulnerability

Please report security issues privately via GitHub's
[security advisory form](https://github.com/logloom/logloom/security/advisories/new)
rather than a public issue. Expect an acknowledgement within a few days.

## Threat model

Logloom reads a log file you point it at and writes a report file you choose.
It makes **no network requests** and has **no runtime dependencies**.

What Logloom does *not* do:

- read anything other than the path (or stdin) you give it;
- upload, phone home, or collect telemetry;
- modify the original log file;
- execute commands, run shell hooks, or write outside the chosen output path.

## Secret handling

Logloom is a *privacy-aware* tool, not a guarantee. Be aware of these limits:

- **Without `--redact`, the generated HTML contains the original text.** Secrets
  are highlighted for review, not removed. Sharing that file shares the secret.
- **With `--redact`, detected secrets are replaced** in both the findings and
  the raw output. Everything matched by a rule is replaced, nothing else.
- **The "Hide secrets in view" toggle in the toolbar only affects your browser.**
  Use *Download this view* while it is checked to write a scrubbed copy, or
  generate the report with `--redact`.
- **Detection is pattern based.** It covers common credential shapes (AWS keys,
  GitHub tokens, Slack tokens, JWTs, PEM blocks, URLs with inline credentials,
  `password=` style assignments, emails). It does not cover every encoding,
  obfuscation, or secret format. Review before sharing.
- **Emails are flagged but not redacted by default**, because they are usually
  not credentials. Review the list and decide.

## Handling a leaked credential

If a real credential appeared in a shared Logloom report:

1. Revoke and rotate the credential first — assume it is compromised.
2. Delete the shared report.
3. Regenerate with `logloom analyze build.log --redact`.
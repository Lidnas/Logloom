# Design notes

How Logloom turns a wall of text into a report, and why each piece is the way
it is.

## Pipeline

```
file | stdin | pasted text
        │
        ▼
   parser.py      lines → ANSI stripped, severity, timestamp, kind
        │
        ▼
 signatures.py    message → normalised text → signature hash + label
        │
        ▼
  analyzer.py     groups → issues, counts, stack frames, summary
        │
        ▼
  redaction.py    spans → secret candidates (reviewable, not auto-applied)
        │
        ▼
   report.py      analysis → one standalone HTML file
```

Each stage is a pure function over plain data, which is why the whole thing is
testable without a browser and renderable as JSON as well as HTML.

## parser.py — forgiving by design

Terminal output, CI logs and package managers disagree about format, so the
parser tries hard to recognise the common shapes and gives up quietly:

- ANSI/CSI escape sequences are stripped first, so colourised logs classify the
  same as plain ones.
- Severity comes from bracketed tags (`[ERROR]`, `[WARN ]`), a leading severity
  word (`ERROR:`, `Warning -`), glog lines (`E0910 10:22:42.220  3301 f.cc:1]`),
  and pytest/unittest progress letters (`E   ModuleNotFoundError: ...`).
  Word boundaries are required, so `Errors were found in 3 files` stays a log
  line.
- Timestamps are captured but never required.
- Lines are classified as `blank`, `noise`, `header`, `trace` or a severity, and
  the kind drives what the analyser does with them.
- **Noise** is low-information progress output (`Compiling crate a`, `.......`).
  It is counted, not grouped, and it never becomes a finding.
- **Stack frames** (Python `File "...", line n`, JS/Java `at fn (File:1:2)`,
  native `#0 0x…`, caret markers, `... n more`) attach to the issue above them
  as context instead of becoming their own group.

Anything unrecognised is kept verbatim as a `log` line. Nothing is discarded.

## signatures.py — collapse what varies, keep what matters

`normalize()` replaces the parts of a message that change between runs:

| Replaced | Example |
| --- | --- |
| numbers | `after 3 attempts` → `after <n> attempts` |
| durations | `30000ms` → `<dur>` |
| quoted strings | `'app.users'` → `<str>` |
| paths, URLs, emails, UUIDs, hex addresses, hashes | `10.0.0.7:5432` → `<addr>` |

The signature is a truncated SHA-1 of that normalised text, so identical
problems collapse and different problems stay apart.

`classify()` is a **curated, ordered** list of `(regex, label, severity)`. The
first match wins, specific patterns before generic ones. This is the part of
Logloom that must stay honest: it only claims a label when a pattern it
maintains actually matched. Unknown failures still get grouped — the title is
just the truncated normalised message.

## analyzer.py — findings are not every line

The first version grouped every distinct line, which turned a 73-line log into
53 "findings". That is noise with extra steps.

A group becomes a **finding** when it is at warning severity or above, or when
it matched a curated pattern. Everything else is folded into the summary
counters (`other_groups`, `noise_lines`, `blank_lines`). Pass `--min-severity
info` (or lower) to see everything.

Findings are ordered by severity, then by count, then by first occurrence.
`first_failure` is the *earliest* error line, not the top-ranked group — the
difference between "the report leads with a fatal git error at the end of the
file" and "the first failure was line 16".

Stack frames accumulate into the issue that precedes them, capped at 8 so a
deep traceback cannot flood a card. Occurrence lists are capped at 60 with an
explicit "… and N more", so a 20,000-line loop still renders instantly.

## redaction.py — flag, then let a human decide

Rules are ordered by confidence and specificity; overlapping matches keep the
first (highest priority) rule so one credential never produces three findings.
Findings carry exact `start`/`end` offsets, which is what lets the report
highlight the precise span in the raw output.

Multi-line rules (PEM blocks) are matched against the whole buffer and mapped
back to per-line spans, so the key material is removed from *every* line it
covers rather than just the `BEGIN` line.

Email addresses are flagged but not redacted by default. Redaction is opt-in
per finding, both from the CLI (`--redact`) and in the report UI.

## report.py — server rendered, JS as enhancement

Everything (findings, secrets table, raw output) is rendered to HTML by Python
and escaped with `html.escape`. JavaScript only adds search, severity filters,
expand/collapse, the redact toggle and the download button. Consequences:

- the file is useful with JavaScript disabled (with a `<noscript>` note);
- search operates on `data-search` attributes, which are built from the
  **redacted** text so an unredacted credential can never hide inside an
  attribute in a redacted report;
- there is no build step and no framework.

The template lives at `templates/report.html` in the repository and is copied
into the wheel as `logloom/templates/report.html`, so both source checkouts and
installed packages find it.

## CLI contract

- stdin: only ever log input.
- stdout: only ever an explicitly requested report (`--format json` without
  `--output`, or `--stdout`).
- stderr: diagnostics, summaries, warnings.

This is what makes `pytest 2>&1 | logloom analyze -` safe in a pipeline.

## Explicit non-goals

- No AI explanations, no API integrations, no cloud dashboard.
- No terminal interception or background daemon.
- No automatic fixes and nothing that modifies the user's system.
- No root-cause claims.

## Extension points

- New heuristic → `signatures.PATTERNS` + a test.
- New secret rule → `redaction.RULES` (+ positive and near-miss negative tests).
- New report section → render in `report.py`, keep `templates/report.html` free
  of logic.
- New CLI output → add a `--format`, keep stderr for humans.

## Performance

Analysis is linear in lines with a bounded number of regex passes per line.
A 100k-line log renders in well under a second on a laptop; the practical
bottleneck is regex backtracking on pathological input, not the algorithm.
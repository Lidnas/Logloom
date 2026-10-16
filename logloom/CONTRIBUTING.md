# Contributing to Logloom

Thanks for helping. Logloom is small on purpose, so the bar is mostly about
behaviour: never lose evidence, never upload anything, never crash on a weird
log.

## Setup

```bash
git clone https://github.com/logloom/logloom
cd logloom
python -m venv .venv
# Linux/macOS:   source .venv/bin/activate
# Windows:      .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Python 3.9+ is required. There are no runtime dependencies.

## Run the tests

```bash
python -m unittest discover -v
```

CI runs the same command on Windows and Linux across Python 3.9–3.13. Please make
sure it passes locally before opening a pull request.

## Try it without installing

```bash
python -m logloom analyze examples/failed-tests.log --output /tmp/report.html
```

## The most valuable contribution: real log fixtures

A sanitised log that currently parses badly is worth more than a refactor. Add
it under `tests/fixtures/`, mention what the log came from (CI, npm, cargo,
gradle, …) and what you expected Logloom to report.

Please remove credentials, tokens, hostnames and personal data. The
`tests/fixtures/secrets.log` file shows the level of sanitisation we expect.

## Good first issues

- **Add a heuristic.** Patterns live in `logloom/signatures.py`; add a
  `(regex, label, severity)` entry and a test in `tests/test_signatures.py`.
  Keep the list curated — a broad pattern that misfires is worse than none.
- **Add a secret rule.** Rules live in `logloom/redaction.py`. Include a
  positive test and a near-miss negative test.
- **Improve a report detail.** `templates/report.html` holds the whole UI; it is
  plain HTML/CSS/JS and needs no build step.

## Rules of the road

1. **Evidence is never destroyed.** Grouping may hide lines; the raw output
   section must still contain every original line with its line number.
2. **Stay offline.** No network calls, no telemetry, no AI APIs.
3. **Stay dependency-free at runtime.** Standard library only. Dev tooling is
   fine, but keep `pyproject.toml` `dependencies` empty.
4. **Never fail on bad input.** Empty files, binary garbage, mixed encodings and
   unterminated stack traces are all expected inputs.
5. **Respect the streams.** stdin is input, stdout is requested output, stderr
   is diagnostics.

## Pull requests

- One focused change per PR, with tests.
- Explain *why*, not just what. Especially for heuristic changes — show the log
  snippet that motivated it.
- Update `README.md` or `docs/design.md` if you change behaviour or options.

## Reporting bugs

Open an issue with the command you ran, the first ~50 lines of the offending
log (sanitised), what you expected, and what happened instead. A failing
fixture is the fastest possible bug report.
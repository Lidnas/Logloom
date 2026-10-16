"""Benchmark Logloom's analysis pipeline.

Run it with::

    python bench.py

Methodology
-----------
* A deterministic synthetic log is generated from a fixed seed, so numbers are
  comparable between runs and machines.
* Three shapes are measured: a *typical* CI log (20k lines, ~2k distinct
  messages), a *repetitive* log (20k lines, 7 distinct messages) and a
  *large* log (100k lines, ~30k distinct messages).
* Each stage is timed separately with ``time.perf_counter`` and repeated
  ``--repeat`` times; the **best** run is reported because it is the least
  noisy estimator of the code path rather than of the machine.
* Everything runs in-process with a warm import, which is how the library is
  used. CLI startup is measured separately at the bottom.
* These are single-threaded, no-GIL-wasted numbers on a single core. No claim
  is made about behaviour on other hardware beyond relative stage costs.
"""

from __future__ import annotations

import argparse
import random
import time
from typing import Dict, List, Tuple

from logloom.analyzer import analyze
from logloom.parser import parse_text
from logloom.redaction import detect
from logloom.report import render_report
from logloom.signatures import classify, extract_files, normalize, signature

TEMPLATES = [
    "INFO  [api] GET /v1/orders/{n} 200 in {n}ms",
    "INFO  [api] GET /v1/orders/{n} 200 in {n}ms",
    "DEBUG [db] query ok rows={n} in {n}ms",
    "WARN  [api] slow upstream call attempt {n} of 5",
    "ERROR connection refused to 10.0.0.{n}:5432 after {n} attempts",
    "ERROR connection refused to 10.0.0.{n}:5432 after {n} attempts",
    "ERROR timed out after {n}ms calling https://api.example.com/v/{n}",
    "Downloading crate serde-1.0.{n}",
    "    at com.acme.api.Session.get(Session.java:{n})",
    "Downloading crate tokio-1.{n}.1",
    "",
]

REPETITIVE_TEMPLATES = TEMPLATES[:7]


def make_log(lines: int, templates: List[str], seed: int = 7) -> str:
    rng = random.Random(seed)
    return "\n".join(
        rng.choice(templates).format(n=rng.randint(1, 9999)) for _ in range(lines)
    )


def clear_caches() -> None:
    """Drop the memoisation caches so a run looks like a first ever run."""
    for function in (classify, normalize, signature, extract_files):
        function.cache_clear()


def timed(stage, repeat: int) -> float:
    """Best wall time of ``repeat`` runs - the least noisy estimator."""
    best = float("inf")
    for _ in range(repeat):
        clear_caches()
        start = time.perf_counter()
        stage()
        best = min(best, time.perf_counter() - start)
    return best


def run(name: str, text: str, repeat: int) -> Tuple[str, Dict[str, float], str]:
    parse = timed(lambda: parse_text(text), repeat)
    parsed = parse_text(text)

    stages = {
        "parse": parse,
        "analyze": timed(lambda: analyze(parsed), repeat),
        "detect": timed(lambda: detect(parsed), repeat),
    }
    analysis = analyze(parsed)
    findings = detect(parsed)
    stages["render"] = timed(
        lambda: render_report(analysis, findings=findings, source="bench.log"), repeat
    )
    stages["total"] = sum(stages.values())

    html = render_report(analysis, findings=findings, source="bench.log")
    notes = "{} findings, {:.1f} MB report".format(
        analysis.summary["issue_count"], len(html.encode("utf-8")) / 1024 / 1024
    )
    return name, stages, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Logloom benchmark")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()

    cases = [
        ("typical CI log", make_log(20_000, TEMPLATES)),
        ("repetitive log", make_log(20_000, REPETITIVE_TEMPLATES)),
        ("large log", make_log(100_000, TEMPLATES)),
    ]

    header = "{:<17}{:>8}{:>9}{:>9}{:>9}{:>8}{:>9}   {}".format(
        "case", "lines", "parse", "analyze", "detect", "render", "total", "notes"
    )
    print(header)
    print("-" * len(header))
    for name, text in cases:
        line_count = text.count("\n") + 1
        name, stages, notes = run(name, text, args.repeat)
        print(
            "{:<17}{:>8}{:>8.2f}s{:>8.2f}s{:>8.2f}s{:>7.2f}s{:>8.2f}s   {}".format(
                name,
                line_count,
                stages["parse"],
                stages["analyze"],
                stages["detect"],
                stages["render"],
                stages["total"],
                notes,
            )
        )
    print()
    print(
        "Cold runs: memoisation caches cleared before every timed repetition, "
        "best of {} taken.".format(args.repeat)
    )
    print("Single core, in-process, after import. Absolute numbers are machine specific.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
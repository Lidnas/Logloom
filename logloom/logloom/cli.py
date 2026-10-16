"""Command line interface.

Contract: stdin is only ever used for log input, diagnostics always go to
stderr, and stdout is reserved for an explicitly requested ``--format json``.
That keeps ``some-command | logloom analyze -`` safe in a pipeline.
"""

from __future__ import annotations

import argparse
import io
import sys
from typing import List, Optional, Sequence, TextIO

from . import __version__
from .analyzer import analyze
from .parser import ORDER, parse_text
from .redaction import detect
from .report import render_json, render_report

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_INPUT_ERROR = 3

DEFAULT_OUTPUT = "logloom-report.html"


def _read_stream(stream: TextIO) -> str:
    data = stream.read()
    return data


def read_input(path: Optional[str], stdin: TextIO) -> str:
    """Read log text from a path, or from stdin when path is ``-``/omitted."""
    if path in (None, "-"):
        return _read_stream(stdin)
    with io.open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        return handle.read()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logloom",
        description="Turn terminal chaos into a debugging report.",
        epilog="Logs are processed locally. Nothing is uploaded.",
    )
    parser.add_argument("--version", action="version", version="logloom {}".format(__version__))
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    analyze_parser = subparsers.add_parser(
        "analyze", help="analyse a log file, stdin, or pasted text"
    )
    analyze_parser.add_argument(
        "path",
        nargs="?",
        default="-",
        help="log file to analyse, or '-' for stdin (default)",
    )
    analyze_parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="report file (default: {} for html, stdout for json)".format(DEFAULT_OUTPUT),
    )
    analyze_parser.add_argument(
        "--format", choices=("html", "json"), default="html", help="report format"
    )
    analyze_parser.add_argument(
        "--redact", action="store_true", help="replace detected secrets in the report"
    )
    analyze_parser.add_argument(
        "--no-raw", action="store_true", help="omit the raw output section"
    )
    analyze_parser.add_argument(
        "--title", default=None, help="report title (default: derived from the source)"
    )
    analyze_parser.add_argument(
        "--min-severity",
        choices=ORDER,
        default="warning",
        help="hide findings below this severity (default: %(default)s)",
    )
    analyze_parser.add_argument(
        "--fail-on",
        choices=("never", "warning", "error"),
        default="never",
        help="exit non-zero when findings reach this severity",
    )
    analyze_parser.add_argument(
        "--stdout", action="store_true", help="write the report to stdout instead of a file"
    )
    analyze_parser.add_argument("-q", "--quiet", action="store_true", help="suppress the summary")

    return parser


def _summary_lines(summary: dict, output: str, secret_count: int) -> List[str]:
    lines = [
        "logloom: {} lines, {} findings ({} errors, {} warnings), "
        "{} duplicate lines folded".format(
            summary.get("total_lines", 0),
            summary.get("issue_count", 0),
            summary.get("errors", 0),
            summary.get("warnings", 0),
            summary.get("duplicates", 0),
        )
    ]
    first = summary.get("first_failure")
    if first:
        lines.append("logloom: first error at line {}".format(first))
    if secret_count:
        lines.append(
            "logloom: {} potential secret(s) detected - review them before sharing "
            "(re-run with --redact for a scrubbed report)".format(secret_count)
        )
    lines.append("logloom: wrote {}".format(output))
    return lines


def _should_fail(summary: dict, fail_on: str) -> bool:
    if fail_on == "never":
        return False
    if fail_on == "warning":
        return bool(summary.get("errors") or summary.get("warnings"))
    return bool(summary.get("errors"))


def command_analyze(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    try:
        text = read_input(args.path, stdin)
    except OSError as error:
        print("logloom: cannot read input: {}".format(error), file=stderr)
        return EXIT_INPUT_ERROR

    source = args.path if args.path not in (None, "-") else "stdin"
    title = args.title or "Logloom report — {}".format(source)

    lines = parse_text(text)
    # Asking for info-level output implies "show me everything, not just problems".
    include_info = args.min_severity in ("info", "debug", "log")
    analysis = analyze(
        lines, min_severity=args.min_severity, include_info=include_info
    )
    findings = detect(lines)

    report_text: str
    if args.format == "json":
        report_text = render_json(
            analysis, findings=findings, source=source, version=__version__
        )
    else:
        report_text = render_report(
            analysis,
            findings=findings,
            redacted=args.redact,
            include_raw=not args.no_raw,
            title=title,
            source=source,
            version=__version__,
        )

    # `--format json` without an explicit path streams to stdout, which keeps
    # `logloom analyze build.log --format json | jq` working.
    to_stdout = args.stdout or (args.format == "json" and not args.output)
    destination = DEFAULT_OUTPUT if args.output is None else args.output

    if to_stdout:
        print(report_text, file=stdout, end="" if report_text.endswith("\n") else "\n")
        output = "stdout"
    else:
        try:
            with io.open(destination, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(report_text)
        except OSError as error:
            print("logloom: cannot write report: {}".format(error), file=stderr)
            return EXIT_INPUT_ERROR
        output = destination

    if not args.quiet:
        for line in _summary_lines(analysis.summary, output, len(findings)):
            print(line, file=stderr)

    return EXIT_FINDINGS if _should_fail(analysis.summary, args.fail_on) else EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stderr = sys.stderr

    if args.command != "analyze":
        parser.print_help(stderr)
        return EXIT_INPUT_ERROR

    try:
        return command_analyze(args, sys.stdin, sys.stdout, stderr)
    except BrokenPipeError:
        return EXIT_INPUT_ERROR
    except KeyboardInterrupt:
        print("logloom: interrupted", file=stderr)
        return EXIT_INPUT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
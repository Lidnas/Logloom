"""Log line parsing: ANSI stripping, timestamps, severity, stack frames.

The parser is deliberately forgiving. Terminal output, CI logs, and package
managers all disagree about how a line should be formatted, so anything that
cannot be recognised is kept verbatim and classified as a plain log line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

__all__ = [
    "LogLine",
    "SEVERITIES",
    "RANK",
    "highest",
    "parse_line",
    "parse_text",
]

# Matches CSI/OSC style escape sequences emitted by coloured build output.
ANSI_RE = re.compile(
    r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])"
)

SEVERITIES = {
    "fatal": "fatal",
    "critical": "fatal",
    "crit": "fatal",
    "panic": "fatal",
    "emerg": "fatal",
    "alert": "fatal",
    "severe": "fatal",
    "error": "error",
    "err": "error",
    "exception": "error",
    "traceback": "error",
    "fail": "error",
    "failed": "error",
    "failure": "error",
    "warn": "warning",
    "warning": "warning",
    "info": "info",
    "notice": "info",
    "debug": "debug",
    "trace": "debug",
    "verbose": "debug",
}

RANK = {"fatal": 50, "error": 40, "warning": 30, "info": 20, "debug": 10, "log": 0}
ORDER = ("fatal", "error", "warning", "info", "debug", "log")


def highest(*severities: str) -> str:
    """Return the most severe of the given severities."""
    best = "log"
    for severity in severities:
        if RANK.get(severity, 0) > RANK.get(best, 0):
            best = severity
    return best


TIMESTAMP_RES = (
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\d{4}/\d{2}/\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?"),
    re.compile(r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"),
    re.compile(r"(?<!\d)\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?!\d)"),
)

SEVERITY_WORD_RE = re.compile(
    r"(?i)^(fatal|critical|crit|panic|error|err|eror|warn|warning|info|notice|debug|trace|verbose"
    r"|exception|fail|failed|failure)(?![a-z0-9])(?:[\s:\-–—|]*)(.*)$",
    re.DOTALL,
)

# pytest / unittest progress letters: ``E   ModuleNotFoundError: ...``
PYTEST_CODE_RE = re.compile(r"^(?P<code>[EWFS])(?P<gap>\s{2,})(?P<msg>\S.*)$")

# ``E        +  where 1 = cache.get("a")`` - an assertion diff detail, which is
# evidence for the assertion above it rather than a finding of its own.
PYTEST_DIFF_RE = re.compile(r"^[+-](?:\s|$)")

TAG_RE = re.compile(r"^[\[<]([^\[\]<>]{0,60})[\]>]")

# `[10:22:41.513] [ERROR] (web:1420): message` - the parenthesised logger
# context is routing metadata, not part of the message.
CONTEXT_TAG_RE = re.compile(r"^\((?:[\w./-]{1,40}:)?\d{1,6}\)")

# `E0912 10:11:12.123456   4242 file.cc:99] message` (glog / glogger output)
GLOG_RE = re.compile(
    r"^(?P<sev>[EWIF])(?P<date>\d{4})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d{1,6})\s+\d+\s+[^]]*\]\s*(?P<msg>.*)$"
)

TRACEBACK_HEADER_RE = re.compile(
    r"^(?:"
    r"traceback \(most recent call last\)|"
    # JavaScript / Java / .NET frames
    r"at\s+[\w.$<>]+\s*\([^)]*\)|"
    # Python frames
    r'file "[^"]*", line \d+|'
    r"\.\.\.\d+ more|"
    # Native frames and Rust panics
    r"#\d+\s+0x[0-9a-f]+|"
    r"\^+|"
    r"note: |"
    # `module.Class.method(File.ext:123)`
    r"(?:[\w.$]+\.)*[\w$]+\([\w$]+\.(?:py|java|kt|kts|groovy|scala|cs|rb):\d+\)|"
    # `src/pkg/mod.py:42:in func`
    r"[\w./\\-]+\.(?:py|rb|rbw|js|ts|java|kt):\d+[:\s]"
    r")",
    re.IGNORECASE,
)

HEADER_RE = re.compile(
    r"^(={3,}|_{3,}|~{3,}|\*{3,}|\+{3,}|-{3,}\s|\s*-{3,}\s|#{2,}\s|\*{2,}\s|"
    r"[A-Z][A-Z0-9 _/\\.-]{6,}:?$)"
)

NOISE_RES = (
    re.compile(r"^[\s\.\-=_*+#~>]*$"),
    re.compile(r"^\W+$"),
    re.compile(r"(?i)^(?:downloading|fetching|resolving|installing|compiling|"
               r"building|linking|copying|extracting|updating|checking|waiting|"
               r"progress|step|ok|done)\b.{0,80}$"),
    re.compile(r"^[\d\s]{0,12}%?$"),
    re.compile(r"^[!+*\-.=~:]{1,10}$"),
)


@dataclass
class LogLine:
    """One physical line of input plus everything we could infer about it."""

    number: int
    raw: str
    severity: str = "log"
    message: str = ""
    timestamp: Optional[str] = None
    kind: str = "log"
    tags: List[str] = field(default_factory=list)

    @property
    def is_noise(self) -> bool:
        return self.kind in ("blank", "noise")

    @property
    def is_trace(self) -> bool:
        return self.kind == "trace"


def _is_noise(message: str) -> bool:
    stripped = message.strip()
    if len(stripped) < 3:
        return True
    return any(pattern.match(stripped) for pattern in NOISE_RES)


def _strip_tags(text: str, timestamps: List[str], tags: List[str]) -> str:
    """Consume leading ``[tag]``/``<tag>`` groups, recording what they hold."""
    rest = text
    while True:
        match = TAG_RE.match(rest)
        if not match:
            break
        tag = match.group(1).strip()
        remainder = rest[match.end() :].lstrip()
        # A "tag" that is really the start of the message (very long, has
        # spaces) is treated as content so we never eat real information.
        if tag and len(tag) > 60:
            break
        if any(pattern.fullmatch(tag) for pattern in TIMESTAMP_RES):
            timestamps.append(tag)
        else:
            tags.append(tag)
        rest = remainder
    while CONTEXT_TAG_RE.match(rest):
        rest = rest[CONTEXT_TAG_RE.match(rest).end() :].lstrip(" :")
    return rest


def _strip_timestamp(text: str, timestamps: List[str]) -> str:
    rest = text.lstrip()
    for pattern in TIMESTAMP_RES:
        match = pattern.match(rest)
        if match:
            timestamps.append(match.group(0))
            return rest[match.end() :].lstrip()
    return text


def parse_line(number: int, raw: str) -> LogLine:
    """Parse a single physical line. Never raises."""
    text = ANSI_RE.sub("", raw).rstrip("\r\n")

    if not text.strip():
        return LogLine(number=number, raw=text, kind="blank", message="")

    lead = len(text) - len(text.lstrip())
    body = text.strip()
    timestamps: List[str] = []
    tags: List[str] = []
    severity = "log"
    diff_detail = False

    glog = GLOG_RE.match(body)
    if glog:
        level = {"E": "error", "W": "warning", "I": "info", "F": "fatal"}[glog.group("sev")]
        timestamps.append(glog.group("date") + " " + glog.group("time"))
        severity = level
        body = glog.group("msg").strip()
    else:
        body = _strip_tags(body, timestamps, tags)
        body = _strip_timestamp(body, timestamps)

        if tags:
            for tag in reversed(tags):
                mapped = SEVERITIES.get(tag.strip().lower())
                if mapped:
                    severity = mapped
                    break

        if severity == "log":
            pytest_code = PYTEST_CODE_RE.match(body)
            if pytest_code:
                severity = {
                    "E": "error",
                    "W": "warning",
                    "F": "fatal",
                    "S": "info",
                }.get(pytest_code.group("code"), "log")
                body = pytest_code.group("msg").strip()
                diff_detail = PYTEST_DIFF_RE.match(body) is not None

        if severity == "log":
            match = SEVERITY_WORD_RE.match(body)
            if match:
                word = match.group(1).lower()
                severity = SEVERITIES.get(word, "log")
                body = match.group(2).strip()

    message = body.strip()
    indented = lead > 0

    if diff_detail:
        kind = "trace"
    elif TRACEBACK_HEADER_RE.match(message) or (indented and message):
        kind = "trace"
    elif HEADER_RE.match(message):
        kind = "header"
    elif message.lower().startswith("caused by:") or message.lower().startswith("suppressed:"):
        kind = "error"
        severity = highest(severity, "error")
    elif severity != "log":
        kind = severity
    elif _is_noise(message):
        kind = "noise"
    else:
        kind = "log"

    if kind == "header" and re.match(r"(?i)^traceback", message):
        severity = highest(severity, "error")

    return LogLine(
        number=number,
        raw=text,
        severity=severity,
        message=message,
        timestamp=timestamps[0] if timestamps else None,
        kind=kind,
        tags=tags,
    )


def parse_text(text: str, *, start_number: int = 1) -> List[LogLine]:
    """Parse a whole log into :class:`LogLine` objects."""
    lines = []
    previous_kind = "log"
    for offset, raw in enumerate(text.splitlines()):
        line = parse_line(start_number + offset, raw)
        # An indented line directly under a stack frame is part of that frame.
        if (
            line.kind == "trace"
            and previous_kind not in ("trace", "blank")
            and raw[:1].isspace()
            and not TRACEBACK_HEADER_RE.match(line.message)
        ):
            line.kind = "trace"
        lines.append(line)
        previous_kind = line.kind
    return lines
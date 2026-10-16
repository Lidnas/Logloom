"""Secret detection and reviewable redaction.

Detection is pattern based and deliberately conservative: a false negative
leaks a credential into a shared report, a false positive only adds one row to
a review list. Every finding can be toggled by the user, either from the CLI
(``--redact``) or inside the generated report.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .parser import LogLine, parse_text

__all__ = ["SecretFinding", "RULES", "detect", "detect_text", "apply", "marker_for"]


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: "re.Pattern"
    confidence: str = "high"
    redact_by_default: bool = True
    description: str = ""
    multiline: bool = False


RULES: List[Rule] = [
    Rule(
        "private_key",
        re.compile(
            r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"
            r"[\s\S]*?"
            r"-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"
        ),
        description="PEM private key block",
        multiline=True,
    ),
    Rule(
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),
        description="AWS access key id",
    ),
    Rule(
        "aws_secret_key",
        re.compile(r"(?i)\baws_secret_access_key\b\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})[\"']?"),
        description="AWS secret access key",
    ),
    Rule(
        "github_token",
        re.compile(
            r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"
        ),
        description="GitHub personal access token",
    ),
    Rule(
        "slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), description="Slack token"
    ),
    Rule(
        "google_api_key",
        re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
        description="Google API key",
    ),
    Rule(
        "stripe_key",
        re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}\b"),
        description="Stripe secret key",
    ),
    Rule(
        "openai_key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b"),
        description="OpenAI style API key",
    ),
    Rule(
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\b"),
        description="JSON web token",
    ),
    Rule(
        "bearer_token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{16,}"),
        description="Authorization bearer token",
    ),
    Rule(
        "basic_auth_url",
        re.compile(
            r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://)([^\s:/@]{1,64}):([^\s/@]{1,128})@([^\s/?#]{1,253})"
        ),
        description="URL with inline credentials",
    ),
    Rule(
        "connection_string",
        re.compile(
            r"(?i)\b(?:server|host|data source|address)\s*=\s*[^;\s]+;\s*"
            r"(?:user id|uid)\s*=\s*[^;\s]+;\s*(?:password|pwd)\s*=\s*[^;\s]+"
        ),
        description="Database connection string with password",
    ),
    Rule(
        "password_assignment",
        re.compile(
            r"(?i)\b(pass(?:word|wd)?|pwd|secret|api[_\-]?key|apikey|access[_\-]?token|"
            r"refresh[_\-]?token|auth[_\-]?token|client[_\-]?secret|private[_\-]?key|"
            r"session[_\-]?secret)\b\s*[:=]\s*[\"']?[^\s\"',;]{6,}[\"']?"
        ),
        confidence="medium",
        description="Credential-looking assignment",
    ),
    Rule(
        "email",
        # The trailing alpha-only label matters: `request@2.88.2` and
        # `tough-cookie@4.1.3` are npm package names, not addresses, and
        # matching them made every npm deprecation notice look like a leak.
        re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[A-Za-z]{2,})+\b"),
        confidence="low",
        redact_by_default=False,
        description="Email address (often harmless, left for review)",
    ),
]


@dataclass(frozen=True)
class SecretFinding:
    """One candidate secret, with the exact span it occupies."""

    rule: str
    line_number: int
    start: int
    end: int
    text: str
    confidence: str = "high"
    redact_by_default: bool = True
    end_line: int = 0

    @property
    def spans_lines(self) -> bool:
        return bool(self.end_line) and self.end_line > self.line_number

    @property
    def marker(self) -> str:
        return "[REDACTED:{}]".format(self.rule)

    @property
    def preview(self) -> str:
        text = self.text
        if len(text) <= 12:
            return text[0] + "*" * max(len(text) - 1, 0)
        return "{}...{} ({} chars)".format(text[:4], text[-4:], len(text))

    def to_dict(self) -> Dict[str, object]:
        return {
            "rule": self.rule,
            "line": self.line_number,
            "start": self.start,
            "end": self.end,
            "end_line": self.end_line or self.line_number,
            "confidence": self.confidence,
            "preview": self.preview,
            "redact_by_default": self.redact_by_default,
        }


def marker_for(rule: str) -> str:
    return "[REDACTED:{}]".format(rule)


def _spans(text: str, rule: Rule) -> Iterable[Tuple[int, int]]:
    for match in rule.pattern.finditer(text):
        start, end = match.span()
        if end > start:
            yield start, end


def detect(lines: Sequence[LogLine]) -> List[SecretFinding]:
    """Return secret candidates, ordered by line then column."""
    if not lines:
        return []

    by_number: Dict[int, str] = {line.number: line.raw for line in lines}
    numbers: List[int] = [line.number for line in lines]
    line_starts: List[int] = []
    position = 0
    for line in lines:
        line_starts.append(position)
        position += len(line.raw) + 1
    buffer = "\n".join(line.raw for line in lines)

    def locate(offset: int) -> Tuple[int, int]:
        index = max(bisect_right(line_starts, offset) - 1, 0)
        return numbers[index], offset - line_starts[index]

    accepted: Dict[int, List[Tuple[int, int]]] = {}
    findings: List[SecretFinding] = []

    def clashes(number: int, start: int, end: int) -> bool:
        return any(start < other_end and other_start < end
                   for other_start, other_end in accepted.get(number, ()))

    # Multi-line rules run first: a PEM block swallows the lines below it.
    for rule in RULES:
        if not rule.multiline:
            continue
        for match in rule.pattern.finditer(buffer):
            start_line, start_col = locate(match.start())
            end_line, end_col = locate(match.end())
            if end_line < start_line:
                continue
            for number in range(start_line, end_line + 1):
                start = start_col if number == start_line else 0
                end = end_col if number == end_line else len(by_number.get(number, ""))
                accepted.setdefault(number, []).append((start, max(end, start)))
            text = buffer[match.start() : match.end()]
            findings.append(
                SecretFinding(
                    rule=rule.name,
                    line_number=start_line,
                    start=start_col,
                    end=end_col if end_line == start_line else len(by_number.get(start_line, "")),
                    text=text,
                    confidence=rule.confidence,
                    redact_by_default=rule.redact_by_default,
                    end_line=end_line,
                )
            )

    for line in lines:
        text = line.raw
        if len(text) < 8:
            continue
        for rule in RULES:
            if rule.multiline:
                continue
            for start, end in _spans(text, rule):
                if clashes(line.number, start, end):
                    continue
                accepted.setdefault(line.number, []).append((start, end))
                findings.append(
                    SecretFinding(
                        rule=rule.name,
                        line_number=line.number,
                        start=start,
                        end=end,
                        text=text[start:end],
                        confidence=rule.confidence,
                        redact_by_default=rule.redact_by_default,
                    )
                )

    findings.sort(key=lambda finding: (finding.line_number, finding.start))
    return findings


def detect_text(text: str) -> List[SecretFinding]:
    """Detect secrets in raw log text."""
    return detect(parse_text(text))


def apply(lines: Sequence[str], findings: Sequence[SecretFinding]) -> List[str]:
    """Return ``lines`` with every finding replaced by its marker.

    ``lines`` must be numbered from 1, matching :func:`detect` output.
    """
    ranges: Dict[int, List[Tuple[int, Optional[int], str]]] = {}
    for finding in findings:
        if finding.spans_lines:
            ranges.setdefault(finding.line_number, []).append((finding.start, None, finding.marker))
            for number in range(finding.line_number + 1, finding.end_line + 1):
                ranges.setdefault(number, []).append((0, None, finding.marker))
        else:
            ranges.setdefault(finding.line_number, []).append(
                (finding.start, finding.end, finding.marker)
            )

    output: List[str] = []
    for index, text in enumerate(lines):
        line_ranges = sorted(ranges.get(index + 1, []), key=lambda item: item[0])
        if not line_ranges:
            output.append(text)
            continue
        pieces: List[str] = []
        cursor = 0
        for start, end, marker in line_ranges:
            if start < cursor:
                continue
            stop = len(text) if end is None else min(end, len(text))
            if stop < start:
                continue
            pieces.append(text[cursor:start])
            pieces.append(marker)
            cursor = stop
        pieces.append(text[cursor:])
        output.append("".join(pieces))
    return output


def by_line(findings: Sequence[SecretFinding]) -> Dict[int, List[SecretFinding]]:
    """Group findings by line number for rendering."""
    grouped: Dict[int, List[SecretFinding]] = {}
    for finding in findings:
        grouped.setdefault(finding.line_number, []).append(finding)
    return grouped


def rule_description(name: str) -> str:
    for rule in RULES:
        if rule.name == name:
            return rule.description
    return name
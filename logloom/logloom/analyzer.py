"""Failure grouping and noise reduction.

The analyser never deletes information. Every physical line keeps its original
number and text; grouping only decides how lines are presented and how many
occurrences are listed individually.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .parser import RANK, LogLine, highest
from .signatures import classify, extract_files, normalize, signature

__all__ = ["Issue", "Analysis", "analyze", "analyze_text"]

MAX_OCCURRENCES_SHOWN = 60
MAX_CONTEXT = 8
COALESCE_WINDOW = 25


@dataclass
class Issue:
    """A group of log lines that share a normalised signature."""

    key: str
    label: str
    severity: str
    message: str
    normalized: str
    pattern: Optional[str] = None
    count: int = 0
    first_line: int = 0
    last_line: int = 0
    occurrences: List[int] = field(default_factory=list)
    context: List[Tuple[int, str]] = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    @property
    def duplicates(self) -> int:
        return max(self.count - 1, 0)

    @property
    def occurrences_shown(self) -> int:
        return min(len(self.occurrences), MAX_OCCURRENCES_SHOWN)

    @property
    def occurrences_hidden(self) -> int:
        return max(len(self.occurrences) - MAX_OCCURRENCES_SHOWN, 0)

    def to_dict(self) -> Dict[str, object]:
        return {
            "signature": self.key,
            "label": self.label,
            "severity": self.severity,
            "pattern": self.pattern,
            "message": self.message,
            "normalized": self.normalized,
            "count": self.count,
            "first_line": self.first_line,
            "last_line": self.last_line,
            "occurrences": list(self.occurrences),
            "occurrences_hidden": self.occurrences_hidden,
            "context": [[number, text] for number, text in self.context],
            "files": list(self.files),
        }


@dataclass
class Analysis:
    """Result of analysing a parsed log."""

    lines: List[LogLine]
    issues: List[Issue]
    summary: Dict[str, object]

    def by_severity(self, severity: str) -> List[Issue]:
        return [issue for issue in self.issues if issue.severity == severity]

    def to_dict(self) -> Dict[str, object]:
        return {
            "summary": self.summary,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _fallback_label(normalized: str) -> str:
    text = normalized or "Unclassified line"
    if len(text) > 72:
        text = text[:69].rstrip() + "..."
    return text


def _sort_key(issue: Issue) -> Tuple[int, int, int]:
    return (-RANK.get(issue.severity, 0), -issue.count, issue.first_line)


def _coalesce(issues: List[Issue], window: int = COALESCE_WINDOW) -> List[Issue]:
    """Merge nearby groups that share a curated label.

    Five separate "Build failed" cards from one build are one problem, not five.
    Only pattern-matched groups merge: unlabelled lines are kept apart because
    the shared key would just be a truncated message.
    """
    merged: List[Issue] = []
    by_label: Dict[str, Issue] = {}

    for issue in issues:
        label = issue.pattern
        if label is None:
            merged.append(issue)
            continue
        existing = by_label.get(label)
        if (
            existing is not None
            and issue.first_line - existing.last_line <= window
            and existing.severity == issue.severity
        ):
            existing.count += issue.count
            existing.last_line = max(existing.last_line, issue.last_line)
            existing.occurrences.extend(issue.occurrences)
            existing.context.extend(
                item for item in issue.context if len(existing.context) < MAX_CONTEXT * 2
            )
            for reference in issue.files:
                if reference not in existing.files and len(existing.files) < 8:
                    existing.files.append(reference)
            existing.severity = highest(existing.severity, issue.severity)
            continue
        merged.append(issue)
        by_label[label] = issue

    return merged


def analyze(
    lines: Sequence[LogLine],
    *,
    min_severity: str = "warning",
    include_info: bool = False,
    max_context: int = MAX_CONTEXT,
) -> Analysis:
    """Group parsed lines into issues and summarise the log.

    Only actionable groups become findings: anything at warning severity or
    above, plus anything matching a curated pattern. Ordinary informational
    output is folded into the summary instead, so a 2,000 line log does not
    produce 400 "findings". Pass ``include_info=True`` to surface everything.
    """
    threshold = RANK.get(min_severity, 0)
    groups: Dict[str, Issue] = {}
    order: List[str] = []
    current: Optional[str] = None

    blank_lines = 0
    noise_lines = 0
    trace_lines = 0
    header_lines = 0
    grouped_lines = 0

    for line in lines:
        if line.kind == "blank":
            blank_lines += 1
            continue
        if line.kind == "noise":
            noise_lines += 1
            current = None
            continue
        if line.kind == "trace":
            trace_lines += 1
            if current is not None:
                issue = groups[current]
                if len(issue.context) < max_context and line.message:
                    issue.context.append((line.number, line.raw.strip()))
            continue
        if line.kind == "header":
            header_lines += 1
            current = None
            continue

        grouped_lines += 1
        key = signature(line.message)
        current = key
        issue = groups.get(key)
        classification = classify(line.message)

        if issue is None:
            issue = Issue(
                key=key,
                label=classification.label
                if classification
                else _fallback_label(normalize(line.message)),
                severity=line.severity,
                message=line.message,
                normalized=normalize(line.message),
                pattern=classification.label if classification else None,
                first_line=line.number,
            )
            # extract_files is memoised: copy before storing.
            issue.files = list(extract_files(line.message))
            groups[key] = issue
            order.append(key)
        else:
            if classification and issue.pattern is None:
                issue.pattern = classification.label
            for reference in extract_files(line.message):
                if reference not in issue.files and len(issue.files) < 8:
                    issue.files.append(reference)

        if classification and classification.severity:
            issue.severity = highest(issue.severity, classification.severity)
        else:
            issue.severity = highest(issue.severity, line.severity)

        issue.count += 1
        if not issue.first_line:
            issue.first_line = line.number
        issue.last_line = line.number
        issue.occurrences.append(line.number)

    issues = _coalesce([groups[key] for key in order])
    visible = [
        issue
        for issue in issues
        if RANK.get(issue.severity, 0) >= threshold
        and (include_info or RANK.get(issue.severity, 0) >= RANK["warning"] or issue.pattern)
    ]
    visible.sort(key=_sort_key)

    failures = [
        issue
        for issue in issues
        if RANK.get(issue.severity, 0) >= RANK["error"]
    ]

    summary: Dict[str, object] = {
        "total_lines": len(lines),
        "blank_lines": blank_lines,
        "noise_lines": noise_lines,
        "trace_lines": trace_lines,
        "header_lines": header_lines,
        "grouped_lines": grouped_lines,
        "issue_count": len(visible),
        "total_groups": len(issues),
        "errors": sum(1 for issue in visible if RANK.get(issue.severity, 0) >= RANK["error"]),
        "warnings": sum(1 for issue in visible if issue.severity == "warning"),
        "duplicates": sum(issue.duplicates for issue in issues),
        "other_groups": len(issues) - len(visible),
        "first_failure": min((issue.first_line for issue in failures), default=None),
    }

    return Analysis(lines=list(lines), issues=visible, summary=summary)


def analyze_text(
    text: str,
    *,
    min_severity: str = "warning",
    include_info: bool = False,
    max_context: int = MAX_CONTEXT,
) -> Analysis:
    """Parse and analyse ``text`` in one call."""
    from .parser import parse_text

    return analyze(
        parse_text(text),
        min_severity=min_severity,
        include_info=include_info,
        max_context=max_context,
    )
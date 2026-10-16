"""Standalone HTML report generation.

The report is server rendered: findings, secrets and raw output are present in
the markup, and JavaScript only adds search, filtering and the redact toggle.
The file works offline, with no network calls and no dependencies.
"""

from __future__ import annotations

import html
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .analyzer import Analysis, Issue
from .parser import LogLine
from .redaction import SecretFinding, by_line, rule_description

__all__ = ["render_report", "render_json", "template_path"]

SEVERITY_LABEL = {
    "fatal": "Fatal",
    "error": "Error",
    "warning": "Warning",
    "info": "Info",
    "debug": "Debug",
    "log": "Log",
}

# How many of the top findings start expanded.
DEFAULT_EXPANDED = 3


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def template_path() -> Path:
    """Locate ``templates/report.html`` for both source and installed use."""
    here = Path(__file__).resolve().parent
    candidates = (here / "templates" / "report.html", here.parent / "templates" / "report.html")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("report template not found (looked in {})".format(
        ", ".join(str(candidate) for candidate in candidates)
    ))


def _render_spans(text: str, spans: Sequence[SecretFinding], redacted: bool) -> str:
    """Escape ``text`` and wrap secret spans in reviewable markup."""
    if not spans:
        return esc(text)
    pieces: List[str] = []
    cursor = 0
    for span in spans:
        if span.start < cursor:
            continue
        pieces.append(esc(text[cursor : span.start]))
        if redacted:
            pieces.append(
                '<span class="secret" data-rule="{}" data-redacted="{}">{}</span>'.format(
                    esc(span.rule), esc(span.marker), esc(span.marker)
                )
            )
        else:
            original = text[span.start : span.end]
            pieces.append(
                '<mark class="secret" data-rule="{rule}" data-plain="{plain}" '
                'data-redacted="{marker}">{plain}</mark>'.format(
                    rule=esc(span.rule), plain=esc(original), marker=esc(span.marker)
                )
            )
        cursor = span.end
    pieces.append(esc(text[cursor:]))
    return "".join(pieces)


def _plain_text(text: str, spans: Sequence[SecretFinding], redacted: bool) -> str:
    """Return the visible text of a line with every secret span replaced.

    Used for search indexes so unredacted credentials never leak into an
    attribute in an otherwise redacted report.
    """
    if not spans:
        return text
    pieces: List[str] = []
    cursor = 0
    for span in sorted(spans, key=lambda item: item.start):
        if span.start < cursor:
            continue
        pieces.append(text[cursor : span.start])
        pieces.append(span.marker)
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _render_stats(summary: Dict[str, object]) -> str:
    stats: List[tuple] = [
        ("Lines", summary.get("total_lines", 0)),
        ("Findings", summary.get("issue_count", 0)),
        ("Errors", summary.get("errors", 0)),
        ("Warnings", summary.get("warnings", 0)),
        ("Duplicates folded", summary.get("duplicates", 0)),
        ("Stack frames", summary.get("trace_lines", 0)),
        ("First error at line", summary.get("first_failure") or "-"),
        (
            "Skipped lines",
            (summary.get("blank_lines", 0) or 0) + (summary.get("noise_lines", 0) or 0),
        ),
    ]
    cells = "".join(
        '<div class="stat card"><div class="n">{}</div><div class="k">{}</div></div>'.format(
            esc(value), esc(key)
        )
        for key, value in stats
    )
    return cells


def _issue_search_text(
    issue: Issue,
    lines_by_number: Dict[int, str],
    findings_by_line: Dict[int, List[SecretFinding]],
    redacted: bool,
) -> str:
    first_spans = findings_by_line.get(issue.first_line, [])
    parts = [
        _plain_text(issue.label, _spans_within(issue.label, first_spans), redacted),
        issue.key or "",
    ]
    parts.extend(issue.files)
    parts.extend("line {}".format(number) for number in issue.occurrences)
    for number in issue.occurrences:
        parts.append(
            _plain_text(
                lines_by_number.get(number, ""), findings_by_line.get(number, []), redacted
            )
        )
    for number, text in issue.context:
        parts.append(
            _plain_text(lines_by_number.get(number, text), findings_by_line.get(number, []), redacted)
        )
    return " ".join(parts).lower()


def _spans_within(text: str, spans: Sequence[SecretFinding]) -> List[SecretFinding]:
    """Re-map spans from the raw line onto a derived string (e.g. a label).

    A finding title is built from the normalised message, so its offsets no
    longer line up with the raw line. Searching for the secret text is exact
    enough for the strings involved, and lets the redaction toggle cover the
    title as well as the body.
    """
    mapped: List[SecretFinding] = []
    for span in spans:
        index = text.find(span.text)
        if index == -1:
            continue
        mapped.append(
            replace(span, start=index, end=index + len(span.text), line_number=0)
        )
    return mapped


def _render_issue(
    issue: Issue,
    lines_by_number: Dict[int, str],
    findings_by_line: Dict[int, List[SecretFinding]],
    redacted: bool,
    expanded: bool = False,
) -> str:
    severity = issue.severity if issue.severity in SEVERITY_LABEL else "log"
    span = (
        "line {}".format(issue.first_line)
        if issue.first_line == issue.last_line
        else "lines {}–{}".format(issue.first_line, issue.last_line)
    )

    files = ""
    if issue.files:
        tags = "".join('<span class="tag">{}</span>'.format(esc(ref)) for ref in issue.files)
        files = '<div class="tags">{}</div>'.format(tags)

    first_line_text = lines_by_number.get(issue.first_line, issue.message)
    first_rendered = _render_spans(
        first_line_text, findings_by_line.get(issue.first_line, []), redacted
    )

    occurrences = ""
    if len(issue.occurrences) > 1:
        items = []
        for index, number in enumerate(issue.occurrences[: issue.occurrences_shown]):
            source = lines_by_number.get(number, "")
            spans = findings_by_line.get(number, [])
            rendered = _render_spans(source, spans, redacted)
            # Repeating the identical line six times helps nobody; the line
            # numbers already say where it happened.
            if index and rendered == first_rendered:
                items.append("<li>{}</li>".format(esc(number)))
            else:
                items.append("<li>{}</li>".format(rendered))
        if issue.occurrences_hidden:
            items.append(
                "<li class=\"muted\">... and {} more occurrences</li>".format(
                    issue.occurrences_hidden
                )
            )
        occurrences = '<ol class="occ">{}</ol>'.format("".join(items))

    context = ""
    if issue.context:
        frames = "\n".join(
            "{:>6}  {}".format(number, text) for number, text in issue.context
        )
        context = '<pre class="ctx">{}</pre>'.format(esc(frames))

    return (
        '<details class="group" data-severity="{sev}" data-signature="{key}" '
        'data-search="{search}"{open}>'
        "<summary>"
        '<span class="sev {sev}">{label}</span>'
        '<span class="label">{title}</span>'
        '<span class="count">× {count}</span>'
        '<span class="loc">{span}</span>'
        "</summary>"
        '<div class="body">'
        '<div class="msg">{message}</div>{files}{occurrences}{context}'
        "</div></details>"
    ).format(
        sev=esc(severity),
        key=esc(issue.key),
        search=esc(_issue_search_text(issue, lines_by_number, findings_by_line, redacted)),
        open=" open" if expanded else "",
        label=esc(SEVERITY_LABEL.get(severity, severity)),
        title=_render_spans(
            issue.label, _spans_within(issue.label, findings_by_line.get(issue.first_line, [])), redacted
        ),
        count=esc(issue.count),
        span=esc(span),
        message=first_rendered,
        files=files,
        occurrences=occurrences,
        context=context,
    )


def _render_raw(
    lines: Iterable[LogLine],
    findings_by_line: Dict[int, List[SecretFinding]],
    redacted: bool,
) -> str:
    rows: List[str] = []
    for line in lines:
        spans = findings_by_line.get(line.number, [])
        rows.append(
            '<div class="rl" data-ln="{ln}" data-sev="{sev}" data-kind="{kind}" data-search="{search}">'
            '<span class="ln">{ln}</span><span class="tx">{text}</span></div>'.format(
                ln=esc(line.number),
                sev=esc(line.severity),
                kind=esc(line.kind),
                search=esc(_plain_text(line.raw, spans, redacted).lower()),
                text=_render_spans(line.raw, spans, redacted),
            )
        )
    return "".join(rows) or '<div class="empty">No input was captured.</div>'


def _render_secrets(
    findings: Sequence[SecretFinding],
    redacted: bool,
    generated_id: str,
) -> str:
    if not findings:
        return ""
    rows: List[str] = []
    for index, finding in enumerate(findings):
        description = rule_description(finding.rule) or finding.rule
        rows.append(
            "<tr><td><input type=\"checkbox\" id=\"{gid}\" data-line=\"{line}\" "
            'data-start="{start}" data-end="{end}" data-marker="{marker}"{checked}></td>'
            '<td><code>{marker}</code></td><td>{desc}</td><td>{conf}</td>'
            '<td>line {line}</td><td><code>{preview}</code></td></tr>'.format(
                gid="{}-{}".format(generated_id, index),
                line=esc(finding.line_number),
                start=esc(finding.start),
                end=esc(finding.end),
                marker=esc(finding.marker),
                checked=" checked" if (redacted or finding.redact_by_default) else "",
                desc=esc(description),
                conf=esc(finding.confidence),
                preview=esc(finding.preview),
            )
        )
    note = (
        "<p class=\"muted\" id=\"banner-redact-note\" hidden>Secrets are hidden in this view only; "
        "the downloaded copy will be redacted too.</p>"
        if not redacted
        else ""
    )
    return (
        '<h2>Potential secrets</h2>'
        '<div class="card pads">'
        '<p class="muted" style="margin-top:0">{count} candidate(s) detected. '
        "Toggle individual findings, then use the toolbar to hide them in the view "
        "or export a redacted copy. The original log on disk is never modified.</p>"
        "{note}"
        '<table class="secrets"><thead><tr><th>Redact</th><th>Replacement</th><th>Rule</th>'
        "<th>Confidence</th><th>Where</th><th>Preview</th></tr></thead>"
        "<tbody>{rows}</tbody></table></div>"
    ).format(count=len(findings), note=note, rows="".join(rows))


def _render_banner(
    findings: Sequence[SecretFinding], redacted: bool
) -> str:
    if redacted:
        return (
            '<div class="banner ok"><strong>Redacted copy.</strong><span>'
            "{count} potential secret(s) replaced with markers. The raw output below is "
            "already scrubbed; the original log file is untouched.</span></div>"
        ).format(count=len(findings))
    if findings:
        return (
            '<div class="banner warn"><strong>Contains secrets.</strong><span>'
            "{count} potential secret(s) are highlighted below and are still present in this "
            "file. Use <em>Hide secrets in view</em> plus <em>Download this view</em>, or "
            "re-run with <code>--redact</code>, before sharing.</span></div>"
        ).format(count=len(findings))
    return (
        '<div class="banner ok"><strong>No secrets detected.</strong><span>'
        "Nothing matched the credential patterns in this log. Review anyway before sharing.</span></div>"
    )


def render_report(
    analysis: Analysis,
    *,
    findings: Optional[Sequence[SecretFinding]] = None,
    redacted: bool = False,
    include_raw: bool = True,
    title: Optional[str] = None,
    source: str = "stdin",
    generated: Optional[datetime] = None,
    version: str = "0.1.0",
) -> str:
    """Render the standalone HTML report."""
    findings = list(findings or [])
    findings_by_line = by_line(findings)
    lines_by_number = {line.number: line.raw for line in analysis.lines}
    generated = generated or datetime.now()

    if issues := analysis.issues:
        # Open the first few cards: they are the most severe, so the report is
        # useful on first paint without being a wall of expanded traces.
        issues_html = "".join(
            _render_issue(
                issue,
                lines_by_number,
                findings_by_line,
                redacted,
                expanded=index < DEFAULT_EXPANDED,
            )
            for index, issue in enumerate(issues)
        )
    else:
        issues_html = (
            '<div class="card pads empty">No failures matched. The log parsed cleanly '
            "(or contains only informational output).</div>"
        )

    raw_html = _render_raw(analysis.lines, findings_by_line, redacted)
    if include_raw:
        raw_block = (
            '<div class="card" id="raw-wrap" style="padding:0 4px">'
            '<pre class="raw" id="raw">{}</pre></div>'.format(raw_html)
        )
    else:
        raw_block = '<div class="card pads empty" id="raw-wrap">Raw output omitted (--no-raw).</div>'

    redact_button = ""
    if findings and not redacted:
        redact_button = (
            '<label class="chip"><input type="checkbox" id="redact">'
            "Hide secrets in view</label>"
        )

    document_title = title or "Logloom report — {}".format(source)

    replacements = {
        "{{HEAD_TITLE}}": esc(document_title),
        "{{TITLE}}": esc(document_title),
        "{{SOURCE}}": esc(source),
        "{{GENERATED}}": esc(generated.strftime("%Y-%m-%d %H:%M:%S")),
        "{{VERSION}}": esc(version),
        "{{LINE_COUNT}}": esc(analysis.summary.get("total_lines", 0)),
        "{{BANNER}}": _render_banner(findings, redacted),
        "{{STATS}}": _render_stats(analysis.summary),
        "{{ISSUES}}": issues_html,
        "{{SECRETS}}": _render_secrets(findings, redacted, "sec"),
        "{{RAW}}": raw_html,
        "{{REDACT_BUTTON}}": redact_button,
    }

    html_text = template_path().read_text(encoding="utf-8")
    for token, value in replacements.items():
        html_text = html_text.replace(token, value)

    # The template ships a raw wrapper; swap it when raw output is omitted.
    if not include_raw:
        start = html_text.find('<div class="card pads" id="raw-wrap" style="padding:0 4px">')
        end = html_text.find("</pre></div>", start)
        if start != -1 and end != -1:
            html_text = html_text[:start] + raw_block + html_text[end + len("</pre></div>") :]

    return html_text


def render_json(
    analysis: Analysis,
    *,
    findings: Optional[Sequence[SecretFinding]] = None,
    source: str = "stdin",
    version: str = "0.1.0",
) -> str:
    """Render the machine-readable JSON report."""
    import json

    payload = {
        "tool": "logloom",
        "version": version,
        "source": source,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "summary": analysis.summary,
        "issues": [issue.to_dict() for issue in analysis.issues],
        "secrets": [finding.to_dict() for finding in (findings or [])],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
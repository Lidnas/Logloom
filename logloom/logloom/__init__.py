"""Logloom - turn terminal chaos into a debugging report.

Local-first, dependency-free log analysis. Parses noisy build, test and package
manager output, groups repeated failures by normalised signature, flags likely
secrets, and renders a standalone HTML report.

Logloom organises evidence. It does not claim to identify root causes.
"""

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "analyze",
    "analyze_text",
    "parse_text",
    "detect",
    "render_report",
    "render_json",
]


def __getattr__(name):
    # Lazy re-exports keep `import logloom` cheap and avoid import cycles.
    if name in ("analyze", "analyze_text"):
        from . import analyzer

        return getattr(analyzer, name)
    if name == "parse_text":
        from .parser import parse_text

        return parse_text
    if name == "detect":
        from .redaction import detect

        return detect
    if name in ("render_report", "render_json"):
        from . import report

        return getattr(report, name)
    raise AttributeError("module 'logloom' has no attribute {!r}".format(name))
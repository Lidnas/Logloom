"""Regenerate the documentation tables in README.md from the code.

Run after adding a heuristic or a secret rule::

    python docs/generate_tables.py

It rewrites the block between the BEGIN/END markers in README.md.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from logloom.redaction import RULES  # noqa: E402
from logloom.signatures import PATTERNS  # noqa: E402

BEGIN = "<!-- BEGIN GENERATED: patterns -->"
END = "<!-- END GENERATED: patterns -->"
BEGIN_SECRETS = "<!-- BEGIN GENERATED: secrets -->"
END_SECRETS = "<!-- END GENERATED: secrets -->"


def pattern_table() -> str:
    rows = [
        "| Label | Matches (examples) | Severity |",
        "| --- | --- | --- |",
    ]
    for _, classification in PATTERNS:
        rows.append(
            "| **{}** | {} | {} |".format(
                classification.label,
                "`{}`".format(
                    ", ".join(
                        "`{}`".format(token.strip())
                        for token in _examples(classification.label)
                    )
                ),
                classification.severity,
            )
        )
    return "\n".join(rows)


# Short, readable examples per label. Kept next to the generator so the README
# stays informative even if a regex changes.
EXAMPLES = {
    "Missing module": ["ModuleNotFoundError", "Cannot find module"],
    "Missing file": ["FileNotFoundError", "ENOENT", "file or directory not found"],
    "Command not found": ["command not found", "is not recognized as an internal"],
    "Permission denied": ["EACCES", "Access is denied", "Operation not permitted"],
    "Process crash": ["Segmentation fault", "core dumped", "panic:"],
    "Out of memory": ["JavaScript heap out of memory", "exit code 137", "cannot allocate memory"],
    "Disk full": ["No space left on device", "ENOSPC"],
    "Port already in use": ["Address already in use", "EADDRINUSE"],
    "Syntax error": ["SyntaxError", "unexpected token", "parse error"],
    "Link error": ["undefined reference", "use of undeclared crate"],
    "Null reference": ["NullPointerException", "Cannot read property of null", "NoneType"],
    "Type mismatch": ["TypeError", "incompatible types"],
    "Invalid value": ["ValueError", "ValidationError", "invalid literal for"],
    "Missing key": ["KeyError", "Key not found"],
    "Out of range": ["IndexError", "out of bounds"],
    "Missing attribute": ["AttributeError", "has no attribute"],
    "Connection refused": ["Connection refused", "ECONNREFUSED"],
    "Timeout": ["ETIMEDOUT", "deadline exceeded", "Read timed out"],
    "Connection reset": ["ECONNRESET", "BrokenPipe"],
    "DNS failure": ["getaddrinfo", "Name or service not known", "NXDOMAIN"],
    "TLS or certificate": ["certificate verify failed", "self-signed certificate"],
    "Authentication": ["401", "authentication failed", "invalid credentials"],
    "Rate limited": ["429", "Too Many Requests", "rate limit"],
    "Not found": ["404", "Not Found", "not found:"],
    "Server error": ["500", "Internal Server Error"],
    "Test failure": ["AssertionError", "assert 1 == 2", "FAILED tests/api/x.py::test_y"],
    "Deprecation": ["DeprecationWarning", "has been deprecated"],
    "Build failed": ["error: could not compile", "ELIFECYCLE", "BUILD FAILED", "*** [Makefile:42]"],
    "Registry error": ["EAI_AGAIN", "registry request to ... failed"],
    "Unresolved reference": ["could not resolve", "cannot find value x in this scope"],
    "Non-zero exit": ["exit code 1", "exited with 2", "exit status 1"],
}


def _examples(label: str):
    return EXAMPLES.get(label, ["(see logloom/signatures.py)"])


def secret_table() -> str:
    rows = [
        "| Rule | Detects | Default | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for rule in RULES:
        default = "redact" if rule.redact_by_default else "review"
        rows.append(
            "| `{}` | {} | {} | {} |".format(
                rule.name,
                rule.description,
                default,
                rule.confidence,
            )
        )
    return "\n".join(rows)


def replace_block(text: str, begin: str, end: str, block: str) -> str:
    start = text.index(begin)
    stop = text.index(end)
    return text[: start + len(begin)] + "\n\n" + block + "\n\n" + text[stop:]


def main() -> int:
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    text = replace_block(text, BEGIN, END, pattern_table())
    text = replace_block(text, BEGIN_SECRETS, END_SECRETS, secret_table())
    readme.write_text(text, encoding="utf-8")
    print("README.md tables updated ({} patterns, {} secret rules)".format(
        len(PATTERNS), len(RULES)
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
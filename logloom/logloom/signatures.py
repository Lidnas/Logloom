"""Message normalisation, signature hashing, and known-pattern classification.

Logloom does not claim to understand every error. It normalises the parts of a
message that vary between runs (numbers, paths, ids) so identical problems
collapse into one group, and labels a message when it matches a pattern we
have explicitly curated.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import List, NamedTuple, Optional, Tuple

__all__ = [
    "PATTERNS",
    "Classification",
    "FILE_RE",
    "classify",
    "normalize",
    "signature",
    "extract_files",
]


class Classification(NamedTuple):
    label: str
    severity: Optional[str] = None


# Ordered: earliest rules win, so keep specific patterns above generic ones.
PATTERNS: List[Tuple[re.Pattern, Classification]] = [
    (re.compile(r"ModuleNotFoundError|ImportError:|cannot find module|"
                r"cannot find module|Can't resolve module|no module named|"
                r"unable to resolve module|ERR_MODULE_NOT_FOUND", re.I),
     Classification("Missing module", "error")),
    (re.compile(r"NoSuchFileError|FileNotFoundError|ENOENT|file or directory not found|"
                r"cannot find the (?:path|file) specified|system cannot find the (?:file|path)", re.I),
     Classification("Missing file", "error")),
    (re.compile(r"command not found|is not recognized as an internal or external command|"
                r"No such file or directory", re.I),
     Classification("Command not found", "error")),
    (re.compile(r"PermissionError|Permission denied|EACCES|Access is denied|"
                r"UnauthorizedAccessException|Operation not permitted", re.I),
     Classification("Permission denied", "error")),
    (re.compile(r"Segmentation fault|Access violation|stack overflow|"
                r"core dumped|panic:|Bus error|Fatal error", re.I),
     Classification("Process crash", "fatal")),
    (re.compile(r"OutOfMemoryError|MemoryError|OUT OF MEMORY|cannot allocate memory|"
                r"Killed process|exit code 137|JavaScript heap out of memory", re.I),
     Classification("Out of memory", "fatal")),
    (re.compile(r"No space left on device|ENOSPC|Disk quota exceeded|"
                r"write error: No space", re.I),
     Classification("Disk full", "fatal")),
    (re.compile(r"Address already in use|EADDRINUSE|bind: address already in use|"
                r"port .+ (?:is )?already (?:in use|used)", re.I),
     Classification("Port already in use", "error")),
    (re.compile(r"SyntaxError|IndentationError|unexpected token|unexpected end of input|"
                r"parse error|error: expected|Parsing error", re.I),
     Classification("Syntax error", "error")),
    (re.compile(r"cannot find symbol|undefined reference|unresolved external|"
                r"ld: (?:cannot|error)|linker command failed|No such module|"
                r"use of undeclared crate|unresolved import", re.I),
     Classification("Link error", "error")),
    (re.compile(r"NullPointerException|NullReferenceException|"
                r"Cannot read propert(?:y|ies) of (?:null|undefined)|"
                r"NoneType|AttributeError: 'NoneType'|is not iterable|of undefined", re.I),
     Classification("Null reference", "error")),
    (re.compile(r"TypeError|type error|incompatible types|"
                r"Mismatched (?:input|argument) types|expected .*, got", re.I),
     Classification("Type mismatch", "error")),
    (re.compile(r"ValueError|ValidationError|InvalidArgument|invalid literal for|"
                r"is not a valid|value error", re.I),
     Classification("Invalid value", "error")),
    (re.compile(r"KeyError|Key not found|missing key|\bkey .+ not found", re.I),
     Classification("Missing key", "error")),
    (re.compile(r"IndexError|out of range|out of bounds|ArrayIndexOutOfBounds|"
                r"list index out of range", re.I),
     Classification("Out of range", "error")),
    (re.compile(r"AttributeError|has no attribute|does not have (?:a )?(?:property|attribute)", re.I),
     Classification("Missing attribute", "error")),
    (re.compile(r"Connection refused|ECONNREFUSED|ConnectionError", re.I),
     Classification("Connection refused", "error")),
    (re.compile(r"timed? ?out|ETIMEDOUT|Timeout|TimeoutError|deadline exceeded|"
                r"Timeout awaiting|Read timed out", re.I),
     Classification("Timeout", "error")),
    (re.compile(r"ECONNRESET|Connection reset|connection closed|BrokenPipe|"
                r"EPIPE|remote end closed", re.I),
     Classification("Connection reset", "error")),
    (re.compile(r"Temporary failure in name resolution|getaddrinfo|"
                r"Name or service not known|NXDOMAIN|UnknownHost|ENOTFOUND|name resolution", re.I),
     Classification("DNS failure", "error")),
    (re.compile(r"certificate verify failed|self.signed certificate|"
                r"unable to get local issuer|SSL: |CERTIFICATE_VERIFY_FAILED|"
                r"TLS handshake", re.I),
     Classification("TLS or certificate", "error")),
    (re.compile(r"\b401\b|Unauthorized|unauthorized|authentication failed|"
                r"invalid credentials|Login failed|authentication required|\b403\b Forbidden", re.I),
     Classification("Authentication", "error")),
    (re.compile(r"\b429\b|Too Many Requests|rate limit", re.I),
     Classification("Rate limited", "warning")),
    (re.compile(r"\b404\b|Not Found|not found:|No such route", re.I),
     Classification("Not found", "error")),
    (re.compile(r"\b50[0-9]\b|Internal Server Error|HTTP/1\.[01] 5\d\d|"
                r"Internal error|server error", re.I),
     Classification("Server error", "error")),
    (re.compile(r"AssertionError|assertion failed|assertion `.*` failed|Assert\.Equal\(\) failed|"
                r"\bassert\b[^\n]{0,60}?(?:==|!=|>=|<=|\bis\b|\bin\b)", re.I),
     Classification("Test failure", "error")),
    # `FAILED tests/api/test_payments.py::test_x` and `12 passed; 3 failed`.
    # Deliberately narrow: a bare `FAILED` matches "failed to resolve",
    # "build failed" and half the internet otherwise.
    (re.compile(r"\bFAILED\b(?=\s+(?:tests?[/\\]|[\w.]+::))|"
                r"\b\d+ (?:tests? )?(?:failed|failures?)\b|"
                r"\btests? \d+ (?:failed|failures?)\b|"
                r"\btest[s]? .*\b(?:failed|failure)\b", re.I),
     Classification("Test failure", "error")),
    (re.compile(r"DeprecationWarning|is deprecated|deprecat", re.I),
     Classification("Deprecation", "warning")),
    (re.compile(r"(?:error: )?could not compile|BUILD FAILURE|BUILD FAILED|"
                r"error: build failed|ELIFECYCLE|Command failed with exit code|"
                r"error: internal compiler error|compilation terminated|"
                r"\*\*\* \[.*\] Error \d+|make: \*\*\*", re.I),
     Classification("Build failed", "error")),
    (re.compile(r"EAI_AGAIN|registry request to .* failed|"
                r"unable to resolve .* from the registry|Connection to .* refused", re.I),
     Classification("Registry error", "error")),
    (re.compile(r"could not resolve|cannot find value .* in this scope|"
                r"could not read|is not exported from", re.I),
     Classification("Unresolved reference", "error")),
    (re.compile(r"exited with (?:code |status )?\d+|exit code \d+|exit status \d+|"
                r"returned non-zero exit code|Command exited", re.I),
     Classification("Non-zero exit", "error")),
]

# Compiled once: (compiled_regex, label, severity).
_COMPILED = [(pattern, classification.label, classification.severity)
             for pattern, classification in PATTERNS]

# Every pattern is merged into one alternation so classification costs a single
# scan instead of up to 28. On a 100k line log this was the hot spot.
# Scoped `(?i:...)` flags are re-applied inline because each pattern was
# originally compiled with re.IGNORECASE.
_CLASSIFY_RE = re.compile(
    "|".join(
        "(?P<{name}>(?i:{body}))".format(
            name="p{}".format(index), body=pattern.pattern
        )
        for index, (pattern, _, _) in enumerate(_COMPILED)
    )
)

_CLASSIFY_BY_NAME = {
    "p{}".format(index): (label, severity)
    for index, (_, label, severity) in enumerate(_COMPILED)
}

FILE_RE = re.compile(
    r"(?<![\w.\-])"
    r"((?:[A-Za-z]:)?[\\/]?(?:[\w.\-]+[\\/])+[\w.\-]+|[\w\-]+\.\w{1,5})"
    r"[:(\s](\d{1,6})\)?"
)


# Analysis is regex heavy and real logs repeat the same message many times, so
# every pure lookup here is memoised. Real world logs collapse to a few hundred
# distinct messages, which turns the hot loop into dictionary lookups.
_CACHE_SIZE = 50_000


@lru_cache(maxsize=_CACHE_SIZE)
def classify(message: str) -> Optional[Classification]:
    """Return a curated classification for ``message``, or ``None``."""
    if not message:
        return None
    match = _CLASSIFY_RE.search(message)
    if match is None:
        return None
    label, severity = _CLASSIFY_BY_NAME.get(match.lastgroup or "", (message, None))
    return Classification(label, severity)


# One pass, one scan. Running twelve sequential `re.sub` calls over every log
# line dominated the runtime on large files; a single alternation is ~3x faster
# and behaves the same for the cases that matter (most specific first).
_SUBSTITUTIONS: Tuple[Tuple[str, str], ...] = (
    (r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "<uuid>"),
    (r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?", "<ts>"),
    (r"(?<!\d)\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?!\d)", "<time>"),
    (r"0x[0-9a-fA-F]+", "<addr>"),
    (r"\b[0-9a-fA-F]{12,}\b", "<hash>"),
    (r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", "<email>"),
    (r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>)]+", "<url>"),
    (r"[A-Za-z]:\\(?:[^\s'\"<>|:]+\\)*[^\s'\"<>|:]+", "<path>"),
    (r"(?<![\w.])/{1,2}[\w.+-]+(?:/[\w.+-]+)+/?", "<path>"),
    (r"\"[^\"\n]*\"|'[^'\n]*'|`[^`\n]*`", "<str>"),
    (r"\b\d+(?:\.\d+)?(?:ms|s|m|h)\b", "<dur>"),
    (r"\b\d+(?:\.\d+)?\b", "<n>"),
)

_NORMALIZE_RE = re.compile(
    "|".join(
        "(?P<sub{}>{})".format(index, pattern)
        for index, (pattern, _) in enumerate(_SUBSTITUTIONS)
    )
)

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_replacement(match: "re.Match") -> str:
    index = match.lastindex
    if index is None:
        return match.group(0)
    return _SUBSTITUTIONS[index - 1][1]


@lru_cache(maxsize=_CACHE_SIZE)
def normalize(message: str) -> str:
    """Replace run-specific noise so equivalent messages share a signature."""
    text = _NORMALIZE_RE.sub(_normalize_replacement, message.strip())
    return _WHITESPACE_RE.sub(" ", text).strip()


@lru_cache(maxsize=_CACHE_SIZE)
def signature(message: str) -> str:
    """Stable short hash of the normalised message."""
    normalized = normalize(message) or " "
    return hashlib.sha1(normalized.encode("utf-8", "replace")).hexdigest()[:12]


@lru_cache(maxsize=_CACHE_SIZE)
def extract_files(message: str, limit: int = 6) -> List[str]:
    """Pull ``path/to/file.ext:123`` references out of a message.

    The returned list is cached and must be treated as read-only.
    """
    found: List[str] = []
    for match in FILE_RE.finditer(message or ""):
        reference = "{}:{}".format(match.group(1), match.group(2))
        if reference not in found:
            found.append(reference)
        if len(found) >= limit:
            break
    return found
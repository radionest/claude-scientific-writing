"""Raw-span extractor for revision fidelity: the artifacts an edit must not damage.

`lib.qmd_prose` strips citations, code and URLs to lint clean prose; fidelity needs
the opposite view — the raw spans themselves, original offsets kept so a finding can
point into the file. NFKC + dash unification + whitespace squeeze happen only in
`Span.normalized` (the comparison view); `Span.text` keeps the source slice verbatim.
Overlapping matches resolve by category priority: the first span to claim a range
wins (fenced code beats the citation inside it; inline-python beats inline-code).
An unclosed fence simply does not match — both revision sides are affected equally.
"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass

# Priority order: earlier = stronger claim on an overlapping range.
CATEGORIES = ("fenced-code", "yaml", "html-comment", "citation", "crossref",
              "inline-python", "inline-code", "url")

_PRIORITY = {c: i for i, c in enumerate(CATEGORIES)}


@dataclass(frozen=True, slots=True)
class Span:
    category: str
    start: int  # 0-based offset into the raw source
    end: int
    text: str
    normalized: str


_FENCED_RE = re.compile(
    r"^[ \t]*(?P<fence>```+|~~~+)[^\n]*\n.*?^[ \t]*(?P=fence)[^\n]*$",
    re.DOTALL | re.MULTILINE)
_YAML_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_CITATION_RE = re.compile(r"\[-?@[^\]\n]+\]")
_CROSSREF_RE = re.compile(r"@(?:tbl|fig|sec|eq)-[A-Za-z0-9_-]+")
_INLINE_PYTHON_RE = re.compile(r"`\{[a-zA-Z0-9_]+\}[^`\n]*`")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_URL_RE = re.compile(r"(?:https?://|doi\.org/)\S+")
_CITE_KEY_RE = re.compile(r"@([A-Za-z0-9_:+.-]+)")

_PATTERNS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (category, rx) for category, rx in (
        ("fenced-code", _FENCED_RE), ("yaml", _YAML_RE),
        ("html-comment", _HTML_COMMENT_RE), ("citation", _CITATION_RE),
        ("crossref", _CROSSREF_RE), ("inline-python", _INLINE_PYTHON_RE),
        ("inline-code", _INLINE_CODE_RE), ("url", _URL_RE)))


def normalize(text: str) -> str:
    """Comparison view: NFKC, em/en/minus dashes unified, whitespace squeezed."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2014", "-").replace("\u2013", "-").replace("\u2212", "-")
    return re.sub(r"\s+", " ", text).strip()


def extract_spans(source: str) -> list[Span]:
    found = [(category, m) for category, rx in _PATTERNS for m in rx.finditer(source)]
    found.sort(key=lambda cm: (cm[1].start(), -cm[1].end(), _PRIORITY[cm[0]]))
    accepted: list[Span] = []
    for category, m in found:
        if any(s.start < m.end() and m.start() < s.end for s in accepted):
            continue
        accepted.append(Span(category, m.start(), m.end(),
                             m.group(0), normalize(m.group(0))))
    return sorted(accepted, key=lambda s: (s.start, s.end))


def citation_keys(source: str) -> list[str]:
    """Cited bib keys in document order, including the suppressed `-@key` form."""
    keys: list[str] = []
    for s in extract_spans(source):
        if s.category == "citation":
            keys += _CITE_KEY_RE.findall(s.text)
    return keys

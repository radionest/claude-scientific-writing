"""Extract narrative-prose lines from a Quarto .qmd, skipping non-prose regions."""
from __future__ import annotations
import re
from dataclasses import dataclass, field


@dataclass
class ProseLine:
    lineno: int
    text: str
    suppress: set[str] = field(default_factory=set)


_FENCE_RE = re.compile(r"^\s*(?:```+|~~~+)")
_YAML_DELIM_RE = re.compile(r"^---\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_LINT_OK_RE = re.compile(r"<!--\s*lint-ok:\s*([^>]*?)\s*-->")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# Tolerates numbering («7. Литература»), Quarto attributes («{.unnumbered}», «{#sec-refs}»)
# and the longer Russian variants («Список использованной литературы»).
_BIBLIO_RE = re.compile(
    r"^\s*(?:\d+[.)]\s*)?(?:список\s+(?:\w+\s+)?)?"
    r"(?:литератур\w*|библиограф\w*|references|bibliography)\s*(?:\{[^}]*\})?\s*$",
    re.IGNORECASE)
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_HTML_COMMENT_INLINE_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_INLINE_PYTHON_RE = re.compile(r"`\{[a-zA-Z0-9_]+\}[^`]*`")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_CITATION_RE = re.compile(r"\[-?@[^\]]+\]")
_URL_RE = re.compile(r"https?://\S+")


def _strip_inline(line: str) -> str:
    line = _HTML_COMMENT_INLINE_RE.sub(" ", line)
    line = _INLINE_PYTHON_RE.sub(" ", line)
    line = _INLINE_CODE_RE.sub(" ", line)
    line = _CITATION_RE.sub(" ", line)
    line = _URL_RE.sub(" ", line)
    return line


def is_russian(text: str) -> bool:
    """False only for substantial Latin-script text — an English abstract, a Latin
    reference entry. The rules are Russian-specific and would call every English word a
    typo. Short lines and Russian prose carrying Latin terms («3D Slicer») stay in."""
    cyr = len(_CYRILLIC_RE.findall(text))
    lat = len(_LATIN_RE.findall(text))
    return not (lat >= 25 and cyr * 2 < lat)


def extract_prose(source: str) -> list[ProseLine]:
    lines = source.splitlines()
    out: list[ProseLine] = []
    in_fence = False
    in_yaml = bool(lines) and _YAML_DELIM_RE.match(lines[0]) is not None
    in_html_comment = False
    biblio_level = 0  # >0 while inside a reference list
    for idx, raw in enumerate(lines):
        lineno = idx + 1
        if in_yaml:
            if idx != 0 and _YAML_DELIM_RE.match(raw):
                in_yaml = False
            continue
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if in_html_comment:
            if "-->" in raw:
                in_html_comment = False
            continue
        heading = _HEADING_RE.match(raw)
        if heading:
            level = len(heading.group(1))
            if _BIBLIO_RE.match(heading.group(2).strip()):
                biblio_level = level
                continue
            if biblio_level and level <= biblio_level:
                biblio_level = 0
        if biblio_level:
            continue
        if _TABLE_ROW_RE.match(raw):
            continue
        suppress = set()
        m = _LINT_OK_RE.search(raw)
        if m:
            suppress = {tok.strip() for tok in m.group(1).split(",") if tok.strip()}
        working = raw
        # an HTML comment opened on this line but not closed -> rest is comment
        if "<!--" in raw and "-->" not in raw:
            in_html_comment = True
            working = raw.split("<!--", 1)[0]
        cleaned = _strip_inline(working)
        if cleaned.strip() and is_russian(cleaned):
            out.append(ProseLine(lineno=lineno, text=cleaned, suppress=suppress))
    return out

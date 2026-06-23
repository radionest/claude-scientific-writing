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


def extract_prose(source: str) -> list[ProseLine]:
    lines = source.splitlines()
    out: list[ProseLine] = []
    in_fence = False
    in_yaml = bool(lines) and _YAML_DELIM_RE.match(lines[0]) is not None
    in_html_comment = False
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
        if cleaned.strip():
            out.append(ProseLine(lineno=lineno, text=cleaned, suppress=suppress))
    return out

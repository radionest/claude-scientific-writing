"""Document view over a .qmd: prose lines plus sentence segmentation.

Line-scoped regex rules read `lines`; punctuation rules read `sentences`; abbreviation,
casing and repeat rules read the whole document. Extraction itself stays in
`lib.qmd_prose` — this only adds structure on top.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from lib.qmd_prose import ProseLine, extract_prose

# Tokens that carry a period without ending a sentence.
_ABBR = frozenset("""
др т е д рис табл г гг в вв см мм мл кг сек мин соавт проф акад доц напр
ср стр с п пп им обр etc al vs no
""".split())

_SENT_BREAK = re.compile(r'([.!?…]+)(["»”)\]]*)(\s+)')
_LAST_WORD = re.compile(r"([^\W\d_]+)\W*$", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Sentence:
    lineno: int
    col: int  # 1-based column of the sentence start within its line
    text: str


@dataclass(frozen=True, slots=True)
class Document:
    path: str
    lines: tuple[ProseLine, ...]
    sentences: tuple[Sentence, ...]
    suppressed: dict[int, frozenset[str]] = field(default_factory=dict)

    @staticmethod
    def from_source(source: str, path: str = "<text>") -> "Document":
        lines = tuple(extract_prose(source))
        sentences = tuple(s for pl in lines for s in split_sentences(pl))
        suppressed = {pl.lineno: frozenset(pl.suppress) for pl in lines if pl.suppress}
        return Document(path=path, lines=lines, sentences=sentences, suppressed=suppressed)

    def is_suppressed(self, lineno: int, rule_id: str) -> bool:
        return rule_id in self.suppressed.get(lineno, frozenset())

    def line_text(self, lineno: int) -> str:
        for pl in self.lines:
            if pl.lineno == lineno:
                return pl.text
        return ""


def split_sentences(pl: ProseLine) -> list[Sentence]:
    """Segment one prose line into sentences.

    Sentences are segmented *within* a line: in .qmd a paragraph is normally one line.
    A hard-wrapped paragraph yields one sentence per line fragment, which costs recall on
    cross-line constructions but keeps every finding on an exact line.
    """
    text = pl.text
    out: list[Sentence] = []
    start = 0
    for m in _SENT_BREAK.finditer(text):
        head = text[start:m.start()]
        if _is_abbreviation(head):
            continue
        end = m.end(2)
        piece = text[start:end]
        if piece.strip():
            out.append(Sentence(lineno=pl.lineno, col=start + 1, text=piece))
        start = m.end()
    tail = text[start:]
    if tail.strip():
        out.append(Sentence(lineno=pl.lineno, col=start + 1, text=tail))
    return out


def _is_abbreviation(head: str) -> bool:
    """True if the period closing `head` belongs to an abbreviation or an initial."""
    m = _LAST_WORD.search(head)
    if not m:
        return False
    word = m.group(1)
    return len(word) == 1 or word.lower() in _ABBR

"""docs/design.md anchors prose claims on concrete test names and test-module names;
renaming a test or merging a module must not leave a dead anchor in the doc, caught
by nothing. Every ``test_*`` identifier mentioned in the doc must resolve to either
a ``def <name>`` in some tests/*.py source or a tests/<name>.py module file — a regex
sweep, no imports."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_design_md_test_anchors_resolve():
    doc = (ROOT / "docs" / "design.md").read_text(encoding="utf-8")
    anchors = sorted(set(re.findall(r"\btest_\w+", doc)))
    assert anchors, "no test_* anchors found in docs/design.md — extraction broke"

    sources = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "tests").rglob("*.py")}
    dead = [
        name for name in anchors
        if not any(re.search(rf"\bdef {name}\b", src) for src in sources.values())
        and f"{name}.py" not in sources
    ]
    assert not dead, f"docs/design.md anchors on names that no longer exist: {dead}"

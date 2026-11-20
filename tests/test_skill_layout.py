"""Progressive-disclosure layout: SKILL.md stays a compact procedural core; heavy
reference material lives in references/ and is routed from the core. Rule behavior is
pinned elsewhere (fixtures, eval manifest) — this pins the shape, so the monoliths
cannot quietly grow back."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BUDGETS = {
    "writing-russian-academic-prose": 210,
    "say-it-once-academic-prose": 130,
    "reader-first-academic-prose": 140,
}
REFERENCES = {
    "writing-russian-academic-prose": [
        "punctuation.md", "nominalization.md", "voice-and-agency.md",
        "bayes-terminology.md", "examples.md", "rhetoric.md",
    ],
    "say-it-once-academic-prose": [
        "repeat-types.md", "information-placement.md", "examples.md",
    ],
    "reader-first-academic-prose": [
        "paragraphs.md", "claims-and-caveats.md", "cold-read.md",
    ],
}


@pytest.mark.parametrize("skill", sorted(BUDGETS))
def test_skill_md_stays_compact(skill):
    path = ROOT / "skills" / skill / "SKILL.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= BUDGETS[skill], (
        f"{skill}: SKILL.md grew to {len(lines)} lines — move a section to references/")


@pytest.mark.parametrize("skill,ref", [(s, r) for s, rs in REFERENCES.items() for r in rs])
def test_reference_exists_nonempty_and_routed(skill, ref):
    skill_dir = ROOT / "skills" / skill
    ref_file = skill_dir / "references" / ref
    assert ref_file.is_file(), f"missing {ref_file}"
    assert len(ref_file.read_text(encoding="utf-8").splitlines()) >= 10, ref_file
    core = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert f"references/{ref}" in core, f"SKILL.md does not route to {ref}"


def test_section_moves_routed_and_stays_a_pointer():
    text = (ROOT / "canon" / "section-moves.md").read_text(encoding="utf-8")
    for profile in ("article.md", "report.md"):
        assert "section-moves.md" in (ROOT / "canon" / "profiles" / profile).read_text(
            encoding="utf-8"
        ), f"canon/profiles/{profile} does not route to section-moves.md"
    # Discussion norms live in the writing-discussion skill — only a pointer here.
    assert "writing-discussion" in text
    assert len(text.splitlines()) <= 80, "section-moves.md grew — functions, not norms"
    # educational is explicitly out of scope.
    assert "educational" in text

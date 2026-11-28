"""The rule-set contour is family-wide: every prose CLI (`lint_prose`, `tune_diff`,
`docx_review`, `review_plan`) accepts the same `--dictionary` / `--local-dictionary` /
`--no-local` trio, threads it into `effective_entries`, and derives the
degraded-morphology note (and the plan's `covered_by_lint`) from that effective set.

One bug kept being found per entry point (issues #44, #55, #77, #93): a tool deriving
the note or the triage rule set from canon-only/defaults-only entries describes a
different rule set than the one it actually applied. These tests pin the family, not
the instances."""
import json
import subprocess

import pytest

import lib.lint_prose
from lib.lint_prose import degraded_note, effective_entries, load_check_entries
from lib.lint_prose import main as lint_main
from lib.morph import Morph
from lib.review_plan import main as review_main
from lib.tune_diff import main as tune_main
from lib.docx_review import main as docx_main
from tests.test_docx_review import _anchor, _docx, _para, _run

# Two canon checks the overlay moves across the note's lists: `punct-comma-deeprichastie`
# (needs morph, no canon `severity_without_morph` → listed as skipped) gains a degraded
# severity (moves to «ослабленный режим»), `ortho-hyphen-linebreak` (listed as demoted)
# is disabled outright. A note derived from canon-only entries describes a different set.
OVERLAY = [
    {"id": "punct-comma-deeprichastie", "severity_without_morph": "info"},
    {"id": "ortho-hyphen-linebreak", "disabled": True},
]

CUSTOM_RULE = {"id": "calque-kvazi", "pattern": "квазирандомизированн",
               "severity": "warn", "message": "калька quasi-random", "layer": "universal"}


@pytest.fixture(autouse=True)
def _clear_git_cache():
    # effective_entries caches per rule-set key; the CLI runs below must not reuse
    # entries computed under a previous flag combination.
    lib.lint_prose._clear_caches()
    yield
    lib.lint_prose._clear_caches()


def _overlay(tmp_path, entries=OVERLAY):
    p = tmp_path / "overlay.json"
    p.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    return p


def _qmd(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def no_morph(monkeypatch):
    monkeypatch.setattr(Morph, "load", lambda: Morph(available=False))


@pytest.mark.parametrize("main", [lint_main, tune_main, docx_main, review_main],
                         ids=["lint_prose", "tune_diff", "docx_review", "review_plan"])
def test_uniform_rule_set_flag_contour(main, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--dictionary", "--local-dictionary", "--no-local"):
        assert flag in out, f"{main.__module__} is missing {flag} — the contour is per-entry-point again"


def test_house_pack_rides_the_contour(tmp_path, capsys):
    """The pack is rule-set input like the overlay: its terms drive `doc-term-canon` and
    the plan's `covered_by_lint`, and `--no-local` drops them from both."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    d = tmp_path / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "house.json").write_text(json.dumps(
        {"name": "h", "terms": [{"canonical": "мастер-модель", "forbidden": ["прототип"]}]},
        ensure_ascii=False), encoding="utf-8")
    dirty = tmp_path / "dirty.qmd"
    dirty.write_text("Печать прототипа заняла весь день.\n", encoding="utf-8")
    clean = tmp_path / "clean.qmd"
    clean.write_text("Печать мастер-модели заняла весь день.\n", encoding="utf-8")

    assert lint_main([str(dirty), "--json"]) == 0
    assert "doc-term-canon" in capsys.readouterr().out
    assert lint_main([str(dirty), "--json", "--no-local"]) == 0
    assert "doc-term-canon" not in capsys.readouterr().out

    def covered(*args: str) -> bool:
        assert review_main([str(clean), "--json", *args]) == 0
        dims = json.loads(capsys.readouterr().out)["dimensions"]
        return next(d for d in dims if d["id"] == "terminology")["covered_by_lint"]

    assert covered() is True
    assert covered("--no-local") is False


def test_lint_prose_note_from_effective_set(tmp_path, capsys):
    f = _qmd(tmp_path, "doc.qmd", "Очаги распознавали вручную.\n")
    ov = _overlay(tmp_path)
    rc = lint_main([str(f), "--no-morph", "--local-dictionary", str(ov)])
    err = capsys.readouterr().err.strip()
    assert rc == 0
    # The oracle discriminates: the canon-only note (the pre-#77 derivation) disagrees
    # with the effective-set note on both overlay edits above.
    assert "ortho-hyphen-linebreak" in degraded_note(load_check_entries(None), tool="lint_prose")
    assert err == degraded_note(
        effective_entries(f, dictionary=None, local_dictionary=str(ov), use_local=True)[1],
        tool="lint_prose")
    assert "ortho-hyphen-linebreak" not in err


def test_tune_diff_note_from_effective_set(tmp_path, capsys, no_morph):
    pristine = _qmd(tmp_path, "pristine.qmd", "Очаги распознавали вручную.\n")
    edited = _qmd(tmp_path, "edited.qmd", "Очаги распознавали вручную.\n")
    ov = _overlay(tmp_path)
    rc = tune_main([str(pristine), str(edited), "--local-dictionary", str(ov)])
    err = capsys.readouterr().err.strip()
    assert rc == 0
    assert err == degraded_note(
        effective_entries(edited, dictionary=None, local_dictionary=str(ov), use_local=True)[1],
        tool="tune_diff")


def test_docx_review_note_from_effective_set(tmp_path, capsys, no_morph):
    p = _docx(tmp_path, [_para(_run("Очаги распознавали вручную."))], [])
    ov = _overlay(tmp_path)
    rc = docx_main([str(p), "--local-dictionary", str(ov)])
    err = capsys.readouterr().err.strip()
    assert rc == 0
    assert err == degraded_note(
        effective_entries(p, dictionary=None, local_dictionary=str(ov), use_local=True)[1],
        tool="docx_review")


def test_docx_review_dictionary_flags_reach_triage(tmp_path, capsys):
    """Triage must score exactly the rule set the flags name: a custom canon that covers
    the anchor clears it, the default canon misses it, a forced overlay covers it,
    `--no-local` drops the overlay even when forced (#93)."""
    custom = _overlay(tmp_path, [CUSTOM_RULE])
    p = _docx(tmp_path, [_para(_run("Дизайн "), _anchor("1", "квазирандомизированный"),
                               _run(" критиковали рецензенты."))],
              [("1", "Ред", "калька")])
    rc = docx_main([str(p), "--only-missed", "--json", "--dictionary", str(custom)])
    assert rc == 0 and json.loads(capsys.readouterr().out) == []

    rc = docx_main([str(p), "--only-missed", "--json"])
    assert rc == 0
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1 and items[0]["triage"] == "FN"

    rc = docx_main([str(p), "--only-missed", "--json", "--local-dictionary", str(custom)])
    assert rc == 0 and json.loads(capsys.readouterr().out) == []

    rc = docx_main([str(p), "--only-missed", "--json", "--local-dictionary", str(custom),
                    "--no-local"])
    assert rc == 0
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1 and items[0]["triage"] == "FN"


def test_tune_diff_local_dictionary_flags_reach_triage(tmp_path, capsys):
    pristine = _qmd(tmp_path, "pristine.qmd", "Очаги распознавали вручную.\n")
    edited = _qmd(tmp_path, "edited.qmd", "Квазирандомизированный дизайн критиковали рецензенты.\n")
    ov = _overlay(tmp_path, [CUSTOM_RULE])
    rc = tune_main([str(pristine), str(edited), "--local-dictionary", str(ov), "--json"])
    assert rc == 0
    hunks = json.loads(capsys.readouterr().out)
    assert len(hunks) == 1 and hunks[0]["triage"] == "FP" and hunks[0]["rule_hit"] == "calque-kvazi"

    rc = tune_main([str(pristine), str(edited), "--no-local", "--json"])
    assert rc == 0
    hunks = json.loads(capsys.readouterr().out)
    assert len(hunks) == 1 and hunks[0]["triage"] == "FN" and hunks[0]["rule_hit"] is None


def test_custom_dictionary_errors_exit_clean(tmp_path, capsys):
    """A user-supplied `--dictionary` is rule-set input like the overlay: broken files
    (missing, entry without `pattern`) must reach the clean ConfigError path (exit 3),
    not a traceback — by the hook contract exit 1 means «error-severity findings»."""
    qmd = _qmd(tmp_path, "doc.qmd", "Очаги распознавали вручную.\n")
    docx = _docx(tmp_path, [_para(_run("Очаги распознавали вручную."))], [])
    runs = [(lint_main, [str(qmd)]), (tune_main, [str(qmd), str(qmd)]),
            (docx_main, [str(docx)])]
    missing = str(tmp_path / "nope.json")
    no_pattern = tmp_path / "no-pattern.json"
    no_pattern.write_text(json.dumps({"entries": [{
        "id": "calque-x", "kind": "regex", "severity": "warn",
        "message": "m", "layer": "universal"}]}, ensure_ascii=False), encoding="utf-8")

    for main, base in runs:
        rc = main([*base, "--dictionary", missing])
        err = capsys.readouterr().err
        assert rc == 3, err
        assert "ошибка" in err

    for main, base in runs:
        rc = main([*base, "--dictionary", str(no_pattern)])
        err = capsys.readouterr().err
        assert rc == 3, err
        assert "pattern" in err

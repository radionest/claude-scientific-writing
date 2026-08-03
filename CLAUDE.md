# scientific-writing — plugin dev notes

Claude Code plugin (staged Russian scientific-medical writing + deterministic prose linter).
See `docs/design.md` for architecture.

## Tests
Run from repo root: `.venv/bin/pytest` — pytest `pythonpath` is set in `pyproject.toml`, no `PYTHONPATH=` prefix needed.
Morphology-dependent tests skip themselves when the optional extra is absent: `.venv/bin/pip install -e '.[morph]'`.

## Where a rule goes
| Rule is about | Put it in |
|---|---|
| a lexical calque, jargon, term canon | `canon/dictionary.json` (regex) |
| punctuation / orthography, closed list | `canon/orthography.json` (regex) |
| needs morphology, a whole sentence, or the whole document | `lib/checks/*.py` + a `kind: "check"` entry in `canon/orthography.json` |
| this document only (terms, abbreviations, wordlist) | project overlay `<git-root>/.claude/scientific-writing/dictionary.json` |
| judgment (когда тире законно, «;», ритм) | the prose skills — **not** the linter |

## Gotchas
- `tests/fixtures/*.qmd` **intentionally contain calques and punctuation errors** — they are the linter's oracle (`calques.qmd` lexical, `editor-review.qmd` orthography/punctuation/consistency). Never "fix" them; the hook (`hooks/text-lint.sh`) explicitly skips this path.
- `canon/dictionary.json` + `canon/orthography.json` are the **source of truth** for rules: `lib/lint_prose.py` consumes both and the prose skills reference them. Add or adjust a *cross-project* rule there, not in skill prose. A **project-local** overlay (`<git-root>/.claude/scientific-writing/dictionary.json`, `layer: doc`) is merged on top per-repo (add / override-by-id / `disabled` / `allow`); document-specific rules and the project term wordlist belong there.
- Morphology (`lib/morph.py`) is **optional and soft-imported** — the hook runs the linter under the system `python3`, which usually lacks it. Never make a check hard-fail without it: skip, or declare `severity_without_morph`. `mawo-pymorphy3` needs `dawg-python` and exposes `word_is_known()` only on `analyzer._dawg_dict`; `Parse.is_known` is always `True`.
- `lint_prose --json` prints a **flat array** of findings — `/text-review` and `/tune-draft` parse it. The degraded-morphology note goes to stderr on purpose; don't wrap stdout in an object.
- `.claude-plugin/plugin.json` has **no `version` field on purpose** — Claude Code then uses the git commit SHA as the version, so the plugin auto-updates per commit. Do not "fix" this by adding `version` (that would pin it and require manual bumps).

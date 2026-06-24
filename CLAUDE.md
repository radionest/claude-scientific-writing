# scientific-writing — plugin dev notes

Claude Code plugin (staged Russian scientific-medical writing + deterministic prose linter).
See `docs/design.md` for architecture.

## Tests
Run from repo root: `.venv/bin/pytest` — pytest `pythonpath` is set in `pyproject.toml`, no `PYTHONPATH=` prefix needed.

## Gotchas
- `tests/fixtures/*.qmd` **intentionally contain calques** — they are the linter's oracle. Never "fix" them; the hook (`hooks/text-lint.sh`) explicitly skips this path.
- `canon/dictionary.json` is the **single source of truth** for calque patterns: `lib/lint_prose.py` consumes it and the prose skills reference it. Add or adjust a calque there, not in skill prose.

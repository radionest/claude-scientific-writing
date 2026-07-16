# scientific-writing — plugin dev notes

Claude Code plugin (staged Russian scientific-medical writing + deterministic prose linter).
See `docs/design.md` for architecture.

## Tests
Run from repo root: `.venv/bin/pytest` — pytest `pythonpath` is set in `pyproject.toml`, no `PYTHONPATH=` prefix needed.

## Gotchas
- `tests/fixtures/*.qmd` **intentionally contain calques** — they are the linter's oracle. Never "fix" them; the hook (`hooks/text-lint.sh`) explicitly skips this path.
- `canon/dictionary.json` is the **universal source of truth** for calque patterns: `lib/lint_prose.py` consumes it and the prose skills reference it. Add or adjust a *cross-project* calque there, not in skill prose. A **project-local** overlay (`<git-root>/.claude/scientific-writing/dictionary.json`, `layer: doc`) is merged on top per-repo (add / override-by-id / `disabled`); document-specific rules belong there, not in the plugin dictionary.
- `.claude-plugin/plugin.json` has **no `version` field on purpose** — Claude Code then uses the git commit SHA as the version, so the plugin auto-updates per commit. Do not "fix" this by adding `version` (that would pin it and require manual bumps).

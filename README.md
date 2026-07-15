# scientific-writing

Claude Code plugin: staged Russian scientific-medical writing (spec → write → review → fix)
with a deterministic prose linter. See `docs/design.md`.

## Project-local dictionary

The linter merges an optional per-project dictionary on top of the plugin's universal `canon/dictionary.json`:

- Path: `<git-root>/.claude/scientific-writing/dictionary.json` (tracked; same schema as the plugin dictionary, `layer: doc`).
- A new `id` adds a rule; reusing a built-in `id` replaces that entry wholesale — re-declare `except` if the built-in had one; `{"id": "<id>", "disabled": true}` mutes a built-in rule for this project only.
- Local `error` rules gate only this repo's commits, so they are safe to block on.
- Flags: `--no-local` ignores it; `--local-dictionary <path>` forces a non-standard location.

`/init-doc-spec` seeds this file from a document's machine-checkable local bans.

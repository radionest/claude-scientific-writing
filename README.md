# scientific-writing

Claude Code plugin: staged Russian scientific-medical writing (spec → write → review → fix)
with a deterministic prose linter. See `docs/design.md`.

## Project-local dictionary

The linter's universal rules live in `canon/dictionary.json` (lexical calques) and
`canon/orthography.json` (punctuation, orthography, whole-document consistency). An optional
per-project dictionary merges on top of both:

- Path: `<git-root>/.claude/scientific-writing/dictionary.json` (tracked; same schema as the plugin dictionaries, `layer: doc`).
- A new `id` adds a rule; reusing a built-in `id` overrides it **field-wise**, so you only restate what you change; `{"id": "<id>", "disabled": true}` mutes a built-in rule for this project only.
- A check rule (`kind: "check"` — `ortho-spelling`, `doc-abbrev-variants`, `doc-repeat-window`, …) is tuned with an `allow` list of this project's terms and abbreviations: `{"id": "ortho-spelling", "allow": ["ремнант", "волюмометрия"]}`.
- That `allow` list **replaces** the canon one entirely (field-wise override, not a merge): to extend `doc-repeat-window`, list the canon stop-words from `canon/orthography.json` as well; give words in all surface forms (`очаг`, `очаги` — see the canon allow list) — without morphology (the hook path) there is no lemmatization, each form has its own key.
- Local `error` rules gate only this repo's commits, so they are safe to block on.
- Flags: `--no-local` ignores it; `--local-dictionary <path>` forces a non-standard location; `--no-morph` ignores the optional morphology extra (`pip install -e '.[morph]'`), matching how the commit hook runs.

`/init-doc-spec` seeds this file from a document's machine-checkable local bans.

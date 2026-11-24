# scientific-writing

Claude Code plugin: staged Russian scientific-medical writing (spec → write → review → fix)
with a deterministic prose linter. See `docs/design.md`.

## Render lint

`lib/lint_prose.py` never sees table text or captions — they are generated inside fenced
chunks and exist as prose only in the rendered .docx. `lib/render_lint.py` runs the canon's
regex rules (plus the project overlay when `--qmd` is given) over that render (paragraphs +
table cells) and points each finding back at the generating chunk (`--qmd`); vertical checks
over the same pass flag caption-sequence gaps, reordering, mention↔caption ref targets and
heading-level skips (all warn, silent when the material is absent). The advisory
`/render-review` skill pairs it with a subagent review of the chunks themselves.

## Project-local dictionary

The linter's universal rules live in `canon/dictionary.json` (lexical calques) and
`canon/orthography.json` (punctuation, orthography, whole-document consistency). An optional
per-project dictionary merges on top of both:

- Path: `<git-root>/.claude/scientific-writing/dictionary.json` (tracked; same schema as the plugin dictionaries, `layer: doc`).
- A new `id` adds a rule; reusing a built-in `id` overrides it **field-wise**, so you only restate what you change; `{"id": "<id>", "disabled": true}` mutes a built-in rule for this project only.
- A check rule (`kind: "check"` — `ortho-spelling`, `doc-abbrev-variants`, `doc-repeat-window`, …) is tuned with an `allow` list of this project's terms and abbreviations: `{"id": "ortho-spelling", "allow": ["ремнант", "волюмометрия"]}`.
- That `allow` list **replaces** the canon one entirely (field-wise override, not a merge): to extend `doc-repeat-window`, list the canon stop-words from `canon/orthography.json` as well. Matching differs per rule: `doc-repeat-window` folds words into keys — the lemma with the morphology extra, otherwise (a run without it; the hook path is one) the first six characters. An entry exempts the forms folding to it: a six-character entry («пациен») covers the whole «пациент» family, a longer one («пациенты») only its exact form, and forms differing within the six characters («очаг», «очаги» — see the canon allow list) keep distinct keys — one entry each. `ortho-spelling` matches by lemma and stem, so one entry covers the word family and its derived adjectives («абляция» exempts «абляционную» too).
- Local `error` rules gate only this repo's commits, so they are safe to block on.
- Seeding is enforced, not advisory: rules marked `seed: "allow"` (`ortho-spelling`, `doc-abbrev-variants`) escalate their findings from `info` to `warn` on changed lines in `--diff` mode, and `lib.lint_prose <doc>.qmd --unseeded` prints the unseeded-word counts a workflow must disposition (seed or fix).
- Flags: `--no-local` ignores it; `--local-dictionary <path>` forces a non-standard location; `--no-morph` ignores the optional morphology extra (`pip install -e '.[morph]'`), matching how the commit hook runs.

`/init-doc-spec` seeds this file from a document's machine-checkable local bans.

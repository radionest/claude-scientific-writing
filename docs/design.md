# Design: `scientific-writing` plugin — staged scientific-text authoring (spec → write → review → fix)

**Date:** 2026-06-23
**Status:** approved design (brainstorm), pre-plan

## Goal

A superpowers-style plugin that turns Russian scientific medical writing into a disciplined pipeline —
**spec → write → review → fix** — and cleanly separates **text** review from **code** review (pre and post).
Kills the recurring calque-churn (lesion_nature_report PRs #85–#121: a large share are prose-cleanup
re-fixing the *same* classes — метод-как-деятель, тире-калька, референсный) by making the
"bad phrases" a single machine-checkable source and gating prose at PR time.

## Decisions settled in brainstorm

| Question | Decision |
|---|---|
| Packaging | **Superpowers-style plugin**, cross-project, reuses/owns the prose skills |
| Bad-phrase mechanism | **Layered**: deterministic linter (regex dictionary) + prose skills (judgment) |
| Spec model | **Layered**: universal canon + genre profile + per-document spec |
| Text-pre gate | **Blocking hook on the linter** (deterministic, no LLM in the gate); agent ensemble is advisory |
| Genres | **All three**: data-driven reports, journal articles, educational/slide articles |
| Build scope | **Whole plugin at once** (all stages + 3 genres + migration) |
| Writer | **Plugin owns the writer** (`scientific-writer`); generic `quarto-article-writer` deprecated; `init-article` stays project-bootstrap |
| Review orchestrator | **Ensemble of subagents** (dimensions in parallel + synthesis), à la `pr-diff-reviewer` |

## Architecture: 3 discipline layers × 4 stages

Genres have **conflicting style** (educational slides want short subsections + lists; научная проза bans
both). So the canon splits — universal rules bind everywhere, genre rules override style:

| Layer | Holds | Scope |
|---|---|---|
| **Canon (universal)** | calques, усечения (гистология→гистологическое исследование), term-drift, instrument-as-agent | all genres |
| **Genre profile** | section template, sentence rhythm, lists-vs-prose | selected genre |
| **Document spec** | this doc's sections + its terms (histology-truth rule, «мастер-модель» canon) | one document |

Stages: **spec → write → review → fix**. Review = deterministic linter (literal calques) + prose-skill
ensemble (judgment — when тире is legitimate, when «полностью» is a graduable-process verb, cross-section
repeats).

## Component manifest

```
scientific-writing/                      # own git repo (see "Where it lives")
  .claude-plugin/
    plugin.json                          # manifest (no hooks field; version bumped manually — see AGENTS.md)
    marketplace.json                     # local marketplace entry (install via /plugin marketplace add)
  canon/
    canon.md                             # human-readable universal canon (prose discipline + term policy)
    dictionary.json                      # MACHINE universal source: regex + bad/good + message + severity + layer
    orthography.json                     # punctuation/orthography rules + kind:"check" declarations
    section-moves.md                     # rhetorical functions of sections (argument layer; judgment, not machine rules)
    profiles/
      report.md  article.md  educational.md   # per-genre section templates + style deltas
  skills/
    writing-scientific-documents/SKILL.md      # orchestrator-entry (spec→write→review→fix)
      references/                              # rewrite-preservation
    writing-russian-academic-prose/SKILL.md    # phrase level: triggers/diagnosis/exceptions + routing
      references/                              # punctuation, nominalization, voice-and-agency, bayes-terminology, examples
    say-it-once-academic-prose/SKILL.md        # document level: repeats / information architecture
      references/                              # repeat-types, information-placement, examples
    reader-first-academic-prose/SKILL.md       # argument level: paragraph contract, claims/caveats, cold read
      references/                              # paragraphs, claims-and-caveats, cold-read
    tuning-rules/SKILL.md                      # rule-derivation discipline (see tune-draft/tune-learn)
    init-doc-spec/SKILL.md                     # scaffold a per-document spec from canon + genre (interactive)
    text-edit/SKILL.md                         # scoped .qmd edit: light/deep modes, protected inventory, revision_guard + fidelity check
    text-review/SKILL.md                       # advisory ensemble orchestrator (linter + prose subagents)
    tune-draft/SKILL.md                        # rule-calibration loop: generate → hand-edit
    tune-learn/SKILL.md                        # … → derive rule changes from the edit
    eval-prose/SKILL.md                        # eval harness run: lint baseline + behavioral rewrite eval
    render-review/SKILL.md                     # advisory render review: render_lint + render ensemble dimension
  agents/
    scientific-writer.md                 # spec/canon/genre-aware writer
    prose-reviewer.md                    # one parameterized ensemble agent, dispatched once per dimension (dimension = arg)
  hooks/
    hooks.json                           # PreToolUse registration (auto-read; never declared in plugin.json)
    text-lint.sh                         # gate gh pr create / git commit on linter ERROR findings
  lib/
    lint_prose.py                        # deterministic linter (regex entries + code checks)
    qmd_prose.py                         # shared: extract narrative prose from .qmd (skip code/yaml/tables/refs/biblio/latin)
    document.py                          # sentence + whole-document view over the extracted prose
    morph.py                             # OPTIONAL Russian morphology adapter (soft import)
    checks/                              # kind:"check" implementations: hyphenation, spelling, punctuation, consistency
    tune_diff.py                         # pristine→edited prose diff + FN/FP triage
    docx_review.py                       # editor .docx review → the same triage shape
    render_lint.py                       # rendered .docx lint — table text + captions, vertical checks (advisory)
    protected_spans.py                   # raw-span extractor: the artifacts an edit must not damage
    revision_guard.py                    # before/after artifact diff for scoped edits (advisory CLI)
    citation_audit.py                    # local citation audit
    claim_registry.py                    # claims+numbers sidecar check
  docs/
    design.md                            # this file, carried over
```

Progressive disclosure (2026-11-19): the prose skills keep triggers, diagnosis,
mandatory exceptions and the edit order in `SKILL.md`; tables with worked examples and
special references live in `references/`, routed from the core, each piece of content
in exactly one place. `tests/test_skill_layout.py` pins the shape. The canon stays the
only machine-readable rule source — references carry judgment only.

## Check kinds and scopes (added 2026-08-03)

The original design had one rule shape — a regex over one prose line. A real editor review
(105 comments on `lesion_nature_report`'s article) showed that shape reaches about a fifth
of what an editor flags: half the review was **punctuation and orthography**, and another
chunk was **document-scoped consistency**, neither of which a per-line regex can express.
So a rule is now one of two kinds, and checks see more than a line:

| Kind | Declared in | Sees | Examples |
|---|---|---|---|
| `regex` (default) | `canon/dictionary.json` (lexical), `canon/orthography.json` (punctuation) | one prose line | `calque-referens`, `style-takzhe-slitno`, `punct-percent-spacing` |
| `check` | `canon/orthography.json` with `kind: "check"`, implemented in `lib/checks/*.py` | a sentence or the whole document | `ortho-hyphen-linebreak`, `punct-comma-prichastie`, `doc-abbrev-variants`, `doc-list-marker-consistency` |

Both kinds share `severity`, `message`, `except`, the project-local overlay and
`<!-- lint-ok: id -->` (`allow` is read by check functions only). `lib/document.py` supplies the
sentence/document view; a check
yields `Hit(lineno, col, matched, detail)` and `lib/lint_prose.py` stamps the entry's
metadata onto it.

**Optional morphology** (`lib/morph.py`, extra `pip install '.[morph]'` →
`mawo-pymorphy3` + `dawg-python`). Soft import: `hooks/text-lint.sh` runs the linter under
the system `python3`, which usually lacks it, so the linter must never hard-fail. A rule
whose precision depends on the dictionary declares `severity_without_morph`.

| | with morphology | without |
|---|---|---|
| `ortho-hyphen-linebreak` | `error` — 7/7 with no false positives on the review | `warn` — "occurs once in the document" heuristic, ~50 % precision |
| `ortho-spelling` | `info`, needs a project `allow` wordlist | skipped |
| `punct-comma-prichastie`, `-deeprichastie` | `warn` | skipped |

What morphology buys is *dictionary membership*, not part-of-speech tagging as such: bare
POS tags read «время» as GRND and «данным» as PRTF. Every POS query goes through
`Morph.has_pos`, which requires the reading to be the top **dictionary** parse.

`ortho-hyphen-linebreak` shows the shape of that: its discriminator is membership, not a
wordlist of legitimate compounds —

    artifact  iff  known(left + right)  and not (known(left) and known(right))

«невоз-можности» joins into a word whose halves are not words; «мастер-модели» is the mirror
image. Without morphology it falls back to "this hyphenated form occurs exactly once in the
document", which halves precision — hence the demotion to `warn`.

**Not everything punctuational belongs here.** «;» was implemented and removed: it fired 16
times on a review where the editor asked for a comma twice, because the two legitimate uses
(перечень рубрик, однородные ряды с запятыми внутри) are a judgment call.
`skills/writing-russian-academic-prose` § «Точка с запятой» owns it.

## Eval manifest and corpora (added 2026-11-16)

Above the fixture oracle (`tests/fixtures/*.qmd`: a finding must appear on each defective
line) sits the eval layer, `tests/eval/`:

- `lint-manifest.json` — every canon rule registered with its pinned severity and a
  rationale; bad/good stay in canon (single source), the manifest pins id/severity and
  freezes the finding profiles of the two corpus documents. A canon change that shifts a
  severity or any profile fails `tests/test_lint_manifest.py` until the manifest is
  consciously updated — baseline drift cannot pass silently. Without the morph extra the
  profile comparison filters rules that go silent (`needs_morph`) or demote
  (`severity_without_morph`).
- `lint-good.qmd` — legitimate passive voice, dashes, semicolons, номинализация,
  причастные/деепричастные обороты, содержательные антитезы и триады, term repetition,
  hedges, a null result: zero errors, the only findings being `ortho-spelling` infos on
  real medical vocabulary. A new warning on this text is a false positive to account
  for, not noise.
- `lint-bad.qmd` — 58 of the 59 canon rules fire; the commit hook exempts it by path
  identity with the plugin's own corpus (the dev repo's or the installed copy's), not by
  the `tests/eval/lint-bad.qmd` suffix a user file could carry (#89), while
  `lint-good.qmd` stays gated.
- `rewrite-cases.json` — meaning-damage minimal pairs (lost negation/quantifier/
  comparator, modality shifts, denominator change, dropped citation key, altered inline
  code, plus clean controls) that the linter provably does not see: catching them is the
  semantic reviewer's job, not the regex layer's. Gold set for the future revision
  fidelity work.
- `/eval-prose` runs the deterministic baseline and the behavioral rewrite eval (hidden
  rubric, fresh subagents, gitignored JSON reports, A/B against a previous report);
  behavioral runs stay out of blocking CI.

## Render lint (added 2026-11-14)

Some defects materialize only in the render: table text and captions live in fenced chunks
(`#| tbl-cap:` / `#| fig-cap:` options, f-strings) that `qmd_prose` skips, so `lint_prose`
never sees them. `lib/render_lint.py` runs the canon's regex-kind rules over every paragraph
and table cell of the rendered .docx — regex-only (check-kind rules expect sentences and
whole documents, the wrong shape for cell fragments) and advisory: no hook gates on it.
`--qmd` attaches a `qmd:L12 (chunk)` hint by locating the matched text in the generating
chunk; `/render-review` pairs this lint with the `render` ensemble dimension of
`prose-reviewer` (chunk-level judgment: unconditional missing-data rows, denominators).

Vertical checks (added 2026-11-20) ride the same pass: `_vertical_checks` reads paragraph
styles and caption/mention numbers — table and figure sequence (jumps, duplicates),
mention↔caption ref targets («табл. N»), heading-level skips by `Heading1…6` styles. All
warn, skip when the material is absent (a non-Quarto .docx stays quiet), CLI and exit
policy unchanged. Cross-reference existence is checked only at the render — `#| label:`
lives in fenced chunks `Document` never sees; a source-side `@tbl-`↔label audit stays out
of scope (cf. the citation-audit wiring, #63).

## The dictionary — universal source of truth (`canon/dictionary.json`)

Consolidates what was scattered across two skill tables + 4 feedback-memory files. The linter consumes
`pattern/message/severity/except`; the prose skills **reference** this file as the machine-readable source
and keep only the nuance regex can't express — since #17 the inline calque tables are gone from the skills
(the `skill` field marks a rule's owning skill — the linter itself does not route findings by it; on divergence canon wins).

A **project-local overlay** (`<git-root>/.claude/scientific-writing/dictionary.json`, `layer: doc`) is merged
on top per-repo: a new `id` adds a rule, a reused `id` overrides it **field-wise** (restate only what
changes — `{"id": "ortho-spelling", "allow": [...]}` is a complete entry), and `{"id": "<id>", "disabled": true}`
mutes it. Document-specific rules live there; this file stays cross-project.

Entry schema:

```yaml
- id: calque-targetnyj
  layer: universal              # universal | genre:report|article|educational | doc
  pattern: '\bтаргетн\w*'       # Python re, case-insensitive, applied to extracted prose only
  except: 'терапи'              # optional: suppress if this token is near the match
  severity: error               # error (blocks PR) | warn (advisory) | info
  message: 'калька targeted → «прицельный»; «таргетная терапия» — устоявшийся онкотермин, не трогать'
  bad: 'таргетный поиск очага'
  good: 'прицельный поиск очага'
  skill: writing-russian-academic-prose   # judgment-skill that owns the nuance
```

**Severity policy** (principle; full classification in the plan):
- **error** (blocks) — unambiguous lexical calques, near-always-correct fix, low false-positive risk:
  референсный, характеризаци·, таргетный, «по построению»,
  «полностью|целиком + выявить|обнаружить|распознать», гистология/морфология/цитология *as procedure*,
  «отнести … к категории», parasites «является / осуществляется / носит … характер».
- **warn** (advisory, agent decides) — heuristic / context-dependent, false-positive-prone:
  тире density (>1 «—» per sentence), «;» density, instrument-as-agent (`метод\w*.{0,30}(распозна|выявля|визуализир)`),
  «когорт·» (только существительное: прилагательное «когортн…» — термин когортного дизайна, исключено паттерном), sentences > 40 words.
- **judgment-only** (NOT in dictionary as error) — legitimate-тире (nulevaya svyazka, ellipsis, range «–»),
  graduable «полностью удалить/резецировать» — these live in the prose skill, never block.
- **`severity_without_morph`** — a check whose precision depends on the morphology dictionary declares its
  degraded severity here, and `_effective_severity` applies it when the extra is absent (the hook's normal
  case). `ortho-hyphen-linebreak` is `error` with morphology and `warn` without.
- Punctuation is in scope for **error** only where measured precision is 100 % on a real review —
  in practice just `style-takzhe-slitno` and `ortho-hyphen-linebreak` (with morphology). Everything else in
  that class is `warn`: a gate that false-blocks on commas gets switched off, and then it protects nothing.
  Compound-conjunction commas were demoted for exactly this reason — both placements are correct Russian.

Inline suppression: `<!-- lint-ok: <id> -->` on/above a line (eslint-disable-style), for the genuinely-legit
case the regex can't tell apart. Keeps error-severity usable without false blocks.

Sourcing for initial entries: the tables in both prose skills (since #17 consolidated away — the skills
now point here) + memories `feedback_ru_report_phrasing`,
`feedback_russian_prose_skill`, `feedback_no_bold_in_docx_reports`, `project_docx_apply_bypasses_prose_pass`.

The `rhetoric-*` family (added 2026-11-20) catches shell phrases — template openings, empty
significance, vague authority, empty amplifiers — as info/warn regex rules whose message names
the consequence to supply instead of banning the pattern. The function judgment (the classes,
the specificity rule — the number is never invented — and anti-overcompensation) lives in
`skills/writing-russian-academic-prose/references/rhetoric.md`; novelty claims pay their
nearest precedent via `skills/reader-first-academic-prose/references/claims-and-caveats.md`.

## Project pack (`<git-root>/.claude/scientific-writing/house.json`, added 2026-11-25)

Next to the overlay `dictionary.json` lives the pack — what every document of a repo
shares: `name`, `genre_default`, `terms` (`canonical`, `forbidden`, `caution`, `note`),
`abbreviations` (`abbr`, `expansion`), `passport` (the «Редакционного паспорта» keys),
`norms` (`id`, `text`, `source` — project overrides of `canon/norms.json` by id),
`samples`, `lanes`. All fields optional; a malformed file, an unknown key or a wrong
type raise `ConfigError` (CLI exit 3).

`lib/house.py`:

- `house_path(target)` / `load_house(doc_path) -> House | None` — discovery mirrors
  `local_dict_path`: a linked worktree's own copy wins over the main checkout's.
- `load_norms(house)` — `canon/norms.json` ⊕ the pack's `norms` by id; the first default
  is `denominator-policy` (#75), referenced as `norms:denominator-policy` from
  `canon/profiles/article.md` and `skills/writing-russian-academic-prose/SKILL.md`.

The pack rides the rule-set contour: `effective_entries` connects it under the same
`use_local` switch (`--no-local` drops it, `--local-dictionary` does not affect it) and
its path joins the cache key. `terms` are passed to the checks through the rule records:
`doc-term-canon` (warn — a forbidden synonym, the canonical term in `detail`) and
`doc-term-caution` (info — a `caution` variant, the term's note in `detail`), both in
`lib/checks/terms.py`, morphology-free. The canon entries carry demo `terms` for the
bad/good oracle; the effective set replaces them with the pack's (or empties them), so
without a pack both rules stay silent. Pack abbreviations join the `allow` lists of
`doc-abbrev-first-use`/`doc-abbrev-variants` without duplicates. When the pack has
`terms` and the document's `doc-term-canon` run is clean, the review plan marks
`terminology` `covered_by_lint` — the flag lets the ensemble skip the duplicate
reviewer; wiring the dispatcher is the next step of the stack
(`PlanEntry.covered_by_lint`, `lib.review_plan` joined the `--dictionary` /
`--local-dictionary` / `--no-local` contour for it). `init-doc-spec` (steps 4–6)
prefills terms, abbreviations and the passport from the pack. Pinned by
`tests/test_house.py`.

## The linter (`lib/lint_prose.py`)

| Aspect | Contract |
|---|---|
| Input | a `.qmd` (whole-file mode) or a git range (`--diff [REF]`, changed prose lines only) |
| Prose extraction (`qmd_prose.py`) | exclude fenced ` ```{...} ` chunks, inline `` {python} ``, YAML front matter, markdown tables (`\|`-rows), BibTeX/`[@…]` citations, HTML comments, bare URLs, **reference sections** (a «Литература»/«References»/«Библиография» heading and everything under it until a same-or-higher heading) and **Latin-script blocks** (an English abstract — `qmd_prose.is_russian`). Headings otherwise **included** (calques appear there too) |
| Output | findings `{file,line,col,id,severity,message,matched}` — **every** match on a line, not just the first — sorted by `(line, col, id)`; human or `--json` (a flat array; the degraded-morphology note goes to stderr so the array stays the contract) |
| Exit | `1` if any **error**-severity finding (drives the hook); `3` on a malformed project-local dictionary (`2` is argparse's own usage-error code, kept distinct) |
| Modes | whole-file (for `/text-review`) vs **diff-only** (for the hook — see below) |
| Morphology | optional (`pip install -e '.[morph]'`); `--no-morph` forces the degraded path that the hook's system `python3` normally takes |
| Project-local overlay | `<git-root>/.claude/scientific-writing/dictionary.json` merged onto the base by `id` (add / **field-wise** override / `disabled`); an override restates only what it changes, so `{"id": "ortho-spelling", "allow": [...]}` is a complete entry. `--no-local` ignores it, `--local-dictionary <path>` forces a file |

**A linked worktree does not check out a gitignored overlay.** With `.claude/` gitignored, the overlay
exists only in the main checkout, so `local_dict_path` in `lib/lint_prose.py` falls back to that copy;
a tracked overlay in the worktree itself wins over the main checkout's (the worktree tests in
`tests/test_local_dict.py`: `test_local_dict_path_worktree_falls_back_to_main`,
`test_worktree_lint_sees_main_checkout_overlay`, `test_worktree_prefers_own_tracked_overlay`,
`test_local_dict_path_main_checkout_named_dotgit`).

**The rule-set contour is family-wide.** Every prose CLI — `lint_prose`, `tune_diff`, `docx_review` —
accepts the same `--dictionary` / `--local-dictionary` / `--no-local` trio and threads it into
`effective_entries`, and the degraded-morphology stderr note is derived from that effective set, so
the note and the triage describe the rule set actually applied — in a multi-file `lint_prose` run
the last file's set wins (issues #44/#55/#77/#93 were this bug found per entry point — canon-only
or defaults-only derivation). Pinned by `tests/test_rule_set_threading.py`.

**The hook scans the diff, not the whole file.** Pre-existing calque debt must not block every PR; only
**newly introduced** error-severity findings gate. `/text-review` may scan whole-file on demand.

**Seeding contract (`seed: "allow"`, issue #25).** Rules whose `allow` wordlist is the designated sink
for the document's terms — canon marks `ortho-spelling` and `doc-abbrev-variants` with `"seed": "allow"`
(a project overlay may mark its own rules the same way) — carry an enforceable contract, not an
advisory hint. Two mechanisms, neither a gate (seeding is a wordlist edit, not a prose defect):
in `--diff` mode a seeding-rule finding at `info` on a changed line is escalated to `warn` — the term
was introduced by this edit and must be dispositioned (seeded into the overlay's `allow`, or fixed);
and `--unseeded` prints a per-rule JSON report `{"<rule>": {"<word>": <count>}}` (findings per
distinct word, aggregated over all files, mutually exclusive with `--json`, exit code unchanged)
that the workflow must disposition. Escalation needs an available morphology: without it — the
hook's system-`python3` mode — a rule's `severity_without_morph` demotion, or an explicit overlay
retune of a seeding rule's severity, is not silently overridden. The `--unseeded` report works
degraded too, but there `ortho-spelling` is silent while `doc-abbrev-variants` still counts — the
stderr degraded note is the cue that the report proves less, not nothing.

## Stages

### spec — `skills/init-doc-spec/SKILL.md`
Interactive: pick genre → load `profiles/<genre>.md` → propose section outline → collect doc-specific terms
(canonical term per concept, abbreviations, any doc-local forbidden phrasings) → write `<doc>.spec.md`
(sections + term list) and a doc-scoped dictionary overlay (`layer: doc`). The doc's forbidden terms thereby
feed the same linter. Existing good report → can reverse-engineer the outline/terms, then edit.
The spec carries an «Редакционный паспорт» section for any genre (numbers, dates, ranges,
units/%, list markers, headings, the link system, house-style samples). A step-0 book guard
mirrors the orchestrator: when a book spec exists (`_quarto.yml` + `<book>/specs/*.md`), no
per-chapter spec is created.

### write — `agents/scientific-writer.md`
Inputs: target `.qmd` + its `<doc>.spec.md` + selected genre profile + canon. Drafts/edits prose conforming
to the spec's sections and the genre's style; every quantitative claim cited (carried from the current
writer); **self-checks against the dictionary — never introduces a banned calque**; verifies the seeding
contract before finishing (`--unseeded` → `{}` on the `seed: "allow"` rules, issue #25); external content it can't
make canon-clean → `<!-- TODO ред: … -->`. Supersedes the generic `quarto-article-writer`.

### review — `skills/text-review/SKILL.md` (ensemble of subagents)
1. Run `lint_prose.py` first (cheap) — its findings scope the agents (focus on what regex can't catch).
2. Dispatch parallel subagents, one per dimension:
   - **phrase-calques** — applies `writing-russian-academic-prose` to changed prose.
   - **repeats-termdrift** — applies `say-it-once-academic-prose` (cross-section, whole-doc context).
   - **structure-genre** — checks doc vs genre profile template + spec outline (missing/extra/misordered
     sections; slide-size for educational).
   - **discussion** — applies `writing-discussion` to the «Обсуждение» section (section-level
     argumentation: five moves, the findings → comparison → meaning cycle, anti-patterns);
     dispatched only when the document has an «Обсуждение» section.
   - **genre** — genre-norm counters vs the profile's Discussion section (refusal-ending
     ratio over literature paragraphs, opening quantification, restated disclaimers);
     dispatched with `discussion`, only when the document has an «Обсуждение» section.
   - **argument** — paragraph and section-move logic (`reader-first-academic-prose` +
     `canon/section-moves.md`): paragraph contract, reverse outline, section functions;
     substantive sections only (Введение/Методы/Результаты/Реферат/Заключение — the
     «Обсуждение» stays with `discussion`), skipped for single-phrase or punctuation edits.
   - **render** — chunk-level judgment over the generating chunks plus the vertical render
     lint (`lib.render_lint`: caption numbering, ref targets, heading levels) — `/render-review`.
   - **evidence** — claim–citation audit against a valid `<doc>.claims.jsonl` registry
     (`lib.claim_registry`), full articles only.
   - **terminology** — term consistency vs the spec's canonical-term list + abbreviation policy.
3. **Synthesis** pass dedups/merges + ranks → one report (blockers / warnings / nits), mirroring
   `pr-diff-reviewer`'s structure. Advisory — does not block.

Implementable as a command dispatching parallel `Agent`s, or a `Workflow` (fan-out + synthesis) for big
multi-section docs.

## Review plan (added 2026-11-25)

The ensemble dispatch had a hand-maintained copy in each consumer
(`skills/text-review/SKILL.md`, `skills/writing-scientific-documents/SKILL.md`,
`agents/prose-reviewer.md`, `hermes/skills/scientific-writing/SKILL.md`). The single
source is `canon/review-dimensions.json` — one record per dimension
`{id, tier, when, skills, source}` (`tier` is `default` for all in v1; `source` anchors
the contract at `agents/prose-reviewer.md#<id>`, which stays the home of the dimension
contracts — the anchors name the bold list items, not headings; JSON carries no comments,
so this caveat lives here; `skills` names the prose skills the reviewer applies) —
resolved per document by `lib/review_plan.py`:

- `plan(doc, *, mode, spec=None, genre=None, before=None) -> ReviewPlan`;
  `ReviewPlan(mode, dimensions)`, `PlanEntry(id, when, reason)` — included dimensions
  only, `reason` is one line. Sections come from `qmd_prose.extract_prose`, the
  «Обсуждение» flag from `checks/genre._discussion_span`, registry validity from
  `claim_registry.check_document` (an existing `<doc>.claims.jsonl` with no `schema`
  findings).
- `when` ∈ `always` (calques, repeats, terminology, structure, render) ·
  `has_section:Обсуждение` (genre, discussion) · `substantive_edit` (argument) ·
  `has_before_after` (fidelity) · `claims_registry_valid` (evidence).
- Modes: `light` drops `argument`; `diff` (the default) takes the staged changed lines
  via `lint_prose.changed_lines` and includes `argument` only when at least two prose
  lines of a substantive section (Введение, Методы, Результаты, Реферат/Аннотация,
  Заключение/Выводы) changed; `deep`/`full` take everything the conditions allow.
- CLI: `python3 -m lib.review_plan <file.qmd> [--mode diff|light|deep|full]
  [--before <path>] --json` → `{"mode", "dimensions": [{id, when, reason}]}`; exit 0
  normal, 2 missing file / usage error, 3 broken `canon/review-dimensions.json`
  (`ConfigError`, like the linter).

Consumers keep only the plan command and what each reviewer is handed (spec, genre
profile, linter findings); `/text-review` maps `--deep` → `--mode deep`, else
`--mode diff`. The contour's behavior is unchanged. Pinned by `tests/test_review_plan.py`
(registry ids = the agent's bold ids, scenario documents match the hand dispatch, CLI
contract, exit 3).

### fix
Not blind regex-replace. Unambiguous literal swaps (референсный→эталонный) auto-applied; risky ones (тире,
«полностью») edited by the prose skill **with judgment**; hard rule «never bake a calque — fix or leave
TODO» (already in `russian-qmd-prose.md`). Re-run the linter until clean.

## pre/post × code/text routing + the hook

The deliverable for "разграничить pre/post review для кода и для текста":

|  | PRE (before it leaves your hands) | POST (incorporating someone else's review) |
|---|---|---|
| **CODE** | `pr-diff-reviewer` + `pre-pr-review.sh` hook ✅ | `receiving-code-review` ✅ |
| **TEXT** | `/text-review` + **`text-lint.sh` hook (NEW)** | `apply-docx-review` + **mandatory review/fix pass** (formalized) |

**Diff router** (in `text-lint.sh` / a PreToolUse on `gh pr create`, `git commit`):
- prose-only diff (only `.qmd` narrative changed) → require **text-lint pass**; auto-satisfy the code-review
  marker (formalizes `feedback_skip_reviewer_prose_only`: write HEAD into the marker so the existing code hook
  doesn't false-block).
- diff touches `.py`/SQL/`{python}`/schemas → code path (existing `pr-diff-reviewer` + marker); text-lint
  still runs on any prose also touched.
- mixed → both gates apply.

Post-path formalization: `apply-docx-review` → `qmd-review-importer` already runs a prose pass (step 4, added
2026-06-22); the plugin makes "apply → review → lint-clean before commit" the contract, closing the
editor-reinjects-calque loop at its source.

**The editor's review also feeds the rules** (added 2026-08-03). `lib/docx_review.py` reads
comment anchors and tracked changes straight out of the OOXML parts, keeping exact offsets, and
anchors a comment stored without selected text — a bare `w:commentReference` or an empty range —
at its position instead of dropping it; when the sentence around the mark is blank, its paragraph
is the unit, so the ±25 window below still applies. It emits the triage shape `lib/tune_diff.py`
produces, so `/tune-learn --from-docx <review.docx>` runs a real editor
review through the same `tuning-rules` skill. An item counts as
`covered` only when a rule fires **on the anchor** — within ±25 characters of it
(`docx_review._NEAR`), and `info`-severity findings never count, since `ortho-spelling` fires on
live terminology. The loose version, crediting any finding in the same sentence, is what made the
old dictionary look like it covered a review it in fact missed entirely. The importer's report
generator (`~/.zcode/scripts/docx_review.py`) lost comments while it parsed them out of pandoc
markdown — a heading-anchored one in #22, 7 of 28 on a later live review.

## Genre profiles (`canon/profiles/`)

| Profile | Sections | Style deltas vs universal canon |
|---|---|---|
| `report.md` (data-driven отчёт) | Реферат · Введение · Материалы и методы (Дизайн / Пациенты / Стат.анализ) · Результаты · Обсуждение · Заключение · Список сокращений | full научная проза; inline `{python}` for numbers; crossref tables; ГОСТ 7.32 docx |
| `article.md` (журнальная статья) | Аннотация/Abstract · Введение · Материалы и методы · Результаты · Обсуждение · Выводы · Литература | journal-target; Zotero/BibTeX refs |
| `educational.md` (учебные/слайды) | Требуемые знания · Тестирование · Статья · Тесты · Рекомендации (existing `article-writer` template) | **relaxes** universal "no rubленый style / prefer prose over lists" — short subsections + lists + `:::{.text}` are correct here; **still binds**: calques, term consistency, citations |

The educational profile is the explicit reason genre is its own layer: it overrides style rules the report
profile enforces, while the universal calque/term discipline still applies.

## Migration of existing assets

| Asset | Action |
|---|---|
| `~/.claude/skills/writing-russian-academic-prose` | **move** into plugin `skills/`; delete original |
| `~/.claude/skills/say-it-once-academic-prose` | **move** into plugin `skills/`; delete original |
| `~/.claude/rules/russian-qmd-prose.md` | update to reference plugin skills (verify bare skill-name still resolves vs `scientific-writing:<name>` namespacing — **open question**) |
| `~/.claude/commands/init-article.md` | keep as project bootstrap (Zotero/MCP/CSL/Makefile); **drop** its inline `quarto-article-writer`/`writing-science` agent bodies, point at the plugin's `scientific-writer` |
| `~/.claude/agents/qmd-review-importer.md` | keep (post-path docx importer); its step-4 prose pass now uses the plugin skills |
| feedback memories (`feedback_ru_report_phrasing`, …) | **mine into `dictionary.json`**; keep the memory files as provenance |
| project `.claude/rules/russian-qmd-prose.md` (nir_liver) | unaffected — points at the (now plugin-provided) skills by name |

## Where the plugin lives + install

Own git repo at `~/Projects/scientific-writing/` (a sibling project — **editable from its own session**,
not blocked by the nir_liver cross-project hook). Registered as a **local marketplace**
(`/plugin marketplace add ~/Projects/scientific-writing`), installed into Claude Code. Versioned and
shareable (could be published later). Migration of the two prose skills out of `~/.claude/skills/` (deleting
originals) needs a `~/.claude`-capable session — sequence in the plan.

## Build order (whole plugin, dependency-ordered)

1. `lib/qmd_prose.py` + `lib/lint_prose.py` + `canon/dictionary.json` (mine skills + memory) — the deterministic core.
2. `hooks/text-lint.sh` + diff router + marker coordination with the existing code hook.
3. `canon/canon.md` + `canon/profiles/{report,article,educational}.md`.
4. Migrate the two prose skills into the plugin; rewrite `russian-qmd-prose.md` references.
5. `skills/writing-scientific-documents` (orchestrator) + `skills/text-review/SKILL.md` (ensemble) + `agents/prose-reviewer.md`.
6. `skills/init-doc-spec/SKILL.md` + `agents/scientific-writer.md`.
7. `.claude-plugin/{plugin.json,marketplace.json}`; install; rewire `init-article`.
8. Validate on nir_liver `lesion_nature_report.qmd` (lint diff, /text-review, hook block, fix loop).

## Open questions / risks

- **Skill-name resolution under plugin namespacing** — does `russian-qmd-prose.md`'s «run the
  writing-russian-academic-prose skill» still resolve once the skill is plugin-scoped
  (`scientific-writing:writing-russian-academic-prose`)? Verify before deleting the `~/.claude/skills` copies.
- **Marker coordination** — exact handshake between `text-lint.sh` and the global `pre-pr-review.sh` so a
  prose-only PR satisfies the code marker without bypassing code review on mixed diffs.
- **Linter false positives** — тире/«;»/instrument-as-agent are WARN, not ERROR, precisely to keep the gate
  trustworthy; revisit the split after first real runs (`<!-- lint-ok -->` is the escape hatch).
- **Cross-project edits** — building the plugin + deleting old skills spans the plugin repo session **and** a
  `~/.claude` session; the plan must order them.

## Out of scope

- Non-Russian prose (linter/skills are Russian-calque-specific).
- Auto-commit / auto-render of `.qmd`.
- Replacing the docx import mechanics (`docx_review.py`) — the plugin formalizes the *pass*, not the parser.
- Code review itself (`pr-diff-reviewer` unchanged) — the plugin only routes around it for text.

## Owner style (added 2026-11-26)

The style the owner actually writes with is calibrated, not decreed.

**Pairs (R8).** A «draft → owner edit» pair lives in the project pack,
`<git-root>/.claude/scientific-writing/tune/<slug>/pairs.jsonl` — one record
`{id, file, base_commit, edit_commit, before, after, provenance}` per prose hunk
of the edit commit against its base (code chunks never count). The plugin keeps
only a local index, `var/tune/index.jsonl` in its own root (gitignored):
`{project_root, slug, pairs_path, pairs}`. The first pairs are the owner's manual
edits from the article history — 9432ea8 against the 55c9755 snapshot of
`clarinet_nir_ablation`, six prose hunks, `provenance: "owner"`; they currently
ride the gitignored eval-reports scratch dir as eval data, the article repo's own
pack directory is their destination. `tune-draft` now writes its tuning fixtures
into the same destination path (the project pack) instead of a throwaway `/tmp`
dir.

**Profile (R9).** `lib/style_profile.py`: `profile(doc, morph)` — a fixed vector
of style features (`FEATURES`, deliberately keyed off none of тире/«является»/
«данный»), `baseline(samples, morph)` — per-feature (median, MAD) over approved
samples, `distance(profile, baseline)` — robust z-scores. `/eval-prose --only
style` calibrates over two corpora — «human / LLM» (AINL-Eval-2025, downloaded as
untrusted data into a fresh `$TMPDIR` dir, nothing executed from it, Python only
with `-I`) and the owner pairs; the third corpus («samples vs new drafts») does
not exist yet and its step is skipped. Pinned by `tests/test_style_profile.py`.

**Experiment outcome (2026-11-26): no calibrated markers.** No feature is
direction-stable across both corpora (LLM-vs-human in AINL vs draft-vs-edit in
the pairs): the corpora disagree on every feature's direction, and the two
near-agreements — `commas_per_sent` by means, `mattr` by medians — flip under the
other estimator, knife-edge artifacts of six light-edit pairs, not signals. Per
the gate (only features agreeing in at least two corpora go to the report), step
3 was skipped in full: no markers table or «Что не считать машинным признаком»
section in `references/rhetoric.md`, no `doc-rhetoric-density` check, no canon,
manifest or test-oracle changes. Re-run `/eval-prose --only style` as the pairs
accumulate — the harness is the library plus the skill step, the corpus and the
report stay out of the repo.

**Samples (R10).** `house.samples` — at least three owner-approved fragments; the
key present with fewer raises `ConfigError`. `init-doc-spec` (step 4) asks for
them when the pack lacks the key and prefills the passport's «house-style» from
them; the writer receives them as input — the sound reference between equal
formulations (`agents/scientific-writer.md`, the orchestrator's write stage).

**Stop rule (R10).** `/text-edit` gains the `--only rhetoric` class (the
`rhetoric-*` family, edited by `references/rhetoric.md`) and every scoped edit is
bounded by `lib.revision_guard.next_state(prev, cur, guard)` → `CONTINUE |
STOP_ZERO_EDIT | STOP_OVERHARDENING`: a round that changed nothing stops the loop
(a zero edit list is a normal outcome), and past `MAX_SUBSTANTIVE_ROUNDS` (2)
further rewriting is presumed over-hardening — leftovers get reported, not
polished away.

## Related

- `skills/tuning-rules/SKILL.md` — rule-calibration loop driven by the user's edits
  (`tune-draft` → manual edit → `tune-learn` → rule deltas, rules proven on the test oracle) and by an
  editor's `.docx` review (`tune-learn --from-docx`). The design/plan docs it grew from were retired once
  they started contradicting the code they described.

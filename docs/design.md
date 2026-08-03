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
    plugin.json                          # manifest
    marketplace.json                     # local marketplace entry (install via /plugin marketplace add)
  canon/
    canon.md                             # human-readable universal canon (prose discipline + term policy)
    dictionary.json                      # MACHINE universal source: regex + bad/good + message + severity + layer
    orthography.json                     # punctuation/orthography rules + kind:"check" declarations
    profiles/
      report.md  article.md  educational.md   # per-genre section templates + style deltas
  skills/
    writing-scientific-documents/SKILL.md      # NEW orchestrator-entry (spec→write→review→fix)
    writing-russian-academic-prose/SKILL.md    # MIGRATED from ~/.claude/skills (phrase level)
    say-it-once-academic-prose/SKILL.md        # MIGRATED (document level)
    tuning-rules/SKILL.md                      # rule-derivation discipline (see tune-draft/tune-learn)
  commands/
    init-doc-spec.md                     # scaffold a per-document spec from canon + genre (interactive)
    text-review.md                       # advisory ensemble orchestrator (linter + prose subagents)
    tune-draft.md  tune-learn.md         # rule-calibration loop (generate → hand-edit → derive rules)
  agents/
    scientific-writer.md                 # spec/canon/genre-aware writer
    prose-reviewer.md                    # one parameterized ensemble agent, dispatched once per dimension (dimension = arg)
  hooks/
    hooks.json                           # PreToolUse registration
    text-lint.sh                         # gate gh pr create / git commit on linter ERROR findings
  lib/
    lint_prose.py                        # deterministic linter (regex entries + code checks)
    qmd_prose.py                         # shared: extract narrative prose from .qmd (skip code/yaml/tables/refs/biblio/latin)
    document.py                          # sentence + whole-document view over the extracted prose
    morph.py                             # OPTIONAL Russian morphology adapter (soft import)
    checks/                              # kind:"check" implementations: hyphenation, spelling, punctuation, consistency
    tune_diff.py                         # pristine→edited prose diff + FN/FP triage
    docx_review.py                       # editor .docx review → the same triage shape
  docs/
    design.md                            # this file, carried over
```

## Check kinds and scopes (added 2026-08-03)

The original design had one rule shape — a regex over one prose line. A real editor review
(105 comments on `lesion_nature_report`'s article) showed that shape reaches about a fifth
of what an editor flags: half the review was **punctuation and orthography**, and another
chunk was **document-scoped consistency**, neither of which a per-line regex can express.
So a rule is now one of two kinds, and checks see more than a line:

| Kind | Declared in | Sees | Examples |
|---|---|---|---|
| `regex` (default) | `canon/dictionary.json` (lexical), `canon/orthography.json` (punctuation) | one prose line | `calque-referens`, `style-takzhe-slitno`, `punct-percent-spacing` |
| `check` | `canon/orthography.json` with `kind: "check"`, implemented in `lib/checks/*.py` | a sentence or the whole document | `ortho-hyphen-linebreak`, `punct-comma-prichastie`, `doc-abbrev-variants` |

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

## The dictionary — universal source of truth (`canon/dictionary.json`)

Consolidates what is today scattered across two skill tables + 4 feedback-memory files. The linter consumes
`pattern/message/severity/except`; the prose skills **reference** this file as the literal-calque list and
keep only the nuance regex can't express.

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
  референсный/референтный, характеризаци·, таргетный, «по построению»,
  «полностью|целиком + выявить|обнаружить|распознать», гистология/морфология/цитология *as procedure*,
  «отнести … к категории», parasites «является / осуществляется / носит … характер».
- **warn** (advisory, agent decides) — heuristic / context-dependent, false-positive-prone:
  тире density (>1 «—» per sentence), «;» density, instrument-as-agent (`метод\w*.{0,30}(распозна|выявля|визуализир)`),
  «когорт·», sentences > 40 words.
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

Sourcing for initial entries: the tables in both prose skills + memories `feedback_ru_report_phrasing`,
`feedback_russian_prose_skill`, `feedback_no_bold_in_docx_reports`, `project_docx_apply_bypasses_prose_pass`.

## The linter (`lib/lint_prose.py`)

| Aspect | Contract |
|---|---|
| Input | a `.qmd` (whole-file mode) or a git range (`--diff [REF]`, changed prose lines only) |
| Prose extraction (`qmd_prose.py`) | exclude fenced ` ```{...} ` chunks, inline `` {python} ``, YAML front matter, markdown tables (`\|`-rows), BibTeX/`[@…]` citations, HTML comments, bare URLs, **reference sections** (a «Литература»/«References»/«Библиография» heading and everything under it until a same-or-higher heading) and **Latin-script blocks** (an English abstract — `qmd_prose.is_russian`). Headings otherwise **included** (calques appear there too) |
| Output | findings `{file,line,col,id,severity,message,matched}` — **every** match on a line, not just the first — sorted by `(line, col, id)`; human or `--json` (a flat array; the degraded-morphology note goes to stderr so the array stays the contract) |
| Exit | `1` if any **error**-severity finding (drives the hook); `2` on a malformed project-local dictionary |
| Modes | whole-file (for `/text-review`) vs **diff-only** (for the hook — see below) |
| Morphology | optional (`pip install -e '.[morph]'`); `--no-morph` forces the degraded path that the hook's system `python3` normally takes |
| Project-local overlay | `<git-root>/.claude/scientific-writing/dictionary.json` merged onto the base by `id` (add / **field-wise** override / `disabled`); an override restates only what it changes, so `{"id": "ortho-spelling", "allow": [...]}` is a complete entry. `--no-local` ignores it, `--local-dictionary <path>` forces a file |

**The hook scans the diff, not the whole file.** Pre-existing calque debt must not block every PR; only
**newly introduced** error-severity findings gate. `/text-review` may scan whole-file on demand.

## Stages

### spec — `commands/init-doc-spec.md`
Interactive: pick genre → load `profiles/<genre>.md` → propose section outline → collect doc-specific terms
(canonical term per concept, abbreviations, any doc-local forbidden phrasings) → write `<doc>.spec.md`
(sections + term list) and a doc-scoped dictionary overlay (`layer: doc`). The doc's forbidden terms thereby
feed the same linter. Existing good report → can reverse-engineer the outline/terms, then edit.

### write — `agents/scientific-writer.md`
Inputs: target `.qmd` + its `<doc>.spec.md` + selected genre profile + canon. Drafts/edits prose conforming
to the spec's sections and the genre's style; every quantitative claim cited (carried from the current
writer); **self-checks against the dictionary — never introduces a banned calque**; external content it can't
make canon-clean → `<!-- TODO ред: … -->`. Supersedes the generic `quarto-article-writer`.

### review — `commands/text-review.md` (ensemble of subagents)
1. Run `lint_prose.py` first (cheap) — its findings scope the agents (focus on what regex can't catch).
2. Dispatch parallel subagents, one per dimension:
   - **phrase-calques** — applies `writing-russian-academic-prose` to changed prose.
   - **repeats-termdrift** — applies `say-it-once-academic-prose` (cross-section, whole-doc context).
   - **structure-genre** — checks doc vs genre profile template + spec outline (missing/extra/misordered
     sections; slide-size for educational).
   - **terminology** — term consistency vs the spec's canonical-term list + abbreviation policy.
3. **Synthesis** pass dedups/merges + ranks → one report (blockers / warnings / nits), mirroring
   `pr-diff-reviewer`'s structure. Advisory — does not block.

Implementable as a command dispatching parallel `Agent`s, or a `Workflow` (fan-out + synthesis) for big
multi-section docs.

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
comment anchors and tracked changes straight out of the OOXML parts (keeping exact offsets,
unlike the pandoc round-trip in `~/.claude/scripts/docx_review.py`) and emits the triage shape
`lib/tune_diff.py` produces, so `/tune-learn --from-docx <review.docx>` runs a real editor
review through the same `tuning-rules` skill. An item counts as `covered` only when a rule fires
**on the anchor** — within ±25 characters of it (`docx_review._NEAR`), and `info`-severity findings
never count, since `ortho-spelling` fires on live terminology. The loose version, crediting any
finding in the same sentence, is what made the old dictionary look like it covered a review it in
fact missed entirely.

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
5. `skills/writing-scientific-documents` (orchestrator) + `commands/text-review.md` (ensemble) + `agents/prose-reviewer.md`.
6. `commands/init-doc-spec.md` + `agents/scientific-writer.md`.
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

## Related

- `skills/tuning-rules/SKILL.md` — rule-calibration loop driven by the user's edits
  (`tune-draft` → manual edit → `tune-learn` → rule deltas, rules proven on the test oracle) and by an
  editor's `.docx` review (`tune-learn --from-docx`). The design/plan docs it grew from were retired once
  they started contradicting the code they described.

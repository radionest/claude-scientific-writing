# Design: `scientific-writing` plugin — staged scientific-text authoring (spec → write → review → fix)

**Date:** 2026-06-23
**Status:** approved design (brainstorm), pre-plan
**Note:** cross-project infra. This doc lives in nir_liver `.claude/plans/` (local, gitignored) because the
brainstorm ran here; **carry it into the plugin repo as `docs/design.md` when scaffolding**. The plugin
itself is built from a session rooted at the plugin repo, **not** from nir_liver (the `/home/nest/.claude`
+ `../clarinet` cross-project edit hook blocks those paths from this session).

## Goal

A superpowers-style plugin that turns Russian scientific medical writing into a disciplined pipeline —
**spec → write → review → fix** — and cleanly separates **text** review from **code** review (pre and post).
Kills the recurring calque-churn (lesion_nature_report PRs #85–#121: a large share are prose-cleanup
re-fixing the *same* classes — метод-как-деятель, тире-калька, модальность/референсный) by making the
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
    dictionary.yml                       # MACHINE single source: regex + bad/good + message + severity + layer
    profiles/
      report.md  article.md  educational.md   # per-genre section templates + style deltas
  skills/
    writing-scientific-documents/SKILL.md      # NEW orchestrator-entry (spec→write→review→fix)
    writing-russian-academic-prose/SKILL.md    # MIGRATED from ~/.claude/skills (phrase level)
    say-it-once-academic-prose/SKILL.md        # MIGRATED (document level)
  commands/
    init-doc-spec.md                     # scaffold a per-document spec from canon + genre (interactive)
    text-review.md                       # advisory ensemble orchestrator (linter + prose subagents)
  agents/
    scientific-writer.md                 # spec/canon/genre-aware writer
    prose-reviewer.md                    # one parameterized ensemble agent, dispatched once per dimension (dimension = arg)
  hooks/
    hooks.json                           # PreToolUse registration
    text-lint.sh                         # gate gh pr create / git commit on linter ERROR findings
  lib/
    lint_prose.py                        # deterministic linter
    qmd_prose.py                         # shared: extract narrative prose from .qmd (skip code/yaml/tables/refs)
  docs/
    design.md                            # this file, carried over
```

## The dictionary — single source of truth (`canon/dictionary.yml`)

Consolidates what is today scattered across two skill tables + 4 feedback-memory files. The linter consumes
`pattern/message/severity/except`; the prose skills **reference** this file as the literal-calque list and
keep only the nuance regex can't express.

Entry schema:

```yaml
- id: calque-modalnost
  layer: universal              # universal | genre:report|article|educational | doc
  pattern: '\bмодальн\w*'       # Python re, case-insensitive, applied to extracted prose only
  except: 'DICOM'               # optional: suppress if this token is near the match
  severity: error               # error (blocks PR) | warn (advisory) | info
  message: 'калька modality → «метод (лучевой диагностики)»; «модальность» только в DICOM-смысле'
  bad: 'оба метода визуализации (модальности)'
  good: 'оба метода'
  skill: writing-russian-academic-prose   # judgment-skill that owns the nuance
```

**Severity policy** (principle; full classification in the plan):
- **error** (blocks) — unambiguous lexical calques, near-always-correct fix, low false-positive risk:
  модальность(non-DICOM), референсный/референтный, характеризаци·, таргетный, «по построению»,
  «полностью|целиком + выявить|обнаружить|распознать», гистология/морфология/цитология *as procedure*,
  «отнести … к категории», parasites «является / осуществляется / носит … характер».
- **warn** (advisory, agent decides) — heuristic / context-dependent, false-positive-prone:
  тире density (>1 «—» per sentence), «;» density, instrument-as-agent (`метод\w*.{0,30}(распозна|выявля|визуализир)`),
  «когорт·», sentences > 40 words.
- **judgment-only** (NOT in dictionary as error) — legitimate-тире (nulevaya svyazka, ellipsis, range «–»),
  graduable «полностью удалить/резецировать» — these live in the prose skill, never block.

Inline suppression: `<!-- lint-ok: <id> -->` on/above a line (eslint-disable-style), for the genuinely-legit
case the regex can't tell apart. Keeps error-severity usable without false blocks.

Sourcing for initial entries: the tables in both prose skills + memories `feedback_ru_report_phrasing`,
`feedback_russian_prose_skill`, `feedback_no_bold_in_docx_reports`, `project_docx_apply_bypasses_prose_pass`.

## The linter (`lib/lint_prose.py`)

| Aspect | Contract |
|---|---|
| Input | a `.qmd` (whole-file mode) or a git range (`--diff`/`--since REF`, changed prose lines only) |
| Prose extraction (`qmd_prose.py`) | exclude fenced ` ```{...} ` chunks, inline `` {python} ``, YAML front matter, markdown tables (`\|`-rows), BibTeX/`[@…]` citations, HTML comments, bare URLs. Headings **included** (calques appear there too) |
| Output | findings `{file,line,col,id,severity,message,matched,suggestion}`; human + `--json` |
| Exit | non-zero if any **error**-severity finding (drives the hook) |
| Modes | whole-file (for `/text-review`) vs **diff-only** (for the hook — see below) |

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
Not blind regex-replace. Unambiguous literal swaps (модальность→метод) auto-applied; risky ones (тире,
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
| feedback memories (`feedback_ru_report_phrasing`, …) | **mine into `dictionary.yml`**; keep the memory files as provenance |
| project `.claude/rules/russian-qmd-prose.md` (nir_liver) | unaffected — points at the (now plugin-provided) skills by name |

## Where the plugin lives + install

Own git repo at `~/Projects/scientific-writing/` (a sibling project — **editable from its own session**,
not blocked by the nir_liver cross-project hook). Registered as a **local marketplace**
(`/plugin marketplace add ~/Projects/scientific-writing`), installed into Claude Code. Versioned and
shareable (could be published later). Migration of the two prose skills out of `~/.claude/skills/` (deleting
originals) needs a `~/.claude`-capable session — sequence in the plan.

## Build order (whole plugin, dependency-ordered)

1. `lib/qmd_prose.py` + `lib/lint_prose.py` + `canon/dictionary.yml` (mine skills + memory) — the deterministic core.
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

---
name: writing-scientific-documents
description: Use when writing or substantially revising a Russian scientific-medical document (research report, journal article, educational article) in Quarto .qmd — when starting a new section, drafting from a spec, or preparing prose for a PR/editor. Routes through spec → write → review → fix and the calque linter.
---

# Writing Scientific Documents (orchestrator)

## Overview
Russian scientific writing runs as **spec → write → review → fix**, never freehand. The discipline that
keeps prose canon-clean is **placement**: each stage invokes the right sub-skill/tool, so calques and
repeats are caught before a PR, not in a later cleanup commit.

## Stages
1. **Spec.** No document without a spec. If `<doc>.spec.md` is absent → run `/scientific-writing:init-doc-spec`.
   The spec fixes sections (from the genre profile) + canonical terms + doc-local forbidden phrasings.
2. **Write.** Dispatch the `scientific-writer` agent (or write per the spec yourself). Obey the genre
   profile's style; every quantitative claim cited; never introduce a dictionary calque.
3. **Review.** Run `/scientific-writing:text-review` on the changed prose: the deterministic linter + the
   ensemble (calques / repeats / structure / terminology).
   - **REQUIRED SUB-SKILL:** Use scientific-writing:writing-russian-academic-prose for phrase-level findings.
   - **REQUIRED SUB-SKILL:** Use scientific-writing:say-it-once-academic-prose for cross-section repeats (multi-section docs).
4. **Fix.** Apply findings *with judgment* — unambiguous swaps directly; тире/«полностью» per the skill's
   nuance; legitimate cases get `<!-- lint-ok: id -->`. **Never bake a calque silently — fix or leave
   `<!-- TODO ред: … -->`.** Re-run the linter until the diff is clean.

## Red flags — STOP
- Drafting prose with no spec → run `/scientific-writing:init-doc-spec` first.
- "I'll clean up the calques later" → that is the churn this skill exists to kill. Fix in the fix stage.
- Applying an editor's docx review verbatim → still counts as editing; run the review/fix pass.

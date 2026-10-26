---
name: scientific-writing
description: Use when writing or substantially revising a Russian scientific-medical document (research report, journal article, educational article, review/*.qmd, главы Quarto-книг (review/*/chapters/*.qmd), отчёт, методичка) in any clarinet downstream project — when starting a new document or section, drafting from a spec, or preparing prose for a PR/editor. Routes through spec → write → review → fix with the deterministic calque linter (canon: dictionary.json + orthography.json + genre profiles). Hermes-native bridge over the claude-scientific-writing plugin repo.
---

# Scientific Writing (Hermes bridge)

Русская научная проза пишется как **spec → write → review → fix**, никогда не «с листа».
Источник истины — репо плагина `claude-scientific-writing` (одно место, обновляется `git pull`):

- `ROOT = /home/nest/Projects/claude-scientific-writing` (переопределяется env `SCIENTIFIC_WRITING_ROOT`)
- Линтер: `PYTHONPATH=$ROOT $ROOT/.venv/bin/python -m lib.lint_prose <file.qmd> [--json] [--diff [REF]]`
  (venv содержит морфологию; системный python3 даёт ослабленный режим)
- Канон: `$ROOT/canon/dictionary.json`, `$ROOT/canon/orthography.json`, жанровые профили `$ROOT/canon/profiles/{report,article,educational}.md`
- Сопутствующие скиллы (те же external_dirs): `writing-russian-academic-prose` (уровень фразы), `say-it-once-academic-prose` (структура/повторы), `tuning-rules` (вывод правил из правок).

## Стадии

1. **Spec.** Документ без спецификации не начинается. Если `<doc>.spec.md` рядом с `.qmd` отсутствует — создай его (исключение — глава Quarto-книги: per-chapter спеки не заводятся, главы делят спеку книги `<book>/specs/*.md` рядом с её `_quarto.yml`; в rtk_lung — `review/final_act/specs/`):
   - жанр из `$2` или спроси владельца (report/article/educational);
   - разделы — стартовый список из `canon/profiles/<жанр>.md`; если `.qmd` уже существует — извлеки фактические заголовки и термины;
   - зафиксируй канонические термины (один на понятие) + запрещённые синонимы, сокращения, локальные запреты;
   - формат: `# Spec: <doc>` / `genre:` / `## Разделы` / `## Канонические термины` / `## Сокращения` / `## Локальные запреты (layer: doc)`;
   - каждый машинно-проверяемый запрет (`pattern`) засей в локальный словарь проекта `<git-root>/.claude/scientific-writing/dictionary.json`
     (`{"entries": [{"id","layer":"doc","pattern","severity","message"}]}`; слияние по `id`, `{"id":..,"disabled":true}` отключает наследие);
     термины и аббревиатуры документа заведи в `allow` правил `ortho-spelling` и `doc-abbrev-variants`.

2. **Write.** Пиши по спецификации и жанровому профилю; каждое количественное утверждение — с цитированием; не вводи кальку из словаря.
   Фразовый уровень — по скиллу `writing-russian-academic-prose`.

3. **Review.** Прогони изменённую прозу:
   - линтер: `PYTHONPATH=$ROOT $ROOT/.venv/bin/python -m lib.lint_prose <file.qmd> --json --diff`
     (без `--diff` — весь файл; `severity`: error/warn/info);
   - ансамбль (для сколько-нибудь длинного документа): 4 параллельных субагента (delegate_task) — по одному на измерение
     `calques` / `repeats` / `terminology` / `structure`; каждому передай путь к файлу, `<doc>.spec.md`, жанровый профиль и находки линтера;
     для короткого документа — примени оба прозо-скилла (`writing-russian-academic-prose`, `say-it-once-academic-prose`) последовательно сам;
   - синтез: дедуп по (файл, строка, проблема), ранжир blocker → warning → nit.

4. **Fix.** Правки с суждением: однозначные замены сразу; тире/«полностью» — по нюансу скилла; легитимные случаи помечай
   `<!-- lint-ok: id -->`. **Кальку молча не пропускать — исправить или оставить `<!-- TODO ред: … -->`.**
   Перегоняй линтер до чистого diff.

## Красные флаги — СТОП
- Проза без spec → сначала шаг 1.
- «Почищу кальки потом» → именно этот churn система и убивает: фикс на стадии fix.
- Правки редактора из docx применяются дословно → это тоже редактирование: прогони review/fix.

## Гейт коммитов
Хук `text_lint_gate.py` (pre_tool_call, зарегистрирован в downstream-профилях) блокирует `git commit` / `gh pr create`,
если в изменённых `.qmd` есть error-находки линтера. Экстренный обход: `SKIP_TEXT_LINT=1`.

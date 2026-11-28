---
name: scientific-writing
description: Use for Russian scientific prose and plugin releases.
---

# Scientific Writing (Hermes bridge)

## When to Use

- Пишешь или существенно правишь русский научно-медицинский документ в downstream-проекте.
- Исследуешь внешние writing-скиллы или планируешь развитие самого плагина.
- Релизишь плагин (бамп версии, тег) или раскатываешь его скиллы по профилям Hermes.
- Не используй для нерусской прозы и задач без научно-редакционного компонента.

Русская научная проза пишется как **spec → write → review → fix**, никогда не «с листа».
Источник истины — репо плагина `claude-scientific-writing` (одно место, обновляется `git pull`):

- `ROOT = /home/nest/Projects/claude-scientific-writing` (переопределяется env `SCIENTIFIC_WRITING_ROOT`)
- Линтер: `PYTHONPATH=$ROOT $ROOT/.venv/bin/python -m lib.lint_prose <file.qmd> [--json] [--diff [REF]]`
  (venv содержит морфологию; системный python3 даёт ослабленный режим)
- Рендер-линт: PYTHONPATH=$ROOT $ROOT/.venv/bin/python -m lib.render_lint <render.docx> --qmd <doc.qmd> [--json] (текст таблиц/подписей, существующий только в рендере)
- Канон: `$ROOT/canon/dictionary.json`, `$ROOT/canon/orthography.json`, функции секций `$ROOT/canon/section-moves.md`, жанровые профили `$ROOT/canon/profiles/{report,article,educational}.md`
- Сопутствующие скиллы (те же external_dirs): `writing-russian-academic-prose` (уровень фразы), `say-it-once-academic-prose` (структура/повторы), `reader-first-academic-prose` (абзацы, claims/оговорки, cold read), `writing-discussion` (аргументация раздела «Обсуждение»), `tuning-rules` (вывод правил из правок).

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
   Содержательные секции (Введение/Методы/Результаты/Реферат/Заключение) — сначала функции из `canon/section-moves.md` и абзацный контракт скилла `reader-first-academic-prose`, потом drafting.
   Раздел «Обсуждение» — по скиллу `writing-discussion` (пять ходов, цикл «находка → сопоставление → значение», антипаттерны).

3. **Review.** Прогони изменённую прозу:
   - линтер: `PYTHONPATH=$ROOT $ROOT/.venv/bin/python -m lib.lint_prose <file.qmd> --json --diff`
     (без `--diff` — весь файл; `severity`: error/warn/info);
   - ансамбль (для сколько-нибудь длинного документа): план ревью —
     `PYTHONPATH=$ROOT $ROOT/.venv/bin/python -m lib.review_plan <file.qmd> --json`
     (`--mode diff` по умолчанию; `--mode deep` для глубокого ревью; `--before <path>` добавляет
     `fidelity`), затем до 10 параллельных субагентов (delegate_task) — по одному на измерение из
     плана; каждому передай его измерение, путь к файлу, `<doc>.spec.md`, жанровый профиль и находки линтера;
     для короткого документа — примени прозо-скиллы (`writing-russian-academic-prose`, `say-it-once-academic-prose`; при наличии «Обсуждения» — также `writing-discussion`; содержательные секции — `reader-first-academic-prose`) последовательно сам; прозо-скиллы не видят табличные чанки — при наличии рендера прогони `lib.render_lint` (python3 -m, с `--qmd`);
   - синтез: дедуп по (файл, строка, проблема), ранжир blocker → warning → nit.

4. **Fix.** Ограниченная правка (эквивалент `text-edit`): protected inventory до
   правки → минимальные правки (language-only/structural) → артефакт-контур
   `PYTHONPATH=$ROOT $ROOT/.venv/bin/python -m lib.revision_guard <before> <after> --json`
   → для deep — argument- и fidelity-ревью точного кандидата вместе. Правки с суждением: однозначные замены сразу;
   тире/«полностью» — по нюансу скилла; легитимные случаи помечай `<!-- lint-ok: id -->`.
   **Кальку молча не пропускать.** Находки закрывай статусами; решение владельца из
   spec повторно не поднимается. Перегоняй линтер до чистого diff.

## Красные флаги — СТОП
- Проза без spec → сначала шаг 1.
- «Почищу кальки потом» → именно этот churn система и убивает: фикс на стадии fix.
- Правки редактора из docx применяются дословно → это тоже редактирование: прогони review/fix.

## Релиз версии и раскатка по профилям Hermes
Версия живёт только в `.claude-plugin/plugin.json` (+ строка «currently X» в `AGENTS.md`). `pyproject.toml` версию не хранит (placeholder).

1. Сначала интегрируй входящие коммиты: `git -C $ROOT status -sb`; если main behind origin/main — проверь `git log main..origin/main --stat` на пересечение с грязными файлами и сделай `git merge --ff-only origin/main` (FF с грязным деревом безопасен при отсутствии пересечений).
2. Бамп явными путями: `git add .claude-plugin/plugin.json AGENTS.md` → `chore(release): bump plugin version to X.Y.Z` → `git tag vX.Y.Z`. Sweeping `git add` запрещён: в дереве регулярно лежит несвязный мусор (uv.lock, .zcode/), который попадёт в релизный коммит.
3. Push сам не делай — покажи оператору `git -C $ROOT push origin main vX.Y.Z` (удалённые мутации только по явной команде).
4. Раскатка:
   - default-профиль: ничего копировать не нужно — его `skills.external_dirs` читает `$ROOT/skills` и `$ROOT/hermes/skills` из рабочего дерева напрямую; версия там = состояние репо.
   - hwriter: копии-подмножество в `~/.hermes/profiles/hwriter/skills/scientific-writing/`. Перед перезаписью — `diff -rq` в обе стороны; уникальные правки дома сначала классифицируй (hermes-skill-canon), потом синкай `cp -r $ROOT/skills/<name>/. <house>/<name>/` (cp/ln/mkdir в skills/ разрешены гардом, rm/mv — оператор).
   - Перед отчётом «всё синхронизировано» найди все остальные копии: `find ~/.hermes/profiles -maxdepth 5 -type d -path '*skills/scientific-writing*'` — копии живут не только в hwriter.
5. Гейты: у hwriter `skills.write_approval: true` — прямые write_file/patch в его skills/ блокирует skill_write_guard; заблокированное гардом через терминал не обходить, косметические метки версии (DESCRIPTION.md) пропускай с пометкой оператору.

## Развитие плагина по внешним скиллам
При исследовании чужих writing-скиллов и планировании улучшений плагина используй
`references/external-skill-research.md`: сначала карта текущих возможностей и открытых дефектов,
затем первичные `SKILL.md`/references, затем адаптация механизмов и проверяемый план.

## Гейт коммитов
Хук `text_lint_gate.py` (pre_tool_call, зарегистрирован в downstream-профилях) блокирует `git commit` / `gh pr create`,
если в изменённых `.qmd` есть error-находки линтера. Экстренный обход: `SKIP_TEXT_LINT=1`.

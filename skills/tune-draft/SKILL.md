---
name: tune-draft
description: Use when starting the rule-calibration loop: generate a canon-clean draft from a source (writer plus self-lint cycle) as the 'before' half for tune-learn.
allowed-tools: Bash, Read, Write, WebFetch, Task
---

Сгенерируй черновик из источника (аргументы вызова: `<source: URL|тема|путь> [genre: report|article|educational]`) с применением канона — «до» для петли калибровки правил.

`CLAUDE_PLUGIN_ROOT` — корень установленного плагина. Если переменная не задана (zcode), возьми корень из пути этого SKILL.md: он лежит на два уровня ниже корня плагина (`<корень>/skills/<имя>/SKILL.md`). Для pytest используй `.venv` в корне плагина; если её нет — скажи явно, что прогон pytest недоступен.

## Шаги
1. Определи источник (первый аргумент): URL → WebFetch; путь к файлу → Read; иначе трактуй как тему-задание.
   Жанр (второй аргумент) ∈ {report, article, educational}; не задан → спроси (default: article).
   Необязательная подсказка длины из запроса (напр. «~1000 слов»).
2. Выбери стабильный каталог — пакет проекта: `D=<git-root>/.claude/scientific-writing/tune/<slug>`
   (git root — `git rev-parse --show-toplevel`; `SLUG` — короткое имя темы/файла в kebab-case;
   при коллизии добавь суффикс). `mkdir -p "$D"`.
3. Вызови агента `scientific-writer` в режиме **tuning-fixture** (БЕЗ `<doc>.spec.md`): напиши
   `<genre>`-черновик из источника по `canon/profiles/<жанр>.md` + `canon/canon.md` + `canon/dictionary.json` + `canon/orthography.json`, применяя канон.
   Спецификация намеренно пропускается — это калибровочная фикстура, правило «нет документа без спецификации» здесь не действует.
   Сохрани результат в `$D/$SLUG.qmd`.
4. Само-линт-цикл (≤3 итерации):
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$D/$SLUG.qmd" --json`
   — есть error/warn → писатель правит эти места → повтор. Чисто (или только `lint-ok`) → выход.
   Не свелось за 3 → оставь как есть, отметь остаточные находки (они тоже сигнал).
5. Сохрани нетронутую копию и файл-спутник:
   - `cp "$D/$SLUG.qmd" "$D/$SLUG.pristine.qmd"`
   - запиши `$D/$SLUG.tune.json`:
     `{"source": "<источник — первый аргумент>", "genre": "<жанр>", "draft": "<$SLUG.qmd>", "pristine": "<$SLUG.pristine.qmd>", "lint_clean": <true|false>}`
6. Печать: путь `$D/$SLUG.qmd` + «Правь вручную как считаешь нужным, потом:
   `/scientific-writing:tune-learn $D/$SLUG.qmd`».

Если источник недоступен — сообщи и спроси альтернативу. Не делай коммит и не выполняй рендеринг.

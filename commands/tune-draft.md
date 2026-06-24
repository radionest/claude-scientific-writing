---
description: Сгенерировать черновик из источника с применением канона (writer + само-линт) для последующей калибровки правил
argument-hint: <source: URL|тема|путь> [genre: report|article|educational]
allowed-tools: Bash, Read, Write, WebFetch, Task
---

Сгенерируй черновик из `$ARGUMENTS` с применением канона — «до» для петли калибровки правил.

## Шаги
1. Определи источник ($1): URL → WebFetch; путь к файлу → Read; иначе трактуй как тему-задание.
   Жанр ($2) ∈ {report, article, educational}; не задан → спроси (default: article).
   Необязательная подсказка длины из запроса (напр. «~1000 слов»).
2. Выбери стабильный каталог: `D=${TMPDIR:-/tmp}/sci-tune` и короткое имя из источника
   (`SLUG` — короткое имя темы/файла в kebab-case; при коллизии добавь суффикс). `mkdir -p "$D"`.
3. Вызови агента `scientific-writer` в режиме **tuning-fixture** (БЕЗ `<doc>.spec.md`): напиши
   `<genre>`-черновик из источника по `canon/profiles/<жанр>.md` + `canon/canon.md` + `canon/dictionary.json`, применяя канон.
   Спецификация намеренно пропускается — это калибровочная фикстура, правило «нет документа без спецификации» здесь не действует.
   Сохрани результат в `$D/$SLUG.qmd`.
4. Само-линт-цикл (≤3 итерации):
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$D/$SLUG.qmd" --json`
   — есть error/warn → писатель правит эти места → повтор. Чисто (или только `lint-ok`) → выход.
   Не свелось за 3 → оставь как есть, отметь остаточные находки (они тоже сигнал).
5. Сохрани нетронутую копию и файл-спутник:
   - `cp "$D/$SLUG.qmd" "$D/$SLUG.pristine.qmd"`
   - запиши `$D/$SLUG.tune.json`:
     `{"source": "<$1>", "genre": "<жанр>", "draft": "<$SLUG.qmd>", "pristine": "<$SLUG.pristine.qmd>", "lint_clean": <true|false>}`
6. Печать: путь `$D/$SLUG.qmd` + «Правь вручную как считаешь нужным, потом:
   `/scientific-writing:tune-learn $D/$SLUG.qmd`».

Если источник недоступен — сообщи и спроси альтернативу. Не делай коммит и не выполняй рендеринг.

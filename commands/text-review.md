---
description: Совещательное ревью прозы .qmd — линтер + ансамбль субагентов (кальки/повторы/структура/термины/рендер/обсуждение)
argument-hint: <file.qmd> [--whole-file] [--deep]
allowed-tools: Bash, Read, Task
---

Ревью русской научной прозы для `$ARGUMENTS`. Совещательно — ничего не коммитит и не блокирует.

## Шаги
1. Определи целевой `.qmd` ($1). Без него — спроси.
2. Линтер (файл идёт ПЕРВЫМ аргументом — у `--diff` опциональное значение, иначе путь будет принят за значение флага):
   - весь файл: `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$1" --json`
   - только изменённое (по умолчанию, без `--whole-file`): `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$1" --json --diff`
   Прочитай находки (поле `severity`: error/warn/info). В `--diff` находка правила засейки
   (`seed: "allow"`: `ortho-spelling`, `doc-abbrev-variants`) на изменённой строке поднимается с info
   до warn — её диспозиция не правка прозы, а засейка слова в `allow` проектного словаря
   (`/init-doc-spec`, шаг 6) или исправление опечатки; счётчик по правилам: `... lib.lint_prose "$1" --unseeded`.
3. Запусти параллельно (в ОДНОМ сообщении) субагентов `prose-reviewer`, по одному на измерение:
   `calques`, `repeats`, `terminology`, `structure`, `render` — всегда; `discussion` — только если
   в документе есть раздел «Обсуждение».
   `evidence` — только при наличии валидного `<doc>.claims.jsonl` (полная статья).
   Передай каждому путь к файлу, спецификацию (`<doc>.spec.md`),
   жанровый профиль (`canon/profiles/<жанр>.md`) и (для фокуса) находки линтера.
   - Без `--deep` и для короткого документа можно вместо ансамбля применить прозо-скиллы главным
     агентом последовательно (`scientific-writing:writing-russian-academic-prose`,
     `scientific-writing:say-it-once-academic-prose`; при наличии раздела «Обсуждение» —
     также `scientific-writing:writing-discussion`) — но по умолчанию используй ансамбль.
     Прозо-скиллы не видят табличные чанки: при наличии рендера прогони
     `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.render_lint <render.docx> --qmd "$1"` или `/render-review`.
4. Синтез: собери находки всех измерений + линтера, дедуплицируй по (файл, строка, проблема), отранжируй
   blocker → warning → nit. Выведи единый отчёт.
5. Подсказка: правки вноси в стадии fix скилла `scientific-writing:writing-scientific-documents`
   (с суждением; не слепой replace).

Примечание: локальный словарь проекта `<git-root>/.claude/scientific-writing/dictionary.json`
автоподхватывается, если существует (отключается `--no-local`); его правила видны в находках
наряду с канонными.

Измерение `fidelity` (before/after правки — вызывается из `/text-edit`) в диспетчеризацию
этой команды не входит.

Exit-коды линтера (`lib.lint_prose`):

| Exit | Значение |
|---|---|
| 0 | нет error-находок — warn/info возможны, читай находки |
| 1 | есть error-находки — не сбой, читай находки |
| 2 | usage-ошибка CLI (проверь аргументы) |
| 3 | словарь битый — stderr называет файл и ошибку, поправь его |

Трейсбек в stderr — это сбой: проверь `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}`, что путь к словарю
(`canon/dictionary.json`, `canon/orthography.json`) на месте и файл существует.

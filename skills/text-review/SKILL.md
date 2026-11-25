---
name: text-review
description: Use when Russian scientific prose in a .qmd needs advisory review: the linter first, then a prose-reviewer ensemble dispatched from the review plan (canon/review-dimensions.json declares the dimensions and their launch conditions). Commits and blocks nothing.
allowed-tools: Bash, Read, Task
---

Ревью русской научной прозы для целевого `.qmd` (аргументы вызова: `<file.qmd> [--whole-file] [--deep]`). Совещательно — ничего не коммитит и не блокирует. Пусть `$Q` — путь целевого файла.

`CLAUDE_PLUGIN_ROOT` — корень установленного плагина. Если переменная не задана (zcode), возьми корень из пути этого SKILL.md: он лежит на два уровня ниже корня плагина (`<корень>/skills/<имя>/SKILL.md`). Для pytest используй `.venv` в корне плагина; если её нет — скажи явно, что прогон pytest недоступен.

## Шаги
1. Определи целевой `.qmd` (`$Q`). Без него — спроси.
2. Линтер (файл идёт ПЕРВЫМ аргументом — у `--diff` опциональное значение, иначе путь будет принят за значение флага):
   - весь файл: `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$Q" --json`
   - только изменённое (по умолчанию, без `--whole-file`): `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$Q" --json --diff`
   Прочитай находки (поле `severity`: error/warn/info). В `--diff` находка правила засейки
   (`seed: "allow"`: `ortho-spelling`, `doc-abbrev-variants`) на изменённой строке поднимается с info
   до warn — её диспозиция не правка прозы, а засейка слова в `allow` проектного словаря
   (`/init-doc-spec`, шаг 6) или исправление опечатки; счётчик по правилам: `... lib.lint_prose "$Q" --unseeded`.
3. Получи план ревью (`--deep` → `--mode deep`, иначе `--mode diff`; состав измерений и
   условия запуска объявляет `canon/review-dimensions.json`, не этот скилл):
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.review_plan "$Q" --mode <mode> --json`
   Запусти параллельно (в ОДНОМ сообщении) субагентов `prose-reviewer`, по одному на
   измерение из плана. Передай каждому его измерение, путь к файлу, спецификацию
   (`<doc>.spec.md`) вместе с её разделом «Зафиксированные решения» (процитируй раздел в
   задаче; раздела нет — передай spec без цитаты; политика закрытия — в «Статусах находок»
   агента `prose-reviewer`), жанровый профиль (`canon/profiles/<жанр>.md`) и (для фокуса)
   находки линтера.
   - Без `--deep` и для короткого документа можно вместо ансамбля применить прозо-скиллы главным
     агентом последовательно (`scientific-writing:writing-russian-academic-prose`,
     `scientific-writing:say-it-once-academic-prose`; при наличии раздела «Обсуждение» —
     также `scientific-writing:writing-discussion`; для содержательных секций —
     `scientific-writing:reader-first-academic-prose`) — но по умолчанию используй ансамбль;
     в этом пути тоже прочитай раздел spec «Зафиксированные решения» — шаг 4 сверяет
     находки с ним.
     Прозо-скиллы не видят табличные чанки: при наличии рендера прогони
     `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.render_lint <render.docx> --qmd "$Q"` или `/render-review`.
4. Синтез: собери находки всех измерений + линтера, дедуплицируй по (файл, строка, проблема), отранжируй
   blocker → warning → nit. Замечание, противоречащее разделу spec «Зафиксированные решения»,
   пометь `declined-by-owner-decision` со ссылкой на решение — в стадию fix оно не идёт
   и в следующих раундах заново не поднимается; сомнительное покрытие — вопрос владельцу
   в отчёте, не находка на правку. Выведи единый отчёт.
5. Подсказка: правки вноси в стадии fix скилла `scientific-writing:writing-scientific-documents`
   (с суждением; не слепой replace).

Примечание: локальный словарь проекта `<git-root>/.claude/scientific-writing/dictionary.json`
автоподхватывается, если существует (отключается `--no-local`); его правила видны в находках
наряду с канонными.

Измерение `fidelity` (before/after правки — вызывается из `/text-edit`) в диспетчеризацию
этого скилла не входит.

Exit-коды линтера (`lib.lint_prose`):

| Exit | Значение |
|---|---|
| 0 | нет error-находок — warn/info возможны, читай находки |
| 1 | есть error-находки — не сбой, читай находки |
| 2 | usage-ошибка CLI (проверь аргументы) |
| 3 | словарь битый — stderr называет файл и ошибку, поправь его |

Трейсбек в stderr — это сбой: проверь `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}`, что путь к словарю
(`canon/dictionary.json`, `canon/orthography.json`) на месте и файл существует.

Exit-коды плана (`lib.review_plan`):

| Exit | Значение |
|---|---|
| 0 | план получен — запускай по измерению на ревьюера |
| 2 | файл не найден или usage-ошибка CLI (проверь аргументы) |
| 3 | битый `canon/review-dimensions.json` — stderr называет файл и ошибку, поправь его |

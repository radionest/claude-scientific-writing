---
description: Совещательное ревью прозы .qmd — линтер + ансамбль субагентов (кальки/повторы/структура/термины)
argument-hint: <file.qmd> [--whole-file] [--deep]
allowed-tools: Bash, Read, Task
---

Ревью русской научной прозы для `$ARGUMENTS`. Совещательно — ничего не коммитит и не блокирует.

## Шаги
1. Определи целевой `.qmd` ($1). Без него — спроси.
2. Линтер (файл идёт ПЕРВЫМ аргументом — у `--diff` опциональное значение, иначе он «съест» путь):
   - весь файл: `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$1" --json`
   - только изменённое (по умолчанию, без `--whole-file`): `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$1" --json --diff`
   Прочитай находки (поле `severity`: error/warn/info).
3. Диспетчируй параллельно (в ОДНОМ сообщении) субагентов `prose-reviewer`, по одному на измерение:
   `calques`, `repeats`, `terminology`, `structure`. Передай каждому путь к файлу, спеку (`<doc>.spec.md`),
   жанровый профиль (`canon/profiles/<жанр>.md`) и (для фокуса) находки линтера.
   - Без `--deep` и для короткого документа можно вместо ансамбля применить оба прозо-скилла главным
     агентом последовательно (`scientific-writing:writing-russian-academic-prose`,
     `scientific-writing:say-it-once-academic-prose`) — но по умолчанию используй ансамбль.
4. Синтез: собери находки всех измерений + линтера, дедуплицируй по (файл, строка, проблема), отранжируй
   blocker → warning → nit. Выведи единый отчёт.
5. Подсказка: правки вноси в стадии fix скилла `scientific-writing:writing-scientific-documents`
   (с суждением; не слепой replace).

Если линтер упал: проверь `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}`, что путь к словарю
(`canon/dictionary.json`) на месте и файл существует.

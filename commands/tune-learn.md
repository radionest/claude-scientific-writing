---
description: Вывести изменения правил плагина из различий (черновик, чистый по канону → твоя правка); словарные правила доказываются тестом до применения
argument-hint: <edited.qmd> [--pristine <path>]
allowed-tools: Bash, Read, Edit, Write
---

Выведи предложения по правилам плагина из правок в `$ARGUMENTS`. Совещательно: применяю только после подтверждения, не делаю коммит.

## Шаги
1. Определи «до»: `--pristine <path>` если задан; иначе соседние файлы от `<edited.qmd>` по файлу-спутнику
   `<edited без .qmd>.tune.json` → поле `pristine`. Нет ни того, ни другого → ошибка + подсказка `--pristine`.
2. Разметка:
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.tune_diff "<pristine>" "<edited.qmd>" --json`
   Пустой список → «прозы-правок нет, нечего выводить», остановись. Иначе прочитай фрагменты
   (`triage` FN/FP/neutral, `rule_hit`, `before_dirty`).
3. **Примени скилл `scientific-writing:tuning-rules`.** По нему классифицируй каждый фрагмент, маршрутизируй
   по слою и напиши правку. Контекст для классификации: `canon/dictionary.json`, оба прозо-скилла,
   `canon/profiles/<жанр>.md` (жанр из файла-спутника) и `<doc>.spec.md` если есть.
4. Самопроверка словарных правил по скиллу `tuning-rules` (раздел «Самопроверка словаря»), для каждой записи ДО
   применения. Процедура зависит от класса:
   - **FN (новое/расширенное правило):** добавь убранную фразу (`before`) в `tests/fixtures/calques.qmd`, затем
     `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m pytest tests/test_dictionary.py tests/test_lint_prose.py` → зелёный,
     и `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "<edited.qmd>" --json` → id нового правила НЕ на хорошем тексте.
   - **FP (ослабление):** `calques.qmd` **не** трогай (фраза не калька — сломает оракул).
     `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "<edited.qmd>" --json` → id ослабляемого правила больше НЕ появляется;
     `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m pytest tests/test_dictionary.py tests/test_lint_prose.py` → зелёный.
   - провал любого → запись не применять (уточнить/в скилл).
5. Отчёт на подтверждение: сгруппируй по слою (словарь / прозо-скиллы / профиль / спецификация / код / шум). Каждый пункт:
   фрагмент-обоснование (`- before` / `+ after`), класс, правка; для словаря — результат зелёного теста.
6. Подтверждение → применяй правки (Edit/Write) в рабочее дерево; фикстур-строки оставь (они доказывают правило).
   Прогони весь `pytest` (`PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m pytest -q`) → зелёный.
   **Не делай коммит** — пользователь проверяет и делает коммит сам.

Если вспомогательный модуль завершился с ошибкой: проверь `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}`, что pristine и edited существуют, словарь на месте.

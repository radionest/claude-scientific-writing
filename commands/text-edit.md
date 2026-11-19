---
description: Ограниченная правка прозы .qmd — режимы light/deep, protected inventory, revision_guard и fidelity-проверка точного кандидата
argument-hint: <file.qmd> [--mode light|deep] [--only <класс>] [--scope <разделы>]
allowed-tools: Bash, Read, Edit, Write, Task
---

Правка русской научной прозы для `$ARGUMENTS` с сохранением научного содержания.
`/text-review` остаётся audit-командой; правит только эта команда.

## Шаги
1. Определи целевой `.qmd` ($1), режим (`--mode light` по умолчанию | `deep`), фокус
   (`--only <класс находок>`) и область (`--scope <разделы>`; для deep обязательна).
   Прочитай `<doc>.spec.md` (в т.ч. «Зафиксированные решения» и «Защищённые
   формулировки», если есть) и жанровый профиль.
2. **Protected inventory до правки.** Сохрани копию исходника и зафиксируй в отчёте:
   числа/знаки/CI, citation keys, `@tbl/@fig`, URL/DOI, inline `{python}`, fenced code,
   замороженные формулировки из spec. Разрешённые изменения: light — только минимальные
   фразовые spans проблемных мест; deep — перемещения функций абзацев внутри `--scope`
   (сначала зафиксируй destination каждой функции, потом правь).
   `BEFORE=$(mktemp /tmp/text-edit-XXXXXX.qmd) && cp "$1" "$BEFORE"`
3. **Правка** через агента `scientific-writer` (передай режим language-only/structural
   и границы). Соседние абзацы — читать для связности, не переписывать. Изменение
   знаменателя, популяции, цели или причинности — не surface-правка: останови правку и
   доложи (нужен claim-calibration: рекомендация, изменение силы утверждения — только
   после решения автора).
4. **Guard (артефакты):**
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.revision_guard "$BEFORE" "$1" --json`
   (плюс `--frozen <doc>.frozen.txt`, если spec содержит «Защищённые формулировки»).
   Каждое расхождение: восстанови элемент ИЛИ выпиши как осознанно разрешённое с
   причиной. Пустой diff = артефакты совпали, НЕ «смысл сохранён».
5. **Fidelity (смысл)** — для deep или содержательной правки: субагент `prose-reviewer`
   с измерением `fidelity`; передай before (`$BEFORE`), after (`$1`) и diff без своих
   рассуждений. Финальная проверка — на точном последнем кандидате: любая правка после
   неё инвалидирует проверку. Недоступные проверки — `not_run/unavailable`, не PASS.
6. **Линтер:** `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$1" --json --diff`
   — error-находки устранить, до чистого diff.
7. `rm -f "$BEFORE"`; выведи отчёт: режим, тронутые места, расхождения guard и их
   разрешение, вердикт fidelity, статусы находок (`open / fixed /
   declined-by-owner-decision / blocked / not-applicable`; закрытое решением владельца
   со ссылкой на spec повторно не поднимается). Нулевой список правок — нормальный
   результат.

Контракт сохранности целиком —
`skills/writing-scientific-documents/references/rewrite-preservation.md`.

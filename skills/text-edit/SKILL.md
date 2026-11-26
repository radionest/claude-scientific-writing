---
name: text-edit
description: Use when existing Russian scientific prose in a .qmd needs a bounded edit: light minimal spans or deep paragraph-function moves inside a declared scope, with protected inventory, revision_guard and a fidelity check of the exact final candidate. The only skill that edits prose.
allowed-tools: Bash, Read, Edit, Write, Task
---

Правка русской научной прозы для целевого `.qmd` (аргументы вызова: `<file.qmd> [--mode light|deep] [--only <класс>] [--scope <разделы>]`) с сохранением научного содержания. Пусть `$Q` — путь целевого файла.
`/text-review` остаётся audit-скиллом; правит только этот скилл.

`CLAUDE_PLUGIN_ROOT` — корень установленного плагина. Если переменная не задана (zcode), возьми корень из пути этого SKILL.md: он лежит на два уровня ниже корня плагина (`<корень>/skills/<имя>/SKILL.md`). Для pytest используй `.venv` в корне плагина; если её нет — скажи явно, что прогон pytest недоступен.

## Шаги
1. Определи целевой `.qmd` (`$Q`), режим (`--mode light` по умолчанию | `deep`), фокус
   (`--only <класс находок>` — семейство правил канона: `calque-*`, `parasite-*`,
   `punct-*`, …; `--only rhetoric` — риторический класс: семейство `rhetoric-*`,
   правка по `references/rhetoric.md` скилла `writing-russian-academic-prose`) и
   область (`--scope <разделы>`; для deep обязательна).
   Прочитай `<doc>.spec.md` (в т.ч. «Зафиксированные решения» и «Защищённые
   формулировки», если есть) и жанровый профиль.
2. **Protected inventory до правки.** Сохрани копию исходника и зафиксируй в отчёте:
   числа/знаки/CI, citation keys, `@tbl/@fig`, URL/DOI, inline `{python}`, fenced code,
   замороженные формулировки из spec. Разрешённые изменения: light — только минимальные
   фразовые spans проблемных мест; deep — перемещения функций абзацев внутри `--scope`
   (сначала зафиксируй destination каждой функции, потом правь).
   `BEFORE=$(mktemp /tmp/text-edit-XXXXXX.qmd) && cp "$Q" "$BEFORE"`
3. **Правка** через агента `scientific-writer` (передай режим language-only/structural
   и границы). Правка идёт раундами; перед первым раундом заведи путь снимка и
   счётчик (`PREV=$(mktemp /tmp/text-edit-XXXXXX.qmd)`, `ROUNDS=0`), перед каждым
   раундом сохрани кандидата (`cp "$Q" "$PREV"`), после — стоп-правило. Счётчик
   раундов наращивается: первый вызов — `EditState(rounds=0)`; содержательный раунд —
   следующий вызов с `EditState(rounds + 1)`. Вызов (первый аргумент — кандидат до
   раунда, второй — после, третий — число завершённых содержательных раундов):
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -c 'import sys; from lib.revision_guard import EditState, next_state; a, b, n = open(sys.argv[1], encoding="utf-8").read(), open(sys.argv[2], encoding="utf-8").read(), int(sys.argv[3]); print(next_state(a, b, EditState(n)))' "$PREV" "$Q" "$ROUNDS"`
   Вердикт: `CONTINUE` — ещё раунд; `STOP_ZERO_EDIT` — раунд ничего не изменил, стоп
   (нулевой список правок — нормальный результат); `STOP_OVERHARDENING` — счётчик
   дошёл до `MAX_SUBSTANTIVE_ROUNDS` (= 2: максимум два содержательных раунда, дальше
   полировка только навредит — остатки находок доложи, не правь).
   Соседние абзацы — читать для связности, не переписывать. Изменение
   знаменателя, популяции, цели или причинности — не surface-правка: останови правку и
   доложи (нужен claim-calibration: рекомендация, изменение силы утверждения — только
   после решения автора).
4. **Guard (артефакты):**
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.revision_guard "$BEFORE" "$Q" --json`
   (плюс `--frozen <doc>.frozen.txt`, если spec содержит «Защищённые формулировки»).
   Каждое расхождение: восстанови элемент ИЛИ выпиши как осознанно разрешённое с
   причиной. Пустой diff = артефакты совпали, НЕ «смысл сохранён».
5. **Fidelity (смысл)** — для deep или содержательной правки: субагент `prose-reviewer`
   с измерением `fidelity`; передай before (`$BEFORE`), after (`$Q`) и diff без своих
   рассуждений. Финальная проверка — на точном последнем кандидате: любая правка после
   неё инвалидирует проверку. Недоступные проверки — `not_run/unavailable`, не PASS.
6. **Линтер:** `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$Q" --json --diff`
   — error-находки устранить, до чистого diff.
7. `rm -f "$BEFORE"`; выведи отчёт: режим, тронутые места, расхождения guard и их
   разрешение, вердикт fidelity, статусы находок (`open / fixed /
   declined-by-owner-decision / blocked / not-applicable`; закрытое решением владельца
   со ссылкой на spec повторно не поднимается). Нулевой список правок — нормальный
   результат.

Контракт сохранности целиком —
`skills/writing-scientific-documents/references/rewrite-preservation.md`.

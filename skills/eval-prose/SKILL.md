---
name: eval-prose
description: Use when plugin rule or prompt changes need measuring: the deterministic lint-manifest baseline and a behavioral rewrite eval with a hidden rubric, JSON report and A/B against a previous run.
allowed-tools: Bash, Read, Write, Task
---

Оценка качества правил и ревью-поведения плагина (аргументы вызова: `[--baseline <report.json>] [--only lint|rewrite]`). Ничего не правит и не
коммитит: замеряет и пишет отчёт.

`CLAUDE_PLUGIN_ROOT` — корень установленного плагина. Если переменная не задана (zcode), возьми корень из пути этого SKILL.md: он лежит на два уровня ниже корня плагина (`<корень>/skills/<имя>/SKILL.md`). Для pytest используй `.venv` в корне плагина; если её нет — скажи явно, что прогон pytest недоступен.

## Шаги
1. **Детерминированный контур** (всегда, если не `--only rewrite`):
   `(cd "${CLAUDE_PLUGIN_ROOT}" && .venv/bin/pytest tests/test_lint_manifest.py -q)` → зелёный?
   Сведи цифры: сколько правил в `tests/eval/lint-manifest.json`, размер профилей
   `lint-good.qmd` / `lint-bad.qmd` (суммы `count`). Красный = дрейф baseline: находка,
   а не шум — назови правило и профиль, не «чинить» молча.
2. **Поведенческий контур** (если не `--only lint`): для каждого кейса
   `tests/eval/rewrite-cases.json` запусти СВЕЖЕГО субагента общего назначения (general-purpose,
   не `prose-reviewer` — его контракт требует JSON-находки одного измерения, а здесь нужен
   свободный ответ о потерях смысла; по одному вызову на кейс, батчами в одном сообщении).
   Промпт агенту содержит ТОЛЬКО `before` и `after` — без `dimension`/`expect`/`note`
   (это скрытый rubric) — и вопрос: «Правка сохраняет смысл исходника? Перечисли потери
   (отрицание, кванторы, числа/знаменатель, сравнение, модальность, условие, ссылки, код)
   или ответь, что потерь нет».
3. **Оцени сам** (rubric живёт здесь, не в агенте): кейс `expect: damage` засчитан, если
   агент назвал потерю, совпадающую с `note`; кейс `expect: clean` — если агент НЕ заявил
   потерю. Посчитай: accuracy, recall по damage, false-alarm по clean; провалы выведи
   с `id` и ответом агента.
4. **Отчёт** → `${CLAUDE_PLUGIN_ROOT}/tests/eval/reports/<ISO-дата>-<метка>.json`
   (якорь обязателен: команда исполняется из cwd пользовательского проекта — отчёты
   принадлежат плагину, а не чужому репозиторию): `{version: (cd "${CLAUDE_PLUGIN_ROOT}" && git rev-parse --short HEAD),
   lint: {ok, rules, good_findings, bad_findings}, rewrite: [{id, expect, verdict, correct}],
   summary: {accuracy, damage_recall, clean_precision}}`. Каталог отчётов не коммитится.
5. **A/B** (`--baseline <report.json>`): прочитай прежний отчёт, выведи разницу по каждому
   полю (правила, профили, accuracy по кейсам) — «улучшилось/ухудшилось/без изменений».
   Нестабильные кейсы (расхождение verdict с прежним прогоном) пометь и предложи повтор.
6. Скажи явно, что поведенческие прогоны не входят в blocking CI: это калибровочный
   сигнал для изменений правил и промптов.

Примечание: should-trigger/should-not-trigger оценки скиллов (реагирует ли prose-скилл на
задачу своего жанра и молчит ли на чужую) — отдельный прогон; набор задач собирается из
`tune`-корпуса, в CI не идёт.

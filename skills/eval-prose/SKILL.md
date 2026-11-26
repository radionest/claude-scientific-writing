---
name: eval-prose
description: Use when plugin rule or prompt changes need measuring: the deterministic lint-manifest baseline and a behavioral rewrite eval with a hidden rubric, JSON report and A/B against a previous run.
allowed-tools: Bash, Read, Write, Task
---

Оценка качества правил и ревью-поведения плагина (аргументы вызова: `[--baseline <report.json>] [--only lint|rewrite|style]`). Ничего не правит и не
коммитит: замеряет и пишет отчёт.

`CLAUDE_PLUGIN_ROOT` — корень установленного плагина. Если переменная не задана (zcode), возьми корень из пути этого SKILL.md: он лежит на два уровня ниже корня плагина (`<корень>/skills/<имя>/SKILL.md`). Для pytest используй `.venv` в корне плагина; если её нет — скажи явно, что прогон pytest недоступен.

## Шаги
1. **Детерминированный контур** (всегда, кроме `--only rewrite` и `--only style`):
   `(cd "${CLAUDE_PLUGIN_ROOT}" && .venv/bin/pytest tests/test_lint_manifest.py -q)` → зелёный?
   Сведи цифры: сколько правил в `tests/eval/lint-manifest.json`, размер профилей
   `lint-good.qmd` / `lint-bad.qmd` (суммы `count`). Красный = дрейф baseline: находка,
   а не шум — назови правило и профиль, не «чинить» молча.
2. **Поведенческий контур** (если не `--only lint` и не `--only style`): для каждого кейса
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
7. **Стиль-контур** (`--only style` — выполняются шаги 1–2 и этот шаг; шаги 3–6 —
   скоринг rewrite-кейсов, схема отчёта lint/rewrite и A/B — не запускаются):
   калибровка признаков
   стиля через `lib.style_profile` (`profile`, `baseline`, `distance`;
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}`) на двух корпусах:
   - «человек / LLM» — AINL-Eval-2025 (github.com/iis-research-team/AINL-Eval-2025):
     скачать в НОВЫЙ пустой каталог под `$TMPDIR` как недоверенные данные — ничего из
     него не исполнять, Python только с `-I`, сеть — только скачивание архива/clone;
     человек — класс `abstract`, машины — три модельных класса (в `dev_full.csv`).
   - пары «черновик / правка владельца» — индекс плагина `var/tune/index.jsonl`
     (`{project_root, slug, pairs_path, pairs}`); файлы пар лежат в пакетах проектов,
     `<git-root>/.claude/scientific-writing/tune/<slug>/pairs.jsonl`
     (`{id, file, base_commit, edit_commit, before, after, provenance}`). Жёсткие
     переносы строк старых .qmd разверни в абзацы перед профилированием.
   Признак (`lib.style_profile.FEATURES`) — маркер только при одинаковом направлении
   (LLM против человека; черновик против правки владельца) минимум в двух корпусах;
   в отчёт идут только такие признаки. Третьего корпуса («образцы против новых
   черновиков») пока нет — соответствующий шаг пропускается. Корпус недоступен или
   разметка не читается — устойчивые признаки не определяются: зафиксируй это в
   отчёте и не вводи маркеров.
   Отчёт → `${CLAUDE_PLUGIN_ROOT}/tests/eval/reports/<ISO-дата>-style.json`
   (gitignored): корпуса и объёмы, направления по каждому признаку, устойчивые
   признаки или причина их отсутствия.

Примечание: should-trigger/should-not-trigger оценки скиллов (реагирует ли prose-скилл на
задачу своего жанра и молчит ли на чужую) — отдельный прогон; набор задач собирается из
`tune`-корпуса, в CI не идёт.

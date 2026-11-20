---
name: init-doc-spec
description: Use when a document has no <doc>.spec.md: scaffold sections, canonical terms, abbreviations and machine-checkable local bans from the canon and the genre profile, and seed the project-local dictionary.
allowed-tools: Bash, Read, Write, AskUserQuestion
---

Создай `<doc>.spec.md` для целевого `.qmd` (аргументы вызова: `<file.qmd> [genre]`).

## Шаги
1. Определи `.qmd` и жанр из аргументов вызова. Жанр не задан → спроси (report/article/educational).
2. Прочитай `canon/profiles/<жанр>.md` — возьми список разделов как стартовый.
3. Если `.qmd` уже существует — извлеки фактические заголовки и термины, предложи их (восстановив из готового файла).
4. Спроси недостающее: канонические термины (один на понятие) + их запрещённые синонимы; сокращения;
   любые локальные запреты (напр. правило гистологической истины, канон «мастер-модель»).
   Для жанра `article` (полная статья) спроси также управляющие блоки шаблона ниже:
   журнал и тип статьи, читателя, дизайн исследования, главный вопрос/вклад,
   зафиксированные решения, защищённые формулировки, границу правки. Для правки одного
   абзаца или письма ничего из этого не требуется.
5. Запиши `<doc>.spec.md` в формате:

   ```markdown
   # Spec: <doc>
   genre: report|article|educational
   ## Разделы
   - <section> — <one-line purpose>
   ## Канонические термины
   - <concept>: <canonical term>  (запрещённые синонимы: …)
   ## Сокращения
   - <ABBR> — <expansion>
   ## Локальные запреты (layer: doc)
   - id: <id> | pattern: <regex> | severity: warn|error | message: <…>
   ## Управление статьёй (только genre: article)
   journal: <журнал/площадка + тип статьи>
   reader: <редактор | специалист | широкий коллега>
   design: <дизайн исследования + применимое руководство отчётности>
   main-question: <главный вопрос и главный вклад>
   edit-boundary: style-only | structure | claim-calibration
   ## Зафиксированные решения
   - <решение> — <обоснование>   # закрывает находки ревью статусом declined-by-owner-decision
   ## Защищённые формулировки
   - <формулировка>              # одна строка = одна формулировка (см. шаг 6.5)
   ```

   Перечисляй в спецификации **все** локальные запреты (и regex-, и суждение-правила) — как читаемый ориентир.

6. **Засей локальный словарь.** Для каждого локального запрета с `pattern` (машинно-проверяемого) добавь запись в
   локальный словарь проекта `<git-root>/.claude/scientific-writing/dictionary.json`:
   - корень: `git rev-parse --show-toplevel`;
   - нет файла → создай `{"entries": []}`; есть → прочитай и слей по `id` (та же `id` — переопределение по полям: указывай только то, что меняешь; `{"id": "<id>", "disabled": true}` — отключить унаследованное правило);
   - запись: `{"id", "layer": "doc", "pattern", "severity": "warn"|"error", "message", "except"?, "skill"?}`.
   - **словник и аббревиатуры документа** (шаги 4–5) заведи в `allow` соответствующих check-правил — иначе `ortho-spelling` будет ругаться на живые термины проекта, а `doc-abbrev-variants` — на законные варианты:
     `{"id": "ortho-spelling", "allow": ["<термины документа>"]}`,
     `{"id": "doc-abbrev-variants", "allow": ["<аббревиатуры документа>"]}`.
   Линтер (хук `text-lint.sh` + `/text-review`) подхватит эти записи автоматически — правка плагинных `canon/dictionary.json` и `canon/orthography.json` не нужна.
   Правила без `pattern` (референт-дрейф, семантика) оставляй только в прозе спецификации — их применяет `prose-reviewer`.
6.5. **Защищённые формулировки → файл для guard.** Если раздел непуст — запиши его же
   построчно в `<doc>.frozen.txt` рядом со spec (одна формулировка = строка; передавай
   в `lib.revision_guard --frozen`). Машиночитаемых данных в нём нет — только строки.
7. Сообщи путь и напомни: дальше — стадия write (агент `scientific-writing:scientific-writer`).

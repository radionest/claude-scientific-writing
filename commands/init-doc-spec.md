---
description: Заготовка спецификации документа (разделы + термины + локальные запреты) из канона и жанрового профиля
argument-hint: <file.qmd> [genre]
allowed-tools: Bash, Read, Write, AskUserQuestion
---

Создай `<doc>.spec.md` для `$ARGUMENTS`.

## Шаги
1. Определи `.qmd` ($1) и жанр ($2). Жанр не задан → спроси (report/article/educational).
2. Прочитай `canon/profiles/<жанр>.md` — возьми список разделов как стартовый.
3. Если `.qmd` уже существует — извлеки фактические заголовки и термины, предложи их (восстановив из готового файла).
4. Спроси недостающее: канонические термины (один на понятие) + их запрещённые синонимы; сокращения;
   любые локальные запреты (напр. правило гистологической истины, канон «мастер-модель»).
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
   ```

   Перечисляй в спецификации **все** локальные запреты (и regex-, и суждение-правила) — как читаемый ориентир.

6. **Засей локальный словарь.** Для каждого локального запрета с `pattern` (машинно-проверяемого) добавь запись в
   локальный словарь проекта `<git-root>/.claude/scientific-writing/dictionary.json`:
   - корень: `git rev-parse --show-toplevel`;
   - нет файла → создай `{"entries": []}`; есть → прочитай и слей по `id` (та же `id` — замена; `{"id": "<id>", "disabled": true}` — отключить унаследованное правило);
   - запись: `{"id", "layer": "doc", "pattern", "severity": "warn"|"error", "message", "skill"?}`.
   Линтер (хук `text-lint.sh` + `/text-review`) подхватит эти записи автоматически — правка плагинного `canon/dictionary.json` не нужна.
   Правила без `pattern` (референт-дрейф, семантика) оставляй только в прозе спецификации — их применяет `prose-reviewer`.
7. Сообщи путь и напомни: дальше — стадия write (агент `scientific-writing:scientific-writer`).

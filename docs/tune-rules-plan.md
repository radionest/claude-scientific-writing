# tune-rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Замкнуть петлю обратной связи плагина: генерация с применением канона → ручная правка пользователя → автоматический вывод изменений правил с самопроверкой на тест-оракуле.

**Architecture:** Две команды с паузой на ручную правку. `tune-draft` вызывает `scientific-writer` + само-линт-цикл → «до», чистое по линтеру. `tune-learn` запускает детерминированный вспомогательный модуль `lib/tune_diff.py` (прозо-разница + FN/FP-разметка по regex словаря), затем главный агент под новым скиллом `tuning-rules` классифицирует фрагменты, маршрутизирует по слоям и пишет правки; regex-правила доказываются `pytest` + линтером до применения.

**Tech Stack:** Python 3 stdlib (`difflib`, `re`, `argparse`, `json`, `dataclasses`), pytest, Quarto `.qmd`, Claude Code plugin commands/skills/agents (markdown).

**Spec:** `docs/tune-rules-design.md`

## Global Constraints

- **Stdlib only** в `lib/` — никаких новых зависимостей (как `lib/lint_prose.py`: «Stdlib only»).
- **Python/pytest invocation:** `PYTHONPATH=. .venv/bin/python -m pytest <args> > /tmp/test-tune-<unique>.txt 2>&1`, затем читать файл. Редирект в уникальный файл, **никогда не пайп** (`| tail`/`| tee`).
- **Commits:** Conventional Commits (`feat:`/`fix:`/`test:`/`docs:`), **без** `Co-Authored-By`. Работать на feature-ветке/worktree, **не** на `main` (текущая ветка — `main`; перед началом создать ветку через `superpowers:using-git-worktrees`).
- **Dictionary entry schema** (verbatim, `canon/dictionary.json`): `{id, layer, pattern, except?, severity, message, bad?, good?, note?, skill}`. `layer ∈ {universal, genre:report, genre:article, genre:educational, doc}`; `severity ∈ {error, warn, info}`.
- **Severity policy:** `docs/design.md` строки 98–110 (error — однозначные лексические кальки, низкий FP-риск; warn — эвристики, FP-prone).
- **Fixtures:** `tests/fixtures/calques.qmd` — одна фраза на строку, каждую обязан ловить какой-то rule. Хук `text-lint.sh` уже пропускает `tests/fixtures/*.qmd` (коммит 244a904) — добавление строк не самоблокирует коммит.
- **Команды/скиллы пишутся по-русски** в стиле существующих (`commands/text-review.md`, `skills/writing-russian-academic-prose/SKILL.md`); идентификаторы/пути — английские. `${CLAUDE_PLUGIN_ROOT}` для путей внутри плагина.
- **Регистр русской прозы (команды/скилл/доки):** формальный, без англицизмов-жаргона и разговорных оборотов. Запрещены, среди прочего: дог-фудинг, хелпер, сайдкар, стэш, триаж, дифф, патч (в значении «правка»), approve/reject, кейс, гейт, бриф, дёрнуть, прогон, ревьюить, плейбук, промоушен, резолв, легитимный, доку-специфичный, оверкилл. Английский — только для идентификаторов/путей/имён инструментов. Образец — копирайт-пасс `42a72ab` (спеки→спецификации, генерик→общий, хардкод→вписывать вручную, бьётся→проверяется, эскейп→подавление, режь→убирай, диспетчируй→запусти).

## File Structure

| Файл | Ответственность |
|---|---|
| `lib/tune_diff.py` (new) | Чистая функция `diff_prose(pristine_src, edited_src, entries) -> list[Hunk]` + CLI. Превращает два `.qmd` в размеченные прозо-фрагменты. Переиспользует `qmd_prose.extract_prose`, `lint_prose.load_entries`. |
| `tests/test_tune_diff.py` (new) | Юнит-тесты `diff_prose`: FN/FP/neutral/no-change/before_dirty. |
| `skills/tuning-rules/SKILL.md` (new) | Дисциплина вывода: таксономия 8 классов → маршруты, regex-канон, фильтр шума, порядок ослабления при FP, обязательная самопроверка словаря. |
| `commands/tune-draft.md` (new) | Координация фазы генерации (writer + само-линт + сохранение копии pristine + файл-спутник). |
| `commands/tune-learn.md` (new) | Координация фазы вывода (вспомогательный модуль → скилл → правки → самопроверка → применение). |
| `docs/design.md` (modify) | Указатель на петлю калибровки. |

---

### Task 1: `lib/tune_diff.py` — детерминированная прозо-разница + FN/FP-разметка

**Files:**
- Create: `lib/tune_diff.py`
- Test: `tests/test_tune_diff.py`

**Interfaces:**
- Consumes: `lib.qmd_prose.extract_prose(source: str) -> list[ProseLine]` (поля `.lineno: int`, `.text: str`, `.suppress: set[str]`); `lib.lint_prose.load_entries(path: str | None) -> list[dict]` (каждая запись с компилированным `_rx` и ключами `id`, `except?`).
- Produces: `diff_prose(pristine_src: str, edited_src: str, entries: list[dict]) -> list[Hunk]`; `@dataclass Hunk(line: int, before: str, after: str, triage: str, rule_hit: str | None, before_dirty: bool)` где `triage ∈ {"FN","FP","neutral"}`. CLI: `python3 -m lib.tune_diff <pristine> <edited> [--dictionary PATH] [--json]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tune_diff.py`:

```python
from lib.lint_prose import load_entries
from lib.tune_diff import diff_prose

ENTRIES = load_entries(None)


def test_no_change_yields_no_hunks():
    src = "Очаги распознавали методами лучевой диагностики.\n"
    assert diff_prose(src, src, ENTRIES) == []


def test_fp_when_edit_trips_a_rule():
    # pristine чист; пользователь уходит к кальке, которую словарь запрещает
    before = "Использовали эталонный стандарт сравнения.\n"
    after = "Использовали референсный стандарт сравнения.\n"
    hunks = diff_prose(before, after, ENTRIES)
    assert len(hunks) == 1
    assert hunks[0].triage == "FP"
    assert hunks[0].rule_hit == "calque-referens"
    assert hunks[0].before_dirty is False


def test_fn_when_replacement_trips_no_rule():
    # 'продемонстрировало' нет в словаре -> FN-кандидат
    before = "Исследование продемонстрировало увеличение очага.\n"
    after = "Исследование показало рост очага.\n"
    hunks = diff_prose(before, after, ENTRIES)
    assert len(hunks) == 1
    assert hunks[0].triage == "FN"
    assert hunks[0].rule_hit is None


def test_pure_deletion_is_neutral():
    before = "Первое предложение.\nВторое предложение.\n"
    after = "Первое предложение.\n"
    hunks = diff_prose(before, after, ENTRIES)
    assert len(hunks) == 1
    assert hunks[0].triage == "neutral"


def test_before_dirty_flags_writer_miss():
    # pristine сам трогает правило (само-линт промахнулся) -> before_dirty True
    before = "Оценивали оба метода визуализации (модальности).\n"
    after = "Оценивали оба метода.\n"
    hunks = diff_prose(before, after, ENTRIES)
    assert len(hunks) == 1
    assert hunks[0].before_dirty is True
    assert hunks[0].triage == "FN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_tune_diff.py -v > /tmp/test-tune-diff.txt 2>&1`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.tune_diff'` (читать `/tmp/test-tune-diff.txt`).

- [ ] **Step 3: Write minimal implementation**

Create `lib/tune_diff.py`:

```python
"""Prose-level diff + FN/FP triage between a pristine and an edited .qmd. Stdlib only."""
from __future__ import annotations
import argparse, json
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path

from lib.qmd_prose import extract_prose
from lib.lint_prose import load_entries


@dataclass
class Hunk:
    line: int            # 1-based line in the edited file (or pristine for pure deletions)
    before: str
    after: str
    triage: str          # "FN" | "FP" | "neutral"
    rule_hit: str | None
    before_dirty: bool


def _rule_hit(text: str, entries: list[dict]) -> str | None:
    """Id of the first dictionary rule matching `text` (honoring `except`), else None."""
    low = text.lower()
    for e in entries:
        exc = e.get("except")
        if exc and exc.lower() in low:
            continue
        if e["_rx"].search(text):
            return e["id"]
    return None


def _prose(src: str):
    pls = extract_prose(src)
    return [pl.text.strip() for pl in pls], [pl.lineno for pl in pls]


def diff_prose(pristine_src: str, edited_src: str, entries: list[dict]) -> list[Hunk]:
    b_text, b_line = _prose(pristine_src)
    a_text, a_line = _prose(edited_src)
    sm = SequenceMatcher(a=b_text, b=a_text, autojunk=False)
    hunks: list[Hunk] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        before = " ".join(b_text[i1:i2]).strip()
        after = " ".join(a_text[j1:j2]).strip()
        if not before and not after:
            continue
        after_hit = _rule_hit(after, entries) if after else None
        before_hit = _rule_hit(before, entries) if before else None
        if after_hit:
            triage = "FP"
        elif before and after:
            triage = "FN"
        else:
            triage = "neutral"
        line = a_line[j1] if j1 < len(a_line) else (b_line[i1] if i1 < len(b_line) else 0)
        hunks.append(Hunk(line=line, before=before, after=after, triage=triage,
                          rule_hit=after_hit, before_dirty=bool(before_hit)))
    return hunks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prose diff + FN/FP triage for rule tuning")
    ap.add_argument("pristine")
    ap.add_argument("edited")
    ap.add_argument("--dictionary", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    entries = load_entries(args.dictionary)
    pristine_src = Path(args.pristine).read_text(encoding="utf-8")
    edited_src = Path(args.edited).read_text(encoding="utf-8")
    hunks = diff_prose(pristine_src, edited_src, entries)
    if args.json:
        print(json.dumps([asdict(h) for h in hunks], ensure_ascii=False, indent=2))
    else:
        for h in hunks:
            print(f"[{h.triage}] L{h.line} rule={h.rule_hit} before_dirty={h.before_dirty}")
            print(f"  - {h.before}")
            print(f"  + {h.after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_tune_diff.py -v > /tmp/test-tune-diff.txt 2>&1`
Expected: PASS — `5 passed`.

- [ ] **Step 5: Verify CLI smoke + no regression**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q > /tmp/test-tune-all.txt 2>&1`
Expected: `25 passed` (20 существующих + 5 новых).

- [ ] **Step 6: Commit**

```bash
git add lib/tune_diff.py tests/test_tune_diff.py
git commit -m "feat: tune_diff helper — prose diff + FN/FP triage for rule tuning"
```

---

### Task 2: `skills/tuning-rules/SKILL.md` — дисциплина вывода правил

**Files:**
- Create: `skills/tuning-rules/SKILL.md`

**Interfaces:**
- Consumes: вывод `lib/tune_diff.py` (фрагменты с `triage`/`rule_hit`/`before_dirty`); `canon/dictionary.json`; `skills/writing-russian-academic-prose`, `skills/say-it-once-academic-prose`; `canon/profiles/<жанр>.md`.
- Produces: дисциплина, на которую ссылается `commands/tune-learn.md` («примени скилл `scientific-writing:tuning-rules`»).

- [ ] **Step 1: Write the skill file**

Create `skills/tuning-rules/SKILL.md`:

```markdown
---
name: tuning-rules
description: Use when turning a diff between a canon-clean draft and the user's hand-edit into proposed plugin-rule changes (dictionary entries, prose-skill rows, profile/spec edits, or linter-code changes). Invoked by the tune-learn command. Classifies each edit, routes it to the right rule layer, and proves dictionary rules on the test oracle before applying.
---

# Tuning Rules (вывод правил из правок)

## Overview
Петля калибровки: `scientific-writer` выдаёт чистый по линтеру черновик → пользователь правит
вручную → этот скилл превращает различия в **изменения правил**. Раз «до» гарантированно чист, каждая правка —
это **промах правил** (FN) либо **перекомпенсация** (FP). Твоя задача — классифицировать каждый фрагмент,
направить в нужный слой и для словарных правил **доказать** их на тест-оракуле до применения.

Вход — фрагменты из `lib/tune_diff.py`: `triage` (FN/FP/neutral), `rule_hit` (какое правило тронул
edited-текст), `before_dirty` (pristine сам трогал правило — само-линт промахнулся, более слабый сигнал).

## Таксономия и маршрутизация
| Класс правки | Признак | Маршрут |
|---|---|---|
| Пропущенная калька (FN), regex-выразима | `triage=FN`, убран обобщаемый лексический паттерн | новая/расширенная запись `canon/dictionary.json` |
| Перекомпенсация (FP) | `triage=FP`, `rule_hit` задан | ослабить `rule_hit`: `except` / сузить `pattern` / `severity`↓ / уточнение в скилле |
| Суждение (фраза, regex не выражает) | FN, но паттерн контекстный (тире, номинализация, инструмент-деятель) | строка в таблице `skills/writing-russian-academic-prose` |
| Документный (повтор/термин-дрейф) | правка убирает повтор/синоним между разделами | `skills/say-it-once-academic-prose` |
| Структура/жанр | правка трогает порядок/состав разделов, длину | `canon/profiles/<жанр>.md` |
| Терм конкретного документа | канонический терм этого документа | `<doc>.spec.md` — **НЕ** глобальное правило |
| Шум / разовый вкус | одиночная стилевая правка без обобщаемого паттерна | ничего; показать как «не обобщаю» |
| Нужен код | regex принципиально не выражает | правка логики `lib/lint_prose.py` (опиши, при малом объёме — правку) |

## Фильтр шума — когда НЕ предлагать правило
- Одиночная правка без обобщаемого лексического/синтаксического паттерна → не правило (покажи и пропусти).
- Терм конкретного документа → в `<doc>.spec.md`, не в универсальный слой (не добавляй в глобальные правила).
- `before_dirty=True` → это промах само-линта писателя, а не пробел правил; правило уже есть — отметь, но
  нового не выдумывай.
- Финальный фильтр генеральности — подтверждение/отклонение пользователя. Сомнения трактуй как «показать, не применять».

## Как писать запись словаря
Схема: `{id, layer, pattern, except?, severity, message, bad?, good?, note?, skill}`.
- `id` — kebab-case, осмысленный (`calque-…`, `parasite-…`, `vulgar-…`, `jargon-…`, `style-…`).
- `pattern` — Python `re`, применяется к извлечённой прозе с флагами `IGNORECASE|UNICODE` (их ставит линтер —
  **не** дублируй inline-флаги). Границы `\b`; морфология через `\w*`. Узкий контекст, не жадные `.*`.
- `except` — токен-исключение для допустимого смысла (как `DICOM` у `calque-modalnost`).
- `severity` — `error` только для однозначной лексической кальки с низким FP-риском; эвристики/контекстное —
  `warn` (см. `docs/design.md` 98–110).
- `message` — формат «суть → как правильно»; `skill: writing-russian-academic-prose`.

## Порядок ослабления при FP (`rule_hit`)
1. `except`: добавить узкий допустимый токен.
2. Сузить `pattern`: уточнить границу/контекст, убрать пересечение с законной формой.
3. `severity`↓ (error→warn), если правило по сути эвристично.
4. В крайнем случае — уточнение в `skills/writing-russian-academic-prose`, правило снять.

## Самопроверка словаря — ОБЯЗАТЕЛЬНО до применения
Процедура зависит от класса правки.

**Новое/расширенное правило (FN — ловим пропущенную кальку):**
1. Добавить убранную фразу (`before`) строкой в `tests/fixtures/calques.qmd` — это калька, её обязано ловить какое-то правило.
2. `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m pytest tests/test_dictionary.py tests/test_lint_prose.py` → должно
   пройти (новое правило ловит фразу; все прежние фикстуры ловятся; `id` уникальны; схема валидна).
3. `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose <edited.qmd> --json` → id нового правила **НЕ**
   появляется на оставленном хорошем тексте.

**Ослабление правила (FP — правило переусердствовало):** фразу в `calques.qmd` **не** добавлять (это не калька —
добавление сломает `test_every_fixture_phrase_is_flagged`).
1. `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose <edited.qmd> --json` → у этого `id` на оставленном
   тексте больше нет находки с `severity: error` (`except`/сужение убирают находку совсем; `severity↓ error→warn`
   оставляет её как `warn` — это и есть цель: блокирующая ошибка снята). NB: `--json` печатает находки **всех**
   severity — фильтруй по полю `severity`, а не по наличию `id`.
2. `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m pytest tests/test_dictionary.py tests/test_lint_prose.py` → должно
   пройти (ослабление не сломало выявление истинных калек в `calques.qmd`; схема валидна).

Любой шаг провалился → запись **не применять**: уточнить паттерн/`except` или перевести в предложение для скилла.

## Red flags — STOP
- Предлагать правило из одной нечёткой правки без паттерна → это шум, не правило.
- Применять словарную запись без зелёного `pytest` и проверки FP на хорошем тексте → запрещено.
- Переносить терм конкретного документа в универсальный слой → в спецификацию документа.
- Делать коммит самому → команда только применяет в рабочее дерево; проверка и коммит — за пользователем.
```

- [ ] **Step 2: Verify frontmatter and required content**

Run: `PYTHONPATH=. .venv/bin/python -c "import pathlib; t=pathlib.Path('skills/tuning-rules/SKILL.md').read_text(); assert t.startswith('---'); assert 'name: tuning-rules' in t; assert all(k in t for k in ['Самопроверка','ослабления при FP','Фильтр шума','dictionary.json']); print('ok')" > /tmp/test-tune-skill.txt 2>&1`
Expected: `ok` (читать `/tmp/test-tune-skill.txt`).

- [ ] **Step 3: Commit**

```bash
git add skills/tuning-rules/SKILL.md
git commit -m "feat: tuning-rules skill — taxonomy + dictionary self-validation discipline"
```

---

### Task 3: `commands/tune-draft.md` — фаза генерации

**Files:**
- Create: `commands/tune-draft.md`

**Interfaces:**
- Consumes: агент `agents/scientific-writer.md`; `lib/lint_prose.py` (само-линт); `canon/profiles/<жанр>.md`.
- Produces: артефакты в стабильном tmp-каталоге — `<slug>.qmd`, `<slug>.pristine.qmd`, `<slug>.tune.json` (имена соседних файлов), которые читает Task 4.

- [ ] **Step 1: Write the command file**

Create `commands/tune-draft.md`:

```markdown
---
description: Сгенерировать черновик из источника с применением канона (writer + само-линт) для последующей калибровки правил
argument-hint: <source: URL|тема|путь> [genre: report|article|educational]
allowed-tools: Bash, Read, Write, WebFetch, Task
---

Сгенерируй черновик из `$ARGUMENTS` с применением канона — «до» для петли калибровки правил.

## Шаги
1. Определи источник ($1): URL → WebFetch; путь к файлу → Read; иначе трактуй как тему-задание.
   Жанр ($2) ∈ {report, article, educational}; не задан → спроси (default: article).
   Необязательная подсказка длины из запроса (напр. «~1000 слов»).
2. Выбери стабильный каталог: `D=${TMPDIR:-/tmp}/sci-tune` и короткое имя из источника
   (`SLUG` — короткое имя темы/файла в kebab-case; при коллизии добавь суффикс). `mkdir -p "$D"`.
3. Вызови агента `scientific-writer` в режиме **tuning-fixture** (БЕЗ `<doc>.spec.md`): напиши
   `<genre>`-черновик из источника по `canon/profiles/<жанр>.md` + `canon/canon.md` + `canon/dictionary.json`, применяя канон.
   Спецификация намеренно пропускается — это калибровочная фикстура, правило «нет документа без спецификации» здесь не действует.
   Сохрани результат в `$D/$SLUG.qmd`.
4. Само-линт-цикл (≤3 итерации):
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "$D/$SLUG.qmd" --json`
   — есть error/warn → писатель правит эти места → повтор. Чисто (или только `lint-ok`) → выход.
   Не свелось за 3 → оставь как есть, отметь остаточные находки (они тоже сигнал).
5. Сохрани нетронутую копию и файл-спутник:
   - `cp "$D/$SLUG.qmd" "$D/$SLUG.pristine.qmd"`
   - запиши `$D/$SLUG.tune.json`:
     `{"source": "<$1>", "genre": "<жанр>", "draft": "<$SLUG.qmd>", "pristine": "<$SLUG.pristine.qmd>", "lint_clean": <true|false>}`
6. Печать: путь `$D/$SLUG.qmd` + «Правь вручную как считаешь нужным, потом:
   `/scientific-writing:tune-learn $D/$SLUG.qmd`».

Если источник недоступен — сообщи и спроси альтернативу. Не делай коммит и не выполняй рендеринг.
```

- [ ] **Step 2: Verify frontmatter and references**

Run: `PYTHONPATH=. .venv/bin/python -c "import pathlib; t=pathlib.Path('commands/tune-draft.md').read_text(); assert t.startswith('---'); assert 'allowed-tools:' in t; assert 'scientific-writer' in t and 'lib.lint_prose' in t and 'tune-learn' in t; print('ok')" > /tmp/test-tune-draft.txt 2>&1`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add commands/tune-draft.md
git commit -m "feat: tune-draft command — canon-clean draft generation for rule tuning"
```

---

### Task 4: `commands/tune-learn.md` — фаза вывода правил

**Files:**
- Create: `commands/tune-learn.md`

**Interfaces:**
- Consumes: `lib/tune_diff.py` (Task 1); скилл `scientific-writing:tuning-rules` (Task 2); `<slug>.pristine.qmd` + `<slug>.tune.json` (Task 3); `canon/dictionary.json`, `tests/fixtures/calques.qmd`, прозо-скиллы, профили.
- Produces: правки в рабочее дерево (не коммит).

- [ ] **Step 1: Write the command file**

Create `commands/tune-learn.md`:

```markdown
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
     `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m lib.lint_prose "<edited.qmd>" --json` → у `id` больше нет находки с `severity: error`
     (`except`/сужение — находка исчезает; `severity↓` — остаётся как `warn`; `--json` печатает все severity, фильтруй по полю);
     `PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m pytest tests/test_dictionary.py tests/test_lint_prose.py` → зелёный.
   - провал любого → запись не применять (уточнить/в скилл).
5. Отчёт на подтверждение: сгруппируй по слою (словарь / прозо-скиллы / профиль / спецификация / код / шум). Каждый пункт:
   фрагмент-обоснование (`- before` / `+ after`), класс, правка; для словаря — результат зелёного теста.
6. Подтверждение → применяй правки (Edit/Write) в рабочее дерево; фикстур-строки оставь (они доказывают правило).
   Прогони весь `pytest` (`PYTHONPATH=${CLAUDE_PLUGIN_ROOT} python3 -m pytest -q`) → зелёный.
   **Не делай коммит** — пользователь проверяет и делает коммит сам.

Если вспомогательный модуль завершился с ошибкой: проверь `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}`, что pristine и edited существуют, словарь на месте.
```

- [ ] **Step 2: Verify frontmatter and references**

Run: `PYTHONPATH=. .venv/bin/python -c "import pathlib; t=pathlib.Path('commands/tune-learn.md').read_text(); assert t.startswith('---'); assert 'lib.tune_diff' in t and 'scientific-writing:tuning-rules' in t and 'calques.qmd' in t and 'test_dictionary' in t; print('ok')" > /tmp/test-tune-learn.txt 2>&1`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add commands/tune-learn.md
git commit -m "feat: tune-learn command — infer rule deltas from edits, self-validate dictionary"
```

---

### Task 5: Указатель в `docs/design.md` + финальная проверка

**Files:**
- Modify: `docs/design.md` (последний пункт «Out of scope», в конце файла)

**Interfaces:**
- Consumes: ничего.
- Produces: указатель на `docs/tune-rules-design.md`.

- [ ] **Step 1: Add the pointer section**

Edit `docs/design.md` — найди последний пункт:

```
- Code review itself (`pr-diff-reviewer` unchanged) — the plugin only routes around it for text.
```

и замени на:

```
- Code review itself (`pr-diff-reviewer` unchanged) — the plugin only routes around it for text.

## Related

- `docs/tune-rules-design.md` — rule-calibration loop driven by the user's edits
  (`tune-draft` → manual edit → `tune-learn` → rule deltas, dictionary rules proven on the test oracle).
```

- [ ] **Step 2: Final full-suite verification**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q > /tmp/test-tune-final.txt 2>&1`
Expected: `25 passed`.

- [ ] **Step 3: Verify new artifacts exist**

Run: `ls lib/tune_diff.py tests/test_tune_diff.py skills/tuning-rules/SKILL.md commands/tune-draft.md commands/tune-learn.md > /tmp/test-tune-ls.txt 2>&1; echo "exit=$?"`
Expected: `exit=0`, все пять путей перечислены.

- [ ] **Step 4: Commit**

```bash
git add docs/design.md
git commit -m "docs: link tune-rules calibration loop from master design"
```

---

## Acceptance (сквозная ручная проверка)

После Task 5 — ручной запуск петли (не автотест):
1. `/scientific-writing:tune-draft <какой-нибудь URL> article` → черновик в `$TMPDIR/sci-tune/`, чистый по линтеру.
2. Внеси 2–3 правки вручную: одну FP (впиши форму, которую правило ловит, напр. «референсный»), одну FN
   (убери кальку, которой нет в словаре).
3. `/scientific-writing:tune-learn <draft>` → отчёт: FP-правка маршрутизирована на ослабление правила,
   FN — на новую запись словаря с зелёным `pytest`. Применение оставляет набор тестов зелёным.

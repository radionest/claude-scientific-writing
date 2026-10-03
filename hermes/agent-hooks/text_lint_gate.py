#!/usr/bin/env python3
"""Hermes shell hook: text_lint_gate — блокирует git commit / gh pr create при
error-находках линтера научной прозы в изменённых .qmd (кальки, пунктуация,
орфография).

Диалект Hermes (как у pr_review_gate.py): stdin payload
{"hook_event_name": "pre_tool_call", "tool_name": "terminal",
 "tool_input": {"command": ...}, "cwd": ...}
Блокировка: stdout {"action": "block", "message": ...} + exit 0.
Пропуск: нет вывода, exit 0.

Экстренный обход: SKIP_TEXT_LINT=1. Хук сам находит репо плагина:
SCIENTIFIC_WRITING_ROOT > git-корень этого файла > ~/Projects/claude-scientific-writing.
Использует .venv плагина (морфология); при его отсутствии — системный python3
(ослабленный режим). Коммит гейтит только error-severity (warn/info — мимо).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
SKIP = os.environ.get("SKIP_TEXT_LINT", "") not in ("", "0")


def plugin_root() -> Path | None:
    env = os.environ.get("SCIENTIFIC_WRITING_ROOT")
    if env:
        p = Path(env)
        if (p / "lib" / "lint_prose.py").exists():
            return p
    # .../hermes/agent-hooks/text_lint_gate.py -> repo root
    if (HOOK_DIR.parent.parent / "lib" / "lint_prose.py").exists():
        return HOOK_DIR.parent.parent
    p = Path.home() / "Projects" / "claude-scientific-writing"
    if (p / "lib" / "lint_prose.py").exists():
        return p
    return None


def main() -> int:
    if SKIP:
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # нечитаемый payload — не блокируем
    cmd = (payload.get("tool_input") or {}).get("command", "") or ""
    cwd = payload.get("cwd") or os.getcwd()

    if "git commit" not in cmd and "gh pr create" not in cmd:
        return 0

    root = plugin_root()
    if root is None:
        return 0  # плагин не найден — гейт не установлен, пропускаем
    venv_py = root / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable

    # изменённые .qmd: staged (git commit) или origin/main...HEAD (gh pr create)
    ref = "origin/main" if "gh pr create" in cmd else None
    try:
        if ref:
            diff_out = subprocess.run(
                ["git", "-C", cwd, "diff", "--name-only", f"{ref}...HEAD"],
                capture_output=True, text=True, timeout=30,
            ).stdout
        else:
            diff_out = subprocess.run(
                ["git", "-C", cwd, "diff", "--cached", "--name-only"],
                capture_output=True, text=True, timeout=30,
            ).stdout
    except Exception:
        return 0
    qmd_files = [f for f in diff_out.splitlines() if f.strip().endswith(".qmd")]
    if not qmd_files:
        return 0

    findings_errs = []
    notes = []
    for f in qmd_files:
        fp = Path(cwd) / f
        if not fp.is_file():
            continue
        if "tests/fixtures/" in str(fp).replace("\\", "/"):
            continue  # oracle-фикстуры намеренно содержат кальки
        run_args = [py, "-m", "lib.lint_prose", str(fp), "--json", "--diff"]
        if ref:
            run_args.append(ref)
        # cwd = проект: changed_lines() зовёт git diff в своём cwd; модуль lib
        # резолвится через PYTHONPATH=корень плагина, файл — абсолютным путём.
        proc = subprocess.run(
            run_args, cwd=cwd, capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONPATH": str(root)},
        )
        if proc.returncode == 2:  # битый локальный словарь — жёсткая блокировка
            print(json.dumps({
                "action": "block",
                "message": (
                    f"text-lint: ошибка локального словаря в {f} (см. вывод линтера). "
                    "Поправь .claude/scientific-writing/dictionary.json проекта. "
                    "Экстренный обход: SKIP_TEXT_LINT=1."
                ),
                "reason": "text_lint_gate: local dictionary error",
            }, ensure_ascii=False))
            return 0
        if proc.returncode == 1 and proc.stdout.strip():
            try:
                for item in json.loads(proc.stdout):
                    if item.get("severity") == "error":
                        findings_errs.append(f"{f}:{item.get('line')}:{item.get('col')} [{item.get('id')}] {item.get('message')}")
            except json.JSONDecodeError:
                notes.append(f"{f}: не удалось разобрать вывод линтера")
        elif proc.returncode not in (0, 1):
            notes.append(f"{f}: линтер упал (rc={proc.returncode})")

    if findings_errs or notes:
        lines = ["text-lint: запрещённые кальки / ошибки пунктуации и орфографии в изменённой прозе:"]
        lines += [f"  - {x}" for x in findings_errs[:30]]
        if notes:
            lines.append("  заметки: " + "; ".join(notes[:5]))
        lines.append("Поправь прозу или добавь <!-- lint-ok: id -->. Экстренный обход: SKIP_TEXT_LINT=1.")
        print(json.dumps({
            "action": "block",
            "message": "\n".join(lines),
            "reason": "text_lint_gate: error-severity findings in changed .qmd",
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

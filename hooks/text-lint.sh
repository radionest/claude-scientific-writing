#!/usr/bin/env bash
# hooks/text-lint.sh — PreToolUse gate: block gh pr create / git commit on NEW error-severity calques.
set -euo pipefail
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
payload="$(cat)"
cmd="$(printf '%s' "$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null || true)"

case "$cmd" in
  *"gh pr create"*) ref="origin/main" ;;
  *"git commit"*)   ref="" ;;            # staged diff
  *) exit 0 ;;
esac

# changed .qmd files
if [ -n "$ref" ]; then
  mapfile -t files < <(git diff --name-only "$ref"...HEAD -- '*.qmd' 2>/dev/null || true)
else
  mapfile -t files < <(git diff --cached --name-only -- '*.qmd' 2>/dev/null || true)
fi
[ "${#files[@]}" -eq 0 ] && exit 0

rc=0
for f in "${files[@]}"; do
  [ -f "$f" ] || continue
  # skip test fixtures — they intentionally contain calques (e.g. this plugin's own oracle)
  case "$f" in tests/fixtures/*|*/tests/fixtures/*) continue ;; esac
  # file BEFORE --diff: --diff has nargs="?", so a trailing filename would be
  # consumed as its optional REF value, leaving no positional. Files-first is unambiguous.
  if [ -n "$ref" ]; then
    s=0
    PYTHONPATH="$PLUGIN_DIR" python3 -m lib.lint_prose "$f" --diff "$ref" || s=$?
    if [ "$s" -gt "$rc" ]; then rc=$s; fi
  else
    s=0
    PYTHONPATH="$PLUGIN_DIR" python3 -m lib.lint_prose "$f" --diff || s=$?
    if [ "$s" -gt "$rc" ]; then rc=$s; fi
  fi
done

if [ "$rc" -eq 2 ]; then
  echo "text-lint: ошибка локального словаря (см. выше). Поправь .claude/scientific-writing/dictionary.json." >&2
  exit 2
fi
if [ "$rc" -ne 0 ]; then
  echo "text-lint: запрещённые кальки в изменённой прозе (см. выше). Поправь или добавь <!-- lint-ok: id -->." >&2
  exit 2
fi
exit 0

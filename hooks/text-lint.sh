#!/usr/bin/env bash
# hooks/text-lint.sh — PreToolUse gate: block gh pr create / git commit on NEW error-severity
# findings (lexical calques, punctuation, orthography).
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

# the eval bad-corpus exemption is path identity, not a suffix pattern (#89): a user
# file at tests/eval/lint-bad.qmd must not bypass linting. When the commit happens in
# the plugin's own repo (dev checkout), that repo's corpus is the oracle; otherwise
# the running plugin copy's corpus is.
root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$root" ] && [ -f "$root/.claude-plugin/plugin.json" ]; then
  evalcorpus="$root/tests/eval/lint-bad.qmd"
else
  evalcorpus="$PLUGIN_DIR/tests/eval/lint-bad.qmd"
fi

rc=0
for f in "${files[@]}"; do
  [ -f "$f" ] || continue
  # skip test fixtures — they intentionally contain calques (the plugin's own
  # oracles); lint-good.qmd stays gated: it must yield no errors
  case "$f" in tests/fixtures/*|*/tests/fixtures/*) continue ;; esac
  [ "$(realpath -- "$f")" = "$evalcorpus" ] && continue
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

if [ "$rc" -eq 3 ]; then
  echo "text-lint: ошибка локального словаря (см. выше). Поправь .claude/scientific-writing/dictionary.json." >&2
  exit 2
fi
if [ "$rc" -ne 0 ]; then
  echo "text-lint: запрещённые кальки и ошибки пунктуации/орфографии в изменённой прозе (см. выше). Поправь или добавь <!-- lint-ok: id -->." >&2
  exit 2
fi
exit 0

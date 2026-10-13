#!/bin/sh
# 冒険者の WebFetch を、許可リストで判定するフックの起動用。標準入力（フックの入力）を web_gate.py に渡す。
# Python は guild/config.json（/guild:init が記録）のものを使い、なければ py・python3・python の順に探す。
HERE=$(cd "$(dirname "$0")" && pwd)
CFG="${CLAUDE_PROJECT_DIR:-.}/guild/config.json"
PY=""
if [ -f "$CFG" ]; then
  PY=$(sed -n 's/.*"python": *"\(.*\)".*/\1/p' "$CFG" | head -n 1 | sed 's/\\/\//g')
fi
if [ -z "$PY" ] || [ ! -e "$PY" ]; then
  for c in py python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || exit 0
exec "$PY" -I "$HERE/web_gate.py"

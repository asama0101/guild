#!/bin/sh
# Guild auto run for Mac and Linux. Placed in <vault>/guild/.system/auto/ by /guild:auto and started by cron.
# It runs "/guild:quest auto" only when there is something to do.
AUTO="$(cd "$(dirname "$0")" && pwd)"
SYS="$(dirname "$AUTO")"
VAULT="$(dirname "$(dirname "$SYS")")"
LOGS="$SYS/logs"
mkdir -p "$LOGS"
NOW="$(date '+%Y-%m-%d %H:%M')"
STAMP="$(date '+%Y%m%d-%H%M')"
[ -f "$AUTO/path.txt" ] && PATH="$(cat "$AUTO/path.txt")" && export PATH
last() { printf '{ "time": "%s", "ok": %s, "skipped": %s }\n' "$NOW" "$1" "$2" > "$LOGS/last.json"; }
# Another run (auto or by hand) is still going. A lock older than 3 hours is left over from a stopped run.
if [ -f "$AUTO/run.lock" ]; then
  if [ -n "$(find "$AUTO/run.lock" -mmin -180 2>/dev/null)" ]; then exit 0; fi
  rm -f "$AUTO/run.lock"
fi
# Nothing new (requests, answers, feedback) and no unfinished run: do nothing.
n=$(ls "$SYS"/requests/*.json "$SYS"/answers/*.json "$SYS"/feedback/*.json 2>/dev/null | wc -l)
if [ "$n" -eq 0 ] && [ ! -f "$AUTO/resume" ]; then last true true; exit 0; fi
touch "$AUTO/run.lock" "$AUTO/resume"
ALLOW=$(grep -v '^#' "$AUTO/allow.txt" | sed 's/^ *//;s/ *$//' | grep -v '^$' | paste -sd, -)
CLAUDE=claude
[ -f "$AUTO/claude.txt" ] && CLAUDE="$(head -n 1 "$AUTO/claude.txt")"
cd "$VAULT" || exit 1
"$CLAUDE" -p "/guild:quest auto" --permission-mode acceptEdits --allowedTools "$ALLOW" > "$LOGS/run-$STAMP.log" 2>&1
if [ $? -eq 0 ]; then rm -f "$AUTO/resume"; last true false; else last false false; fi
rm -f "$AUTO/run.lock"
# Keep the newest 30 logs.
ls -1t "$LOGS"/run-*.log 2>/dev/null | tail -n +31 | while read -r f; do rm -f "$f"; done

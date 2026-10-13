#!/usr/bin/env python3
"""冒険者（guild:adventurer）の WebFetch を、許可リスト（guild/web/access.json）で判定するフック（PreToolUse）。

許可リストにあるドメインは通す。ないものは止めて、止めた URL を pending に残す（ボードの手紙になる）。
冒険者以外（ギルドマスター自身や他のサブエージェント）の呼び出しには、何も言わない。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "quest"))
import webaccess  # noqa: E402


def find_guild(start):
    p = Path(start).resolve()
    for d in (p, *p.parents):
        if (d / "guild" / "config.json").is_file():
            return d / "guild"
    return None


def main():
    stream = sys.stdin
    stream.reconfigure(encoding="utf-8")
    try:
        data = json.loads(stream.read())
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    agent = str(data.get("agent_type") or "")
    if agent.rsplit(":", 1)[-1] != "adventurer":
        return 0
    gdir = find_guild(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".")
    if gdir is None:
        return 0
    tool_input = data.get("tool_input")
    url = tool_input.get("url", "") if isinstance(tool_input, dict) else ""
    verdict, reason = webaccess.gate(gdir, url)
    if verdict == "deny":
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

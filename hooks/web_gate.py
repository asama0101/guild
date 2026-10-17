#!/usr/bin/env python3
"""魔法使い（guild:wizard）の WebFetch を、許可リスト（guild/.work/web/access.json）で判定するフック（PreToolUse）。

許可リストにあるドメインは通す。ないものは止めて、止めた URL を pending に残す（ボードの手紙になる）。
魔法使い以外（ギルドマスター自身や他のサブエージェント）の呼び出しには、何も言わない。
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
        g = d / "guild"
        if (g / ".work" / "config.json").is_file() or (g / "config.json").is_file():  # 旧版の配置も認める（フックの保護を外さない）
            return g
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
    if agent.rsplit(":", 1)[-1] != "wizard":
        return 0
    gdir = find_guild(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".")
    if gdir is None:
        return 0
    tool_input = data.get("tool_input")
    url = tool_input.get("url", "") if isinstance(tool_input, dict) else ""
    prompt = tool_input.get("prompt", "") if isinstance(tool_input, dict) else ""  # 魔法使いが、そのページから取りたい内容（手紙に「目的」として出す）
    verdict, reason = webaccess.gate(gdir, url, prompt)
    if verdict == "deny":
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

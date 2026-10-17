"""総点検（2 回目）の指摘の修正を確かめる。"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
sys.path.insert(0, str(ROOT / "tests"))
import guild  # noqa: E402
import webaccess  # noqa: E402
from test_board_js import extract, node_eval  # noqa: E402

TR = guild.load_transitions()
CRIT = {"viewpoint": "viewpoint 十分に具体的", "pass_line": "pass_line 十分に具体的", "check": "check 十分に具体的"}


def goal(i, state="pending", **kw):
    t = {"id": i, "title": f"{i}を調べる", "kind": "auto", "class": "wizard", "effects": "none", "deps": [], "criteria": dict(CRIT), "state": state, "retries": 0}
    t.update(kw)
    return t


@unittest.skipUnless(shutil.which("node"), "node がありません")
class BoardDatesTest(unittest.TestCase):
    def test_overdue_and_day_number_use_valid_dates(self):
        src = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        line = lambda name: re.search(rf"^const {name} = .*$", src, re.M).group(0)
        code = "\n".join(line(n) for n in ("closed", "overdue", "DAY_MS", "dayNum", "okDate")) + """
const now = new Date('2026-10-17T12:00:00').getTime();
console.log(JSON.stringify([
  overdue({ due: '2026-10-16', state: 'running' }, now),
  overdue({ due: '2026-10-17', state: 'running' }, now),
  overdue({ due: '2026-10-16', state: 'done' }, now),
  okDate('2026-10-17'), okDate('2026-13-45'), dayNum('2026-10-18') - dayNum('2026-10-17')]));"""
        self.assertEqual(node_eval(code), [True, False, False, True, False, 1])


if __name__ == "__main__":
    unittest.main()

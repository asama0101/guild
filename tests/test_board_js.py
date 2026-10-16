"""board.html の JavaScript の構文検査（node があるときだけ）と、承認の手紙・ボードが読む plan.json のキーの契約。"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")


def script():
    return "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", BOARD, re.S))


@unittest.skipUnless(shutil.which("node"), "node がありません")
class BoardSyntaxTest(unittest.TestCase):
    def test_script_parses(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "board.js"
            f.write_text(script(), encoding="utf-8")
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)


class PlanBriefContractTest(unittest.TestCase):
    def test_approval_letter_shows_brief_check_workload_and_diff(self):
        i = BOARD.index("'aria-label': '計画の承認'")
        letter = BOARD[i:i + 1500]
        self.assertIn("planBriefBlock(qd.q.plan)", letter)
        body = BOARD[BOARD.index("function planBriefBlock"):BOARD.index("const TEXT_INPUT")]
        for key in ("p.brief", "p.check", "p.workload", "p.replan_diff", "non_goals", "assumptions", "risks",
                    "coverage", "over_deadline"):
            self.assertIn(key, body)


if __name__ == "__main__":
    unittest.main()

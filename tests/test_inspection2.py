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


class ReplanAcceptedTest(unittest.TestCase):
    def test_accepted_quest_cannot_take_a_replan_decision(self):
        plan = {"approved": True, "status": "active", "accepted": True, "goals": [goal("G1", "done")], "history": []}
        with self.assertRaises(guild.GuildError):
            guild.apply_input(plan, {"type": "decision", "goal": "G1", "choice": "replan"}, TR)
        self.assertTrue(plan["accepted"])
        self.assertEqual(plan["status"], "active")

    def test_replan_before_accepting_still_works(self):
        plan = {"approved": True, "status": "active", "goals": [goal("G1", "done")], "history": []}
        guild.apply_input(plan, {"type": "decision", "goal": "G1", "choice": "replan"}, TR)
        self.assertEqual((plan["status"], plan["approved"]), ("replan", False))


class AdvanceStateTest(unittest.TestCase):
    def run_advance(self, plan, goal_id, event):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.json"
            guild.save_json(path, plan)
            with self.assertRaises(guild.GuildError) as cm:
                guild.mutate_plan("advance", path, ["guild.py", "advance", str(path), goal_id, event])
            return str(cm.exception)

    def test_advance_is_refused_for_aborted_replan_and_unapproved_plans(self):
        for kw in ({"approved": True, "status": "aborted"}, {"approved": True, "status": "replan"}, {"approved": False, "status": "active"}):
            plan = {"quest": "Q001", "title": "t", **kw, "goals": [goal("G1", "running")], "history": []}
            self.assertIn("進められません", self.run_advance(plan, "G1", "submitted"), kw)


class ArchivePrefixTest(unittest.TestCase):
    def test_a_goal_does_not_take_another_goals_reports(self):
        tr = guild.load_transitions()
        self.assertTrue(guild.validate({"goals": [goal("A-B")]}, tr))  # id に - は使えない（reports/<id>-… の前方一致で、別の目標のものまで動くため）
        with tempfile.TemporaryDirectory() as d:
            q = Path(d)
            (q / "reports").mkdir()
            (q / "reports" / "G1-appraiser.md").write_text("x", encoding="utf-8")
            (q / "reports" / "G12-appraiser.md").write_text("y", encoding="utf-8")
            guild.archive_outputs({"goals": [goal("G1")]}, [], q)
            self.assertTrue((q / "reports" / "G12-appraiser.md").exists())
            self.assertFalse((q / "reports" / "G1-appraiser.md").exists())


class EvidenceDecorationTest(unittest.TestCase):
    def check(self, body):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d)
            (q / "reports").mkdir()
            (q / "reports" / "G1-appraiser.md").write_text(body, encoding="utf-8")
            guild.check_evidence({"history": []}, "G1", q)

    def test_decorated_passed_is_accepted(self):
        for body in ("## 判定\npassed\n", "## 判定\n**passed**\n", "## 判定\n- passed\n", "## 判定\n`passed`\n", "## 判定\n> Passed\n"):
            self.check(body)

    def test_other_verdicts_are_refused(self):
        for body in ("## 判定\n**rejected**\n", "## 判定\nnot passed\n", "## 判定\n\n", "判定なし"):
            with self.assertRaises(guild.GuildError, msg=body):
                self.check(body)


if __name__ == "__main__":
    unittest.main()

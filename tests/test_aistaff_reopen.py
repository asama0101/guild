"""完了・中止した依頼の「修正して再実行」（reopen）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402

TR = guild.load_transitions()
CRIT = {"viewpoint": "viewpoint 十分に具体的", "pass_line": "pass_line 十分に具体的", "check": "check 十分に具体的"}


def done_goal(i, **kw):
    t = {"id": i, "title": f"{i}を調べる", "kind": "auto", "class": "wizard", "effects": "none", "deps": [], "criteria": dict(CRIT), "state": "done", "retries": 0}
    t.update(kw)
    return t


class ReopenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.gdir = self.root / "guild"
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, **kw):
        p = {"quest": "Q001", "title": "週報", "series": "週報", "approved": True, "status": "active", "accepted": True, "deliver_to": "docs/reports",
             "goals": [done_goal("G1", deliverable=True)], "history": [{"t": "x", "event": "accepted"}]}
        p.update(kw)
        guild.save_plan(self.q / "plan.json", p)
        return p

    def send(self, obj):
        inbox = self.q / "inbox"
        inbox.mkdir(exist_ok=True)
        (inbox / "reopen.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        plan = guild.load_plan(self.q / "plan.json")
        report = guild.ingest(self.q / "plan.json", plan, TR, commit=lambda: guild.save_plan(self.q / "plan.json", plan))
        return plan, report

    def test_accepted_quest_is_reopened_and_everything_published_is_withdrawn(self):
        self.plan()
        d = self.q / "output" / "G1"
        d.mkdir(parents=True)
        (d / "週報.md").write_text("x", encoding="utf-8")
        guild.publish_deliverables(self.q)
        self.assertTrue(any((self.gdir / "deliverables").iterdir()))
        (self.q / "archive.json").write_text(json.dumps({"status": "done"}), encoding="utf-8")
        plan, report = self.send({"type": "reopen", "comment": "結論を先に書いてほしい"})
        self.assertEqual(report["rejected"], [])
        self.assertEqual((plan["status"], plan["approved"]), ("replan", False))
        self.assertNotIn("accepted", plan)
        self.assertEqual(plan["history"][-1]["event"], "reopen")
        self.assertEqual(plan["history"][-1]["comment"], "結論を先に書いてほしい")
        self.assertEqual(list((self.gdir / "deliverables").glob("Q001_*")), [])
        self.assertFalse((self.q / "archive.json").exists())
        self.assertTrue((self.q / "archive.prev.json").exists())
        self.assertEqual(guild.archive_state(self.q), "none")

    def test_aborted_quest_can_be_reopened_too(self):
        self.plan(accepted=False, status="aborted")
        plan, report = self.send({"type": "reopen", "comment": "条件を変えて、もう一度"})
        self.assertEqual(report["rejected"], [])
        self.assertEqual(plan["status"], "replan")

    def test_running_quest_cannot_be_reopened_and_a_comment_is_required(self):
        self.plan(accepted=False)
        _, report = self.send({"type": "reopen", "comment": "直したい"})
        self.assertEqual(len(report["rejected"]), 1)
        self.plan()
        (self.q / "inbox" / "done").mkdir(parents=True, exist_ok=True)
        for bad in ("", "   ", "あ" * (guild.REOPEN_MAX + 1)):
            _, report = self.send({"type": "reopen", "comment": bad})
            self.assertEqual(len(report["rejected"]), 1, repr(bad[:5]))

    def test_other_inputs_are_still_refused_for_an_aborted_quest(self):
        self.plan(accepted=False, status="aborted")
        _, report = self.send({"type": "accept"})
        self.assertEqual(len(report["rejected"]), 1)


class ReopenWiringTest(unittest.TestCase):
    def test_board_and_skill_know_reopen(self):
        board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        for needle in ("function reopenBlock(", "type: 'reopen'", "修正して再実行", "直したい内容（必須）", "reopenBlock(qd)"):
            self.assertIn(needle, board, needle)
        self.assertIn("`reopen`", (ROOT / "skills" / "quest" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("`reopen`", (ROOT / "docs" / "graph-format.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

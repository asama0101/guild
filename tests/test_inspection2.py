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


class ResultInputTest(unittest.TestCase):
    def plan(self):
        return {"quest": "Q001", "title": "t", "approved": True, "status": "active",
                "goals": [goal("G1", "waiting_user", kind="human", instruction="聞く")], "history": []}

    def test_bad_files_or_note_are_refused_before_the_state_moves(self):
        for extra in ({"files": 5}, {"files": ["a", 3]}, {"files": "a.txt"}, {"note": ["x"]}):
            plan = self.plan()
            plan["goals"][0].pop("class", None)
            with self.assertRaises(guild.GuildError, msg=str(extra)):
                guild.apply_input(plan, {"type": "result", "goal": "G1", "ok": True, **extra}, TR)
            self.assertEqual(plan["goals"][0]["state"], "waiting_user")

    def test_null_files_mean_none(self):
        plan = self.plan()
        guild.apply_input(plan, {"type": "result", "goal": "G1", "ok": True, "files": None}, TR)
        self.assertEqual(plan["goals"][0]["output"]["files"], [])

    def test_a_failed_report_write_is_a_warning_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            q = Path(guild.new_quest(root)["dir"])
            plan = self.plan()
            guild.save_json(q / "plan.json", plan)
            (q / "inbox").mkdir(exist_ok=True)
            (q / "inbox" / "r.json").write_text(json.dumps({"type": "result", "goal": "G1", "ok": True, "note": "済"}), encoding="utf-8")
            p = guild.load_plan(q / "plan.json")
            from unittest import mock
            with mock.patch.object(guild, "write_user_report", side_effect=OSError("ロック中")):
                report = guild.ingest(q / "plan.json", p, TR, commit=lambda: guild.save_json(q / "plan.json", p))
            self.assertEqual(len(report["applied"]), 1)
            self.assertTrue(report["warnings"])
            self.assertEqual(guild.load_plan(q / "plan.json")["goals"][0]["state"], "review")


class WebHostTest(unittest.TestCase):
    def test_hosts_that_cannot_be_answered_are_denied_without_a_letter(self):
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            for url in ("http://127.0.0.1/x", "http://localhost/", "http://[::1]/", "http://intranet/"):
                verdict, _ = webaccess.gate(gdir, url, "p")
                self.assertEqual(verdict, "deny", url)
            self.assertEqual(webaccess.pending(gdir), [])

    def test_japanese_domain_is_queued_as_punycode_and_can_be_answered(self):
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            webaccess.gate(gdir, "https://例え.jp/a", "p")
            dom = webaccess.pending(gdir)[0]["domain"]
            self.assertTrue(dom.startswith("xn--"), dom)
            data = webaccess.load(gdir)
            webaccess.apply(data, {"type": "web", "decisions": {dom: "allow"}})
            webaccess.save(gdir, data)
            self.assertEqual(webaccess.gate(gdir, "https://例え.jp/b", "p")[0], "allow")


class WebIngestOrderTest(unittest.TestCase):
    def test_answers_stay_in_the_inbox_when_saving_fails(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            inbox = gdir / ".work" / "web" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "1.json").write_text(json.dumps({"type": "web", "decisions": {"example.com": "allow"}}), encoding="utf-8")
            with mock.patch.object(webaccess, "save", side_effect=PermissionError("ロック中")):
                with self.assertRaises(PermissionError):
                    webaccess.ingest(gdir)
            self.assertTrue((inbox / "1.json").exists())
            self.assertFalse((inbox / "done").exists())
            report = webaccess.ingest(gdir)  # 次に、そのまま反映できる
            self.assertEqual(len(report["applied"]), 1)
            self.assertIn("example.com", webaccess.load(gdir)["allow"])


if __name__ == "__main__":
    unittest.main()

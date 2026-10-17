"""Phase 2（計画の精度）：adopt の計画検査（エラー／警告）、自己点検（brief）、あなたの作業量、再計画の差分。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402

TR = guild.load_transitions()
GUILD_PY = str(ROOT / "skills" / "quest" / "guild.py")
GOOD = {"viewpoint": "依頼の目的に答えているか", "pass_line": "結論が先頭にあり、出典が3件以上ある", "check": "成果物を開いて見出しと出典の数を数える"}


def goal(i, kind="auto", deps=(), **kw):
    t = {"id": i, "title": f"{i}をする", "kind": kind, "deps": list(deps), "criteria": dict(GOOD)}
    if kind == "auto":
        t["class"] = "wizard"
    t.update(kw)
    return t


def good_goals():
    return [goal("G1"), goal("G2", deps=["G1"], deliverable=True)]


BRIEF = {"intent": "競合の価格を比べて上司に渡す", "non_goals": ["価格交渉はしない"], "assumptions": ["対象は国内3社"],
         "risks": ["口コミ件数は取れない可能性がある"],
         "coverage": [{"requirement": "価格を比べる", "goals": ["G1", "G2"]}]}


class PlanQualityTest(unittest.TestCase):
    def q(self, goals, brief=BRIEF):
        plan = {"goals": goals}
        return guild.plan_quality(plan, brief)

    def test_clean_plan(self):
        errs, warns, brief = self.q(good_goals())
        self.assertEqual((errs, warns), ([], []))
        self.assertEqual(brief["intent"], BRIEF["intent"])

    def test_deliverable_must_be_exactly_one(self):
        self.assertTrue(any("deliverable" in e for e in self.q([goal("G1")])[0]))
        two = [goal("G1", deliverable=True), goal("G2", deliverable=True)]
        self.assertTrue(any("deliverable" in e for e in self.q(two)[0]))

    def test_human_needs_instruction(self):
        t = good_goals() + [goal("G3", kind="human", deps=["G2"])]
        self.assertTrue(any("G3" in e and "instruction" in e for e in self.q(t)[0]))
        t[2]["instruction"] = "メールを送ってください。"
        self.assertEqual(self.q(t)[0], [])

    def test_ambiguous_words_are_warnings_not_errors(self):
        t = good_goals()
        t[0]["criteria"]["pass_line"] = "適切にまとめられていること"
        errs, warns, _ = self.q(t)
        self.assertEqual(errs, [])
        self.assertTrue(any("G1" in w and "適切" in w for w in warns))

    def test_ambiguous_words_do_not_hit_other_words(self):
        t = good_goals()
        t[0]["criteria"]["pass_line"] = "不適切な表現がなく、三十分以内に読める長さである"
        self.assertEqual(self.q(t)[1], [])

    def test_instruction_must_be_a_string(self):
        t = good_goals() + [goal("G3", kind="human", deps=["G2"], instruction=5)]
        self.assertTrue(any("G3" in e for e in self.q(t)[0]))

    def test_non_object_criteria_is_an_error_not_a_crash(self):
        p = {"quest": "Q1", "title": "t", "approved": False, "status": "active",
             "goals": [dict(goal("G1"), criteria="abc", state="pending", retries=0, output=None)]}
        self.assertTrue(any("criteria" in e for e in guild.validate(p, TR)))

    def test_short_criteria_is_warning(self):
        t = good_goals()
        t[0]["criteria"]["check"] = "見る"
        self.assertTrue(any("G1" in w and "check" in w for w in self.q(t)[1]))

    def test_too_many_goals_is_warning(self):
        t = [goal(f"T{i}") for i in range(1, guild.MAX_GOALS + 2)]
        t[-1]["deliverable"] = True
        self.assertTrue(any("目標が" in w for w in self.q(t, None)[1]))

    def test_missing_brief_is_warning(self):
        errs, warns, brief = self.q(good_goals(), None)
        self.assertEqual(errs, [])
        self.assertIsNone(brief)
        self.assertTrue(any("自己点検" in w for w in warns))

    def test_coverage_unknown_goal_is_error(self):
        b = {**BRIEF, "coverage": [{"requirement": "r", "goals": ["G9"]}]}
        self.assertTrue(any("G9" in e for e in self.q(good_goals(), b)[0]))

    def test_uncovered_requirement_is_warning(self):
        b = {**BRIEF, "coverage": [{"requirement": "価格を比べる", "goals": []}]}
        self.assertTrue(any("価格を比べる" in w for w in self.q(good_goals(), b)[1]))

    def test_brief_shape_is_normalized(self):
        errs, warns, brief = self.q(good_goals(), {"intent": " 目的 ", "assumptions": "文字列"})
        self.assertEqual(brief["intent"], "目的")
        self.assertEqual(brief["assumptions"], [])
        self.assertEqual(errs, [])
        self.assertTrue(warns)  # coverage などが空


class WorkloadTest(unittest.TestCase):
    def test_workload_counts_human_goals_by_day(self):
        p = {"due": "2026-10-20", "goals": [
            goal("G1", scheduled="2026-10-17", due="2026-10-18"),
            goal("G2", kind="human", scheduled="2026-10-18", due="2026-10-19", instruction="x"),
            goal("G3", kind="human", scheduled="2026-10-18", due="2026-10-21", instruction="y")]}
        w = guild.workload(p)
        self.assertEqual(w["human"], 2)
        self.assertEqual(w["days"], {"2026-10-18": 2})
        self.assertEqual([i["id"] for i in w["items"]], ["G2", "G3"])
        self.assertEqual(w["over_deadline"], ["G3"])  # 依頼の締切(10-20)を超える

    def test_no_human(self):
        w = guild.workload({"goals": [goal("G1")]})
        self.assertEqual((w["human"], w["days"], w["items"], w["over_deadline"]), (0, {}, [], []))


class PlanDiffTest(unittest.TestCase):
    def test_diff(self):
        old = {"goals": [goal("G1"), goal("G2"), goal("G3")]}
        new = {"goals": [goal("G1"), goal("G2", criteria={**GOOD, "check": "別の確かめ方をする"}), goal("G4")]}
        d = guild.plan_diff(old, new, ["G1"])
        self.assertEqual([x["id"] for x in d["added"]], ["G4"])
        self.assertEqual([x["id"] for x in d["removed"]], ["G3"])
        self.assertEqual([x["id"] for x in d["changed"]], ["G2"])
        self.assertEqual(d["carried"], ["G1"])


class AdoptQualityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        (self.dir / "reports").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, goals, brief=BRIEF):
        d = {"quest": "Q1", "title": "題", "series": "試験", "goals": goals}
        if brief is not None:
            d["brief"] = brief
        (self.dir / "reports" / "plan-draft.json").write_text(json.dumps(d), encoding="utf-8")

    def test_adopt_stores_brief_check_and_workload(self):
        self.draft(good_goals() + [goal("G3", kind="human", deps=["G2"], instruction="送る")])
        guild.adopt(self.path, TR)
        p = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(p["brief"]["intent"], BRIEF["intent"])
        self.assertEqual(p["check"]["warnings"], [])
        self.assertEqual(p["workload"]["human"], 1)

    def test_adopt_rejects_plan_without_deliverable_and_writes_nothing(self):
        self.draft([goal("G1")])
        with self.assertRaises(guild.GuildError) as cm:
            guild.adopt(self.path, TR)
        self.assertIn("deliverable", str(cm.exception))
        self.assertFalse(self.path.exists())

    def test_adopt_keeps_warnings_in_plan(self):
        t = good_goals()
        t[0]["criteria"]["pass_line"] = "適切にまとまっていること"
        self.draft(t, None)
        guild.adopt(self.path, TR)
        p = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(any("適切" in w for w in p["check"]["warnings"]))
        self.assertTrue(any("自己点検" in w for w in p["check"]["warnings"]))
        self.assertIsNone(p["brief"])

    def test_replan_records_diff(self):
        self.draft(good_goals())
        guild.adopt(self.path, TR)
        p = json.loads(self.path.read_text(encoding="utf-8"))
        p["status"] = "replan"
        p["goals"][0]["state"] = "done"
        self.path.write_text(json.dumps(p), encoding="utf-8")
        self.draft(good_goals() + [goal("G3", deps=["G2"], title="足す")])
        d = guild.adopt(self.path, TR)
        self.assertEqual(d["carried"], ["G1"])
        p = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([x["id"] for x in p["replan_diff"]["added"]], ["G3"])
        self.assertEqual(p["replan_diff"]["carried"], ["G1"])

    def test_first_adopt_has_no_diff(self):
        self.draft(good_goals())
        guild.adopt(self.path, TR)
        self.assertNotIn("replan_diff", json.loads(self.path.read_text(encoding="utf-8")))

    def test_cli_error_is_readable(self):
        self.draft([goal("G1")])
        r = subprocess.run([sys.executable, GUILD_PY, "adopt", str(self.path)], capture_output=True, text=True,
                           encoding="utf-8")
        self.assertEqual(r.returncode, 1)
        self.assertIn("deliverable", r.stderr)


if __name__ == "__main__":
    unittest.main()

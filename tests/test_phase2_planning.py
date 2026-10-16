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


def todo(i, kind="auto", deps=(), **kw):
    t = {"id": i, "title": f"{i}をする", "kind": kind, "deps": list(deps), "criteria": dict(GOOD)}
    t.update(kw)
    return t


def good_todos():
    return [todo("T1"), todo("T2", deps=["T1"], deliverable=True)]


BRIEF = {"goal": "競合の価格を比べて上司に渡す", "non_goals": ["価格交渉はしない"], "assumptions": ["対象は国内3社"],
         "risks": ["口コミ件数は取れない可能性がある"],
         "coverage": [{"requirement": "価格を比べる", "todos": ["T1", "T2"]}]}


class PlanQualityTest(unittest.TestCase):
    def q(self, todos, brief=BRIEF):
        plan = {"todos": todos}
        return guild.plan_quality(plan, brief)

    def test_clean_plan(self):
        errs, warns, brief = self.q(good_todos())
        self.assertEqual((errs, warns), ([], []))
        self.assertEqual(brief["goal"], BRIEF["goal"])

    def test_deliverable_must_be_exactly_one(self):
        self.assertTrue(any("deliverable" in e for e in self.q([todo("T1")])[0]))
        two = [todo("T1", deliverable=True), todo("T2", deliverable=True)]
        self.assertTrue(any("deliverable" in e for e in self.q(two)[0]))

    def test_human_needs_instruction(self):
        t = good_todos() + [todo("T3", kind="human", deps=["T2"])]
        self.assertTrue(any("T3" in e and "instruction" in e for e in self.q(t)[0]))
        t[2]["instruction"] = "メールを送ってください。"
        self.assertEqual(self.q(t)[0], [])

    def test_ambiguous_words_are_warnings_not_errors(self):
        t = good_todos()
        t[0]["criteria"]["pass_line"] = "適切にまとめられていること"
        errs, warns, _ = self.q(t)
        self.assertEqual(errs, [])
        self.assertTrue(any("T1" in w and "適切" in w for w in warns))

    def test_short_criteria_is_warning(self):
        t = good_todos()
        t[0]["criteria"]["check"] = "見る"
        self.assertTrue(any("T1" in w and "check" in w for w in self.q(t)[1]))

    def test_too_many_todos_is_warning(self):
        t = [todo(f"T{i}") for i in range(1, guild.MAX_TODOS + 2)]
        t[-1]["deliverable"] = True
        self.assertTrue(any("Todo が" in w for w in self.q(t, None)[1]))

    def test_missing_brief_is_warning(self):
        errs, warns, brief = self.q(good_todos(), None)
        self.assertEqual(errs, [])
        self.assertIsNone(brief)
        self.assertTrue(any("自己点検" in w for w in warns))

    def test_coverage_unknown_todo_is_error(self):
        b = {**BRIEF, "coverage": [{"requirement": "r", "todos": ["T9"]}]}
        self.assertTrue(any("T9" in e for e in self.q(good_todos(), b)[0]))

    def test_uncovered_requirement_is_warning(self):
        b = {**BRIEF, "coverage": [{"requirement": "価格を比べる", "todos": []}]}
        self.assertTrue(any("価格を比べる" in w for w in self.q(good_todos(), b)[1]))

    def test_brief_shape_is_normalized(self):
        errs, warns, brief = self.q(good_todos(), {"goal": " 目的 ", "assumptions": "文字列"})
        self.assertEqual(brief["goal"], "目的")
        self.assertEqual(brief["assumptions"], [])
        self.assertEqual(errs, [])
        self.assertTrue(warns)  # coverage などが空


class WorkloadTest(unittest.TestCase):
    def test_workload_counts_human_todos_by_day(self):
        p = {"due": "2026-10-20", "todos": [
            todo("T1", scheduled="2026-10-17", due="2026-10-18"),
            todo("T2", kind="human", scheduled="2026-10-18", due="2026-10-19", instruction="x"),
            todo("T3", kind="human", scheduled="2026-10-18", due="2026-10-21", instruction="y")]}
        w = guild.workload(p)
        self.assertEqual(w["human"], 2)
        self.assertEqual(w["days"], {"2026-10-18": 2})
        self.assertEqual([i["id"] for i in w["items"]], ["T2", "T3"])
        self.assertEqual(w["over_deadline"], ["T3"])  # 依頼の締切(10-20)を超える

    def test_no_human(self):
        w = guild.workload({"todos": [todo("T1")]})
        self.assertEqual((w["human"], w["days"], w["items"], w["over_deadline"]), (0, {}, [], []))


class PlanDiffTest(unittest.TestCase):
    def test_diff(self):
        old = {"todos": [todo("T1"), todo("T2"), todo("T3")]}
        new = {"todos": [todo("T1"), todo("T2", criteria={**GOOD, "check": "別の確かめ方をする"}), todo("T4")]}
        d = guild.plan_diff(old, new, ["T1"])
        self.assertEqual([x["id"] for x in d["added"]], ["T4"])
        self.assertEqual([x["id"] for x in d["removed"]], ["T3"])
        self.assertEqual([x["id"] for x in d["changed"]], ["T2"])
        self.assertEqual(d["carried"], ["T1"])


class AdoptQualityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        (self.dir / "reports").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, todos, brief=BRIEF):
        d = {"quest": "Q1", "title": "題", "todos": todos}
        if brief is not None:
            d["brief"] = brief
        (self.dir / "reports" / "plan-draft.json").write_text(json.dumps(d), encoding="utf-8")

    def test_adopt_stores_brief_check_and_workload(self):
        self.draft(good_todos() + [todo("T3", kind="human", deps=["T2"], instruction="送る")])
        guild.adopt(self.path, TR)
        p = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(p["brief"]["goal"], BRIEF["goal"])
        self.assertEqual(p["check"]["warnings"], [])
        self.assertEqual(p["workload"]["human"], 1)

    def test_adopt_rejects_plan_without_deliverable_and_writes_nothing(self):
        self.draft([todo("T1")])
        with self.assertRaises(guild.GuildError) as cm:
            guild.adopt(self.path, TR)
        self.assertIn("deliverable", str(cm.exception))
        self.assertFalse(self.path.exists())

    def test_adopt_keeps_warnings_in_plan(self):
        t = good_todos()
        t[0]["criteria"]["pass_line"] = "適切にまとまっていること"
        self.draft(t, None)
        guild.adopt(self.path, TR)
        p = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(any("適切" in w for w in p["check"]["warnings"]))
        self.assertTrue(any("自己点検" in w for w in p["check"]["warnings"]))
        self.assertIsNone(p["brief"])

    def test_replan_records_diff(self):
        self.draft(good_todos())
        guild.adopt(self.path, TR)
        p = json.loads(self.path.read_text(encoding="utf-8"))
        p["status"] = "replan"
        p["todos"][0]["state"] = "done"
        self.path.write_text(json.dumps(p), encoding="utf-8")
        self.draft(good_todos() + [todo("T3", deps=["T2"], title="足す")])
        d = guild.adopt(self.path, TR)
        self.assertEqual(d["carried"], ["T1"])
        p = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([x["id"] for x in p["replan_diff"]["added"]], ["T3"])
        self.assertEqual(p["replan_diff"]["carried"], ["T1"])

    def test_first_adopt_has_no_diff(self):
        self.draft(good_todos())
        guild.adopt(self.path, TR)
        self.assertNotIn("replan_diff", json.loads(self.path.read_text(encoding="utf-8")))

    def test_cli_error_is_readable(self):
        self.draft([todo("T1")])
        r = subprocess.run([sys.executable, GUILD_PY, "adopt", str(self.path)], capture_output=True, text=True,
                           encoding="utf-8")
        self.assertEqual(r.returncode, 1)
        self.assertIn("deliverable", r.stderr)


if __name__ == "__main__":
    unittest.main()

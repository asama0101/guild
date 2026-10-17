"""AI 社員 Phase 4：effects、総合確認、納品物の構成と置き場（deliver_to）、整理。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402

CRIT = {"viewpoint": "v", "pass_line": "p", "check": "c"}
TR = guild.load_transitions()
SPEC = {"headings": ["結論", "詳細"], "reader": "部長"}


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def g(i, **kw):
    t = {"id": i, "title": f"{i}を調べる", "kind": "auto", "class": "wizard", "effects": "none", "deps": [], "criteria": dict(CRIT)}
    t.update(kw)
    return t


def quality(*goals):
    plan = {"goals": list(goals)}
    errs, warns, _ = guild.plan_quality(plan, None)
    return errs, warns


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.gdir = self.root / "guild"
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def overall(self, text="## 判定\n満たしている\n"):
        (self.q / "reports").mkdir(exist_ok=True)
        (self.q / "reports" / guild.OVERALL_REPORT).write_text(text, encoding="utf-8")


class EffectsTest(unittest.TestCase):
    def test_auto_goal_needs_a_valid_effects(self):
        base = g("G1", deliverable=True, deliverable_spec=SPEC)
        self.assertEqual(quality(base)[0], [])
        for bad in (None, "", "maybe", ["none"], 3):
            goal = dict(base, effects=bad)
            if bad is None:
                del goal["effects"]
            errs, _ = quality(goal)
            self.assertTrue(any("effects" in e for e in errs), bad)

    def test_external_and_irreversible_need_confirm(self):
        for e in ("external", "irreversible"):
            errs, _ = quality(g("G1", deliverable=True, deliverable_spec=SPEC, effects=e))
            self.assertTrue(any("confirm" in x for x in errs), e)
            errs, _ = quality(g("G1", deliverable=True, deliverable_spec=SPEC, effects=e, confirm=True))
            self.assertEqual(errs, [], e)

    def test_none_with_a_dangerous_word_is_only_a_warning(self):
        errs, warns = quality(g("G1", title="結果を部長に送信する", deliverable=True, deliverable_spec=SPEC))
        self.assertEqual(errs, [])
        self.assertTrue(any("effects が none" in w and "送信" in w for w in warns))
        errs, warns = quality(g("G1", deliverable=True, deliverable_spec=SPEC, criteria={"viewpoint": "v", "pass_line": "成果物を公開して確認する", "check": "c"}))
        self.assertTrue(any("公開" in w for w in warns))

    def test_none_without_dangerous_words_is_clean(self):
        errs, warns = quality(g("G1", deliverable=True, deliverable_spec=SPEC))
        self.assertEqual(errs, [])
        self.assertEqual([w for w in warns if "effects" in w or "deliverable_spec" in w], [])  # ほかの警告（短い合格基準・brief なし）は、この試験の対象外

    def test_human_goals_need_no_effects(self):
        human = {"id": "G2", "title": "確認する", "kind": "human", "deps": ["G1"], "criteria": dict(CRIT), "instruction": "やってください"}
        errs, _ = quality(g("G1"), dict(human), g("G3", deliverable=True, deliverable_spec=SPEC))
        self.assertEqual(errs, [])

    def test_confirm_with_none_is_allowed(self):
        errs, _ = quality(g("G1", deliverable=True, deliverable_spec=SPEC, confirm=True))
        self.assertEqual(errs, [])


class DeliverableSpecTest(unittest.TestCase):
    def test_missing_spec_warns(self):
        errs, warns = quality(g("G1", deliverable=True))
        self.assertEqual(errs, [])
        self.assertTrue(any("deliverable_spec" in w for w in warns))

    def test_bad_shapes_are_errors(self):
        for bad in ("見出し", [], {"headings": [], "reader": "x"}, {"headings": ["a"], "reader": ""}, {"headings": ["a", ""], "reader": "x"},
                    {"headings": "a", "reader": "x"}, {"headings": ["a"]}, {"headings": [1], "reader": "x"}):
            errs, _ = quality(g("G1", deliverable=True, deliverable_spec=bad))
            self.assertTrue(any("deliverable_spec" in e for e in errs), bad)

    def test_good_spec_is_clean(self):
        errs, warns = quality(g("G1", deliverable=True, deliverable_spec=SPEC))
        self.assertEqual(errs, [])
        self.assertEqual([w for w in warns if "effects" in w or "deliverable_spec" in w], [])  # ほかの警告（短い合格基準・brief なし）は、この試験の対象外


class OverallTest(Base):
    def test_overall_state(self):
        self.assertIsNone(guild.overall_state(self.q))
        for text, want in (("", None), ("## 判定\n", None), ("## 判定\n満たしている\n", "ok"), ("## 判定\n満たしている — 全部\n", "ok"),
                           ("## 判定\n不足あり\n## 不足\n要件 2\n", "gaps"), ("## 判定\nたぶん大丈夫\n", None), ("満たしている", None),
                           ("## 判定の補足\n満たしている\n", None)):
            self.overall(text)
            self.assertEqual(guild.overall_state(self.q), want, text)

    def plan(self):
        return {"quest": "Q001", "title": "t", "approved": True, "status": "active",
                "goals": [dict(g("G1"), state="done", retries=0, output=None)]}

    def test_awaiting_overall_then_accept(self):
        p = self.plan()
        v = guild.next_view(p, self.q)
        self.assertEqual((v["awaiting_overall"], v["awaiting_accept"], v["overall"]), (True, False, "none"))
        self.overall()
        v = guild.next_view(p, self.q)
        self.assertEqual((v["awaiting_overall"], v["awaiting_accept"], v["overall"]), (False, True, "ok"))
        self.overall("## 判定\n不足あり\n## 不足\nあ\n")
        v = guild.next_view(p, self.q)
        self.assertEqual((v["awaiting_accept"], v["overall"]), (True, "gaps"))  # 不足があっても、受け取りの手紙は出る（依頼主が決める）

    def test_not_awaiting_while_goals_remain_or_after_accept_or_when_aborted(self):
        p = self.plan()
        p["goals"][0]["state"] = "running"
        self.assertFalse(guild.next_view(p, self.q)["awaiting_overall"])
        p = self.plan()
        p["accepted"] = True
        self.assertFalse(guild.next_view(p, self.q)["awaiting_overall"])
        p = self.plan()
        p["status"] = "aborted"
        self.assertFalse(guild.next_view(p, self.q)["awaiting_overall"])

    def test_without_qdir_the_overall_check_is_skipped(self):
        v = guild.next_view(self.plan())
        self.assertEqual((v["awaiting_overall"], v["awaiting_accept"]), (False, True))

    def ingest_accept(self):
        write(self.q / "inbox" / "1-accept.json", {"type": "accept"})
        p = self.plan()
        guild.save_json(self.q / "plan.json", p)
        return p, guild.ingest(self.q / "plan.json", p, TR)

    def test_accept_is_refused_before_the_overall_check(self):
        p, r = self.ingest_accept()
        self.assertEqual(len(r["rejected"]), 1)
        self.assertIn("総合確認", r["rejected"][0]["reason"])
        self.assertFalse(p.get("accepted"))

    def test_accept_works_after_the_overall_check_even_with_gaps(self):
        self.overall("## 判定\n不足あり\n## 不足\nあ\n")
        p, r = self.ingest_accept()
        self.assertEqual(r["rejected"], [])
        self.assertTrue(p["accepted"])

    def test_replan_moves_the_old_overall_report_to_prev(self):
        self.overall()
        old = self.plan()
        old["status"] = "replan"
        guild.save_json(self.q / "plan.json", old)
        write(self.q / "reports" / "plan-draft.json", {"quest": "Q001", "title": "題", "series": "s", "goals": [g("G1", deliverable=True, deliverable_spec=SPEC)]})
        guild.adopt(self.q / "plan.json", TR)
        self.assertFalse((self.q / "reports" / guild.OVERALL_REPORT).exists())
        self.assertTrue(list((self.q / "prev").glob("*/reports/" + guild.OVERALL_REPORT)))
        self.assertIsNone(guild.overall_state(self.q))

    def test_receptionist_and_skill_describe_the_overall_check(self):
        r = (ROOT / "agents" / "receptionist.md").read_text(encoding="utf-8")
        for needle in ("総合確認", "overall-receptionist.md", "`plan.json` と、自分が書いた計画", "満たしている", "不足あり"):
            self.assertIn(needle, r, needle)
        s = (ROOT / "skills" / "quest" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("awaiting_overall", "model: sonnet", "overall-receptionist.md"):
            self.assertIn(needle, s, needle)


class DeliverToCheckTest(Base):
    def test_valid_paths_are_normalised(self):
        self.assertEqual(guild.check_deliver_to(self.q, "docs/reports"), "docs/reports")
        self.assertEqual(guild.check_deliver_to(self.q, " ./docs//reports/ "), "docs/reports")
        self.assertEqual(guild.check_deliver_to(self.q, "docs" + chr(92) + "reports"), "docs/reports")
        self.assertEqual(guild.check_deliver_to(self.q, "納品"), "納品")

    def test_bad_paths_are_errors(self):
        for bad in (None, "", "  ", 5, ["a"], "/etc", "C:/x", "c:x", "~/x", "../x", "a/../../x", "..", ".", "guild/out", "Guild/out", ".git/hooks",
                    "a/b:c", 'a/"b', "a/b?", "a/b*"):
            with self.assertRaises(guild.GuildError, msg=repr(bad)):
                guild.check_deliver_to(self.q, bad)

    def test_an_existing_file_is_not_a_folder(self):
        (self.root / "docs").write_text("file", encoding="utf-8")
        with self.assertRaises(guild.GuildError):
            guild.check_deliver_to(self.q, "docs")

    def test_adopt_stores_a_normalised_deliver_to_and_rejects_a_bad_one(self):
        d = {"quest": "Q001", "title": "題", "series": "s", "deliver_to": "./docs/reports/", "goals": [g("G1", deliverable=True, deliverable_spec=SPEC)]}
        write(self.q / "reports" / "plan-draft.json", d)
        guild.adopt(self.q / "plan.json", TR)
        self.assertEqual(json.loads((self.q / "plan.json").read_text(encoding="utf-8"))["deliver_to"], "docs/reports")
        (self.q / "plan.json").unlink()
        write(self.q / "reports" / "plan-draft.json", dict(d, deliver_to="../outside"))
        with self.assertRaises(guild.GuildError):
            guild.adopt(self.q / "plan.json", TR)
        self.assertFalse((self.q / "plan.json").exists())

    def test_plans_without_deliver_to_have_no_key(self):
        write(self.q / "reports" / "plan-draft.json", {"quest": "Q001", "title": "題", "series": "s", "goals": [g("G1", deliverable=True, deliverable_spec=SPEC)]})
        guild.adopt(self.q / "plan.json", TR)
        self.assertNotIn("deliver_to", json.loads((self.q / "plan.json").read_text(encoding="utf-8")))


class DeliverToPublishTest(Base):
    def done(self, deliver_to="docs/reports"):
        plan = {"quest": "Q001", "title": "週報", "series": "s", "approved": True, "status": "active", "accepted": True,
                **({"deliver_to": deliver_to} if deliver_to else {}),
                "goals": [dict(g("G1", deliverable=True), state="done", retries=0, output=None)]}
        guild.save_json(self.q / "plan.json", plan)
        out = self.q / "output" / "G1"
        out.mkdir(parents=True, exist_ok=True)
        (out / "a.md").write_text("本文", encoding="utf-8")
        return plan

    def test_publish_copies_to_both_places_and_records_it(self):
        self.done()
        r = guild.publish_deliverables(self.q)
        self.assertEqual(r["published"], ["Q001_週報.md"])
        self.assertEqual(r["delivered_to"], "docs/reports")
        self.assertEqual((self.gdir / "deliverables" / "Q001_週報.md").read_text(encoding="utf-8"), "本文")
        self.assertEqual((self.root / "docs" / "reports" / "Q001_週報.md").read_text(encoding="utf-8"), "本文")
        rec = json.loads((self.q / "delivered.json").read_text(encoding="utf-8"))
        self.assertEqual((rec["dir"], rec["files"]), ("docs/reports", ["Q001_週報.md"]))

    def test_publish_is_idempotent(self):
        self.done()
        guild.publish_deliverables(self.q)
        guild.publish_deliverables(self.q)
        self.assertEqual(sorted(p.name for p in (self.root / "docs" / "reports").iterdir()), ["Q001_週報.md"])

    def test_no_deliver_to_means_no_copy_and_no_record(self):
        self.done(deliver_to=None)
        r = guild.publish_deliverables(self.q)
        self.assertNotIn("delivered_to", r)
        self.assertFalse((self.q / "delivered.json").exists())
        self.assertFalse((self.root / "docs").exists())

    def test_unpublish_removes_only_the_recorded_files_of_this_quest(self):
        self.done()
        guild.publish_deliverables(self.q)
        mine = self.root / "docs" / "reports"
        (mine / "Q002_他の依頼.md").write_text("keep", encoding="utf-8")
        (mine / "メモ.md").write_text("keep", encoding="utf-8")
        guild.unpublish_deliverables(self.q)
        self.assertEqual(sorted(p.name for p in mine.iterdir()), ["Q002_他の依頼.md", "メモ.md"])
        self.assertFalse((self.q / "delivered.json").exists())
        self.assertFalse((self.gdir / "deliverables" / "Q001_週報.md").exists())

    def test_a_tampered_record_cannot_delete_outside_the_folder(self):
        self.done()
        guild.publish_deliverables(self.q)
        victim = self.root / "大事.md"
        victim.write_text("keep", encoding="utf-8")
        write(self.q / "delivered.json", {"dir": "docs/reports", "files": ["../../大事.md", "Q001_../x", "大事.md"]})
        guild.unpublish_deliverables(self.q)
        self.assertTrue(victim.exists())

    def test_a_broken_record_does_not_stop_unpublishing(self):
        self.done()
        guild.publish_deliverables(self.q)
        (self.q / "delivered.json").write_text("{", encoding="utf-8")
        guild.unpublish_deliverables(self.q)
        self.assertFalse((self.gdir / "deliverables" / "Q001_週報.md").exists())

    def test_replan_adopt_removes_the_copies(self):
        plan = self.done()
        guild.publish_deliverables(self.q)
        plan["status"] = "replan"
        plan["goals"][0]["state"] = "pending"
        guild.save_json(self.q / "plan.json", plan)
        write(self.q / "reports" / "plan-draft.json", {"quest": "Q001", "title": "題", "series": "s", "goals": [g("G1", deliverable=True, deliverable_spec=SPEC)]})
        guild.adopt(self.q / "plan.json", TR)
        self.assertEqual(list((self.root / "docs" / "reports").glob("Q001_*")), [])


class CleanupTest(Base):
    def test_plan_prev_json_is_no_longer_written(self):
        write(self.q / "reports" / "plan-draft.json", {"quest": "Q001", "title": "題", "series": "s", "goals": [g("G1", deliverable=True, deliverable_spec=SPEC)]})
        guild.adopt(self.q / "plan.json", TR)
        p = json.loads((self.q / "plan.json").read_text(encoding="utf-8"))
        p["status"] = "replan"
        guild.save_json(self.q / "plan.json", p)
        guild.adopt(self.q / "plan.json", TR)
        self.assertFalse((self.q / "plan.prev.json").exists())

    def test_close_removes_prev_and_backup_only_for_closed_quests(self):
        def mk(q, **kw):
            plan = {"quest": q.name, "title": "t", "approved": True, "status": "active", "goals": [dict(g("G1"), state="done", retries=0, output=None)], **kw}
            guild.save_json(q / "plan.json", plan)
            (q / "prev" / "20260101000000").mkdir(parents=True)
            (q / "prev" / "20260101000000" / "a.md").write_text("x", encoding="utf-8")
            (self.gdir / ".work" / "backup" / q.name).mkdir(parents=True)
        q2 = Path(guild.new_quest(self.root)["dir"])
        q3 = Path(guild.new_quest(self.root)["dir"])
        mk(self.q, accepted=True)
        mk(q2)
        mk(q3, status="aborted")
        r = guild.close_quests(self.root)
        self.assertEqual(r["removed"], [self.q.name, q3.name])
        self.assertFalse((self.q / "prev").exists())
        self.assertFalse((self.gdir / ".work" / "backup" / self.q.name).exists())
        self.assertTrue((q2 / "prev").exists())  # 進行中のものは残す
        self.assertTrue((self.gdir / ".work" / "backup" / q2.name).exists())
        self.assertFalse((q3 / "prev").exists())

    def test_close_without_backup_still_removes_prev(self):
        guild.save_json(self.q / "plan.json", {"quest": "Q001", "title": "t", "approved": True, "status": "active", "accepted": True,
                                              "goals": [dict(g("G1"), state="done", retries=0, output=None)]})
        (self.q / "prev" / "x").mkdir(parents=True)
        guild.close_quests(self.root)
        self.assertFalse((self.q / "prev").exists())


class BoardWiringTest(unittest.TestCase):
    BOARD = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")

    def test_board_shows_overall_effects_spec_and_deliver_to(self):
        for needle in ("const OVERALL_REPORT = 'overall-receptionist.md'", "d.overallPending", "'総合確認中'", "function overallBlock(qd)", "overallBlock(qd),",
                       "t.effects === 'external' || t.effects === 'irreversible'", "納品物の構成", "p.deliver_to", "不足があります", "自動では直しません"):
            self.assertIn(needle, self.BOARD, needle)

    def test_the_accept_letter_waits_for_the_overall_report(self):
        self.assertIn("p.approved && d.allDone && !p.accepted && hasOverall", self.BOARD)


if __name__ == "__main__":
    unittest.main()

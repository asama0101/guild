"""board.py のテスト（実際の vault は触らない）。"""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "skills" / "quest" / "board.py"
_spec = importlib.util.spec_from_file_location("board", _SRC)
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)

NOW = datetime(2026, 10, 6, 12, 0)


def _board(**kw):
    b = {"vault": "v", "max_active": 4, "studies": [], "quests": [], "questions": [], "notices": [],
         "profile": []}
    b.update(kw)
    return b


def _done_quest(qid, time, **kw):
    q = {"id": qid, "title": "t", "status": "達成", "study": "", "depends_on": [],
         "log": [{"time": time, "who": "guildmaster", "edge": "鑑定中→達成", "text": "ok"}]}
    q.update(kw)
    return q


class TestIds(unittest.TestCase):
    def test_next_and_reserve(self):
        b = _board(quests=[{"id": "Q3"}], questions=[{"id": "A7", "feedback_id": "F2", "interview_id": "I4"}])
        self.assertEqual(bd.next_id(b, "Q"), "Q4")
        self.assertEqual(bd.next_id(b, "F"), "F3")
        self.assertEqual(bd.next_id(b, "I"), "I5")
        self.assertEqual(bd.add_quest(b, {"title": "a"}), "Q4")
        self.assertEqual(bd.add_quest(b, {"title": "b"}), "Q5")

    def test_unknown_prefix(self):
        with self.assertRaises(bd.BoardError):
            bd.next_id(_board(), "X")

    def test_add_quest_attaches_to_study(self):
        b = _board()
        sid = bd.add_study(b, {"title": "研究"})
        qid = bd.add_quest(b, {"title": "q", "study": sid})
        self.assertEqual(b["studies"][0]["quests"], [qid])
        self.assertEqual(b["quests"][0]["retries"], 0)

    def test_add_quest_bad_status(self):
        with self.assertRaises(bd.BoardError):
            bd.add_quest(_board(), {"status": "なぞ"})


class TestStatus(unittest.TestCase):
    def test_quest_edge_logged(self):
        b = _board()
        qid = bd.add_quest(b, {"status": "受付済"})
        bd.set_status(b, qid, "冒険中", "出発", now=NOW)
        q = b["quests"][0]
        self.assertEqual(q["status"], "冒険中")
        self.assertEqual(q["log"][-1], {"time": "2026-10-06 12:00", "who": "guildmaster",
                                        "edge": "受付済→冒険中", "text": "出発"})

    def test_study_log_has_no_edge(self):
        b = _board()
        sid = bd.add_study(b, {})
        bd.set_status(b, sid, "承認待ち", "計画ができた", now=NOW)
        self.assertNotIn("edge", b["studies"][0]["log"][-1])

    def test_rejects_bad_state_and_unknown_id(self):
        b = _board()
        qid = bd.add_quest(b, {})
        with self.assertRaises(bd.BoardError):
            bd.set_status(b, qid, "承認待ち", "")
        with self.assertRaises(bd.BoardError):
            bd.set_status(b, "Q99", "冒険中", "")

    def test_set_field_and_delete(self):
        b = _board()
        qid = bd.add_quest(b, {})
        bd.set_field(b, qid, "retries", 2)
        self.assertEqual(b["quests"][0]["retries"], 2)
        bd.set_field(b, qid, "retries", None)
        self.assertNotIn("retries", b["quests"][0])

    def test_study_priority_validated(self):
        b = _board()
        sid = bd.add_study(b, {})
        with self.assertRaises(bd.BoardError):
            bd.set_field(b, sid, "priority", "急ぎ")
        bd.set_field(b, sid, "priority", "保留")
        self.assertEqual(b["studies"][0]["priority"], "保留")

    def test_set_top_refuses_lists(self):
        with self.assertRaises(bd.BoardError):
            bd.set_top(_board(), "quests", [])


class TestQuestionsAndNotices(unittest.TestCase):
    def test_answer_and_close(self):
        b = _board()
        a1 = bd.add_question(b, {"quest_id": "Q1"})
        a2 = bd.add_question(b, {"quest_id": "Q1"})
        a3 = bd.add_question(b, {"quest_id": "Q2"})
        bd.answer_question(b, a1, "はい", "")
        self.assertEqual(bd.close_questions(b, quest="Q1"), 1)
        self.assertEqual([q["status"] for q in b["questions"]], ["回答済", "回答済", "未回答"])
        self.assertEqual(b["questions"][1]["answer"], "取り消し")

    def test_notice_limit_and_order(self):
        b = _board()
        for i in range(25):
            bd.add_notice(b, f"n{i}")
        self.assertEqual(len(b["notices"]), 20)
        self.assertEqual(b["notices"][0]["text"], "n24")
        bd.add_notice(b, "x", stops=["止まり"])
        self.assertEqual(b["notices"][0]["stops"], ["止まり"])


class TestSummary(unittest.TestCase):
    def test_summary_drops_heavy_fields(self):
        b = _board(quests=[{"id": "Q1", "title": "あ" * 50, "status": "達成", "result": "長い結果", "log": [1],
                            "detail": "くわしく"}],
                   questions=[{"id": "A1", "status": "回答済"}, {"id": "A2", "status": "未回答", "kind": "question",
                                                               "quest_id": "Q1", "text": "長い"}])
        s = bd.summary(b)
        self.assertEqual(len(s["quests"][0]["title"]), 30)
        self.assertNotIn("result", s["quests"][0])
        self.assertNotIn("log", s["quests"][0])
        self.assertEqual(s["open_questions"], [{"id": "A2", "kind": "question", "quest_id": "Q1"}])
        self.assertEqual(s["answered_questions"], 1)


class TestApplySimple(unittest.TestCase):
    def _req(self, d, name, obj):
        (d / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_setting_newest_wins_and_moves(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self._req(d, "M20261006100000.json", {"kind": "setting", "key": "max_active", "value": 2, "posted": "2026-10-06 10:00"})
            self._req(d, "M20261006110000.json", {"kind": "setting", "key": "max_active", "value": 6, "posted": "2026-10-06 11:00"})
            b = _board()
            msgs = bd.apply_simple(b, d, now=NOW)
            self.assertEqual(b["max_active"], 6)
            self.assertEqual(msgs, ["同時数を 6 件にした"])
            self.assertEqual(list(d.glob("*.json")), [])
            self.assertEqual(len(list((d / "済").glob("*.json"))), 2)

    def test_setting_out_of_range_not_applied(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self._req(d, "M1.json", {"kind": "setting", "key": "max_active", "value": 12, "posted": "x"})
            self._req(d, "M2.json", {"kind": "setting", "key": "other", "value": 1, "posted": "x"})
            self._req(d, "M3.json", {"kind": "setting", "key": "max_active", "value": True, "posted": "y"})
            b = _board()
            bd.apply_simple(b, d, now=NOW)
            self.assertEqual(b["max_active"], 4)
            self.assertEqual(list(d.glob("*.json")), [])

    def test_study_priority(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            b = _board(studies=[{"id": "S1", "status": "進行中", "priority": "通常", "log": []},
                                {"id": "S2", "status": "達成", "priority": "通常", "log": []}])
            self._req(d, "S20261006100000.json", {"kind": "study_priority", "target": "S1", "priority": "優先", "posted": "a"})
            self._req(d, "S20261006100001.json", {"kind": "study_priority", "target": "S2", "priority": "保留", "posted": "a"})
            self._req(d, "S20261006100002.json", {"kind": "study_priority", "target": "S9", "priority": "保留", "posted": "a"})
            msgs = bd.apply_simple(b, d, now=NOW)
            self.assertEqual(b["studies"][0]["priority"], "優先")
            self.assertEqual(b["studies"][1]["priority"], "通常")
            self.assertEqual(len(msgs), 3)
            self.assertEqual(b["studies"][0]["log"][-1]["who"], "guildmaster")
            self.assertEqual(list(d.glob("*.json")), [])

    def test_leaves_other_kinds_and_broken_files(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self._req(d, "R1.json", {"kind": "quest", "title": "x"})
            (d / "bad.json").write_text("{", encoding="utf-8")
            self.assertEqual(bd.apply_simple(_board(), d, now=NOW), [])
            self.assertEqual(sorted(p.name for p in d.glob("*.json")), ["R1.json", "bad.json"])

    def test_done_name_collision(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "済").mkdir()
            (d / "済" / "M1.json").write_text("{}", encoding="utf-8")
            self._req(d, "M1.json", {"kind": "setting", "key": "max_active", "value": 3, "posted": "x"})
            bd.apply_simple(_board(), d, now=NOW)
            self.assertTrue((d / "済" / "M1-2.json").exists())

    def test_no_dir(self):
        self.assertEqual(bd.apply_simple(_board(), "/no/such/dir"), [])


class TestArchive(unittest.TestCase):
    OLD = "2026-08-01 10:00"
    NEW = "2026-10-01 10:00"

    def test_old_standalone_moves_and_recent_stays(self):
        b = _board(quests=[_done_quest("Q1", self.OLD), _done_quest("Q2", self.NEW),
                           {"id": "Q3", "status": "冒険中", "log": [{"time": self.OLD}]}],
                   questions=[{"id": "A1", "quest_id": "Q1", "status": "回答済"},
                              {"id": "A2", "quest_id": "Q1", "status": "未回答"},
                              {"id": "A3", "status": "回答済"}])
        moved = bd.archive(b, 30, now=NOW)
        self.assertEqual([q["id"] for q in moved["quests"]], ["Q1"])
        self.assertEqual([q["id"] for q in b["quests"]], ["Q2", "Q3"])
        self.assertEqual([a["id"] for a in moved["questions"]], ["A1"])
        self.assertEqual([a["id"] for a in b["questions"]], ["A2", "A3"])

    def test_numbers_do_not_go_back(self):
        b = _board(quests=[_done_quest("Q5", self.OLD)])
        bd.archive(b, 30, now=NOW)
        self.assertEqual(bd.add_quest(b, {}), "Q6")

    def test_study_moves_with_its_quests(self):
        s = {"id": "S1", "status": "達成", "quests": ["Q1", "Q2"],
             "log": [{"time": self.OLD, "who": "alchemist", "text": "x"}]}
        b = _board(studies=[s], quests=[_done_quest("Q1", self.OLD, study="S1"),
                                        _done_quest("Q2", self.OLD, study="S1", status="中止")])
        moved = bd.archive(b, 30, now=NOW)
        self.assertEqual(len(moved["studies"]), 1)
        self.assertEqual(b["quests"], [])

    def test_study_quest_alone_never_moves(self):
        s = {"id": "S1", "status": "進行中", "quests": ["Q1"], "log": []}
        b = _board(studies=[s], quests=[_done_quest("Q1", self.OLD, study="S1")])
        bd.archive(b, 30, now=NOW)
        self.assertEqual(len(b["quests"]), 1)

    def test_prerequisite_of_live_quest_stays(self):
        b = _board(quests=[_done_quest("Q1", self.OLD),
                           {"id": "Q2", "status": "受付済", "depends_on": ["Q1"], "log": []}])
        moved = bd.archive(b, 30, now=NOW)
        self.assertEqual(moved["quests"], [])
        self.assertEqual(len(b["quests"]), 2)

    def test_prerequisite_keeps_whole_study(self):
        s = {"id": "S1", "status": "達成", "quests": ["Q1", "Q2"], "log": [{"time": self.OLD}]}
        b = _board(studies=[s], quests=[_done_quest("Q1", self.OLD, study="S1"),
                                        _done_quest("Q2", self.OLD, study="S1"),
                                        {"id": "Q3", "status": "受付済", "depends_on": ["Q1"], "log": []}])
        moved = bd.archive(b, 30, now=NOW)
        self.assertEqual(moved["studies"], [])
        self.assertEqual(len(b["quests"]), 3)

    def test_append_archive_accumulates(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "board-archive.json"
            bd.append_archive(p, {"quests": [{"id": "Q1"}], "studies": [], "questions": []})
            bd.append_archive(p, {"quests": [{"id": "Q2"}], "studies": [], "questions": []})
            self.assertEqual([q["id"] for q in json.loads(p.read_text(encoding="utf-8"))["quests"]], ["Q1", "Q2"])


class TestGlossaryIndex(unittest.TestCase):
    def test_parse(self):
        al, m = bd.parse_term_note("---\ntype: term\naliases: [iBGP, 'Internal BGP']\n---\n# 内部 BGP\n\n同じ AS の中の BGP。\n")
        self.assertEqual(al, ["iBGP", "Internal BGP"])
        self.assertEqual(m, "同じ AS の中の BGP。")

    def test_parse_without_frontmatter(self):
        self.assertEqual(bd.parse_term_note("# x\n\n意味\n"), ([], "意味"))

    def test_index_skips_itself_and_escapes_pipes(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "A.md").write_text("---\naliases: [a|b]\n---\n# A\n\nx | y\n", encoding="utf-8")
            bd.write_glossary_index(d)
            first = (d / "用語集.md").read_text(encoding="utf-8")
            self.assertIn("| [[A]] | a/b | x / y |", first)
            bd.write_glossary_index(d)  # 索引自身を拾わない
            self.assertEqual(first, (d / "用語集.md").read_text(encoding="utf-8"))

    def test_empty_glossary(self):
        with tempfile.TemporaryDirectory() as t:
            text = bd.build_glossary_index(Path(t))
            self.assertIn("| 用語 | 別名 | 意味 |", text)


class TestCli(unittest.TestCase):
    def test_roundtrip_via_run(self):
        with tempfile.TemporaryDirectory() as t:
            sysd = Path(t)
            (sysd / "board.json").write_text(json.dumps(_board(), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(bd.run(["add-quest", '{"title": "テスト"}'], sys_dir=sysd), 0)
            self.assertEqual(bd.run(["set-status", "Q1", "冒険中", "--text", "出発"], sys_dir=sysd), 0)
            b = json.loads((sysd / "board.json").read_text(encoding="utf-8"))
            self.assertEqual(b["quests"][0]["status"], "冒険中")
            self.assertEqual(b["last_ids"]["Q"], 1)
            self.assertTrue(b["updated"])
            self.assertEqual(list(sysd.glob(".board-*.tmp")), [])

    def test_broken_json_is_reported(self):
        with tempfile.TemporaryDirectory() as t:
            sysd = Path(t)
            (sysd / "board.json").write_text("{", encoding="utf-8")
            with self.assertRaises(bd.BoardError):
                bd.run(["get", "--summary"], sys_dir=sysd)

    def test_archive_command_writes_files(self):
        with tempfile.TemporaryDirectory() as t:
            sysd = Path(t)
            old = (datetime.now() - timedelta(days=40)).strftime(bd.TIME_FMT)
            (sysd / "board.json").write_text(json.dumps(_board(quests=[_done_quest("Q1", old)]), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(bd.run(["archive", "--days", "30"], sys_dir=sysd), 0)
            self.assertTrue((sysd / "board-archive.json").exists())
            self.assertEqual(json.loads((sysd / "board.json").read_text(encoding="utf-8"))["quests"], [])


if __name__ == "__main__":
    unittest.main()

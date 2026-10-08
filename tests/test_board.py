"""board.py のテスト（実際の vault は触らない）。"""
import contextlib
import hashlib
import importlib.util
import io
import json
import functools
import os
import signal
import tempfile
import unittest
from unittest import mock
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
        self.assertEqual(s["latest_stops"], [])
        b["notices"] = [{"text": "x", "stops": ["Q3 は許可待ち"]}]
        self.assertEqual(bd.summary(b)["latest_stops"], ["Q3 は許可待ち"])


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

    def test_crawl_settings_applied(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self._req(d, "M1.json", {"kind": "setting", "key": "crawl_depth", "value": 3, "posted": "x"})
            self._req(d, "M2.json", {"kind": "setting", "key": "crawl_limit", "value": 100, "posted": "x"})
            b = _board()
            msgs = bd.apply_simple(b, d, now=NOW)
            self.assertEqual((b["crawl_depth"], b["crawl_limit"]), (3, 100))
            self.assertIn("巡回の深さを 3 にした", msgs)
            self.assertIn("巡回の最大ページ数を 100 にした", msgs)
            self.assertEqual(bd.summary(b)["crawl_depth"], 3)

    def test_crawl_settings_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            for i, (k, v) in enumerate([("crawl_depth", 0), ("crawl_depth", 6), ("crawl_depth", True),
                                        ("crawl_depth", "3"), ("crawl_limit", 0), ("crawl_limit", 101),
                                        ("crawl_limit", True), ("crawl_limit", "5")]):
                sub = d / str(i)
                sub.mkdir()
                self._req(sub, "M1.json", {"kind": "setting", "key": k, "value": v, "posted": "x"})
                b = _board()
                msgs = bd.apply_simple(b, sub, now=NOW)
                self.assertNotIn(k, b)
                self.assertIn("受け付けられない", msgs[0])

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


# ---------- 資料庫 ----------

def _env(d, with_dir=True):
    """(vault, sysd, adir, board) を作る。assets_dir は vault 相対。"""
    vault = Path(d)
    sysd = vault / "guild" / ".system"
    (sysd / "requests").mkdir(parents=True)
    adir = vault / "guild" / "50_assets"
    adir.mkdir(parents=True)
    board = _board()
    if with_dir:
        board["assets_dir"] = "guild/50_assets"
    (sysd / "board.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    return vault, sysd, adir, board


def _note(adir, nid, status="候補", sha=None, source=None, **extra):
    lines = ["type: asset", f"status: {status}", "targets: sw1, sw2", "kind: 機器",
             f"source: {source or nid + '.xlsx'}", "version: v1", "date: 2026-10-01",
             f"sha256: {sha or hashlib.sha256(nid.encode()).hexdigest()}", "locator: シート"]
    lines += [f"{k}: {v}" for k, v in extra.items()]
    body = "| 項目 | 値 | 出典箇所 |\n|---|---|---|\n| a | 1 | B3 |\n| b | x/y | C4 |\n"
    if extra.get("conflict"):
        body += "\n## 食い違い\n| 項目 | 旧 | 新 |\n|---|---|---|\n| ip | 1 | 2 |\n"
    (adir / f"{nid}.md").write_text("---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8")


def _st(adir, nid):
    return bd.parse_frontmatter((adir / f"{nid}.md").read_text(encoding="utf-8"))[0]["status"]


def _dec(sysd, name, note, action, posted="2026-10-06 12:00"):
    (sysd / "requests" / f"{name}.json").write_text(
        json.dumps({"kind": "asset_decision", "note": note, "action": action, "posted": posted}), encoding="utf-8")


def _trashed(adir):
    return sorted(p.name for p in (adir / "ゴミ箱").glob("*.md")) if (adir / "ゴミ箱").is_dir() else []


def _cli(argv, sysd):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = bd.run(argv, sys_dir=sysd, now=NOW)
    return code, out.getvalue()


class TestFrontmatter(unittest.TestCase):
    def test_parse(self):
        meta, body = bd.parse_frontmatter("---\ntype: asset\nlocator:  a: b  \n---\n本文\n")
        self.assertEqual(meta, {"type": "asset", "locator": "a: b"})
        self.assertEqual(body, "本文\n")
        self.assertEqual(bd.parse_frontmatter("本文だけ"), ({}, "本文だけ"))

    def test_resolve_assets_dir(self):
        sysd = Path("/v/guild/.system")
        self.assertEqual(bd.resolve_assets_dir({"assets_dir": "guild/50_assets"}, sysd), Path("/v/guild/50_assets"))
        self.assertEqual(bd.resolve_assets_dir({"assets_dir": "/v/guild/x"}, sysd), Path("/v/guild/x"))
        self.assertIsNone(bd.resolve_assets_dir({}, sysd))
        self.assertIn("assets_dir", bd.summary({"assets_dir": "x"}))


class TestAssetsCheck(unittest.TestCase):
    def _file(self, d, name, data=b"abc"):
        f = Path(d) / "in" / name
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(data)
        return f, hashlib.sha256(data).hexdigest()

    def test_four_states_and_priority(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            fa, ha = self._file(d, "a.xlsx", b"A")
            fb, hb = self._file(d, "b.xlsx", b"B")
            fc, hc = self._file(d, "c.xlsx", b"C")
            fd_, hd = self._file(d, "d.xlsx", b"D")
            fe, he = self._file(d, "e.xlsx", b"E")
            _note(adir, "a-x", "置換済", sha=ha, source="a.xlsx")  # 置換済でも registered
            _note(adir, "b-old", "確定", sha="0" * 64, source="b.xlsx")  # 同名別ハッシュ
            _note(adir, "c-x", "候補", sha=hc, source="c.xlsx")
            (adir / "ゴミ箱").mkdir()
            _note(adir / "ゴミ箱", "e-t", sha=he, source="e.xlsx")  # ゴミ箱に同ハッシュ
            _note(adir, "e-live", "確定", sha="1" * 64, source="e.xlsx")  # さらに同名別ハッシュ → trashed が勝つ
            _note(adir / "ゴミ箱", "c-t", sha=hc, source="c.xlsx")  # 生存と両方 → registered が勝つ
            r = {x["file"]: x for x in bd.check_assets([fa, fb, fc, fd_, fe], adir)}
            self.assertEqual((r[str(fa)]["state"], r[str(fa)]["note"]), ("registered", "a-x"))
            self.assertEqual((r[str(fb)]["state"], r[str(fb)]["note"]), ("changed", "b-old"))
            self.assertEqual(r[str(fc)]["state"], "registered")
            self.assertEqual((r[str(fd_)]["state"], r[str(fd_)]["note"]), ("new", None))
            self.assertEqual(r[str(fe)]["state"], "trashed")
            self.assertEqual(r[str(fa)]["sha256"], ha)

    def test_md_copy_excluded_and_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, adir, _ = _env(d)
            fx, _ = self._file(d, "s.xlsx")
            fm, _ = self._file(d, "s.md")
            fo, _ = self._file(d, "other.md")
            r = bd.check_assets([fx, fm, fo, Path(d) / "in" / "nothing.pdf"], adir)
            self.assertEqual([Path(x["file"]).name for x in r], ["s.xlsx", "other.md", "nothing.pdf"])
            self.assertEqual(r[-1]["state"], "unreadable")

    def test_md_copy_excluded_for_docx_and_pptx(self):
        """R1: 同名の .docx / .pptx がある .md は写しなので対象外（.xlsx と同じ扱い）。"""
        with tempfile.TemporaryDirectory() as d:
            _, _, adir, _ = _env(d)
            fd_, _ = self._file(d, "d.docx")
            fdm, _ = self._file(d, "d.md")
            fp, _ = self._file(d, "p.pptx")
            fpm, _ = self._file(d, "p.md")
            r = bd.check_assets([fd_, fdm, fp, fpm], adir)
            self.assertEqual([Path(x["file"]).name for x in r], ["d.docx", "p.pptx"])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            f, h = self._file(d, "z.xlsx")
            code, out = _cli(["assets-check", str(f)], sysd)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)[0]["state"], "new")


class TestAssetsApply(unittest.TestCase):
    def _case(self, action, status, conflict):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            extra = {"conflict": "yes"} if conflict else {}
            _note(adir, "n-1", status, **extra)
            before = (adir / "n-1.md").read_bytes()
            _dec(sysd, "D20261006120000", "n-1", action)
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(list((sysd / "requests").glob("D*.json")), [])
            self.assertEqual(len(list((sysd / "requests" / "済").glob("D*.json"))), 1)
            if _trashed(adir):
                return "trash", None
            same = (adir / "n-1.md").read_bytes() == before
            return ("unchanged" if same else _st(adir, "n-1")), None

    def test_transition_table(self):
        rows = [
            ("approve", "候補", False, "確定"), ("approve", "候補", True, "unchanged"),
            ("overwrite_ok", "候補", True, "確定"), ("overwrite_ng", "候補", True, "trash"),
            ("reject", "候補", False, "trash"), ("reject", "候補", True, "trash"),
            ("trash", "候補", False, "trash"), ("trash", "確定", False, "trash"), ("trash", "置換済", False, "trash"),
            ("approve", "確定", False, "unchanged"), ("reject", "確定", False, "unchanged"),
            ("overwrite_ok", "確定", True, "unchanged"), ("overwrite_ng", "確定", True, "unchanged"),
            ("approve", "置換済", False, "unchanged"), ("reject", "置換済", False, "unchanged"),
            ("overwrite_ok", "候補", False, "unchanged"), ("overwrite_ng", "候補", False, "unchanged"),
            ("bogus", "候補", False, "unchanged"),
        ]
        for action, status, conflict, want in rows:
            with self.subTest(action=action, status=status, conflict=conflict):
                self.assertEqual(self._case(action, status, conflict)[0], want)

    def test_approve_conflict_message(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1", conflict="yes")
            _dec(sysd, "D20261006120000", "n-1", "approve")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertTrue(any("上書き OK/NG" in m for m in msgs))

    def test_supersedes(self):
        for action, new_conflict, old_after in (("approve", False, "置換済"), ("overwrite_ok", True, "置換済"),
                                                ("overwrite_ng", True, "確定")):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as d:
                _, sysd, adir, board = _env(d)
                _note(adir, "old-1", "確定")
                _note(adir, "new-2", supersedes="old-1", **({"conflict": "yes"} if new_conflict else {}))
                _dec(sysd, "D20261006120000", "new-2", action)
                bd.apply_assets(board, sysd / "requests", sysd, NOW)
                self.assertEqual(_st(adir, "old-1"), old_after)

    def test_supersedes_missing_or_not_confirmed(self):
        for old in (None, "置換済", "候補"):
            with self.subTest(old=old), tempfile.TemporaryDirectory() as d:
                _, sysd, adir, board = _env(d)
                if old:
                    _note(adir, "old-1", old)
                _note(adir, "new-2", supersedes="old-1")
                _dec(sysd, "D20261006120000", "new-2", "approve")
                msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
                self.assertEqual(_st(adir, "new-2"), "確定")
                self.assertTrue(any("注意" in m for m in msgs))
                if old:
                    self.assertEqual(_st(adir, "old-1"), old)

    def test_supersedes_self_cycle_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1", supersedes="n-1")
            _dec(sysd, "D20261006120000", "n-1", "approve")
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(_st(adir, "n-1"), "確定")

    def test_trash_confirmed_warns(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1", "確定")
            _dec(sysd, "D20261006120000", "n-1", "trash")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertTrue(any("注意" in m for m in msgs))
            self.assertEqual(_trashed(adir), ["n-1__20261006120000.md"])

    def test_order_is_filename_not_posted(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            # ファイル名は approve が先、posted は reject が先。ファイル名順なら 確定→reject 拒否で残る
            _dec(sysd, "D20261006120000", "n-1", "approve", posted="2026-10-06 12:09")
            _dec(sysd, "D20261006120001", "n-1", "reject", posted="2026-10-06 12:00")
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(_st(adir, "n-1"), "確定")
            self.assertEqual(_trashed(adir), [])

    def test_order_same_second_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            _dec(sysd, "D20261006120000-2", "n-1", "reject")
            _dec(sysd, "D20261006120000", "n-1", "approve")
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(_st(adir, "n-1"), "確定")  # 無印が先

    def test_double_decision_second_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            _dec(sysd, "D20261006120000", "n-1", "trash")
            _dec(sysd, "D20261006120001", "n-1", "approve")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(len(msgs), 2)
            self.assertEqual(len(_trashed(adir)), 1)
            self.assertFalse((adir / "n-1.md").exists())
            self.assertEqual(len(list((sysd / "requests" / "済").glob("D*.json"))), 2)

    def test_idempotent_second_run(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            _dec(sysd, "D20261006120000", "n-1", "approve")
            self.assertTrue(bd.apply_assets(board, sysd / "requests", sysd, NOW))
            snap = (adir / "n-1.md").read_bytes()
            self.assertEqual(bd.apply_assets(board, sysd / "requests", sysd, NOW), [])
            self.assertEqual((adir / "n-1.md").read_bytes(), snap)

    def test_no_request_dir(self):
        self.assertEqual(bd.apply_assets({}, Path("/nonexistent/requests"), Path("/nonexistent/guild/.system"), NOW), [])


class TestAssetsTrustBoundary(unittest.TestCase):
    def test_bad_notes_rejected_and_moved(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            outside = adir.parent / "x.md"  # "../x" が指す先
            outside.write_text("keep", encoding="utf-8")
            bads = ["../x", "/etc/passwd", "a\0b", "nope", "a\\b", "", 123, None, ["n-1"], "n-1.md", "n-1/"]
            for i, bad in enumerate(bads):
                (sysd / "requests" / f"D2026100612000{i:02d}.json").write_text(
                    json.dumps({"kind": "asset_decision", "note": bad, "action": "trash"}), encoding="utf-8")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(len(msgs), len(bads))
            self.assertEqual(_st(adir, "n-1"), "候補")
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")
            self.assertEqual(_trashed(adir), [])
            self.assertEqual(list((sysd / "requests").glob("D*.json")), [])
            self.assertEqual(len(list((sysd / "requests" / "済").glob("D*.json"))), len(bads))

    def test_broken_and_foreign_requests_moved(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            (sysd / "requests" / "D20261006120000.json").write_text("{", encoding="utf-8")
            (sysd / "requests" / "D20261006120001.json").write_text("[1]", encoding="utf-8")
            (sysd / "requests" / "D20261006120002.json").write_text(json.dumps({"kind": "other"}), encoding="utf-8")
            (sysd / "requests" / "M20261006120003.json").write_text("{}", encoding="utf-8")  # D 以外は触らない
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(len(msgs), 3)
            self.assertEqual([p.name for p in (sysd / "requests").glob("*.json")], ["M20261006120003.json"])

    def test_trash_cli_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1")
            (adir.parent / "x.md").write_text("keep", encoding="utf-8")
            for bad in ("../x", "/etc/passwd", "nope"):
                with self.assertRaises(bd.BoardError):
                    _cli(["assets-trash", "n-1", bad], sysd)
            self.assertTrue((adir / "n-1.md").exists())  # 一部だけ動かさない
            self.assertTrue((adir.parent / "x.md").exists())


class TestAssetsAuto(unittest.TestCase):
    def _run(self, old_status="確定", **new_extra):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "old-1", old_status)
            _note(adir, "new-2", supersedes="old-1", **new_extra)
            bd.write_assets_index(adir, sysd, NOW)
            return _st(adir, "new-2"), _st(adir, "old-1")

    def test_promoted_when_all_met(self):
        self.assertEqual(self._run(auto="minor"), ("確定", "置換済"))

    def test_not_promoted_without_auto(self):
        self.assertEqual(self._run(), ("候補", "確定"))

    def test_not_promoted_with_conflict(self):
        self.assertEqual(self._run(auto="minor", conflict="yes"), ("候補", "確定"))

    def test_not_promoted_when_old_not_confirmed(self):
        self.assertEqual(self._run(old_status="候補", auto="minor"), ("候補", "候補"))
        self.assertEqual(self._run(old_status="置換済", auto="minor"), ("候補", "置換済"))

    def test_not_promoted_when_old_missing(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "new-2", supersedes="gone-9", auto="minor")
            bd.write_assets_index(adir, sysd, NOW)
            self.assertEqual(_st(adir, "new-2"), "候補")

    def test_promoted_with_no_decisions(self):
        """決定が 0 件でも、昇格対象（auto: minor の候補）は昇格する。"""
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "old-1", "確定")
            _note(adir, "new-2", supersedes="old-1", auto="minor")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(len(msgs), 1)
            self.assertEqual((_st(adir, "new-2"), _st(adir, "old-1")), ("確定", "置換済"))

    def test_promoted_at_apply_start(self):
        """冒頭の昇格だけに効くケース: 決定（旧ノートのゴミ箱）が走る前に昇格していないと、旧ノートが消えて昇格できなくなる。"""
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "old-1", "確定")
            _note(adir, "new-2", supersedes="old-1", auto="minor")
            _dec(sysd, "D20261006120000", "old-1", "trash")
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(_st(adir, "new-2"), "確定")
            self.assertFalse((adir / "old-1.md").exists())

    def test_promoted_at_apply_end(self):
        """末尾の昇格だけに効くケース: 決定の approve で旧ノートが確定になって初めて、新ノートの auto: minor が成立する。"""
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "old-1", "候補")
            _note(adir, "new-2", supersedes="old-1", auto="minor")
            _dec(sysd, "D20261006120000", "old-1", "approve")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual((_st(adir, "new-2"), _st(adir, "old-1")), ("確定", "置換済"))
            # 末尾の昇格の報告が返る（索引の作り直しでも昇格はするが、報告は末尾の _promote だけが返す）
            self.assertTrue(any("new-2 を自動確定にした" in m for m in msgs), msgs)

    def test_decisions_applied_in_stem_order_not_numeric(self):
        """連番 10 以上は数値順ではない（stem の文字列昇順なので -10 が -2 より先）。将来数値順に変えるならこのテストを更新する。"""
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            _dec(sysd, "D20261006120000-2", "n-1", "trash")
            _dec(sysd, "D20261006120000-10", "n-1", "approve")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(len(msgs), 2)
            # -10（approve）が先に効き、その後 -2（trash）でゴミ箱へ。ゴミ箱の写しの status は 確定
            t = next((adir / "ゴミ箱").glob("n-1__*.md"))
            self.assertEqual(bd.parse_frontmatter(t.read_text(encoding="utf-8"))[0]["status"], "確定")

    def test_fake_index_with_asset_type_is_not_a_note(self):
        """R8: type: asset を名乗る 資料庫.md もノートとして拾わない。"""
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1")
            (adir / "資料庫.md").write_text("---\ntype: asset\nstatus: 候補\n---\n", encoding="utf-8")
            self.assertEqual(sorted(bd._load_notes(adir)), ["n-1"])
            bd.write_assets_index(adir, sysd, NOW)
            ids = [n["id"] for n in json.loads((sysd / "assets.json").read_text(encoding="utf-8"))["notes"]]
            self.assertEqual(ids, ["n-1"])


class TestAssetsTrashCmd(unittest.TestCase):
    def test_trash_notes(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1", "確定")
            code, out = _cli(["assets-trash", "n-1"], sysd)
            self.assertEqual((code, json.loads(out)), (0, ["n-1"]))
            self.assertFalse((adir / "n-1.md").exists())
            self.assertEqual(_trashed(adir), ["n-1__20261006120000.md"])
            meta, body = bd.parse_frontmatter((adir / "ゴミ箱" / "n-1__20261006120000.md").read_text(encoding="utf-8"))
            self.assertEqual(meta["trashed_at"], "20261006120000")
            self.assertIn("n-1.md", meta["trashed_from"])
            self.assertEqual(meta["status"], "確定")
            self.assertIn("| a | 1 | B3 |", body)

    def test_trashed_note_not_listed_or_indexed(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1", "確定")
            _cli(["assets-trash", "n-1"], sysd)
            code, out = _cli(["assets-index"], sysd)
            self.assertEqual(json.loads(out)["counts"], {"候補": 0, "確定": 0, "置換済": 0})
            self.assertEqual(json.loads((sysd / "assets.json").read_text(encoding="utf-8"))["notes"], [])


class TestAssetsIndex(unittest.TestCase):
    def test_index_content_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "a-1", "確定")
            _note(adir, "b-2", "候補")
            _note(adir, "c-3", "置換済")
            _note(adir, "d-4", "確定", conflict="yes")
            (adir / "メモ.md").write_text("ただのメモ", encoding="utf-8")  # type: asset でないので無視
            bd.write_assets_index(adir, sysd, NOW)
            first = ((adir / "資料庫.md").read_bytes(), (sysd / "assets.json").read_bytes())
            bd.write_assets_index(adir, sysd, NOW)  # 索引自身を拾わない
            self.assertEqual(first, ((adir / "資料庫.md").read_bytes(), (sysd / "assets.json").read_bytes()))
            idx = (adir / "資料庫.md").read_text(encoding="utf-8")
            self.assertIn("type: assets-index", idx)
            self.assertIn("| 資料 | 版 | 日付 | 対象 | 種別 | 事実数 |", idx)
            self.assertIn("| [[a-1]] | v1 | 2026-10-01 | sw1, sw2 | 機器 | 2 |", idx)
            self.assertNotIn("[[b-2]]", idx)
            self.assertNotIn("[[c-3]]", idx)
            self.assertEqual(idx.count("[[a-1]]"), 1)
            j = json.loads(first[1])
            self.assertEqual(j["counts"], {"候補": 1, "確定": 2, "置換済": 1})
            self.assertEqual(j["generated"], "2026-10-06 12:00")
            self.assertEqual([n["id"] for n in j["notes"]], ["a-1", "b-2", "c-3", "d-4"])
            a = j["notes"][0]
            self.assertEqual(a["facts"], [{"item": "a", "value": "1", "where": "B3"},
                                          {"item": "b", "value": "x/y", "where": "C4"}])
            self.assertEqual(j["notes"][3]["conflict_rows"], [{"item": "ip", "old": "1", "new": "2"}])
            for k in ("id", "status", "targets", "kind", "source", "version", "date", "sha256", "locator",
                      "supersedes", "conflict", "auto", "conflict_rows"):
                self.assertIn(k, a)
            self.assertEqual(list(adir.glob(".assets-*")), [])
            self.assertEqual(list(sysd.glob(".assets-*")), [])

    def test_cli_index_and_list(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "a-1", "確定")
            code, out = _cli(["assets-index"], sysd)
            j = json.loads(out)
            self.assertEqual((code, j["counts"]["確定"]), (0, 1))
            self.assertTrue(Path(j["index"]).samefile(adir / "資料庫.md"))
            code, out = _cli(["assets-list"], sysd)
            self.assertIn("a-1  確定  sw1, sw2  a-1.xlsx  v1", out)


class TestAssetsNoDir(unittest.TestCase):
    def test_apply_moves_and_exit0_others_fail(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d, with_dir=False)
            _note(adir, "n-1")
            _dec(sysd, "D20261006120000", "n-1", "approve")
            code, out = _cli(["assets-apply"], sysd)
            self.assertEqual(code, 0)
            self.assertTrue(any("未設定" in m for m in json.loads(out)["applied"] + json.loads(out)["rejected"]))
            self.assertEqual(_st(adir, "n-1"), "候補")
            self.assertEqual(len(list((sysd / "requests" / "済").glob("D*.json"))), 1)
            for argv in (["assets-index"], ["assets-list"], ["assets-trash", "n-1"], ["assets-check", "f"]):
                with self.assertRaises(bd.BoardError):
                    _cli(argv, sysd)

    def test_apply_assets_function_without_dir(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, board = _env(d, with_dir=False)
            _dec(sysd, "D20261006120000", "n-1", "approve")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertIn("未設定", msgs[0])

    def test_no_board_json(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(bd.BoardError):
                _cli(["assets-apply"], Path(d))


class TestAssetsApplyCli(unittest.TestCase):
    def test_apply_saves_notice(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1")
            _dec(sysd, "D20261006120000", "n-1", "approve")
            code, out = _cli(["assets-apply"], sysd)
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(out)["applied"]), 1)
            b = json.loads((sysd / "board.json").read_text(encoding="utf-8"))
            self.assertEqual(len(b["notices"]), 1)
            self.assertNotIn("stops", b["notices"][0])


class TestAssetsReview(unittest.TestCase):
    """レビュー指摘（安全性・正確性・画面との整合）の回帰テスト。"""

    def _req(self, sysd, name, text):
        (sysd / "requests" / name).write_text(text, encoding="utf-8")

    def test_nested_json_and_oversize_rejected_and_later_applied(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            self._req(sysd, "D20261006120000.json", "[" * 200000)
            ok = json.dumps({"kind": "asset_decision", "note": "n-1", "action": "approve"})
            self._req(sysd, "D20261006120001.json", ok + " " * (bd.MAX_REQUEST_BYTES + 1))
            self._req(sysd, "D20261006120002.json", ok)
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(len(msgs), 3)
            self.assertEqual(_st(adir, "n-1"), "確定")
            self.assertEqual(list((sysd / "requests").glob("D*.json")), [])
            self.assertEqual(len(list((sysd / "requests" / "済").glob("D*.json"))), 3)

    def test_apply_simple_survives_nested_json(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, board = _env(d)
            self._req(sysd, "M20261006120000.json", "[" * 200000)
            self.assertEqual(bd.apply_simple(board, sysd / "requests", NOW), [])

    def test_messages_truncated(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            _dec(sysd, "D20261006120000", "x" * 5000, "trash")
            _dec(sysd, "D20261006120001", "n-1", "a" * 5000)
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(len(msgs), 2)
            for m in msgs:
                self.assertLess(len(m), 300)

    def test_frontmatter_splits_only_on_newline(self):
        meta, _ = bd.parse_frontmatter("---\ntype: asset\nlocator: a\u2028auto: minor\r\nx: 1\n---\n")
        self.assertNotIn("auto", meta)
        self.assertEqual((meta["locator"], meta["x"]), ("a\u2028auto: minor", "1"))
        out = bd._set_meta("---\ntype: asset\nstatus: 候補\nlocator: x\u2028status: y\n---\nB", {"status": "確定"})
        meta, body = bd.parse_frontmatter(out)
        self.assertEqual((meta["status"], meta["locator"], body), ("確定", "x\u2028status: y", "B"))

    def test_set_meta_replaces_all_duplicate_keys(self):
        out = bd._set_meta("---\nstatus: 候補\nstatus: 確定\n---\n", {"status": "置換済"})
        self.assertEqual(out.count("status: 置換済"), 2)
        self.assertNotIn("候補", out)

    def test_bom_note_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1")
            f = adir / "n-1.md"
            f.write_bytes(b"\xef\xbb\xbf" + f.read_bytes())
            self.assertIn("n-1", bd._load_notes(adir))

    def test_promote_requires_hex_sha_and_existing_old(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "old-1", "確定")
            _note(adir, "new-2", sha="zz" * 32, supersedes="old-1", auto="minor")
            _note(adir, "new-3", sha="ab" * 31, supersedes="old-1", auto="minor")  # 62 桁
            bd.write_assets_index(adir, sysd, NOW)
            self.assertEqual((_st(adir, "new-2"), _st(adir, "new-3"), _st(adir, "old-1")),
                             ("候補", "候補", "確定"))

    def test_promote_chain_converges_in_one_run(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "m-old", "確定")
            _note(adir, "z-mid", supersedes="m-old", auto="minor")
            _note(adir, "a-new", supersedes="z-mid", auto="minor")
            bd.write_assets_index(adir, sysd, NOW)
            self.assertEqual((_st(adir, "a-new"), _st(adir, "z-mid"), _st(adir, "m-old")),
                             ("確定", "置換済", "置換済"))

    def test_promote_only_first_of_competing_candidates(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "old-1", "確定")
            _note(adir, "c-1", supersedes="old-1", auto="minor")
            _note(adir, "c-2", supersedes="old-1", auto="minor")
            bd.write_assets_index(adir, sysd, NOW)
            self.assertEqual((_st(adir, "c-1"), _st(adir, "c-2"), _st(adir, "old-1")),
                             ("確定", "候補", "置換済"))

    def test_conflict_values(self):
        for v, expect in (("yes", True), ("YES", True), ("true", True), ("True", True),
                          ("no", False), ("false", False), ("", False)):
            self.assertEqual(bd._is_conflict({"conflict": v}), expect, v)
        self.assertFalse(bd._is_conflict({}))

    def test_conflict_no_is_not_a_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "old-1", "確定")
            _note(adir, "new-2", supersedes="old-1", auto="minor", conflict="no")
            _note(adir, "n-3", conflict="false")
            _note(adir, "n-4", conflict="false")
            _dec(sysd, "D20261006120000", "n-3", "approve")
            _dec(sysd, "D20261006120001", "n-4", "overwrite_ok")
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual((_st(adir, "new-2"), _st(adir, "n-3"), _st(adir, "n-4")), ("確定", "確定", "候補"))

    def test_assets_json_conflict_is_bool(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "a-1", "確定")
            _note(adir, "b-2", conflict="yes")
            _note(adir, "c-3", conflict="no")
            bd.write_assets_index(adir, sysd, NOW)
            j = {n["id"]: n["conflict"] for n in json.loads((sysd / "assets.json").read_text(encoding="utf-8"))["notes"]}
            self.assertEqual(j, {"a-1": False, "b-2": True, "c-3": False})

    def test_non_regular_file_is_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, adir, _ = _env(d)
            fifo = Path(d) / "fifo.xlsx"
            os.mkfifo(fifo)
            for f in (fifo, Path("/dev/zero")):
                self.assertEqual(bd.check_assets([f], adir)[0]["state"], "unreadable")

    def test_symlink_note_ignored_and_symlink_trash_refused(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1")
            os.symlink(adir / "n-1.md", adir / "link-1.md")
            self.assertEqual(sorted(bd._load_notes(adir)), ["n-1"])
            other = Path(d) / "elsewhere"
            other.mkdir()
            os.symlink(other, adir / "ゴミ箱")
            with self.assertRaises(bd.BoardError):
                bd.trash_notes(adir, ["n-1"], NOW)
            self.assertEqual(list(other.iterdir()), [])
            self.assertTrue((adir / "n-1.md").exists())

    def test_assets_dir_must_be_inside_vault(self):
        with tempfile.TemporaryDirectory() as d:
            sysd = Path(d) / "guild" / ".system"
            sysd.mkdir(parents=True)
            for bad in ("/etc", "../..", "../../other", "guild/../../x"):
                with self.assertRaises(bd.BoardError, msg=bad):
                    bd.resolve_assets_dir({"assets_dir": bad}, sysd)
            self.assertEqual(bd.resolve_assets_dir({"assets_dir": str(Path(d) / "guild" / "a")}, sysd),
                             (Path(d) / "guild" / "a").resolve())

    def test_apply_with_outside_assets_dir_moves_requests(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, board = _env(d)
            board["assets_dir"] = "../.."
            _dec(sysd, "D20261006120000", "n-1", "approve")
            msgs = bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertEqual(len(msgs), 1)
            self.assertEqual(list((sysd / "requests").glob("D*.json")), [])

    def test_trash_name_collision_keeps_both(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1", version="first")
            bd.trash_notes(adir, ["n-1"], NOW)
            _note(adir, "n-1", version="second")
            bd.trash_notes(adir, ["n-1"], NOW)
            self.assertEqual(_trashed(adir), ["n-1__20261006120000-2.md", "n-1__20261006120000.md"])
            t = adir / "ゴミ箱"
            self.assertIn("first", (t / "n-1__20261006120000.md").read_text(encoding="utf-8"))

    def test_trash_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "n-1")
            self.assertEqual(bd.trash_notes(adir, ["n-1", "n-1"], NOW), ["n-1"])

    def test_index_cell_sanitized_and_bad_ids_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, _ = _env(d)
            _note(adir, "a-1", "確定", targets="x\r[[evil]]\u2028y|z")
            for bad in ("b]]c", "d|e", "f[g", "h\ri"):
                _note(adir, bad, "確定")
            bd.write_assets_index(adir, sysd, NOW)
            idx = (adir / "資料庫.md").read_text(encoding="utf-8")
            self.assertEqual(idx.count("[["), 1)
            self.assertNotIn("\u2028", idx)
            self.assertNotIn("\r", idx)
            ids = [n["id"] for n in json.loads((sysd / "assets.json").read_text(encoding="utf-8"))["notes"]]
            self.assertEqual(ids, ["a-1"])

    def test_cell_helper(self):
        self.assertEqual(bd._cell("a|b\nc"), "a/b c")
        self.assertEqual(bd._cell("a\r\u2028b"), "a  b")

    def test_apply_rebuilds_index_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            _dec(sysd, "D20261006120000", "n-1", "approve")
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            j = json.loads((sysd / "assets.json").read_text(encoding="utf-8"))
            self.assertEqual(j["counts"]["確定"], 1)
            self.assertIn("[[n-1]]", (adir / "資料庫.md").read_text(encoding="utf-8"))

    def test_apply_rebuilds_on_promotion_only(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "old-1", "確定")
            _note(adir, "new-2", supersedes="old-1", auto="minor")
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertTrue((sysd / "assets.json").exists())

    def test_apply_without_work_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, adir, board = _env(d)
            _note(adir, "n-1")
            bd.apply_assets(board, sysd / "requests", sysd, NOW)
            self.assertFalse((sysd / "assets.json").exists())

# ---------- 後追い抽出（assets-scan）と一括承認（assets-approve） ----------

def _scan_env(d, projects="projects", quests="quests"):
    """_env に projects_dir・quests_dir を足す。(vault, sysd, adir, board) を返す。"""
    vault, sysd, adir, board = _env(d)
    if projects:
        board["projects_dir"] = projects
    if quests:
        board["quests_dir"] = quests
    (sysd / "board.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    return vault, sysd, adir, board


def _put(vault, rel, data=b"x"):
    f = vault / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


def _h(data):
    return hashlib.sha256(data).hexdigest()


def _timeout(sec=5):
    """FIFO を使うテストがハングしても、数秒で失敗に変える（SIGALRM。Unix のみ）。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            def on_alarm(signum, frame):
                raise AssertionError(f"{sec} 秒で終わらない（ハング）")
            old = signal.signal(signal.SIGALRM, on_alarm)
            signal.alarm(sec)
            try:
                return fn(*a, **kw)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old)
        return wrapper
    return deco


def _drop_chain(base, name, depth):
    """base 配下の name を depth 段重ねた入れ子（末端にファイル 1 つ）を、下から順に片付ける。"""
    for k in range(depth, 0, -1):
        d = base.joinpath(*[name] * k)
        for f in d.glob("*.txt"):
            f.unlink()
        d.rmdir()


def _edit(adir, nid, old, new):
    """ノートの本文・frontmatter の文字列を置き換える。"""
    f = adir / f"{nid}.md"
    t = f.read_text(encoding="utf-8")
    assert old in t
    f.write_text(t.replace(old, new, 1), encoding="utf-8")


def _facts_body(adir, nid, n, value="v"):
    """事実表を n 行にする。"""
    f = adir / f"{nid}.md"
    head = f.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    rows = "".join(f"| k{i} | {value} | B{i} |\n" for i in range(n))
    f.write_text(head + "\n---\n| 項目 | 値 | 出典箇所 |\n|---|---|---|\n" + rows, encoding="utf-8")


class TestResolveVaultDir(unittest.TestCase):
    def test_none_when_key_missing(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, _ = _env(d)
            self.assertIsNone(bd.resolve_vault_dir({}, sysd, "projects_dir"))

    def test_inside_vault_resolved(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, _ = _env(d)
            self.assertEqual(bd.resolve_vault_dir({"projects_dir": "p"}, sysd, "projects_dir"), (vault / "p").resolve())

    def test_quests_dir_outside_vault_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, _ = _env(d)
            with self.assertRaises(bd.BoardError):
                bd.resolve_vault_dir({"quests_dir": "../.."}, sysd, "quests_dir")

    def test_absolute_outside_vault_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            _, sysd, _, _ = _env(d)
            with self.assertRaises(bd.BoardError):
                bd.resolve_vault_dir({"quests_dir": out}, sysd, "quests_dir")


class TestAssetsScan(unittest.TestCase):
    def scan(self, board, sysd, limit=5):
        return bd.scan_assets(board, sysd, limit)

    def test_returns_only_unregistered(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, adir, board = _scan_env(d)
            _put(vault, "projects/研究A/input/new.xlsx", b"new")
            _put(vault, "projects/研究A/input/reg.xlsx", b"reg")
            _put(vault, "quests/012 題/input/tr.xlsx", b"tr")
            _note(adir, "n-1", "確定", sha=_h(b"reg"))
            _note(adir, "n-2", "置換済", sha=_h(b"zzz"))
            (adir / "ゴミ箱").mkdir()
            _note(adir / "ゴミ箱", "n-3", sha=_h(b"tr"))
            r = self.scan(board, sysd)
            self.assertEqual(r["items"], [{"case": "projects/研究A", "file": "input/new.xlsx", "sha256": _h(b"new")}])
            self.assertEqual((r["remaining"], r["unreadable"], r["oversize"]), (0, 0, []))

    def test_order_dup_limit_remaining(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            _put(vault, "projects/B/input/a.txt", b"dup")      # 重複: 先の案件（A）が残る
            _put(vault, "projects/A/input/b.txt", b"dup")
            _put(vault, "projects/A/input/a.txt", b"1")
            _put(vault, "quests/001 x/input/sub/c.txt", b"2")
            _put(vault, "quests/001 x/input/d.txt", b"3")
            r = self.scan(board, sysd, 2)
            self.assertEqual([(i["case"], i["file"]) for i in r["items"]],
                             [("projects/A", "input/a.txt"), ("projects/A", "input/b.txt")])
            self.assertEqual(r["remaining"], 2)  # 重複 hash は 1 件。limit 内の hash は数えない
            r = self.scan(board, sysd, 20)
            self.assertEqual([i["file"] for i in r["items"]],
                             ["input/a.txt", "input/b.txt", "input/d.txt", "input/sub/c.txt"])
            self.assertEqual(r["remaining"], 0)

    def test_only_one_dir_configured(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d, quests=None)
            _put(vault, "projects/A/input/a.txt", b"1")
            self.assertEqual(len(self.scan(board, sysd)["items"]), 1)

    @_timeout()
    def test_excludes_hidden_md_copy_and_nonregular(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            _put(vault, "projects/A/input/.hid.txt", b"h")
            _put(vault, "projects/A/input/.dir/x.txt", b"h2")
            _put(vault, "projects/A/input/t.xlsx", b"t")
            _put(vault, "projects/A/input/t.md", b"copy")
            _put(vault, "projects/A/input/memo.md", b"memo")
            _put(vault, "projects/A/other/o.txt", b"o")        # input/ の外
            _put(vault, "projects/loose.txt", b"l")            # 案件フォルダの外
            os.mkfifo(vault / "projects/A/input/fifo")
            r = self.scan(board, sysd)
            self.assertEqual(sorted(i["file"] for i in r["items"]), ["input/memo.md", "input/t.xlsx"])
            self.assertEqual(r["unreadable"], 0)

    def test_oversize_and_unreadable_names(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            old = bd.MAX_SCAN_BYTES
            bd.MAX_SCAN_BYTES = 5
            try:
                _put(vault, "projects/A/input/big.bin", b"123456")
                _put(vault, "projects/A/input/ok.bin", b"12345")
                _put(vault, "projects/A/input/bad\nname-big.bin", b"123456")  # 危険な名前は oversize に出さない
                _put(vault, "projects/A/input/bad|name.bin", b"1")
                r = self.scan(board, sysd)
            finally:
                bd.MAX_SCAN_BYTES = old
            self.assertEqual([i["file"] for i in r["items"]], ["input/ok.bin"])
            self.assertEqual(r["oversize"], ["projects/A/input/big.bin"])
            self.assertEqual(r["unreadable"], 2)
            self.assertNotIn("name", json.dumps(r, ensure_ascii=False))

    def test_oversize_boundary_follows_constant(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            _put(vault, "projects/A/input/eq.bin", b"1234")
            _put(vault, "projects/A/input/gt.bin", b"12345")
            with mock.patch.object(bd, "MAX_SCAN_BYTES", 4):
                r = self.scan(board, sysd)
            self.assertEqual([i["file"] for i in r["items"]], ["input/eq.bin"])
            self.assertEqual(r["oversize"], ["projects/A/input/gt.bin"])

    def test_symlinks_not_followed(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            vault, sysd, _, board = _scan_env(d)
            outside = Path(out)
            (outside / "input").mkdir()
            (outside / "input" / "s.txt").write_bytes(b"secret")
            (outside / "sub").mkdir()
            (outside / "sub" / "t.txt").write_bytes(b"secret2")
            (outside / "f.txt").write_bytes(b"secret3")
            _put(vault, "projects/ok/input/ok.txt", b"ok")
            (vault / "projects" / "linkcase").symlink_to(outside)                    # 案件フォルダ
            (vault / "projects" / "inl").mkdir()
            (vault / "projects" / "inl" / "input").symlink_to(outside / "input")     # input/
            _put(vault, "projects/sub/input/x.txt", b"x")
            (vault / "projects/sub/input/dirlink").symlink_to(outside / "sub")       # サブフォルダ
            (vault / "projects/sub/input/filelink.txt").symlink_to(outside / "f.txt")  # ファイル
            r = self.scan(board, sysd)
            self.assertEqual(sorted((i["case"], i["file"]) for i in r["items"]),
                             [("projects/ok", "input/ok.txt"), ("projects/sub", "input/x.txt")])

    def test_dir_outside_vault_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, board = _scan_env(d, projects="../..")
            with self.assertRaises(bd.BoardError):
                self.scan(board, sysd)

    def test_zero_fact_note_registers_source(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, adir, board = _scan_env(d)
            _put(vault, "projects/A/input/img.png", b"png")
            self.assertEqual(len(self.scan(board, sysd)["items"]), 1)
            (adir / "n-0.md").write_text(
                f"---\ntype: asset\nstatus: 候補\nsource: img.png\nsha256: {_h(b'png')}\n---\n事実なし: 画像のみ\n",
                encoding="utf-8")
            self.assertEqual(self.scan(board, sysd)["items"], [])

    def test_dangerous_names_are_unreadable_and_not_echoed(self):
        names = ["rlo\u202ename.txt", "zw\u200bname.txt", "bom\ufeffname.txt", "iso\u2066name.txt", "n" * 121 + ".txt"]
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            for i, n in enumerate(names):
                _put(vault, f"projects/A/input/{n}", bytes([i]))
            _put(vault, "projects/A/input/" + "n" * 116 + ".txt", b"edge")  # ちょうど 120 文字は通る
            r = self.scan(board, sysd)
            self.assertEqual(r["unreadable"], len(names))
            self.assertEqual(len(r["items"]), 1)
            self.assertEqual(len(r["items"][0]["file"]) - len("input/"), 120)

    def test_dangerous_case_and_subfolder_names_counted_once(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            _put(vault, "projects/bad|case/input/x.txt", b"1")
            _put(vault, "projects/bad|case/input/y.txt", b"2")
            _put(vault, "projects/A/input/bad\u202edir/p.txt", b"3")
            _put(vault, "projects/A/input/bad\u202edir/q.txt", b"4")
            _put(vault, "projects/A/input/ok/z.txt", b"5")
            r = self.scan(board, sysd)
            self.assertEqual(r["unreadable"], 2)  # 案件 1 + サブフォルダ 1（中のファイル数は数えない）
            self.assertEqual([i["file"] for i in r["items"]], ["input/ok/z.txt"])
            self.assertNotIn("bad", json.dumps(r, ensure_ascii=False))

    def test_depth_1500_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            _put(vault, "projects/A/input/top.txt", b"top")
            base = vault / "projects/A/input"
            for k in range(1, 1501):  # mkdir(parents=True) は深さで再帰が尽きるので 1 段ずつ作る
                base.joinpath(*["d"] * k).mkdir()
            (base.joinpath(*["d"] * 1500) / "bottom.txt").write_bytes(b"bottom")
            try:
                r = self.scan(board, sysd)
            finally:
                _drop_chain(base, "d", 1500)  # 標準の一括後始末は深い入れ子で再帰が尽きるので、下から順に外す
            self.assertEqual([i["file"] for i in r["items"]], ["input/top.txt"])
            self.assertIs(r["truncated"], True)

    def test_depth_limit(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            _put(vault, "projects/A/input/a.txt", b"a")
            _put(vault, "projects/A/input/s1/b.txt", b"b")
            _put(vault, "projects/A/input/s1/s2/c.txt", b"c")
            _put(vault, "projects/A/input/s1/s2/s3/d.txt", b"d")
            with mock.patch.object(bd, "MAX_SCAN_DEPTH", 2):
                r = self.scan(board, sysd)
            self.assertEqual([i["file"] for i in r["items"]], ["input/a.txt", "input/s1/b.txt", "input/s1/s2/c.txt"])
            self.assertIs(r["truncated"], True)
            with mock.patch.object(bd, "MAX_SCAN_DEPTH", 3):
                r = self.scan(board, sysd)
            self.assertEqual(len(r["items"]), 4)
            self.assertNotIn("truncated", r)

    def test_file_count_limit(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            for i in range(5):
                _put(vault, f"projects/A/input/f{i}.txt", str(i).encode())
            with mock.patch.object(bd, "MAX_SCAN_FILES", 3):
                r = self.scan(board, sysd, 10)
            self.assertEqual(len(r["items"]), 3)
            self.assertIs(r["truncated"], True)
            with mock.patch.object(bd, "MAX_SCAN_FILES", 5):
                r = self.scan(board, sysd, 10)
            self.assertEqual(len(r["items"]), 5)
            self.assertNotIn("truncated", r)

    def test_scandir_oserror_counts_unreadable_and_continues(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            _put(vault, "projects/A/input/ok.txt", b"ok")
            _put(vault, "projects/A/input/locked/x.txt", b"x")
            _put(vault, "projects/B/input/y.txt", b"y")
            real = os.scandir

            def fake(p):
                if str(p).endswith("locked") or str(p).endswith("projects/B/input"):
                    raise PermissionError("denied")
                return real(p)
            with mock.patch.object(os, "scandir", fake):
                r = self.scan(board, sysd)
            self.assertEqual([i["file"] for i in r["items"]], ["input/ok.txt"])
            self.assertEqual(r["unreadable"], 2)  # サブフォルダ 1 + 案件 1

    def test_scandir_is_closed(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            _put(vault, "projects/A/input/a.txt", b"a")
            real, calls = os.scandir, []  # with で開閉されることを、enter/exit の回数で確かめる

            class Spy:
                def __init__(self, it): self.it = it
                def __enter__(self): calls.append("enter"); return self.it.__enter__()
                def __exit__(self, *a): calls.append("exit"); return self.it.__exit__(*a)
            with mock.patch.object(os, "scandir", lambda p: Spy(real(p))):
                self.scan(board, sysd)
            self.assertTrue(calls)
            self.assertEqual(calls.count("enter"), calls.count("exit"))

    def test_limit_validation(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, board = _scan_env(d)
            for bad in (0, -1, bd.SCAN_LIMIT_MAX + 1):
                with self.assertRaises(bd.BoardError):
                    self.scan(board, sysd, bad)
                with self.assertRaises(bd.BoardError):
                    _cli(["assets-scan", "--limit", str(bad)], sysd)
            self.assertEqual(self.scan(board, sysd, bd.SCAN_LIMIT_MAX)["items"], [])
            self.assertEqual(self.scan(board, sysd, 1)["items"], [])

    def test_default_limit_is_the_constant(self):
        self.assertEqual(bd.build_parser().parse_args(["assets-scan"]).limit, bd.SCAN_LIMIT)
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            for i in range(bd.SCAN_LIMIT + 2):
                _put(vault, f"projects/A/input/f{i}.txt", str(i).encode())
            r = bd.scan_assets(board, sysd)
            self.assertEqual((len(r["items"]), r["remaining"]), (bd.SCAN_LIMIT, 2))

    def test_batch_bytes_cap(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, board = _scan_env(d)
            for i in range(3):
                _put(vault, f"projects/A/input/f{i}.bin", bytes([i]) * 6)
            with mock.patch.object(bd, "MAX_BATCH_BYTES", 10):
                r = self.scan(board, sysd, 10)
            self.assertEqual((len(r["items"]), r["remaining"]), (1, 2))  # 6 + 6 > 10 で止める
            with mock.patch.object(bd, "MAX_BATCH_BYTES", 12):
                r = self.scan(board, sysd, 10)
            self.assertEqual((len(r["items"]), r["remaining"]), (2, 1))
            with mock.patch.object(bd, "MAX_BATCH_BYTES", 3):
                r = self.scan(board, sysd, 10)
            self.assertEqual((len(r["items"]), r["remaining"]), (1, 2))  # 1 件目は上限を超えても返す

    def test_registered_hash_compared_lowercase(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, adir, board = _scan_env(d)
            _put(vault, "projects/A/input/a.txt", b"a")
            _note(adir, "n-1", "確定", sha=_h(b"a").upper())
            self.assertEqual(self.scan(board, sysd)["items"], [])

    def test_shared_helpers(self):
        self.assertEqual(bd._OFFICE_EXTS, (".xlsx", ".docx", ".pptx"))
        with tempfile.TemporaryDirectory() as d:
            vault, _, adir, _ = _scan_env(d)
            _put(vault, "x/t.xlsx")
            self.assertTrue(bd._is_md_copy(vault / "x/t.md"))
            self.assertFalse(bd._is_md_copy(vault / "x/t.txt"))
            _note(adir, "n-1", sha="A" * 64)
            (adir / "ゴミ箱").mkdir()
            _note(adir / "ゴミ箱", "n-2", sha="B" * 64)
            self.assertEqual(bd._known_hashes(adir), {"a" * 64, "b" * 64})

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            vault, sysd, _, _ = _scan_env(d)
            for i in range(7):
                _put(vault, f"projects/A/input/f{i}.txt", str(i).encode())
            code, out = _cli(["assets-scan"], sysd)
            j = json.loads(out)
            self.assertEqual((code, len(j["items"]), j["remaining"]), (0, 5, 2))
            j = json.loads(_cli(["assets-scan", "--limit", "3"], sysd)[1])
            self.assertEqual((len(j["items"]), j["remaining"]), (3, 4))

    def test_cli_needs_config(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, _ = _env(d)  # projects_dir・quests_dir 無し
            with self.assertRaises(bd.BoardError):
                _cli(["assets-scan"], sysd)
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, _ = _env(d, with_dir=False)
            with self.assertRaises(bd.BoardError):
                _cli(["assets-scan"], sysd)


class TestAssetsApprove(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.vault, self.sysd, self.adir, self.board = _env(self._d.name)

    def approve(self, *args):
        return _cli(["assets-approve", *args], self.sysd)

    def test_requires_filter(self):
        _note(self.adir, "n-1")
        for argv in ([], ["--yes"]):
            with self.assertRaises(bd.BoardError):
                self.approve(*argv)
        self.assertEqual(_st(self.adir, "n-1"), "候補")

    def test_preview_changes_nothing(self):
        _note(self.adir, "n-1")
        _note(self.adir, "n-2", source="n-1.xlsx")
        before = {p.name: p.read_bytes() for p in self.adir.glob("*.md")}
        code, out = self.approve("--all")
        j = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual({p.name: p.read_bytes() for p in self.adir.glob("*.md")}, before)
        self.assertFalse((self.sysd / "assets.json").exists())
        p = j["preview"][0]
        self.assertEqual((p["id"], p["source"], p["version"], p["date"], p["targets"], p["fact_count"]),
                         ("n-1", "n-1.xlsx", "v1", "2026-10-01", "sw1, sw2", 2))
        self.assertTrue(p["path"].endswith("n-1.md"))
        self.assertEqual(p["facts"][0]["item"], "a")
        self.assertIn("n-2", p["warning"])  # 同名の候補あり
        self.assertNotIn("approved", j)

    def test_filters(self):
        _note(self.adir, "n-1", targets="sw1, sw2")
        _note(self.adir, "n-2", source="other.xlsx", targets=" SW1 ")
        _note(self.adir, "n-3", source="other.xlsx", targets="sw2")
        ids = lambda *a: sorted(i["id"] for i in json.loads(self.approve(*a)[1])["preview"])
        self.assertEqual(ids("--source", "other.xlsx"), ["n-2", "n-3"])
        self.assertEqual(ids("--source", "other"), [])
        self.assertEqual(ids("--target", "sw2"), ["n-1", "n-3"])
        self.assertEqual(ids("--target", "Sw1"), [])  # 大文字小文字は区別
        self.assertEqual(ids("--target", "SW1"), ["n-2"])  # 前後の空白は除く
        self.assertEqual(ids("--source", "other.xlsx", "--target", "sw2"), ["n-3"])
        self.assertEqual(ids("--all"), ["n-1", "n-2", "n-3"])

    def test_skips_conflict_and_other_confirmed_same_source(self):
        _note(self.adir, "c-1", conflict="yes")
        _note(self.adir, "old", "確定", source="s.xlsx")
        _note(self.adir, "new", source="s.xlsx")
        _note(self.adir, "ok", source="ok.xlsx")
        _note(self.adir, "gone", "置換済", source="g.xlsx")
        _note(self.adir, "g2", source="g.xlsx")  # 置換済は確定でないので除外しない
        j = json.loads(self.approve("--all", "--yes")[1])
        self.assertEqual(sorted(j["approved"]), ["g2", "ok"])
        self.assertEqual(sorted(s["id"] for s in j["skipped"]), ["c-1", "new"])
        self.assertTrue(all(s["reason"] for s in j["skipped"]))
        self.assertEqual((_st(self.adir, "c-1"), _st(self.adir, "new"), _st(self.adir, "old")),
                         ("候補", "候補", "確定"))

    def test_same_source_candidates_not_excluded(self):
        _note(self.adir, "a-1", source="s.xlsx")
        _note(self.adir, "a-2", source="s.xlsx")
        j = json.loads(self.approve("--all", "--yes")[1])
        self.assertEqual(sorted(j["approved"]), ["a-1", "a-2"])
        self.assertEqual(j["skipped"], [])

    def test_zero_targets_exit0(self):
        _note(self.adir, "n-1", "確定")
        code, out = self.approve("--all", "--yes")
        self.assertEqual((code, json.loads(out)["approved"]), (0, []))

    def test_yes_matches_decide_and_updates_index(self):
        _note(self.adir, "old", "確定", source="o.xlsx")
        _note(self.adir, "up", source="up.xlsx", supersedes="old")
        _note(self.adir, "solo", source="solo.xlsx")
        j = json.loads(self.approve("--source", "up.xlsx", "--yes")[1])
        self.assertEqual(j["approved"], [])  # supersedes を持つ候補は一括承認しない
        self.assertEqual([s["id"] for s in j["skipped"]], ["up"])
        self.assertIn("資料庫タブ", j["skipped"][0]["reason"])
        self.assertEqual((_st(self.adir, "up"), _st(self.adir, "old"), _st(self.adir, "solo")),
                         ("候補", "確定", "候補"))
        self.approve("--source", "solo.xlsx", "--yes")
        self.assertEqual(_st(self.adir, "solo"), "確定")  # supersedes なしは単独で確定
        idx = (self.adir / "資料庫.md").read_text(encoding="utf-8")
        self.assertIn("[[solo]]", idx)
        self.assertIn("[[old]]", idx)
        self.assertNotIn("[[up]]", idx)
        js = json.loads((self.sysd / "assets.json").read_text(encoding="utf-8"))
        self.assertEqual(js["counts"]["確定"], 2)

    def test_supersedes_injection_does_not_replace_other_confirmed(self):
        _note(self.adir, "A-1", "確定", source="A.xlsx")
        _note(self.adir, "B-1", source="B.xlsx", supersedes="A-1")  # 資料内の指示文で賢者が書かされた想定
        j = json.loads(self.approve("--source", "B.xlsx", "--yes")[1])
        self.assertEqual(j["approved"], [])
        self.assertEqual((_st(self.adir, "A-1"), _st(self.adir, "B-1")), ("確定", "候補"))
        pv = json.loads(self.approve("--source", "B.xlsx")[1])
        self.assertEqual((pv["preview"], [s["id"] for s in pv["skipped"]]), ([], ["B-1"]))

    def test_empty_source_is_not_same_source(self):
        _note(self.adir, "c-1", "確定")
        _edit(self.adir, "c-1", "source: c-1.xlsx", "source:")
        _note(self.adir, "c-2")
        _edit(self.adir, "c-2", "source: c-2.xlsx", "source:")
        _note(self.adir, "c-3")
        _edit(self.adir, "c-3", "source: c-3.xlsx", "source:")
        pv = json.loads(self.approve("--all")[1])
        self.assertEqual(sorted(p["id"] for p in pv["preview"]), ["c-2", "c-3"])
        self.assertTrue(all("warning" not in p for p in pv["preview"]))  # 空どうしを同名の候補にしない
        j = json.loads(self.approve("--all", "--yes")[1])
        self.assertEqual((sorted(j["approved"]), j["skipped"]), (["c-2", "c-3"], []))

    def test_yes_with_nothing_to_approve_still_rebuilds_index(self):
        _note(self.adir, "n-1", "確定")
        self.assertFalse((self.sysd / "assets.json").exists())
        self.approve("--all", "--yes")
        self.assertTrue((self.sysd / "assets.json").exists())
        self.assertIn("[[n-1]]", (self.adir / "資料庫.md").read_text(encoding="utf-8"))

    def test_yes_promotes_minor_even_when_nothing_approved(self):
        _note(self.adir, "old", "確定", source="o.xlsx")
        _note(self.adir, "new", source="n.xlsx", supersedes="old", auto="minor")
        j = json.loads(self.approve("--source", "nomatch", "--yes")[1])
        self.assertEqual(j["approved"], [])
        self.assertEqual((_st(self.adir, "new"), _st(self.adir, "old")), ("確定", "置換済"))
        self.assertIn("[[new]]", (self.adir / "資料庫.md").read_text(encoding="utf-8"))
        self.assertTrue(j["promoted"])

    def test_target_matches_whole_element_only(self):
        _note(self.adir, "n-1", targets="sw10, swx")
        ids = lambda *a: [i["id"] for i in json.loads(self.approve(*a)[1])["preview"]]
        self.assertEqual(ids("--target", "sw1"), [])
        self.assertEqual(ids("--target", "sw"), [])
        self.assertEqual(ids("--target", "sw10"), ["n-1"])

    def test_conflict_candidate_is_skipped_not_previewed(self):
        _note(self.adir, "c-1", conflict="yes")
        _note(self.adir, "ok")
        pv = json.loads(self.approve("--all")[1])
        self.assertEqual([p["id"] for p in pv["preview"]], ["ok"])
        self.assertEqual([s["id"] for s in pv["skipped"]], ["c-1"])
        self.assertTrue(pv["skipped"][0]["reason"])

    def test_preview_facts_first_three_and_truncated(self):
        _note(self.adir, "n-1")
        _facts_body(self.adir, "n-1", 5, value="x" * 200)
        p = json.loads(self.approve("--all")[1])["preview"][0]
        self.assertEqual(p["fact_count"], 5)
        self.assertEqual([f["item"] for f in p["facts"]], ["k0", "k1", "k2"])
        self.assertTrue(all(len(f["value"]) == 80 for f in p["facts"]))
        _note(self.adir, "n-2")
        _facts_body(self.adir, "n-2", 2)
        p = [x for x in json.loads(self.approve("--all")[1])["preview"] if x["id"] == "n-2"][0]
        self.assertEqual(len(p["facts"]), 2)

    def test_no_assets_dir(self):
        with tempfile.TemporaryDirectory() as d:
            _, sysd, _, _ = _env(d, with_dir=False)
            with self.assertRaises(bd.BoardError):
                _cli(["assets-approve", "--all"], sysd)


class TestAssetsSha(unittest.TestCase):
    @_timeout()
    def test_fifo_and_symlink_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "real.bin"
            f.write_bytes(b"real")
            (Path(d) / "link.bin").symlink_to(f)
            os.mkfifo(Path(d) / "fifo")
            self.assertEqual(bd._sha256(f), _h(b"real"))
            for name in ("link.bin", "fifo"):
                with self.assertRaises(OSError):
                    bd._sha256(Path(d) / name)

    @_timeout()
    def test_swapped_to_fifo_after_stat_does_not_hang(self):
        """事前の os.stat が通常ファイルと答えても（差し替えの競合）、開いたあとの fstat で拒否して固まらない。"""
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real.bin"
            real.write_bytes(b"real")
            os.mkfifo(Path(d) / "fifo")
            with mock.patch.object(os, "stat", lambda p, *a, **k: real.lstat()):
                with self.assertRaises(OSError):
                    bd._sha256(Path(d) / "fifo")

    def test_size_cap(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "big.bin"
            f.write_bytes(b"12345")
            with mock.patch.object(bd, "MAX_SCAN_BYTES", 4):
                with self.assertRaises(OSError):
                    bd._sha256(f)

    def test_check_assets_lowercase_and_oversize(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, adir, _ = _env(d)
            f = Path(d) / "a.bin"
            f.write_bytes(b"a")
            _note(adir, "n-1", "確定", sha=_h(b"a").upper())
            self.assertEqual(bd.check_assets([f], adir)[0]["state"], "registered")
            (adir / "ゴミ箱").mkdir()
            _note(adir / "ゴミ箱", "t-1", sha=_h(b"b").upper())
            g = Path(d) / "b.bin"
            g.write_bytes(b"b")
            self.assertEqual(bd.check_assets([g], adir)[0]["state"], "trashed")
            with mock.patch.object(bd, "MAX_SCAN_BYTES", 0):
                self.assertEqual(bd.check_assets([f], adir)[0]["state"], "unreadable")


if __name__ == "__main__":
    unittest.main()

"""AI 社員 Phase 3 のレビュー反映：型の誤り・archive.json の形・形式ごとの納品物・one_line の取り違え。"""
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


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.gdir = self.root / "guild"
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()


class FormatTypeTest(Base):
    def test_non_string_formats_are_rejected_with_a_message_not_a_crash(self):
        for bad in (["md"], {"a": 1}, 3, True):
            errs = guild.validate({"goals": [{"id": "G1", "title": "x", "kind": "auto", "class": "wizard", "deps": [], "state": "pending",
                                               "criteria": dict(CRIT), "format": bad}]}, TR)
            self.assertTrue(any("format" in e for e in errs), bad)

    def test_request_format_with_a_bad_type_falls_back_to_md(self):
        for bad in (["html"], {"a": 1}, 5):
            write(self.q / "request.json", {"type": "request", "text": "x", "format": bad})
            self.assertEqual(guild.request_format(self.q), "md")

    def test_new_quest_rejects_a_list_format_instead_of_crashing(self):
        write(self.gdir / ".work" / "requests" / "R1.json", {"type": "request", "text": "x", "format": ["md"], "inputs": [], "files": []})
        with self.assertRaises(guild.GuildError):
            guild.new_quest(self.root, "R1")
        self.assertTrue((self.gdir / ".work" / "requests" / "rejected" / "R1.json").exists())
        self.assertEqual([a for a in guild.arrivals(self.root) if a["kind"] == "request"], [])

    def test_adopt_rejects_a_list_format_with_guilderror(self):
        write(self.q / "reports" / "plan-draft.json", {"quest": "Q001", "title": "題", "series": "s", "goals": [
            {"id": "G1", "title": "x", "kind": "auto", "class": "wizard", "deps": [], "criteria": dict(CRIT), "deliverable": True, "format": ["md"]}]})
        with self.assertRaises(guild.GuildError):
            guild.adopt(self.q / "plan.json", TR)

    def test_a_bad_goal_format_does_not_break_publishing(self):
        plan = {"quest": "Q001", "title": "t", "series": "s", "approved": True, "status": "active", "goals": [
            {"id": "G1", "title": "x", "kind": "auto", "class": "wizard", "deps": [], "criteria": dict(CRIT), "deliverable": True,
             "format": ["md"], "state": "done", "retries": 0, "output": None}]}
        guild.save_plan(self.q / "plan.json", plan)
        (self.q / "output" / "G1").mkdir(parents=True)
        (self.q / "output" / "G1" / "a.md").write_text("x", encoding="utf-8")
        self.assertEqual(guild.publish_deliverables(self.q)["published"], ["Q001_t.md"])


class DigestShapeTest(Base):
    def test_a_non_dict_archive_json_does_not_hide_the_quest(self):
        guild.save_plan(self.q / "plan.json", {"quest": "Q001", "title": "t", "series": "s", "approved": False, "status": "active", "goals": [
            {"id": "G1", "title": "x", "kind": "auto", "class": "wizard", "deps": [], "criteria": dict(CRIT), "state": "pending", "retries": 0, "output": None}]})
        (self.q / "archive.json").write_text("[1]", encoding="utf-8")
        d = guild.digest(self.root)
        self.assertEqual([q["id"] for q in d["quests"]], ["Q001"])
        self.assertEqual(d["needs_total"], 1)  # 計画の承認待ちは、消えない


class FormatDeliverablesTest(Base):
    def done(self, fmt):
        plan = {"quest": "Q001", "title": "週報", "series": "s", "approved": True, "status": "active", "goals": [
            {"id": "G1", "title": "x", "kind": "auto", "class": "alchemist", "deps": [], "criteria": dict(CRIT), "deliverable": True,
             "format": fmt, "state": "done", "retries": 0, "output": None}]}
        guild.save_plan(self.q / "plan.json", plan)
        d = self.q / "output" / "G1"
        d.mkdir(parents=True, exist_ok=True)
        for n in ("memo.md", "report.html", "flow.mmd"):
            (d / n).write_text("x", encoding="utf-8")
        (d / "スライド.prompt.md").write_text("p", encoding="utf-8")

    def names(self):
        return sorted(f.name for f in (self.gdir / "deliverables").iterdir())

    def test_only_the_chosen_format_is_published_so_the_title_names_it(self):
        self.done("html")
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_スライド.prompt.md", "Q001_週報.html"])  # .md のメモは混ざらない
        self.done("mermaid")
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_スライド.prompt.md", "Q001_週報.mmd"])
        self.done("md")
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_スライド.prompt.md", "Q001_週報.md"])


class OneLineTest(unittest.TestCase):
    def test_plain_one_line_keeps_marks_and_codex_line_drops_them(self):
        self.assertEqual(guild.one_line("+81 国際電話"), "+81 国際電話")
        self.assertEqual(guild.one_line("**もう一度** — x"), "**もう一度** — x")
        self.assertEqual(guild.codex_line("+81 国際電話"), "81 国際電話")
        self.assertEqual(guild.one_line("a" + chr(10) + "b"), "a b")

    def test_a_title_made_of_marks_is_kept(self):
        errs, _, title, _ = guild.check_meta({"title": "+81 の確認", "series": "国際電話"})
        self.assertEqual((errs, title), ([], "+81 の確認"))

    def test_archive_entry_names_keep_their_marks(self):
        with tempfile.TemporaryDirectory() as d:
            guild.init_guild(d)
            rel = guild.write_entry(Path(d) / "guild" / "archive", {"type": "term", "name": "+81", "summary": "国番号", "body": "", "confidence": "guess", "source": ""})
            self.assertEqual(guild.read_entry(Path(d) / "guild" / "archive" / rel)["name"], "+81")

    def test_advice_with_bold_marks_is_kept_whole(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d)
            (q / "reports").mkdir()
            (q / "reports" / "G1-appraiser.md").write_text("## 判定\nrejected\n## 勧める対応\n**もう一度** — 直せる\n", encoding="utf-8")
            self.assertIsNone(guild.advice_of(q, "G1"))  # 先頭が ** のものは、決まった書き出しではないので、拾わない（誤解を避ける）


if __name__ == "__main__":
    unittest.main()

"""AI 社員 Phase 3：依頼のタイトルと series、納品形式（md・html・mermaid）。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402

GUILD_PY = str(ROOT / "skills" / "quest" / "guild.py")
CRIT = {"viewpoint": "v", "pass_line": "p", "check": "c"}
TR = guild.load_transitions()


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def g(i, **kw):
    t = {"id": i, "title": f"{i}をする", "kind": "auto", "class": "wizard", "deps": [], "criteria": dict(CRIT)}
    t.update(kw)
    return t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.gdir = self.root / "guild"
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, **kw):
        d = {"quest": "Q001", "title": "週報の作成", "series": "週報", "goals": [g("G1", deliverable=True)]}
        d.update(kw)
        write(self.q / "reports" / "plan-draft.json", d)

    def adopt(self):
        return guild.adopt(self.q / "plan.json", TR)

    def plan(self):
        return json.loads((self.q / "plan.json").read_text(encoding="utf-8"))


class MetaCheckTest(unittest.TestCase):
    def test_title_and_series_are_required(self):
        errs, warns, t, s = guild.check_meta({"title": "A 社見積書の確認", "series": "見積書の確認"})
        self.assertEqual((errs, warns, t, s), ([], [], "A 社見積書の確認", "見積書の確認"))
        for bad in ({}, {"title": "x"}, {"series": "x"}, {"title": " ", "series": "x"}, {"title": 3, "series": None}):
            self.assertTrue(guild.check_meta(bad)[0], bad)

    def test_long_values_warn_then_fail(self):
        errs, warns, *_ = guild.check_meta({"title": "あ" * 25, "series": "x"})
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 1)
        self.assertTrue(guild.check_meta({"title": "あ" * 81, "series": "x"})[0])
        self.assertEqual(guild.check_meta({"title": "あ" * 24, "series": "い" * 24})[1], [])

    def test_whitespace_and_newlines_are_normalised(self):
        _, _, t, s = guild.check_meta({"title": " a" + chr(10) + "b ", "series": "## 見出し"})
        self.assertEqual((t, s), ("a b", "## 見出し"))  # タイトルの記号は落とさない（掟の 1 行とは別）


class AdoptMetaTest(Base):
    def test_adopt_stores_title_and_series(self):
        self.draft()
        self.adopt()
        p = self.plan()
        self.assertEqual((p["title"], p["series"]), ("週報の作成", "週報"))

    def test_adopt_rejects_a_draft_without_series_or_title(self):
        self.draft(series="")
        with self.assertRaises(guild.GuildError):
            self.adopt()
        self.draft(title="")
        with self.assertRaises(guild.GuildError):
            self.adopt()
        self.assertFalse((self.q / "plan.json").exists())

    def test_long_title_is_only_a_warning(self):
        self.draft(title="あ" * 30)
        self.adopt()
        self.assertTrue(any("24 字" in w for w in self.plan()["check"]["warnings"]))

    def test_the_requesters_edits_survive_a_replan(self):
        self.draft()
        self.adopt()
        p = self.plan()
        write(self.q / "inbox" / "1-meta.json", {"type": "meta", "title": "営業部の週報", "series": "営業の週報"})
        guild.ingest(self.q / "plan.json", p, TR, commit=lambda: guild.save_plan(self.q / "plan.json", p))
        p["approved"], p["status"] = True, "replan"
        guild.save_plan(self.q / "plan.json", p)
        self.draft(title="受付係の新しい題", series="新しい series")
        self.adopt()
        p2 = self.plan()
        self.assertEqual((p2["title"], p2["series"]), ("営業部の週報", "営業の週報"))
        self.assertEqual(p2["meta_locked"], ["series", "title"])

    def test_unlocked_values_follow_the_new_draft_on_replan(self):
        self.draft()
        self.adopt()
        p = self.plan()
        p["status"] = "replan"
        guild.save_plan(self.q / "plan.json", p)
        self.draft(title="新しい題", series="新しい series")
        self.adopt()
        self.assertEqual((self.plan()["title"], self.plan()["series"]), ("新しい題", "新しい series"))


class MetaInputTest(Base):
    def setUp(self):
        super().setUp()
        self.draft()
        self.adopt()

    def ingest(self, data):
        write(self.q / "inbox" / "1-meta.json", data)
        p = self.plan()
        r = guild.ingest(self.q / "plan.json", p, TR, commit=lambda: guild.save_plan(self.q / "plan.json", p))
        return r

    def test_changes_title_and_locks_it(self):
        r = self.ingest({"type": "meta", "title": "  新しい題  "})
        self.assertEqual(r["rejected"], [])
        p = self.plan()
        self.assertEqual((p["title"], p["series"], p["meta_locked"]), ("新しい題", "週報", ["title"]))
        self.assertEqual(p["history"][-1]["event"], "meta")

    def test_series_only_and_both(self):
        self.ingest({"type": "meta", "series": "別の series"})
        self.assertEqual(self.plan()["meta_locked"], ["series"])
        write(self.q / "inbox" / "2-meta.json", {"type": "meta", "title": "題", "series": "また別"})
        p = self.plan()
        guild.ingest(self.q / "plan.json", p, TR, commit=lambda: guild.save_plan(self.q / "plan.json", p))
        self.assertEqual(self.plan()["meta_locked"], ["series", "title"])

    def test_bad_input_is_rejected(self):
        for bad in ({"type": "meta"}, {"type": "meta", "title": ""}, {"type": "meta", "title": 5}, {"type": "meta", "title": "あ" * 81}):
            self.assertEqual(len(self.ingest(bad)["rejected"]), 1, bad)
            for f in (self.q / "inbox" / "rejected").glob("*"):
                f.unlink()
        self.assertEqual(self.plan()["title"], "週報の作成")

    def test_rejected_while_replanning_or_aborted(self):
        for status in ("replan", "aborted"):
            p = self.plan()
            p["status"] = status
            guild.save_plan(self.q / "plan.json", p)
            self.assertEqual(len(self.ingest({"type": "meta", "title": "x"})["rejected"]), 1, status)
            for f in (self.q / "inbox" / "rejected").glob("*"):
                f.unlink()

    def test_renaming_after_accept_republishes_under_the_new_title(self):
        p = self.plan()
        p["approved"], p["accepted"] = True, True
        p["goals"][0]["state"] = "done"
        guild.save_plan(self.q / "plan.json", p)
        out = self.q / "output" / "G1"
        out.mkdir(parents=True)
        (out / "報告.md").write_text("本文", encoding="utf-8")
        guild.publish_deliverables(self.q)
        self.assertEqual([f.name for f in (self.gdir / "deliverables").iterdir()], ["Q001_週報の作成.md"])
        self.ingest({"type": "meta", "title": "営業部の週報"})
        self.assertEqual([f.name for f in (self.gdir / "deliverables").iterdir()], ["Q001_営業部の週報.md"])


class FormatTest(Base):
    def request(self, fmt):
        write(self.q / "request.json", {"type": "request", "text": "x", "format": fmt} if fmt else {"type": "request", "text": "x"})

    def test_request_format_defaults_to_md_and_unknown_falls_back(self):
        self.request(None)
        self.assertEqual(guild.request_format(self.q), "md")
        self.request("html")
        self.assertEqual(guild.request_format(self.q), "html")
        self.request("pptx")
        self.assertEqual(guild.request_format(self.q), "md")

    def test_adopt_sets_the_deliverable_format_from_the_request(self):
        self.request("mermaid")
        self.draft(goals=[g("G1"), g("G2", deliverable=True, deps=["G1"])])
        self.adopt()
        goals = {t["id"]: t for t in self.plan()["goals"]}
        self.assertEqual(goals["G2"]["format"], "mermaid")
        self.assertNotIn("format", goals["G1"])

    def test_adopt_rejects_a_conflicting_format(self):
        self.request("html")
        self.draft(goals=[g("G1", deliverable=True, format="mermaid")])
        with self.assertRaises(guild.GuildError):
            self.adopt()

    def test_validate_rejects_an_unknown_goal_format(self):
        errs = guild.validate({"goals": [dict(g("G1"), state="pending", format="pptx")]}, TR)
        self.assertTrue(any("format" in e for e in errs))

    def test_new_quest_rejects_an_unknown_request_format(self):
        write(self.gdir / ".work" / "requests" / "R1.json", {"type": "request", "text": "x", "format": "pptx", "inputs": [], "files": []})
        with self.assertRaises(guild.GuildError):
            guild.new_quest(self.root, "R1")
        self.assertTrue((self.gdir / ".work" / "requests" / "rejected" / "R1.json").exists())

    def test_new_quest_accepts_known_formats(self):
        for i, fmt in enumerate(("md", "html", "mermaid")):
            write(self.gdir / ".work" / "requests" / f"R{i}.json", {"type": "request", "text": "x", "format": fmt, "inputs": [], "files": []})
            q = Path(guild.new_quest(self.root, f"R{i}")["dir"])
            self.assertEqual(json.loads((q / "request.json").read_text(encoding="utf-8"))["format"], fmt)


class PublishFormatTest(Base):
    def done_plan(self, fmt, extra_goal=False):
        goals = [dict(g("G1", deliverable=True, format=fmt), state="done")]
        if extra_goal:
            goals.insert(0, dict(g("G0"), state="done"))
        guild.save_plan(self.q / "plan.json", {"quest": "Q001", "title": "週報: 営業/部?", "series": "週報", "approved": True, "status": "active", "goals": goals})

    def out(self, gid, name, body="x"):
        d = self.q / "output" / gid
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body, encoding="utf-8")

    def names(self):
        d = self.gdir / "deliverables"
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def test_html_and_mermaid_deliverables_are_published_with_the_title(self):
        self.done_plan("html")
        self.out("G1", "report.html", "<p>x</p>")
        self.out("G1", "memo.txt")
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_週報 営業 部.html"])  # 使えない文字は空白にする
        self.done_plan("mermaid")
        self.out("G1", "flow.mmd", "graph TD; A-->B")
        (self.q / "output" / "G1" / "report.html").unlink()
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_週報 営業 部.mmd"])

    def test_md_goal_does_not_publish_html_files(self):
        self.done_plan("md")
        self.out("G1", "a.md")
        self.out("G1", "b.html")
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_週報 営業 部.md"])

    def test_several_deliverable_files_keep_their_own_names(self):
        self.done_plan("md")
        self.out("G1", "a.md")
        self.out("G1", "b.md")
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_a.md", "Q001_b.md"])

    def test_prompt_files_do_not_count_as_the_main_file(self):
        self.done_plan("md", extra_goal=True)
        self.out("G1", "a.md")
        self.out("G0", "スライド.prompt.md")
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_スライド.prompt.md", "Q001_週報 営業 部.md"])

    def test_a_title_that_is_only_symbols_falls_back_to_the_file_name(self):
        self.done_plan("md")
        p = json.loads((self.q / "plan.json").read_text(encoding="utf-8"))
        p["title"] = "///"
        guild.save_plan(self.q / "plan.json", p)
        self.out("G1", "a.md")
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_a.md"])


class PastQuestsTest(Base):
    def test_lists_titles_and_series_newest_first_and_skips_legacy_and_broken(self):
        self.draft()
        self.adopt()
        q2 = Path(guild.new_quest(self.root)["dir"])
        write(q2 / "plan.json", {"quest": "Q002", "todos": []})
        q3 = Path(guild.new_quest(self.root)["dir"])
        (q3 / "plan.json").write_text("{", encoding="utf-8")
        q4 = Path(guild.new_quest(self.root)["dir"])
        write(q4 / "plan.json", {"quest": "Q004", "title": "別の依頼", "series": "別", "goals": []})
        self.assertEqual(guild.past_quests(self.root), [{"id": "Q004", "title": "別の依頼", "series": "別"}, {"id": "Q001", "title": "週報の作成", "series": "週報"}])

    def test_limit_and_cli(self):
        self.draft()
        self.adopt()
        r = subprocess.run([sys.executable, GUILD_PY, "past-quests", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)[0]["series"], "週報")
        self.assertEqual(guild.past_quests(self.root, limit=0), [])

    def test_empty_guild_gives_an_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(guild.past_quests(d), [])


class DocsTest(unittest.TestCase):
    def read(self, *p):
        return ROOT.joinpath(*p).read_text(encoding="utf-8")

    def test_receptionist_explains_title_series_and_format(self):
        s = self.read("agents", "receptionist.md")
        for needle in ("`series`", "24 字以内", "past-quests", "`format`", "タイトルは共通にしない"):
            self.assertIn(needle, s, needle)

    def test_executors_know_the_formats(self):
        for name in ("wizard", "alchemist"):
            s = self.read("agents", f"{name}.md")
            for needle in (".html", ".mmd", "mermaid"):
                self.assertIn(needle, s, f"{name}: {needle}")

    def test_skill_passes_past_quests_and_format(self):
        s = self.read("skills", "quest", "SKILL.md")
        for needle in ("past-quests", "`format`"):
            self.assertIn(needle, s, needle)


if __name__ == "__main__":
    unittest.main()

"""AI 社員 Phase 4 のレビュー反映：deliver_to の抜け穴、受け取りまでのコピー、総合確認の判定のゆれ、危険語、引き継ぎ。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
sys.path.insert(0, str(ROOT / "tests"))
import guild  # noqa: E402

CRIT = {"viewpoint": "viewpoint 十分に具体的", "pass_line": "pass_line 十分に具体的", "check": "check 十分に具体的"}
TR = guild.load_transitions()
SPEC = {"headings": ["結論"], "reader": "部長"}
GUILD_PY = str(ROOT / "skills" / "quest" / "guild.py")


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def g(i, **kw):
    t = {"id": i, "title": f"{i}を調べる", "kind": "auto", "class": "wizard", "effects": "none", "deps": [], "criteria": dict(CRIT)}
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


def make_link(link, target):
    """シンボリックリンクを作る。権限がない Windows では、ジャンクション（mklink /J。管理者権限が要らない）で代える。"""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if r.returncode != 0:
            raise OSError("ジャンクションを作れませんでした")


class DeliverToHardeningTest(Base):
    def test_names_windows_would_rewrite_are_refused(self):
        for bad in ("guild.", ".git.", "docs.", "guild /x", "CON", "con", "Con.txt", "NUL", "aux", "docs/COM1", "lpt9.log", "GUILD~1", "docs/ab~2", "x/prn"):
            with self.assertRaises(guild.GuildError, msg=repr(bad)):
                guild.check_deliver_to(self.q, bad)

    def test_similar_but_ordinary_names_are_accepted(self):
        for ok in ("docs/console", "docs/connect", "a.b", "文書/報告", "reports_2026", "com10", "guilds", "my.guild"):
            self.assertEqual(guild.check_deliver_to(self.q, ok), ok)

    def test_a_link_into_guild_or_git_is_refused_after_resolving(self):
        (self.root / ".git").mkdir()
        for name, target in (("viaguild", self.gdir), ("viagit", self.root / ".git")):
            link = self.root / name
            try:
                make_link(link, target)
            except (OSError, NotImplementedError):
                self.skipTest("シンボリックリンクを作れない環境です")
            with self.assertRaises(guild.GuildError, msg=name):
                guild.check_deliver_to(self.q, name)
            with self.assertRaises(guild.GuildError, msg=name):
                guild.check_deliver_to(self.q, name + "/sub")

    def test_a_link_to_the_outside_is_refused(self):
        with tempfile.TemporaryDirectory() as outside:
            link = self.root / "out"
            try:
                make_link(link, outside)
            except (OSError, NotImplementedError):
                self.skipTest("シンボリックリンクを作れない環境です")
            with self.assertRaises(guild.GuildError):
                guild.check_deliver_to(self.q, "out")


def done_plan(q, deliver_to="docs/reports", accepted=True):
    plan = {"quest": q.name, "title": "週報", "series": "s", "approved": True, "status": "active", "accepted": accepted,
            **({"deliver_to": deliver_to} if deliver_to else {}),
            "goals": [dict(g("G1", deliverable=True), state="done", retries=0, output=None)]}
    guild.save_json(q / "plan.json", plan)
    out = q / "output" / "G1"
    out.mkdir(parents=True, exist_ok=True)
    (out / "a.md").write_text("本文", encoding="utf-8")
    return plan


class CopyOnlyAfterAcceptTest(Base):
    def test_before_accept_only_the_guild_folder_gets_the_files(self):
        done_plan(self.q, accepted=False)
        r = guild.publish_deliverables(self.q)
        self.assertNotIn("delivered_to", r)
        self.assertTrue((self.gdir / "deliverables" / "Q001_週報.md").exists())
        self.assertFalse((self.root / "docs").exists())
        self.assertFalse((self.q / "delivered.json").exists())

    def test_after_accept_the_files_are_copied(self):
        done_plan(self.q, accepted=True)
        self.assertEqual(guild.publish_deliverables(self.q)["delivered_to"], "docs/reports")
        self.assertTrue((self.root / "docs" / "reports" / "Q001_週報.md").exists())

    def test_the_record_is_written_before_copying_so_a_failure_can_be_undone(self):
        done_plan(self.q)
        (self.q / "output" / "G1" / "b.md").write_text("b", encoding="utf-8")
        real = shutil.copy2
        calls = []

        def flaky(src, dst, *a, **k):
            calls.append(str(dst))
            if len(calls) > 2 and "docs" in str(dst):  # deliverables/ には 2 件置けて、docs/ への 2 件目で失敗する
                raise OSError("使用中")
            return real(src, dst, *a, **k)
        with mock.patch.object(guild.shutil, "copy2", side_effect=flaky):
            with self.assertRaises(OSError):
                guild.publish_deliverables(self.q)
        self.assertTrue((self.q / "delivered.json").exists())
        guild.unpublish_deliverables(self.q)
        self.assertEqual(list((self.root / "docs" / "reports").glob("Q001_*")), [])

    def test_accept_through_ingest_survives_a_publish_guilderror(self):
        done_plan(self.q, accepted=False)
        (self.q / "reports").mkdir(exist_ok=True)
        (self.q / "reports" / guild.OVERALL_REPORT).write_text("## 判定\n満たしている\n", encoding="utf-8")
        write(self.q / "inbox" / "1-accept.json", {"type": "accept"})
        p = guild.load_json(self.q / "plan.json")
        with mock.patch.object(guild, "publish_deliverables", side_effect=guild.GuildError("deliver_to が壊れた")):
            r = guild.ingest(self.q / "plan.json", p, TR)
        self.assertEqual(r["rejected"], [])  # 受け取りは、拒否にしない
        self.assertTrue(p["accepted"])
        self.assertTrue(any("納品物の置き直しに失敗" in w for w in r["warnings"]))
        self.assertTrue((self.q / "inbox" / "done" / "1-accept.json").exists())


class OverallJudgementTest(Base):
    def state(self, text, bom=False):
        (self.q / "reports").mkdir(exist_ok=True)
        data = text.encode("utf-8")
        (self.q / "reports" / guild.OVERALL_REPORT).write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
        return guild.overall_state(self.q)

    def test_decorations_and_bom_are_tolerated(self):
        for text, want in (("## 判定\n**不足あり**\n", "gaps"), ("## 判定\n- 満たしている\n", "ok"), ("## 判定\n`満たしている`\n", "ok"),
                           ("## 判定\n> 不足あり — 理由\n", "gaps"), ("## 判定\n__満たしている__\n", "ok"), ("## 判定\n満たしていない\n", None),
                           ("## 判定\n* * *\n", None), ("## 判定\n\n満たしている\n", "ok")):
            self.assertEqual(self.state(text), want, text)
            self.assertEqual(self.state(text, bom=True), want, "BOM: " + text)

    def test_crlf(self):
        self.assertEqual(self.state("## 判定\r\n満たしている\r\n## 不足\r\nなし\r\n"), "ok")


class OverallSkipTest(Base):
    def test_skip_writes_an_honest_gaps_report(self):
        r = guild.overall_skip(self.q)
        self.assertTrue(Path(r["written"]).is_file())
        self.assertEqual(guild.overall_state(self.q), "gaps")
        body = (self.q / "reports" / guild.OVERALL_REPORT).read_text(encoding="utf-8")
        self.assertIn("総合確認ができませんでした", body)
        self.assertNotIn("満たしている", body)  # 判定を作り上げない

    def test_skip_refuses_when_the_check_is_done(self):
        (self.q / "reports").mkdir(exist_ok=True)
        (self.q / "reports" / guild.OVERALL_REPORT).write_text("## 判定\n満たしている\n", encoding="utf-8")
        with self.assertRaises(guild.GuildError):
            guild.overall_skip(self.q)

    def test_skip_overwrites_an_unreadable_report(self):
        (self.q / "reports").mkdir(exist_ok=True)
        (self.q / "reports" / guild.OVERALL_REPORT).write_text("よく分からない", encoding="utf-8")
        guild.overall_skip(self.q)
        self.assertEqual(guild.overall_state(self.q), "gaps")

    def test_cli_and_docs(self):
        r = subprocess.run([sys.executable, GUILD_PY, "overall-skip", str(self.q)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("overall-skip", (ROOT / "docs" / "graph-format.md").read_text(encoding="utf-8"))
        self.assertIn("overall-skip", (ROOT / "skills" / "quest" / "SKILL.md").read_text(encoding="utf-8"))

    def test_accept_is_possible_after_a_skip(self):
        plan = done_plan(self.q, deliver_to=None, accepted=False)
        guild.overall_skip(self.q)
        v = guild.next_view(plan, self.q)
        self.assertEqual((v["awaiting_overall"], v["awaiting_accept"], v["overall"]), (False, True, "gaps"))


class DangerWordsTest(unittest.TestCase):
    def warns(self, title, pass_line="p" * 8):
        plan = {"goals": [g("G1", title=title, deliverable=True, deliverable_spec=SPEC, criteria={"viewpoint": "viewpoint 十分に具体的", "pass_line": pass_line, "check": "check 十分に具体的"})]}
        return [w for w in guild.plan_quality(plan, None)[1] if "effects が none" in w]

    def test_harmless_nouns_are_not_flagged(self):
        for t in ("公開情報を調べる", "公開されている価格表を比べる", "共有フォルダの一覧を読む", "掲載されている記事の要約", "申請書の書き方を調べる"):
            self.assertEqual(self.warns(t), [], t)

    def test_actions_are_flagged(self):
        for t in ("結果を公開する", "部長に共有して確認する", "フォームに投稿", "メールを下書きして送信", "本番へデプロイ", "push する", "Send the report", "upload files", "旧版を削除", "Slack に通知"):
            self.assertTrue(self.warns(t), t)

    def test_criteria_text_is_checked_too(self):
        self.assertTrue(self.warns("調べる", pass_line="確認後に公開して終わる"))


class CarryOverSafetyTest(unittest.TestCase):
    def carried(self, old_kw, new_kw):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "reports").mkdir()
            old = {"quest": "Q1", "title": "t", "approved": True, "status": "replan",
                   "goals": [dict(g("G1", deliverable=True, deliverable_spec=SPEC, format="md"), **old_kw, state="done", retries=0, output=None)]}
            guild.save_json(d / "plan.json", old)
            draft = {"quest": "Q1", "title": "t", "series": "s", "goals": [dict(g("G1", deliverable=True, deliverable_spec=SPEC), **new_kw)]}
            write(d / "reports" / "plan-draft.json", draft)
            return guild.adopt(d / "plan.json", TR)["carried"]

    def test_unchanged_is_carried(self):
        self.assertEqual(self.carried({}, {}), ["G1"])

    def test_changes_that_alter_the_work_or_its_safety_are_redone(self):
        self.assertEqual(self.carried({}, {"deliverable_spec": {"headings": ["別の構成"], "reader": "部長"}}), [])
        self.assertEqual(self.carried({}, {"effects": "external", "confirm": True}), [])
        self.assertEqual(self.carried({"effects": "external", "confirm": True}, {}), [])
        self.assertEqual(self.carried({}, {"confirm": True}), [])


class StaleOverallTest(Base):
    def test_a_report_that_cannot_be_moved_is_removed_instead_of_left_behind(self):
        (self.q / "reports").mkdir(exist_ok=True)
        f = self.q / "reports" / guild.OVERALL_REPORT
        f.write_text("## 判定\n満たしている\n", encoding="utf-8")
        with mock.patch.object(guild.shutil, "move", side_effect=OSError("使用中")):
            guild.archive_outputs({"goals": []}, [], self.q)
        self.assertFalse(f.exists())


class CodexAndBoardTest(unittest.TestCase):
    def test_codex_forbids_external_effects_for_none_goals(self):
        s = (ROOT / "skills" / "quest" / "codex.md").read_text(encoding="utf-8")
        self.assertIn("`effects` が `none`", s)
        self.assertIn("実行せずに", s)

    @unittest.skipUnless(shutil.which("node"), "node がありません")
    def test_board_judges_the_report_like_guild_py(self):
        from test_board_js import extract, node_eval
        funcs = "".join(extract(n) + "\n" for n in ("excerpt", "reportSection", "overallJudge"))
        code = funcs + r"""
const r = (b) => '## 判定\n' + b + '\n## 不足\nなし';
console.log(JSON.stringify([overallJudge(r('満たしている')), overallJudge(r('**不足あり**')), overallJudge(r('- 満たしている')), overallJudge(r('`満たしている`')),
  overallJudge(r('たぶん')), overallJudge(''), overallJudge(null), overallJudge('満たしている')]));"""
        self.assertEqual(node_eval(code), ["ok", "gaps", "ok", "ok", None, None, None, None])

    def test_board_uses_the_same_rule_and_strips_bom(self):
        board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        for needle in ("function overallJudge(txt)", "overallJudge(q.overall) !== null", "const judge = overallJudge(txt)", "判定を読み取れませんでした",
                       "replace(/^" + chr(92) + "uFEFF/, '')"):
            self.assertIn(needle, board, needle)


if __name__ == "__main__":
    unittest.main()


class RejectedRedoArchiveTest(Base):
    """鑑定士の不合格で目標をやり直すとき、古い成果物は prev/ へ退避し、報告（鑑定士の指摘）は残す。"""

    def test_rejected_moves_output_but_keeps_reports(self):
        plan = {"start": "2026-01-01", "due": "2026-01-31", "approved": True, "goals": [g("G1", state="review", retries=0)], "history": []}
        write(self.q / "plan.json", plan)
        (self.q / "output" / "G1").mkdir(parents=True)
        (self.q / "output" / "G1" / "old.md").write_text("古い版", encoding="utf-8")
        (self.q / "reports").mkdir(exist_ok=True)
        (self.q / "reports" / "G1-appraiser.md").write_text("## 判定\nrejected\n", encoding="utf-8")
        r = subprocess.run([sys.executable, GUILD_PY, "advance", str(self.q / "plan.json"), "G1", "rejected"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.q / "output" / "G1").exists())
        self.assertEqual(len(list((self.q / "prev").glob("*/output/G1/old.md"))), 1)
        self.assertTrue((self.q / "reports" / "G1-appraiser.md").is_file())


class QuestionsGoToTheBoardTest(unittest.TestCase):
    def test_instructions_keep_questions_out_of_the_chat(self):
        r = (ROOT / "agents" / "receptionist.md").read_text(encoding="utf-8")
        self.assertIn("返り値の文章で質問しない", r)
        self.assertIn("ファイルの中身そのもの", r)
        s = (ROOT / "skills" / "quest" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("チャットで依頼主に聞かない", s)

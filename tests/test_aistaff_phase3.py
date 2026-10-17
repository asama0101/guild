"""AI 社員 Phase 3：クエストログ（digest）、勧める対応、次の提案。"""
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


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def goal(i, state="pending", kind="auto", deps=(), **kw):
    t = {"id": i, "title": f"{i}をする", "kind": kind, "deps": list(deps), "criteria": dict(CRIT), "state": state, "retries": 0, "output": None}
    if kind == "auto":
        t["class"] = "wizard"
        t["effects"] = "external" if kw.get("confirm") else "none"
    t.update(kw)
    return t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, *goals, **kw):
        p = {"quest": self.q.name, "title": "週報の作成", "series": "週報", "approved": True, "status": "active", "goals": list(goals)}
        p.update(kw)
        guild.save_plan(self.q / "plan.json", p)
        return p

    def report(self, name, text):
        (self.q / "reports").mkdir(exist_ok=True)
        (self.q / "reports" / name).write_text(text, encoding="utf-8")


class AdviceTest(Base):
    def advice(self, body):
        self.report("G1-appraiser.md", f"## 判定\nrejected\n## 指摘\nx\n## 勧める対応\n{body}\n## 出典の確認\nなし\n")
        return guild.advice_of(self.q, "G1")

    def test_each_action_is_recognised_from_the_first_line(self):
        self.assertEqual(self.advice("もう一度 — 記述の不足だけなので、直せる")["action"], "retry")
        self.assertEqual(self.advice("計画を直す — 目標の分け方が合っていない")["action"], "replan")
        self.assertEqual(self.advice("やめる — 取れない情報で、依頼主の判断が要る")["action"], "drop")

    def test_text_is_one_line(self):
        a = self.advice("もう一度 — 理由\n二行目は無視される")
        self.assertEqual(a["text"], "もう一度 — 理由")

    def test_unknown_none_empty_and_missing_are_none(self):
        self.assertIsNone(self.advice("なし"))
        self.assertIsNone(self.advice("好きにして"))
        self.assertIsNone(self.advice(""))
        self.assertIsNone(guild.advice_of(self.q, "G9"))

    def test_section_of_stops_at_the_next_heading_and_ignores_similar_titles(self):
        text = "## 勧める対応の補足\nあ\n## 勧める対応\nい\n## 次\nう\n"
        self.assertEqual(guild.section_of(text, "勧める対応"), "い")
        self.assertEqual(guild.section_of(text, "ない"), "")

    def test_appraiser_doc_describes_the_section(self):
        s = (ROOT / "agents" / "appraiser.md").read_text(encoding="utf-8")
        for needle in ("## 勧める対応", "もう一度", "計画を直す", "やめる"):
            self.assertIn(needle, s, needle)


class DigestTest(Base):
    def test_digest_summarises_progress_workers_needs_and_blockers(self):
        self.plan(goal("G1", "done"), goal("G2", "running", **{"class": "alchemist", "effects": "none"}), goal("G3", "failed"), goal("G4", "blocked", deps=["G3"]),
                  goal("G5", "waiting_user", kind="human", instruction="やる"), goal("G6", "awaiting_confirm", confirm=True))
        self.report("G3-appraiser.md", "## 判定\nrejected\n## 勧める対応\nやめる — 取れない\n")
        d = guild.digest(self.root)
        q = d["quests"][0]
        self.assertEqual((q["title"], q["series"], q["label"]), ("週報の作成", "週報", "あなたの番"))
        self.assertEqual(q["goals"], {"total": 6, "done": 1, "failed": 1, "skipped": 0})
        self.assertEqual(q["active"], [{"id": "G2", "title": "G2をする", "class": "alchemist", "state": "running"}])
        self.assertEqual(q["blockers"], [{"goal": "G4", "because": ["G3"]}])
        kinds = sorted(n["kind"] for n in q["needs"])
        self.assertEqual(kinds, ["confirm", "decision", "result"])
        dec = next(n for n in q["needs"] if n["kind"] == "decision")
        self.assertEqual(dec["advice"]["action"], "drop")
        self.assertEqual(d["needs_total"], 3)
        self.assertIn("rejected_per_goal", d["stats"])

    def test_digest_is_written_to_clog_json(self):
        self.plan(goal("G1", "running"))
        guild.digest(self.root)
        saved = json.loads((self.root / "guild" / ".work" / "clog.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["quests"][0]["label"], "進行中")
        self.assertIn("t", saved)

    def test_labels_for_unapproved_complete_aborted_and_accept(self):
        self.plan(goal("G1", "pending"), approved=False)
        q = guild.digest(self.root)["quests"][0]
        self.assertEqual((q["label"], q["needs"][0]["kind"]), ("あなたの番", "approve"))
        self.plan(goal("G1", "done"))
        q = guild.digest(self.root)["quests"][0]
        self.assertEqual((q["label"], q["needs"]), ("総合確認中", []))  # 受け取りの前に、受付係の総合確認がある
        self.report("overall-receptionist.md", "## 判定\n満たしている\n")
        q = guild.digest(self.root)["quests"][0]
        self.assertEqual((q["label"], q["needs"][0]["kind"]), ("あなたの番", "accept"))
        self.plan(goal("G1", "done"), accepted=True)
        self.assertEqual(guild.digest(self.root)["quests"][0]["label"], "完了")
        self.plan(goal("G1", "running"), status="aborted")
        self.assertEqual(guild.digest(self.root)["quests"][0]["label"], "中止")

    def test_quest_without_plan_is_decomposing_or_asking(self):
        write(self.q / "request.json", {"type": "request", "text": "とても長い依頼文" * 10})
        q = guild.digest(self.root)["quests"][0]
        self.assertEqual(q["label"], "分解中")
        self.assertLessEqual(len(q["title"]), 24)
        write(self.q / "reports" / "plan-draft.json", {"questions": [{"text": "どれ？"}]})
        self.assertEqual(guild.digest(self.root)["quests"][0]["label"], "質問あり")
        write(self.q / "inbox" / "1-answers.json", {"type": "answers", "answers": []})
        self.assertEqual(guild.digest(self.root)["quests"][0]["label"], "分解中")

    def test_legacy_and_broken_quests_do_not_stop_the_digest(self):
        self.plan(goal("G1", "running"))
        q2 = Path(guild.new_quest(self.root)["dir"])
        write(q2 / "plan.json", {"quest": q2.name, "todos": []})
        q3 = Path(guild.new_quest(self.root)["dir"])
        (q3 / "plan.json").write_text("{", encoding="utf-8")
        labels = {q["id"]: q["label"] for q in guild.digest(self.root)["quests"]}
        self.assertEqual(labels[self.q.name], "進行中")
        self.assertEqual(labels[q2.name], "旧形式")
        self.assertNotIn(q3.name, labels)

    def test_archive_proposal_and_followups_appear(self):
        self.plan(goal("G1", "done"), accepted=True)
        write(self.q / "archive.json", {"status": "proposed", "candidates": [], "registered": [], "followups": ["来週分も作る"], "decided": {}})
        q = guild.digest(self.root)["quests"][0]
        self.assertIn("archive", [n["kind"] for n in q["needs"]])
        self.assertEqual(q["followups"], ["来週分も作る"])

    def test_cli_digest_and_wait_updates_the_log(self):
        self.plan(goal("G1", "running"))
        r = subprocess.run([sys.executable, GUILD_PY, "digest", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["quests"][0]["label"], "進行中")
        clog = self.root / "guild" / ".work" / "clog.json"
        clog.unlink()
        r = subprocess.run([sys.executable, GUILD_PY, "wait", str(self.root), "0.2"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(clog.is_file())  # 待機の直前に、ログが更新される


class FollowupTest(Base):
    def propose(self, followups):
        write(self.q / "reports" / "archive-draft.json", {"quest": "Q001", "followups": followups, "candidates": []})
        return guild.archive_propose(self.q)

    def test_followups_are_kept_in_archive_json_and_returned(self):
        r = self.propose(["来週分も作る", "  先方の返信を確認する  "])
        self.assertEqual(r["followups"], ["来週分も作る", "先方の返信を確認する"])
        saved = json.loads((self.q / "archive.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["followups"], r["followups"])
        self.assertEqual(r["status"], "done")  # 提案だけでは、確認待ちにならない

    def test_at_most_three_and_80_chars_and_junk_is_dropped(self):
        r = self.propose(["あ" * 200, "", None, 3, "い", "う", "え"])
        self.assertEqual(len(r["followups"]), 3)
        self.assertEqual(len(r["followups"][0]), guild.FOLLOWUP_MAX)

    def test_wrong_shape_is_ignored(self):
        self.assertEqual(self.propose("来週分")["followups"], [])
        self.assertEqual(self.propose({"a": 1})["followups"], [])

    def test_followups_are_one_line(self):
        self.assertEqual(self.propose(["a" + chr(10) + "## 見出し" + chr(13) + "b"])["followups"], ["a ## 見出し b"])

    def test_librarian_doc_describes_followups(self):
        s = (ROOT / "agents" / "librarian.md").read_text(encoding="utf-8")
        self.assertIn("followups", s)
        self.assertIn("依頼にはしない", s)


if __name__ == "__main__":
    unittest.main()

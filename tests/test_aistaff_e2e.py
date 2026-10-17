"""AI 社員 通しの試験：依頼の追加から、総合確認・受け取り・書庫・掟・クエストログ・後始末まで、guild.py のコマンドだけで 1 本通す（役の仕事は、ファイルを書いて代わりにする）。"""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUILD_PY = str(ROOT / "skills" / "quest" / "guild.py")
CRIT = {"viewpoint": "出典が実在し、内容が合っている", "pass_line": "3 件以上の出典がある", "check": "出典の URL を開いて照合する"}
SPEC = {"headings": ["結論", "比較"], "reader": "部長"}


def cli(*args, ok=True):
    r = subprocess.run([sys.executable, GUILD_PY, *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    if ok:
        assert r.returncode == 0, f"{args}: {r.stdout}{r.stderr}"
    return r


def jcli(*args):
    return json.loads(cli(*args).stdout)


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_whole_quest(self):
        root = self.root
        jcli("init", root)
        g = root / "guild"
        w = g / ".work"
        self.assertTrue((w / "config.json").is_file())
        self.assertTrue((w / "codex" / "default.md").is_file())

        # 1. 依頼（ボードの新規依頼と同じ形。納品形式は html、置き場の指定つき）
        write_json(w / "requests" / "R20261017-100000.json", {"type": "request", "text": "競合 3 社の価格を比べて、部長に渡す資料を作って", "start": None, "due": None,
                                                              "format": "html", "inputs": [], "files": []})
        self.assertEqual([a["kind"] for a in jcli("arrivals", root)], ["request"])
        made = jcli("new", root, "R20261017-100000")
        q = Path(made["dir"])
        self.assertEqual(json.loads((q / "request.json").read_text(encoding="utf-8"))["format"], "html")

        # 2. 受付係の分解（下書き）。タイトルは依頼ごと、series は関連づけ
        write_json(q / "reports" / "plan-draft.json", {
            "quest": q.name, "title": "競合 3 社の価格比較", "series": "価格比較", "deliver_to": "docs/reports",
            "brief": {"intent": "競合 3 社の価格を比べる", "non_goals": ["価格交渉"], "assumptions": ["国内の 3 社"], "risks": ["非公開の価格"],
                      "coverage": [{"requirement": "価格を比べる", "goals": ["G1", "G2"]}]},
            "goals": [
                {"id": "G1", "title": "3 社の価格を調べる", "kind": "auto", "class": "wizard", "effects": "none", "deps": [], "criteria": CRIT},
                {"id": "G2", "title": "比較資料にまとめる", "kind": "auto", "class": "alchemist", "effects": "none", "deps": ["G1"], "deliverable": True,
                 "deliverable_spec": SPEC, "criteria": CRIT}]})
        r = jcli("adopt", q / "plan.json")
        self.assertEqual(r["adopted"], 2)
        plan = json.loads((q / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual((plan["title"], plan["series"], plan["deliver_to"]), ("競合 3 社の価格比較", "価格比較", "docs/reports"))
        self.assertEqual([t["format"] for t in plan["goals"] if t.get("deliverable")], ["html"])

        # 3. 承認 → 実行（職業ごとに呼ぶ役が分かる）
        write_json(q / "inbox" / "1-approve.json", {"type": "approve"})
        self.assertEqual(jcli("ingest", q / "plan.json")["rejected"], [])
        jcli("sync", q / "plan.json")
        v = jcli("next", q / "plan.json")
        self.assertEqual(v["ready_by_class"], {"wizard": ["G1"], "alchemist": [], "adventurer": []})

        def run_goal(gid, out_name, out_text, role):
            write(q / "output" / gid / out_name, out_text)
            write(q / "reports" / f"{gid}-{role}.md", "## 結果\nできた\n")
            jcli("advance", q / "plan.json", gid, "submitted")
            time.sleep(0.02)
            write(q / "reports" / f"{gid}-appraiser.md", "## 判定\npassed\n## 勧める対応\nなし\n")
            jcli("advance", q / "plan.json", gid, "passed")
            jcli("sync", q / "plan.json")

        run_goal("G1", "prices.md", "# 価格\n", "wizard")
        v = jcli("next", q / "plan.json")
        self.assertEqual(v["ready_by_class"]["alchemist"], ["G2"])
        # 経験メモ（役が書く）
        write(w / "experience" / "wizard" / "notes" / f"{q.name}-G1.md", "## うまくいったこと\n出典を 3 つあたった\n")
        run_goal("G2", "report.html", "<h1>比較</h1>", "alchemist")

        # 4. 全目標が合格 → 総合確認 → 受け取り
        v = jcli("next", q / "plan.json")
        self.assertEqual((v["finished"], v["awaiting_overall"], v["awaiting_accept"]), (True, True, False))
        write_json(q / "inbox" / "2-accept.json", {"type": "accept"})
        r = json.loads(cli("ingest", q / "plan.json", ok=False).stdout)  # 拒否があると、終了コードは 0 でない
        self.assertEqual(len(r["rejected"]), 1)  # 総合確認の前は、受け取れない
        for f in (q / "inbox" / "rejected").glob("*"):
            f.unlink()
        write(q / "reports" / "overall-receptionist.md", "## 判定\n満たしている\n## 不足\nなし\n")
        v = jcli("next", q / "plan.json")
        self.assertEqual((v["awaiting_overall"], v["awaiting_accept"], v["overall"]), (False, True, "ok"))
        pub = jcli("publish", q)
        self.assertEqual(pub["published"], ["Q001_競合 3 社の価格比較.html"])  # 納品物が 1 つ：依頼のタイトルが名前になる
        self.assertNotIn("delivered_to", pub)  # 受け取る前は、プロジェクトにはコピーしない
        self.assertFalse((root / "docs").exists())
        write_json(q / "inbox" / "3-accept.json", {"type": "accept"})
        self.assertEqual(jcli("ingest", q / "plan.json")["rejected"], [])
        self.assertEqual((root / "docs" / "reports" / "Q001_競合 3 社の価格比較.html").read_text(encoding="utf-8"), "<h1>比較</h1>")
        self.assertTrue(jcli("next", q / "plan.json")["complete"])

        # 5. 司書：書庫の自動登録・次の提案・経験の要約・掟の提案（心得の 2 回目）
        lesson = {"id": "C1", "type": "lesson", "name": "出典なしの数字は不合格", "aliases": [], "summary": "出典のない数字は鑑定で不合格になる",
                  "body": "", "confidence": "sourced", "source": f"{q.name}/reports/G1-appraiser.md"}
        write_json(q / "reports" / "archive-draft.json", {"quest": q.name, "followups": ["来月分も作る"], "candidates": [
            {"id": "C2", "type": "term", "name": "粗利", "aliases": [], "summary": "売上から原価を引いた額", "body": "", "confidence": "sourced", "source": "https://example.com"},
            {"id": "C3", "type": "fact", "name": "価格の改定月", "aliases": [], "summary": "たぶん 4 月", "body": "", "confidence": "guess", "source": ""}, lesson]})
        write_json(q / "reports" / "experience-draft.json", {"summaries": {"wizard": "- 出典は 3 つ以上あたる"}})
        r = jcli("archive-propose", q)
        self.assertEqual(r["status"], "proposed")
        self.assertEqual(sorted(r["registered"]), ["出典なしの数字は不合格.md", "粗利.md"])
        self.assertEqual(r["pending"], ["C3"])  # 推測だけ、依頼主が選ぶ
        self.assertEqual(r["followups"], ["来月分も作る"])
        self.assertEqual(r["experience"]["written"], ["wizard"])
        self.assertIn("出典は 3 つ以上", (w / "experience" / "wizard" / "summary.md").read_text(encoding="utf-8"))

        # 6. クエストログ
        d = jcli("digest", root)
        self.assertEqual(d["quests"][0]["label"], "完了")
        self.assertEqual([n["kind"] for n in d["quests"][0]["needs"]], ["archive"])
        self.assertEqual(d["quests"][0]["followups"], ["来月分も作る"])

        # 7. 依頼主が推測を捨てる → 閉じる。後始末（prev/・バックアップ）
        write_json(q / "inbox" / "4-archive.json", {"type": "archive", "decisions": {"C3": "skip"}})
        self.assertEqual(jcli("ingest", q / "plan.json")["rejected"], [])
        self.assertEqual(jcli("next", q / "plan.json")["closed"], True)
        (q / "prev" / "20261017000000").mkdir(parents=True)
        self.assertEqual(jcli("close", root)["removed"], [q.name])
        self.assertFalse((q / "prev").exists())

        # 8. 見える場所に、増えたものがない
        self.assertEqual(sorted(p.name for p in g.iterdir() if not p.name.startswith(".")), ["archive", "board.html", "deliverables", "inputs"])

    def test_a_second_quest_proposes_a_codex_line_and_adoption_only_touches_the_project_codex(self):
        root = self.root
        jcli("init", root)
        w = root / "guild" / ".work"
        default_before = (w / "codex" / "default.md").read_text(encoding="utf-8")
        lesson = lambda **kw: dict({"id": "C1", "type": "lesson", "name": "出典なしの数字は不合格", "aliases": [], "summary": "出典のない数字は不合格", "body": "",
                                    "confidence": "sourced", "source": "Q001/reports/x.md"}, **kw)
        for i, cand in enumerate((lesson(), lesson(codex="数字には、必ず出典を添える")), start=1):
            write_json(w / f"R{i}.json", {"type": "request", "text": f"依頼 {i}", "inputs": [], "files": []})
            (w / "requests").mkdir(exist_ok=True)
            (w / f"R{i}.json").replace(w / "requests" / f"R{i}.json")
            q = Path(jcli("new", root, f"R{i}")["dir"])
            write_json(q / "reports" / "archive-draft.json", {"quest": q.name, "candidates": [cand]})
            r = jcli("archive-propose", q)
        self.assertEqual(r["codex_proposals"], ["K1"])
        write_json(q / "plan.json", {"quest": q.name, "title": "t", "approved": True, "status": "active", "accepted": True, "goals": [
            {"id": "G1", "title": "x", "kind": "auto", "class": "wizard", "effects": "none", "deps": [], "criteria": CRIT, "state": "done", "retries": 0, "output": None}]})
        write_json(q / "inbox" / "1-archive.json", {"type": "archive", "decisions": {}, "codex": {"K1": "adopt"}})
        self.assertEqual(jcli("ingest", q / "plan.json")["rejected"], [])
        self.assertIn("数字には、必ず出典を添える", (w / "codex" / "project.md").read_text(encoding="utf-8"))
        self.assertEqual((w / "codex" / "default.md").read_text(encoding="utf-8"), default_before)

    def test_a_dangerous_plan_is_sent_back_and_nothing_is_written(self):
        root = self.root
        jcli("init", root)
        w = root / "guild" / ".work"
        write_json(w / "requests" / "R1.json", {"type": "request", "text": "x", "inputs": [], "files": []})
        q = Path(jcli("new", root, "R1")["dir"])
        write_json(q / "reports" / "plan-draft.json", {"quest": q.name, "title": "題", "series": "s", "deliver_to": "../outside", "goals": [
            {"id": "G1", "title": "部長に送信する", "kind": "auto", "class": "wizard", "effects": "external", "deps": [], "deliverable": True,
             "deliverable_spec": SPEC, "criteria": CRIT}]})
        r = cli("adopt", q / "plan.json", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((q / "plan.json").exists())
        write_json(q / "reports" / "plan-draft.json", {"quest": q.name, "title": "題", "series": "s", "goals": [
            {"id": "G1", "title": "部長に送信する", "kind": "auto", "class": "wizard", "effects": "external", "deps": [], "deliverable": True,
             "deliverable_spec": SPEC, "criteria": CRIT}]})
        r = cli("adopt", q / "plan.json", ok=False)
        self.assertIn("confirm", r.stdout + r.stderr)  # 外部への送信なのに、確認の印がない
        self.assertFalse((q / "plan.json").exists())


if __name__ == "__main__":
    unittest.main()

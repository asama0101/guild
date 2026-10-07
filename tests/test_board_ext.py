"""board.py の 0.2・0.3 の機能のテスト（魔導書・資料室・整理・集計・予定表・人物伝・工房・文の検査）。"""
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_board import Base, board, cli  # noqa: E402


def note(name="見積書の承認フロー", type_="取り決め", status="候補", sources='["shared/規程.pdf"]', used_by='["Q1"]',
         aliases='["承認フロー"]', body="課長→部長の順に承認する。\n", extra=""):
    return (f"---\ntype: {type_}\naliases: {aliases}\nstatus: {status}\nsources: {sources}\nbasis: 原文\n"
            f"confidence: 高\nverified_on: 2026-03-01\nused_by: {used_by}\nlast_used: 2026-03-01\n{extra}---\n{body}")


class ExtBase(Base):
    def put_note(self, name, text):
        d = self.root / "spellbook"
        d.mkdir(exist_ok=True)
        (d / f"{name}.md").write_text(text, encoding="utf-8")

    def read_note(self, name):
        return (self.root / "spellbook" / f"{name}.md").read_text(encoding="utf-8")


class TestSpellbook(ExtBase):
    def test_索引を作り直せる(self):
        self.put_note("見積書の承認フロー", note())
        self.put_note("単価表", note(type_="用語", status="確定", aliases='["単価"]'))
        r = json.loads(self.ok("spellbook-index"))
        self.assertEqual(r["items"], 2)
        idx = (self.root / "spellbook" / "魔導書.md").read_text(encoding="utf-8")
        self.assertIn("| 名前 | aliases | 種別 | 状態 | 使用クエスト数 |", idx)
        self.assertIn("[[見積書の承認フロー]]", idx)

    def test_出典のない項目は索引に載らず終了コード1(self):
        self.put_note("出典なし", note(sources="[]"))
        err = self.ng("spellbook-index")
        self.assertIn("魔導書", err)
        idx = (self.root / "spellbook" / "魔導書.md").read_text(encoding="utf-8")
        self.assertNotIn("出典なし", idx)

    def test_不正な種別も拒否(self):
        self.put_note("x", note(type_="なんでも"))
        self.ng("spellbook-index")

    def test_findはaliasesで項目を返す(self):
        self.put_note("見積書の承認フロー", note())
        out = self.ok("spellbook-find", "承認フロー")
        self.assertIn("見積書の承認フロー｜取り決め｜候補", out)
        self.assertEqual(self.ok("spellbook-find", "無関係な語"), "")

    def test_findは5件まで(self):
        for i in range(8):
            self.put_note(f"用語{i}", note(type_="用語", aliases=f'["語{i}"]'))
        out = self.ok("spellbook-find", "用語")
        self.assertEqual(len(out.splitlines()), 5)

    def test_依頼書に一致した項目だけが付く(self):
        self.put_note("承認フロー", note(name="承認フロー"))
        self.put_note("関係ない", note(aliases='["全然違う"]'))
        q, (g,) = self.to_running()
        self.ok("set", q, "detail", '"見積書の承認フローを確かめる"')
        text = Path(self.ok("make-brief", g, "adventurer")).read_text(encoding="utf-8")
        self.assertIn("魔導書（一致した項目）", text)
        self.assertIn("承認フロー", text)
        self.assertNotIn("関係ない", text)
        self.assertIn("候補（未確定）", text)
        self.assertIn("承認フロー", self.data()["goals"][g]["refs"])
        self.assertIn(q, self.read_note("承認フロー"))  # used_by に記録される

    def test_使用クエストのない候補は依頼書に付かない(self):
        self.put_note("承認フロー", note(used_by="[]"))
        q, (g,) = self.to_running()
        self.ok("set", q, "detail", '"承認フロー"')
        text = Path(self.ok("make-brief", g, "adventurer")).read_text(encoding="utf-8")
        self.assertNotIn("魔導書（一致した項目）", text)

    def test_参照した項目がクエスト票に出る(self):
        self.put_note("承認フロー", note())
        q, (g,) = self.to_running()
        self.ok("set", q, "detail", '"承認フロー"')
        self.ok("make-brief", g, "adventurer")
        self.ok("render-quest", q)
        text = (self.root / self.data()["quests"][q]["dir"] / "quest.md").read_text(encoding="utf-8")
        self.assertIn("魔導書「承認フロー」を参考にした。", text)

    def test_確定と修正(self):
        self.put_note("承認フロー", note())
        self.ok("spellbook-apply", "--item", "承認フロー", "--action", "confirm")
        self.assertIn("status: 確定", self.read_note("承認フロー"))
        self.ng("spellbook-apply", "--item", "承認フロー", "--action", "fix")
        self.ok("spellbook-apply", "--item", "承認フロー", "--action", "fix", "--text", "部長の次に役員")
        self.assertIn("部長の次に役員", self.read_note("承認フロー"))
        self.ng("spellbook-apply", "--item", "../x", "--action", "confirm")

    def test_候補は質問になり_答えで確定する(self):
        q = self.quest()
        self.put_note("承認フロー", note())
        self.ok("apply-simple")
        qs = [x for x in self.data()["questions"] if x.get("tag") == "spell"]
        self.assertEqual(len(qs), 1)
        self.assertEqual([o["label"] for o in qs[0]["options"]], ["確定", "修正する", "あとで決める"])
        self.assertIn("出典", qs[0]["text"])
        self.ok("apply-simple")  # 二重に聞かない
        self.assertEqual(len([x for x in self.data()["questions"] if x.get("tag") == "spell"]), 1)
        self.ok("answer", qs[0]["id"], "--choice", "確定")
        self.assertIn("status: 確定", self.read_note("承認フロー"))

    def test_期限が来ると候補のまま使う(self):
        q = self.quest()
        self.put_note("承認フロー", note())
        self.ok("apply-simple")
        os.environ["GUILD_NOW"] = "2026-03-06T09:00:00"
        self.ok("tick")
        self.assertIn("status: 候補", self.read_note("承認フロー"))

    def test_Dの依頼で確定(self):
        q = self.quest()
        self.put_note("承認フロー", note())
        self.p.requests.mkdir(parents=True, exist_ok=True)
        (self.p.requests / "D1.json").write_text(json.dumps({"kind": "spellbook", "item": "承認フロー", "action": "fix", "text": "直した"}, ensure_ascii=False), encoding="utf-8")
        self.ok("apply-simple")
        self.assertIn("直した", self.read_note("承認フロー"))

    def test_要手直しの理由に出た項目は再確認の質問になる(self):
        self.put_note("承認フロー", note())
        q, (g,) = self.to_running()
        self.ok("set", q, "detail", '"承認フロー"')
        self.ok("make-brief", g, "adventurer")
        self.ok("set-status", g, "冒険中")
        self.ok("set-status", g, "要手直し", "--reason", "precheck_ng")
        qs = [x for x in self.data()["questions"] if x.get("tag") == "spell_recheck"]
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["item"], "承認フロー")


class TestSharedRoom(ExtBase):
    def setup_two(self):
        q1, q2 = self.quest("一つ目"), self.quest("二つ目")
        d = self.root / self.data()["quests"][q1]["dir"] / "input"
        (d / "単価.xlsx").write_bytes(b"x")
        rel = f"{self.data()['quests'][q1]['dir']}/input/単価.xlsx"
        self.put_note("単価", note(type_="用語", sources=json.dumps([rel], ensure_ascii=False), used_by=f'["{q1}", "{q2}"]'))
        return q1, q2, rel

    def test_使用クエストが2件以上の素材が候補になる(self):
        q1, q2, rel = self.setup_two()
        c = json.loads(self.ok("shared-candidates"))
        self.assertEqual([x["file"] for x in c], [rel])

    def test_1件だけなら候補にならない(self):
        q1, q2, rel = self.setup_two()
        self.put_note("単価", note(type_="用語", sources=json.dumps([rel], ensure_ascii=False), used_by=f'["{q1}"]'))
        self.assertEqual(json.loads(self.ok("shared-candidates")), [])

    def test_移すとリンクファイルが残りsourcesが書き換わる(self):
        q1, q2, rel = self.setup_two()
        out = self.ok("shared-move", rel)
        self.assertEqual(out, "shared/単価.xlsx")
        self.assertTrue((self.root / "shared" / "単価.xlsx").exists())
        link = self.root / (rel + ".shared.md")
        self.assertIn("資料室にあります：shared/単価.xlsx", link.read_text(encoding="utf-8"))
        self.assertIn("shared/単価.xlsx", self.read_note("単価"))
        self.assertEqual(json.loads(self.ok("shared-candidates")), [])

    def test_同名は上書きしない(self):
        q1, q2, rel = self.setup_two()
        (self.root / "shared").mkdir(exist_ok=True)
        (self.root / "shared" / "単価.xlsx").write_bytes(b"old")
        self.assertEqual(self.ok("shared-move", rel), "shared/単価-2.xlsx")
        self.assertEqual((self.root / "shared" / "単価.xlsx").read_bytes(), b"old")

    def test_危険なパスは拒否(self):
        q1, q2, rel = self.setup_two()
        self.ng("shared-move", "../x.txt")
        self.ng("shared-move", str(self.root / "board.html"))
        self.ng("shared-move", "shared/単価.xlsx")
        self.ng("shared-move", f"{self.data()['quests'][q1]['dir']}/output/x.md")

    def test_承認で移動する(self):
        q1, q2, rel = self.setup_two()
        self.ok("apply-simple")
        qs = [x for x in self.data()["questions"] if x.get("tag") == "shared_move"]
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["default"], "移す")
        self.ok("answer", qs[0]["id"], "--choice", "移す")
        self.assertTrue((self.root / "shared" / "単価.xlsx").exists())

    def test_期限が来ると推奨案で移す(self):
        q1, q2, rel = self.setup_two()
        self.ok("apply-simple")
        os.environ["GUILD_NOW"] = "2026-03-06T09:00:00"
        self.ok("tick")
        self.assertTrue((self.root / "shared" / "単価.xlsx").exists())


class TestHousekeeping(ExtBase):
    def test_1年使われない魔導書が整理候補になる_最大5件(self):
        self.quest()
        for i in range(8):
            self.put_note(f"古い{i}", note(type_="用語", aliases=f'["古{i}"]').replace("last_used: 2026-03-01", "last_used: 2024-01-01").replace("verified_on: 2026-03-01", "verified_on: 2025-12-01"))
        made = json.loads(self.ok("housekeeping"))
        self.assertEqual(len(made), 5)
        qs = [x for x in self.data()["questions"] if x.get("tag") == "housekeeping"]
        self.assertEqual(qs[0]["default"], "見送る")

    def test_整理するで退避される(self):
        self.quest()
        self.put_note("古い", note(type_="用語").replace("last_used: 2026-03-01", "last_used: 2024-01-01"))
        self.ok("housekeeping")
        qid = [x for x in self.data()["questions"] if x.get("tag") == "housekeeping"][0]["id"]
        self.ok("answer", qid, "--choice", "整理する")
        self.assertFalse((self.root / "spellbook" / "古い.md").exists())
        self.assertTrue((self.root / "spellbook" / ".archive" / "古い.md").exists())

    def test_見送ると二度と聞かない(self):
        self.quest()
        self.put_note("古い", note(type_="用語").replace("last_used: 2026-03-01", "last_used: 2024-01-01"))
        self.ok("housekeeping")
        self.assertEqual(json.loads(self.ok("housekeeping")), [])

    def test_1日1回_tickが実行する(self):
        self.quest()
        self.put_note("古い", note(type_="用語").replace("last_used: 2026-03-01", "last_used: 2024-01-01"))
        self.ok("tick")
        n = len([x for x in self.data()["questions"] if x.get("tag") == "housekeeping"])
        self.assertEqual(n, 1)
        self.ok("tick")
        self.assertEqual(len([x for x in self.data()["questions"] if x.get("tag") == "housekeeping"]), 1)

    def test_半年再発のない掟は見直し候補(self):
        self.quest()
        d = self.data()
        d["rules"] = {"R1": {"id": "R1", "key": "brief|欠落|x", "actor": "_all", "text": "古い掟", "added": "2025-01-01", "recurrences": 0}}
        self.p.board.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        made = json.loads(self.ok("housekeeping"))
        self.assertEqual(len(made), 1)
        qid = made[0]
        self.ok("answer", qid, "--choice", "整理する")
        self.assertNotIn("R1", self.data().get("rules", {}))


class TestUsageCalibSchedule(ExtBase):
    def test_usage集計(self):
        q = self.quest()
        for r, m, t in (("adventurer", "sonnet", 1000), ("alchemist", "opus", 3000), ("adventurer", "sonnet", 500)):
            self.ok("usage-log", "--role", r, "--model", m, "--tokens", str(t), "--quest", q)
        u = json.loads(self.ok("usage", "--quest", q))
        self.assertEqual((u["calls"], u["tokens"]), (3, 4500))
        self.assertEqual(u["by_role"]["adventurer"]["calls"], 2)
        self.assertEqual(u["by_model"], {"sonnet": 2, "opus": 1})
        d = json.loads(self.ok("get", "--quest", q))
        self.assertEqual(d["usage"]["calls"], 3)

    def test_calib(self):
        q, gs = self.to_running(goals=3, estimate_min=60)
        for g in gs:
            self.ok("set-status", g, "冒険中")
            self.ok("set", g, "started_at", '"2026-03-01T09:00:00"')
        os.environ["GUILD_NOW"] = "2026-03-01T10:30:00"
        for g in gs:
            self.to_done_directly(g)
        c = json.loads(self.ok("calib"))
        self.assertEqual(c["factor"], 1.5)
        self.assertEqual(c["by_effort"]["中"]["goals"], 3)
        brief = Path(self.ok("make-brief", q, "fortune_teller")).read_text(encoding="utf-8")
        self.assertIn("見積の補正係数：1.5", brief)

    def to_done_directly(self, g):
        # 達成までの手順を省き、状態だけ達成にして実績の算出を確かめる
        d = self.data()
        q = d["goals"][g]["quest"]
        d["goals"][g]["status"] = "確認待ち"
        self.p.board.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        self.approve("output", g, goal=g, quest=q)
        self.ok("set-status", g, "達成", "--who", "client")

    def test_予定表と余裕(self):
        q = self.quest()
        a = self.goal(q, "A", estimate_min=600, deadline="2026-03-10")
        b2 = self.goal(q, "B", depends_on=a, estimate_min=600, deadline="2026-03-01")
        svg = self.ok("render-schedule")
        self.assertIn("<svg", svg)
        self.assertIn("<title", svg)
        self.assertIn("間に合わないおそれ", svg)
        self.assertLess(self.data()["goals"][b2]["slack_min"], 0)
        self.assertTrue((self.p.sys / "diagrams" / "schedule.svg").exists())
        self.assertIn("間に合わないおそれのあるものは 2 件", (self.p.sys / "diagrams" / "schedule.txt").read_text(encoding="utf-8"))

    def test_予定表は値をエスケープする(self):
        q = self.quest("<b>x</b>")
        self.goal(q, "<script>1</script>", deadline="2026-03-05")
        svg = self.ok("render-schedule")
        self.assertNotIn("<script>", svg)
        self.assertNotIn("<b>x", svg)

    def test_締切のない予定表(self):
        self.quest()
        self.assertIn("<svg", self.ok("render-schedule"))


class TestProfileAndBard(ExtBase):
    def report(self, lines):
        f = self.root / "bard.md"
        f.write_text("## result\n" + "\n".join(f"- {x}" for x in lines) + "\n", encoding="utf-8")
        return str(f)

    def test_教訓と人物伝の案(self):
        q = self.quest()
        self.ok("bard-apply", q, "--file", self.report(["教訓｜欠落｜失敗｜消費税の列を忘れた", "人物伝｜明言｜表は罫線を細くする｜「罫線は細く」"]))
        self.assertIn("消費税の列を忘れた", self.ok("lessons-brief", "--point-code", "欠落"))
        qs = [x for x in self.data()["questions"] if x.get("tag") == "profile"]
        self.assertEqual(len(qs), 1)
        self.assertEqual(self.data()["profile_pending"], 1)
        self.ok("answer", qs[0]["id"], "--choice", "覚える")
        prof = (self.root / "profile.md").read_text(encoding="utf-8")
        self.assertIn("表は罫線を細くする｜kind: 明言｜evidence: 「罫線は細く」", prof)
        self.assertIn("罫線", self.ok("profile-brief"))

    def test_推測は2回観察されるまで案のまま(self):
        q = self.quest()
        r = self.report(["人物伝｜推測｜朝に確認する｜G1 の確認が朝 1 回"])
        self.ok("bard-apply", q, "--file", r)
        self.assertEqual([x for x in self.data()["questions"] if x.get("tag") == "profile"], [])
        self.ok("bard-apply", q, "--file", r)
        self.assertEqual(len([x for x in self.data()["questions"] if x.get("tag") == "profile"]), 1)

    def test_見送りがおすすめで期限後は覚えない(self):
        q = self.quest()
        self.ok("bard-apply", q, "--file", self.report(["人物伝｜観察｜短い文が好き｜G1 で 2 回"]))
        os.environ["GUILD_NOW"] = "2026-03-06T09:00:00"
        self.ok("tick")
        self.assertFalse((self.root / "profile.md").exists())

    def test_人物伝は50項目まで(self):
        q = self.quest()
        (self.root / "profile.md").write_text("# 人物伝\n" + "\n".join(f"- 好み{i}｜kind: 明言｜evidence: x" for i in range(50)), encoding="utf-8")
        self.ok("bard-apply", q, "--file", self.report(["人物伝｜明言｜51 個目｜x"]))
        qid = [x for x in self.data()["questions"] if x.get("tag") == "profile"][0]["id"]
        self.ok("answer", qid, "--choice", "覚える")
        self.assertNotIn("51 個目", (self.root / "profile.md").read_text(encoding="utf-8"))
        self.assertTrue(any("50 項目" in n["text"] for n in self.data()["notices"]))

    def test_bard_briefに評価が入る(self):
        q, (g,) = self.to_running()
        self.p.requests.mkdir(parents=True, exist_ok=True)
        (self.p.requests / "E1.json").write_text(json.dumps({"kind": "evaluation", "quest": q, "goal": g, "score": "bad", "reason": "金額が違う", "comment": "直す"}, ensure_ascii=False), encoding="utf-8")
        self.ok("apply-simple")
        text = Path(self.ok("bard-brief", q)).read_text(encoding="utf-8")
        self.assertIn("bad：金額が違う／直す", text)  # 理由と一言の両方

    def test_達成後のやることがあるときだけClaudeが要る(self):
        q, (g,) = self.to_running()
        self.to_confirm(q, g)
        self.approve("output", g, goal=g, quest=q)
        self.ok("set-status", g, "達成", "--who", "client")
        self.ok("set-status", q, "達成")
        self.assertEqual(self.ok("need-claude"), "no")  # 蓄積の材料がない
        self.p.requests.mkdir(parents=True, exist_ok=True)
        (self.p.requests / "E1.json").write_text(json.dumps({"kind": "evaluation", "quest": q, "goal": g, "score": "good", "reason": "", "comment": "よい"}, ensure_ascii=False), encoding="utf-8")
        self.ok("apply-simple")
        self.assertIn("accumulate", self.ok("need-claude"))
        self.ok("bard-apply", q, "--file", self.report([]))
        self.assertEqual(self.ok("need-claude"), "no")

    def test_魔法使いの材料は用語節だけ(self):
        q, (g,) = self.to_running()
        self.write_report(g, "adventurer", "## result\n- 事実｜a｜b\n## 用語\n- 見積条件：取引先ごとの割引\n")
        self.assertEqual(json.loads(self.ok("accumulate-todo", q))["wizard"], [f"{g}：見積条件：取引先ごとの割引"])
        text = Path(self.ok("wizard-brief", q)).read_text(encoding="utf-8")
        self.assertIn("見積条件：取引先ごとの割引", text)
        self.assertNotIn("事実｜a｜b", text)
        self.assertIn("sources", text)

    def test_インタビュー(self):
        q = self.quest()
        iid = self.ok("interview-add", "--topic", "好みの聞き取り")
        self.assertEqual(iid, "I1")
        f = self.root / "iv.md"
        f.write_text("## 依頼主への質問\n### 1. 好きな表の形は？\n### 2. 色は？\n", encoding="utf-8")
        made = json.loads(self.ok("interview-ask", iid, "--quest", q, "--file", str(f)))
        self.assertEqual(len(made), 2)
        for m in made:
            self.ok("answer", m, "--choice", "自由入力", "--comment", "細い罫線")
        self.ok("tick")
        self.assertEqual(self.data()["interviews"][iid]["status"], "回答済")


class TestTemplates(ExtBase):
    def make_doc_goal(self):
        q, (g,) = self.to_running(form="Word", output_path="output/見積書.docx")
        return q, g

    def test_goodの納品物は設計図の質問になる(self):
        q = self.quest()
        g = self.goal(q, "本体", form="Word", output_path="output/見積書.docx")
        out = self.root / self.data()["quests"][q]["dir"] / "output"
        (out / "見積書.docx").write_bytes(b"PK")
        self.ok("set", g, "form", '"Word"')
        d = self.data()
        d["feedbacks"]["F1"] = {"id": "F1", "quest": q, "goal": g, "score": "good", "reason": "", "comment": ""}
        self.p.board.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        made = json.loads(self.ok("template-propose", q))
        self.assertEqual(len(made), 1)
        qq = self.data()["questions"][-1]
        self.assertEqual(qq["default"], "しない")
        self.ok("answer", made[0], "--choice", "設計図にする")
        self.assertTrue((self.root / "templates" / "見積書.docx").exists())
        self.assertEqual(json.loads(self.ok("template-propose", q)), [])

    def test_template_addは危険なパスを拒否(self):
        self.ng("template-add", "../x.docx")

    def test_占い師の依頼書に設計図の一覧が付く(self):
        (self.root / "templates").mkdir(exist_ok=True)
        (self.root / "templates" / "見積書.docx").write_bytes(b"PK")
        q = self.quest()
        text = Path(self.ok("make-brief", q, "fortune_teller")).read_text(encoding="utf-8")
        self.assertIn("見積書.docx（使用 0 回）", text)

    def test_鍛冶師の依頼書で使用回数が増える(self):
        (self.root / "templates").mkdir(exist_ok=True)
        (self.root / "templates" / "見積書.docx").write_bytes(b"PK")
        q, (g,) = self.to_running()
        self.ok("set", g, "template", '"見積書.docx"')
        self.ok("make-brief", g, "smith")
        self.assertEqual(self.data()["template_use"]["見積書.docx"]["count"], 1)


class TestWorkshop(ExtBase):
    def start(self):
        q, (g,) = self.to_running()
        self.ok("set", g, "output_path", '["output/成果.md"]')
        self.ok("set-status", g, "冒険中", "--who", "workshop", "--text", "工房で作る")
        return q, g

    def work(self, q, name, n, body):
        d = self.root / self.data()["quests"][q]["dir"] / "output" / ".work"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.v{n}.md").write_text(body, encoding="utf-8")

    def test_前置きは短く必要な情報だけ(self):
        q, (g,) = self.to_running()
        text = self.ok("workshop-brief", g)
        self.assertIn("done_when", text)
        self.assertIn(".work", text)

    def test_作業中の達成条件にも前置きを出せるが_確認待ちでは出せない(self):
        q, g = self.start()
        self.ok("workshop-brief", g)

    def test_input_addは素材に写す(self):
        q, g = self.start()
        src = self.root / "元.xlsx"
        src.write_bytes(b"x")
        out = self.ok("input-add", g, str(src))
        self.assertTrue(Path(out).exists())
        self.assertEqual(Path(out).parent.name, "input")
        again = self.ok("input-add", g, str(src))
        self.assertNotEqual(out, again)  # 上書きしない
        self.assertEqual(self.data()["goals"][g]["workshop_added"], 2)

    def test_input_addは場所を検査する(self):
        q, g = self.start()
        self.ng("input-add", g, "../x.txt")
        self.ng("input-add", g, str(self.root / "無い.txt"))
        big = self.root / "big.bin"
        with open(big, "wb") as f:
            f.truncate(board.MAX_FILE_BYTES + 1)
        self.ng("input-add", g, str(big))
        try:
            link = self.root / "link.txt"
            (self.root / "t.txt").write_text("x")
            os.symlink(self.root / "t.txt", link)
        except (OSError, NotImplementedError):
            return
        self.ng("input-add", g, str(link))

    def test_input_addはテキストも足せる(self):
        q, g = self.start()
        out = self.ok("input-add", g, "--text", "メモの中身", "--name", "メモ.md")
        self.assertEqual(Path(out).read_text(encoding="utf-8"), "メモの中身")

    def test_ファイル名の制御文字を除く(self):
        q, g = self.start()
        out = self.ok("input-add", g, "--text", "x", "--name", "a\x01b/../c.md")
        self.assertEqual(Path(out).name, "c.md")

    def test_終了で最新の版を正式な名前で置き_確認待ちへ(self):
        q, g = self.start()
        self.work(q, "成果", 1, "## 事実\n- 古い [出典: a]\n")
        self.work(q, "成果", 2, "## 事実\n- 新しい [出典: a]\n")
        r = json.loads(self.ok("workshop-close", g, "--summary", "金額を直した"))
        self.assertEqual(r["next"], "確認待ち")
        out = self.root / self.data()["quests"][q]["dir"] / "output" / "成果.md"
        self.assertIn("新しい", out.read_text(encoding="utf-8"))
        self.assertEqual(self.data()["goals"][g]["status"], "確認待ち")
        log = [e["text"] for e in self.data()["goals"][g]["log"]]
        self.assertIn("あなたと一緒に工房で作業した：「金額を直した」。素材を 0 件足した。", log)

    def test_鑑定を頼むと鑑定中へ(self):
        q, g = self.start()
        self.work(q, "成果", 1, "## 事実\n- x [出典: a]\n")
        r = json.loads(self.ok("workshop-close", g, "--review"))
        self.assertEqual(r["next"], "鑑定中")
        self.assertEqual(self.data()["goals"][g]["status"], "鑑定中")

    def test_pre_checkがNGなら閉じない(self):
        q, g = self.start()
        self.work(q, "成果", 1, "## 事実\n- 出典のない事実\n")
        self.ng("workshop-close", g)
        self.assertEqual(self.data()["goals"][g]["status"], "冒険中")

    def test_途中で閉じても版と知見メモが残る(self):
        q, g = self.start()
        self.work(q, "成果", 1, "下書き")
        r = json.loads(self.ok("workshop-close", g, "--abort"))
        self.assertEqual(r["closed"], "abort")
        self.assertTrue(list((self.root / self.data()["quests"][q]["dir"] / "output" / ".work").glob("*.v1.md")))
        self.assertTrue((self.p.reports / r["memo"]).exists())
        self.assertEqual(self.data()["goals"][g]["status"], "冒険中")

    def test_知見メモは二重に処理せず_両方の処理後に済へ移る(self):
        q, g = self.start()
        self.work(q, "成果", 1, "## 事実\n- x [出典: a]\n")
        r = json.loads(self.ok("workshop-close", g, "--abort"))
        memo = r["memo"]
        (self.p.reports / memo).write_text(
            f"goal: {g}\n\n## 用語・取り決め\n- 承認フロー：課長→部長\n\n## 好み・直しの傾向\n- 「罫線は細く」\n\n## 直した点\n- brief｜欠落｜output/成果.md｜列が抜けている\n", encoding="utf-8")
        d = self.data()
        d["memos"][memo].update({"wizard": False, "bard": False})
        self.p.board.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.ok("memo-done", memo, "--by", "wizard"), "OK")
        self.assertEqual(self.ok("memo-done", memo, "--by", "bard"), "済")
        self.assertTrue((self.p.reports / "済" / memo).exists())
        self.assertFalse((self.p.reports / memo).exists())

    def test_閉じたあとに書き足した知見メモも蓄積の材料になる(self):
        q, g = self.start()
        self.work(q, "成果", 1, "x")
        memo = json.loads(self.ok("workshop-close", g, "--abort"))["memo"]
        self.assertEqual(json.loads(self.ok("accumulate-todo", q)), {"wizard": [], "bard": []})
        (self.p.reports / memo).write_text(f"goal: {g}\n\n## 用語・取り決め\n- 承認フロー：課長→部長\n\n## 好み・直しの傾向\n- 「罫線は細く」\n", encoding="utf-8")
        todo = json.loads(self.ok("accumulate-todo", q))
        self.assertEqual(len(todo["wizard"]), 1)
        self.assertEqual(len(todo["bard"]), 1)
        self.ok("memo-done", memo, "--by", "wizard")
        self.assertEqual(json.loads(self.ok("accumulate-todo", q))["wizard"], [])

    def test_直した点が2回目で掟の案になる(self):
        q, g = self.start()
        for i in range(2):
            self.work(q, "成果", 1, "x")
            r = json.loads(self.ok("workshop-close", g, "--abort"))
            memo = r["memo"]
            (self.p.reports / memo).write_text(f"goal: {g}\n\n## 直した点\n- brief｜欠落｜output/成果.md｜列が抜けている\n", encoding="utf-8")
            d = self.data()
            d["memos"][memo].update({"wizard": True, "bard": False, "applied": False})
            self.p.board.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            self.ok("memo-done", memo, "--by", "bard")
            os.environ["GUILD_NOW"] = f"2026-03-0{2 + i}T09:00:00"
        self.assertEqual(len([x for x in self.data()["questions"] if x["kind"] == "rule"]), 1)

    def test_工房のために新しいサブエージェントを呼ばない(self):
        # 工房の役は workshop（メイン）だけ。通る辺は transitions.json の workshop の辺に限る
        t = json.loads((Path(board.HERE) / "transitions.json").read_text(encoding="utf-8"))
        edges = [(e["from"], e["to"]) for k in ("quest", "goal") for e in t[k] if "workshop" in e["actor"]]
        self.assertIn(("待機", "冒険中"), edges)
        self.assertIn(("要手直し", "冒険中"), edges)
        self.assertIn(("冒険中", "確認待ち"), edges)

    def test_工房の達成は鑑定を省いても承認は要る(self):
        q, g = self.start()
        self.work(q, "成果", 1, "## 事実\n- x [出典: a]\n")
        self.ok("workshop-close", g)
        self.ng("set-status", g, "達成", "--who", "client")  # 承認②がない

    def test_待機の達成条件にも工房で出発できる(self):
        q, (g,) = self.to_running()
        self.ok("set-status", g, "冒険中", "--who", "workshop")

    def test_要手直しから工房で冒険中に戻れる(self):
        q, (g,) = self.to_running()
        self.ok("set-status", g, "冒険中")
        self.ok("set-status", g, "要手直し", "--reason", "timeout")
        self.ok("set-status", g, "冒険中", "--who", "workshop")


class TestLintText(ExtBase):
    def lint(self, text):
        f = self.root / "t.md"
        f.write_text(text, encoding="utf-8")
        return cli(self.root, "lint-text", str(f))

    def test_良い文は通る(self):
        code, out, err = self.lint("# 見出し\n冒険者が作業を始めた。\n鑑定士が確かめた。\n")
        self.assertEqual(code, 0, err)

    def test_長い文(self):
        code, out, _ = self.lint("あ" * 41 + "。")
        self.assertEqual(code, 1)
        self.assertIn("長い文", out)

    def test_指示語(self):
        code, out, _ = self.lint("それは大事な点だ。")
        self.assertEqual(code, 1)
        self.assertIn("指示語", out)

    def test_指示語の誤検出をしない(self):
        code, _, err = self.lint("あなたが道のりを承認した。この達成条件は達成した。\n")
        self.assertEqual(code, 0, err)

    def test_曖昧語(self):
        code, out, _ = self.lint("適宜、直す。")
        self.assertEqual(code, 1)
        self.assertIn("曖昧語", out)
        code, out, _ = self.lint("いろいろ確かめた。")
        self.assertEqual(code, 1)

    def test_受け身の目印(self):
        code, out, _ = self.lint("納品物が確かめられる。")
        self.assertEqual(code, 1)
        self.assertIn("受け身", out)

    def test_表とコードと見出しは検査しない(self):
        code, _, err = self.lint("| " + "あ" * 80 + " |\n```\n" + "い" * 80 + "\n```\n# " + "う" * 80 + "\n")
        self.assertEqual(code, 0, err)

    def test_リンクの宛先は文字数に数えない(self):
        code, _, err = self.lint("[単価表](output/とても長いファイル名とても長いファイル名とても長いファイル名.xlsx)を見る。")
        self.assertEqual(code, 0, err)

    def test_クエスト票は簡易日本語の規則に合う(self):
        q, (g,) = self.to_running()
        self.make_ready_for_review(q, g)
        self.write_report(g, "appraiser", "## fix_kind\nなし\n")
        self.ok("set-status", g, "確認待ち", "--who", "appraiser")
        text = (self.root / self.data()["quests"][q]["dir"] / "quest.md").read_text(encoding="utf-8")
        # 題名・目的は依頼主が書いた文。記録とあなたがすることの文だけを検査する
        body = text.split("## 記録", 1)[1]
        f = self.root / "rec.md"
        f.write_text(body, encoding="utf-8")
        code, out, err = cli(self.root, "lint-text", str(f))
        self.assertEqual(code, 0, out)

    def test_定型の知らせは簡易日本語(self):
        f = self.root / "n.md"
        f.write_text(board.BUDGET_STOP_NOTICE + "\n", encoding="utf-8")
        self.assertEqual(cli(self.root, "lint-text", str(f))[0], 0)
        for text in board.REWORK_REASONS.values():
            f.write_text(text + "。\n", encoding="utf-8")
            self.assertEqual(cli(self.root, "lint-text", str(f))[0], 0, text)


if __name__ == "__main__":
    unittest.main()

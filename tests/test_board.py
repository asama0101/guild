"""board.py のテスト（SPEC 17 節の 0.1 分）。標準ライブラリの unittest だけで動く。"""
import contextlib
import importlib.util
import io
import json
import multiprocessing
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import constants as C  # noqa: E402

spec = importlib.util.spec_from_file_location("board", ROOT / "skills" / "quest" / "board.py")
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)


def cli(root, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = board.main(["--root", str(root), *args])
    return code, out.getvalue(), err.getvalue()


def _writer(root, n):  # 並行書込テスト用（別プロセス）
    for _ in range(n):
        cli(root, "add-quest", "--title", "並行")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "guild"
        self.root.mkdir()
        os.environ["GUILD_NOW"] = "2026-03-01T09:00:00"
        board.init_board(board.Paths(self.root))
        self.p = board.Paths(self.root)

    def tearDown(self):
        os.environ.pop("GUILD_NOW", None)
        self.tmp.cleanup()

    def ok(self, *args):
        code, out, err = cli(self.root, *args)
        self.assertEqual(code, 0, f"{args}: {err}")
        return out.strip()

    def ng(self, *args):
        code, out, err = cli(self.root, *args)
        self.assertEqual(code, 1, f"{args} は拒否されるはず: {out}")
        return err

    def data(self):
        return json.loads(self.p.board.read_text(encoding="utf-8"))

    def quest(self, title="見積書"):
        return self.ok("add-quest", "--title", title, "--detail", "見積書を作る")

    def goal(self, q, title="単価表", dw="表がそろっている", **kw):
        args = ["add-goal", "--quest", q, "--title", title, "--done-when", dw]
        for k, v in kw.items():
            args += [f"--{k.replace('_', '-')}", str(v)]
        return self.ok(*args)

    def approve(self, scope, target, choice="承認する", quest=None, goal=None, text="確認してください"):
        args = ["add-question", "--quest", quest or target, "--kind", "approval", "--scope", scope, "--text", text,
                "--options", json.dumps([{"label": "承認する"}, {"label": "やり直す"}, {"label": "あとで決める"}],
                                        ensure_ascii=False)]
        if goal:
            args += ["--goal", goal]
        aid = self.ok(*args)
        self.ok("answer", aid, "--choice", choice)
        return aid

    def to_running(self, goals=1, **kw):
        q = self.quest()
        gs = [self.goal(q, f"達成条件{i}", **kw) for i in range(goals)]
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.approve("route", q)
        self.ok("set-status", q, "進行中", "--who", "client")
        return q, gs

    def write_output(self, q, name="成果.md", body="## 事実\n- 単価は 100 円 [出典: 素材/単価.xlsx#A1]\n"):
        qd = self.root / self.data()["quests"][q]["dir"]
        (qd / "output").mkdir(parents=True, exist_ok=True)
        (qd / "output" / name).write_text(body, encoding="utf-8")
        return f"output/{name}"

    def write_report(self, gid, role="adventurer", body="## result\n- 事実｜出典｜2026-03-01\n"):
        self.p.reports.mkdir(parents=True, exist_ok=True)
        (self.p.reports / f"{gid}-{role}.md").write_text(body, encoding="utf-8")

    def make_ready_for_review(self, q, g):
        rel = self.write_output(q)
        self.ok("set", g, "output_path", json.dumps([rel]))
        self.write_report(g)
        self.ok("set-status", g, "冒険中")
        self.ok("set-status", g, "鑑定中")

    def to_confirm(self, q, g):
        self.make_ready_for_review(q, g)
        self.write_report(g, "appraiser", "## fix_kind\nなし\n")
        self.ok("set-status", g, "確認待ち", "--who", "appraiser")


class TestIdsAndQuests(Base):
    def test_採番は通し番号で戻らない(self):
        self.assertEqual(self.quest(), "Q1")
        self.assertEqual(self.quest("二つ目"), "Q2")
        self.assertEqual(self.goal("Q1"), "G1")
        self.assertEqual(self.goal("Q2"), "G2")
        self.assertEqual(self.data()["last_ids"]["Q"], 2)

    def test_クエストを作るとフォルダと票ができる(self):
        q = self.quest("取引先向け/見積書")
        d = self.root / self.data()["quests"][q]["dir"]
        for sub in ("input", "output", "adventure log"):
            self.assertTrue((d / sub).is_dir(), sub)
        self.assertTrue((d / "quest.md").is_file())
        self.assertNotIn("/", d.name.replace("Q1 ", ""))

    def test_done_whenは1から3個(self):
        q = self.quest()
        self.ng("add-goal", "--quest", q, "--title", "x", "--done-when", "a", "--done-when", "b",
                "--done-when", "c", "--done-when", "d")

    def test_受付と分解中だけ達成条件を足せる(self):
        q, _ = self.to_running()
        self.ng("add-goal", "--quest", q, "--title", "後から", "--done-when", "x")

    def test_不明なidと状態は終了コード1(self):
        self.ng("get", "--quest", "Q99")
        q = self.quest()
        self.ng("set-status", q, "ほげ")

    def test_setで状態は変えられない(self):
        q = self.quest()
        self.ng("set", q, "status", '"達成"')
        self.ok("set", q, "priority", '"優先"')
        self.ng("set", q, "priority", '"急ぎ"')


class TestTransitions(Base):
    def test_許されない辺を拒否する(self):
        q = self.quest()
        self.ng("set-status", q, "達成")
        self.ng("set-status", q, "進行中")

    def test_許されない役を拒否する(self):
        q = self.quest()
        self.ng("set-status", q, "分解中", "--who", "adventurer")
        self.ng("set-status", q, "分解中", "--who", "client")

    def test_受付から分解中は未回答の問いがあると通らない(self):
        q = self.quest()
        self.ok("add-question", "--quest", q, "--kind", "choice", "--text", "どの形式ですか", "--options",
                json.dumps([{"label": "Excel"}, {"label": "Word"}], ensure_ascii=False))
        self.ng("set-status", q, "分解中")
        self.ok("answer", "A1", "--choice", "Excel")
        self.ok("set-status", q, "分解中")

    def test_閉路のある道のりは承認待ちに進めない(self):
        q = self.quest()
        a = self.goal(q, "A")
        b2 = self.goal(q, "B", depends_on=a)
        self.ok("set", a, "depends_on", json.dumps([b2]))
        self.ok("set-status", q, "分解中")
        err = self.ng("set-status", q, "承認待ち")
        self.assertIn("閉路", err)

    def test_done_whenのない達成条件があると承認待ちに進めない(self):
        q = self.quest()
        g = self.goal(q)
        self.ok("set", g, "done_when", "[]")
        self.ok("set-status", q, "分解中")
        self.ng("set-status", q, "承認待ち")

    def test_達成条件がないと承認待ちに進めない(self):
        q = self.quest()
        self.ok("set-status", q, "分解中")
        self.ng("set-status", q, "承認待ち")

    def test_承認の辺は回答の記録がないと通らない(self):
        q = self.quest()
        self.goal(q)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.ng("set-status", q, "進行中", "--who", "client")
        self.assertEqual(self.data()["quests"][q]["status"], "承認待ち")
        aid = self.approve("route", q)
        self.ok("set-status", q, "進行中", "--who", "client")
        self.assertTrue(json.loads((self.p.answers / f"{aid}.json").read_text(encoding="utf-8"))["consumed"])

    def test_scopeが違う回答では承認の辺を通せない(self):
        q = self.quest()
        self.goal(q)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.approve("output", q)
        self.ng("set-status", q, "進行中", "--who", "client")

    def test_ギルドマスターは承認の辺を通せない(self):
        q = self.quest()
        self.goal(q)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.approve("route", q)
        self.ng("set-status", q, "進行中", "--who", "guildmaster")

    def test_承認で達成条件が待機になる(self):
        q, (g,) = self.to_running()
        d = self.data()
        self.assertEqual(d["quests"][q]["status"], "進行中")
        self.assertEqual(d["goals"][g]["status"], "待機")
        self.assertTrue(d["quests"][q]["approved_at"])

    def test_回答の記録は一度しか使えない(self):
        q = self.quest()
        self.goal(q)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.approve("route", q)
        self.ok("set-status", q, "進行中", "--who", "client")

    def test_writesの検査(self):
        q, (g,) = self.to_running()
        self.ok("set-status", g, "冒険中", "--touch", "board")
        self.ng("set-status", g, "鑑定中", "--touch", "output")
        self.ng("set-status", g, "鑑定中", "--touch", "spellbook")

    def test_権限表(self):
        self.ok("check-write", "alchemist", "output")
        self.ng("check-write", "adventurer", "output")
        self.ng("check-write", "appraiser", "quest_md")

    def test_保留と再開(self):
        q = self.quest()
        self.goal(q)
        self.ok("set-status", q, "分解中")
        self.decide(q, "保留")
        self.ok("set-status", q, "保留", "--who", "client")
        self.assertEqual(self.data()["quests"][q]["status_before_hold"], "分解中")
        self.decide(q, "再開")
        self.ok("set-status", q, "分解中", "--who", "client")
        self.assertIsNone(self.data()["quests"][q]["status_before_hold"])

    def test_保留前と違う状態には再開できない(self):
        q = self.quest()
        self.decide(q, "保留")
        self.ok("set-status", q, "保留", "--who", "client")
        self.decide(q, "再開")
        self.ng("set-status", q, "分解中", "--who", "client")

    def decide(self, oid, choice, scope="none"):
        self.ok("decide", oid, "--choice", choice, "--scope", scope)

    def test_失敗した達成条件の後続は依頼主への質問になる(self):
        q = self.quest()
        a = self.goal(q, "A")
        b2 = self.goal(q, "B", depends_on=a)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.approve("route", q)
        self.ok("set-status", q, "進行中", "--who", "client")
        self.ok("set-status", a, "冒険中")
        self.ok("set-status", a, "要手直し", "--reason", "report_error")
        self.decide(a, "諦める")
        self.ok("set-status", a, "失敗", "--who", "client")
        d = self.data()
        qs = [x for x in d["questions"] if x.get("tag") == "dependent"]
        self.assertEqual(len(qs), 1)
        self.assertEqual(d["quests"][q]["blocked_on"], "client")
        self.assertEqual([o["label"] for o in qs[0]["options"]], board.DEPENDENT_OPTIONS)
        self.assertFalse(any(o["recommended"] for o in qs[0]["options"]))
        self.ok("answer", qs[0]["id"], "--choice", "この達成条件なしで進める")
        self.assertEqual(self.data()["goals"][b2]["depends_on"], [])


class TestGoalFlow(Base):
    def test_冒険から達成まで(self):
        q, (g,) = self.to_running()
        self.make_ready_for_review(q, g)
        self.write_report(g, "appraiser", "## fix_kind\nなし\n")
        self.ok("set-status", g, "確認待ち", "--who", "appraiser")
        self.ng("set-status", g, "達成", "--who", "client")
        self.approve("output", g, goal=g, quest=q)
        self.ok("set-status", g, "達成", "--who", "client")
        self.assertEqual(self.data()["goals"][g]["status"], "達成")

    def test_納品物がないと鑑定中に進めない(self):
        q, (g,) = self.to_running()
        self.ok("set-status", g, "冒険中")
        self.ng("set-status", g, "鑑定中")

    def test_報告書がないと鑑定中に進めない(self):
        q, (g,) = self.to_running()
        self.ok("set", g, "output_path", json.dumps([self.write_output(q)]))
        self.ok("set-status", g, "冒険中")
        err = self.ng("set-status", g, "鑑定中")
        self.assertIn("報告書", err)

    def test_pre_check_NGは鑑定中に進めず要手直しになる(self):
        q, (g,) = self.to_running()
        rel = self.write_output(q, body="## 事実\n- 出典のない事実\n")
        self.ok("set", g, "output_path", json.dumps([rel]))
        self.write_report(g)
        self.ok("set-status", g, "冒険中")
        self.ng("set-status", g, "鑑定中")
        self.ok("set-status", g, "要手直し", "--reason", "precheck_ng")
        self.assertEqual(self.data()["goals"][g]["status"], "要手直し")

    def test_要手直しには理由が要る(self):
        q, (g,) = self.to_running()
        self.ok("set-status", g, "冒険中")
        self.ng("set-status", g, "要手直し")
        self.ng("set-status", g, "要手直し", "--reason", "なんとなく")
        for r in ("report_error", "precheck_ng", "no_report", "timeout"):
            self.assertIn(r, board.REWORK_REASONS)

    def test_鑑定NGは指摘がないと通らない(self):
        q, (g,) = self.to_running()
        self.make_ready_for_review(q, g)
        self.ng("set-status", g, "要手直し", "--who", "appraiser")
        self.ok("add-finding", g, "--fix-kind", "brief", "--point-code", "欠落", "--target", "output/成果.md#事実",
                "--point", "消費税の列が抜けている")
        self.ok("set-status", g, "要手直し", "--who", "appraiser")
        d = self.data()["goals"][g]
        self.assertEqual(d["retries"], 1)
        self.assertEqual(self.data()["quests"][q]["rework_total"], 1)

    def test_手直しの上限(self):
        q, (g,) = self.to_running()
        self.ok("set-top", "limits", json.dumps({"retries": 1}))
        self.ok("set-status", g, "冒険中")
        self.ok("set-status", g, "要手直し", "--reason", "timeout")
        self.ok("set-status", g, "冒険中")  # 1 回目の手直しは通る
        self.ok("set-status", g, "要手直し", "--reason", "timeout")
        err = self.ng("set-status", g, "冒険中")  # 2 回目は上限
        self.assertIn("上限", err)
        d = self.data()
        qs = [x for x in d["questions"] if x.get("tag") == "rework_limit"]
        self.assertEqual(len(qs), 1)
        self.assertEqual([o["label"] for o in qs[0]["options"]], ["続ける", "工房で直す", "諦める"])
        self.ok("answer", qs[0]["id"], "--choice", "続ける")
        self.ok("set-status", g, "冒険中")

    def test_やり直すは手直しの回数に数える(self):
        q, (g,) = self.to_running()
        self.to_confirm(q, g)
        aid = self.approve("output", g, choice="やり直す", goal=g, quest=q)
        self.ok("set-status", g, "要手直し", "--who", "client", "--text", "金額を直す")
        d = self.data()
        self.assertEqual(d["goals"][g]["retries"], 1)
        self.assertEqual(d["goals"][g]["findings"][-1]["fix_kind"], "brief")
        self.assertEqual(d["quests"][q]["rework_total"], 1)

    def test_同じ指摘が2回出ると掟の案の質問が出る(self):
        q, (g,) = self.to_running()
        self.ok("set-status", g, "冒険中")
        args = ["add-finding", g, "--fix-kind", "brief", "--point-code", "出典なし", "--target", "output/成果.md#事実",
                "--point", "出典がない", "--rule-text", "事実には出典を付ける", "--rule-actor", "alchemist"]
        self.ok(*args)
        self.assertFalse([x for x in self.data()["questions"] if x["kind"] == "rule"])
        self.ok(*args)
        rq = [x for x in self.data()["questions"] if x["kind"] == "rule"]
        self.assertEqual(len(rq), 1)
        self.assertEqual(rq[0]["default"], "掟に足す")
        self.ok("answer", rq[0]["id"], "--choice", "掟に足す")
        text = (self.p.rules / "alchemist.md").read_text(encoding="utf-8")
        self.assertIn("事実には出典を付ける", text)
        self.assertLessEqual(len(text.splitlines()), 20)
        self.ok(*args)  # 採用後の再発は数える
        self.assertIn("再発 1", (self.p.rules / "alchemist.md").read_text(encoding="utf-8"))

    def test_対象が違えば別の指摘(self):
        q, (g,) = self.to_running()
        for t in ("a", "b"):
            self.ok("add-finding", g, "--fix-kind", "brief", "--point-code", "欠落", "--target", t, "--point", "x")
        self.assertFalse([x for x in self.data()["questions"] if x["kind"] == "rule"])

    def test_実行の承認(self):
        q, (g,) = self.to_running()
        self.ok("set", g, "needs_execute", "true")
        self.to_confirm(q, g)
        self.approve("output", g, goal=g, quest=q)
        self.ng("set-status", g, "達成", "--who", "client")  # 実行の承認が先
        self.ok("set-status", g, "実行承認待ち", "--who", "client")
        self.approve("execute", g, goal=g, quest=q)
        self.ok("set-status", g, "達成", "--who", "client")

    def test_クエストの達成(self):
        q, (g,) = self.to_running()
        self.to_confirm(q, g)
        self.approve("output", g, goal=g, quest=q)
        self.ok("set-status", g, "達成", "--who", "client")
        self.ok("set-status", q, "達成")
        self.assertEqual(self.data()["quests"][q]["status"], "達成")

    def test_達成していないクエストは達成にできない(self):
        q, _ = self.to_running()
        self.ng("set-status", q, "達成")

    def test_クエストを中止すると達成条件も中止になる(self):
        q, (g,) = self.to_running()
        self.ok("decide", q, "--choice", "中止")
        self.ok("set-status", q, "中止", "--who", "client")
        self.assertEqual(self.data()["goals"][g]["status"], "中止")

    def test_差し戻し(self):
        q, (g,) = self.to_running()
        self.ok("set-status", g, "冒険中")
        self.ok("add-finding", g, "--fix-kind", "goal", "--point-code", "範囲外", "--target", "x", "--point", "条件が違う")
        self.ok("set-status", q, "分解中")
        d = self.data()
        self.assertEqual(d["goals"][g]["status"], "案")
        self.assertEqual(d["quests"][q]["replans"], 1)
        self.assertIsNone(d["quests"][q]["approved_at"])

    def test_差し戻しの上限(self):
        q, (g,) = self.to_running()
        self.ok("set-top", "limits", json.dumps({"replans": 0}))
        self.ok("add-finding", g, "--fix-kind", "goal", "--point-code", "範囲外", "--target", "x", "--point", "y")
        self.ng("set-status", q, "分解中")

    def test_fix_kindがgoalでなければ差し戻せない(self):
        q, (g,) = self.to_running()
        self.ok("add-finding", g, "--fix-kind", "brief", "--point-code", "欠落", "--target", "x", "--point", "y")
        self.ng("set-status", q, "分解中")


class TestScheduling(Base):
    def test_同時数(self):
        q, gs = self.to_running(goals=3)
        self.ok("set-top", "limits", json.dumps({"max_active": 2}))
        self.ok("set-status", gs[0], "冒険中")
        self.ok("set-status", gs[1], "冒険中")
        self.ng("set-status", gs[2], "冒険中")

    def test_前提が達成するまで出発できない(self):
        q = self.quest()
        a = self.goal(q, "A")
        b2 = self.goal(q, "B", depends_on=a)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.approve("route", q)
        self.ok("set-status", q, "進行中", "--who", "client")
        self.ng("set-status", b2, "冒険中")
        self.assertEqual(self.ok("ready"), json.dumps([a], ensure_ascii=False, indent=1))

    def test_触るノートが重なると出発できない(self):
        q, gs = self.to_running(goals=2, notes_touched="notes/A.md")
        self.ok("set-status", gs[0], "冒険中")
        err = self.ng("set-status", gs[1], "冒険中")
        self.assertIn("重なって", err)

    def test_出発順は余裕が小さい順(self):
        q = self.quest()
        late = self.goal(q, "遅くてよい", deadline="2026-03-30", estimate_min=60)
        soon = self.goal(q, "急ぐ", deadline="2026-03-01", estimate_min=120)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.approve("route", q)
        self.ok("set-status", q, "進行中", "--who", "client")
        self.assertEqual(json.loads(self.ok("ready")), [soon, late])

    def test_優先度は同じ余裕のときに効く(self):
        q1 = self.quest("一つ目")
        q2 = self.quest("二つ目")
        g1 = self.goal(q1, "A")
        g2 = self.goal(q2, "B")
        for q in (q1, q2):
            self.ok("set-status", q, "分解中")
            self.ok("set-status", q, "承認待ち")
            self.approve("route", q)
            self.ok("set-status", q, "進行中", "--who", "client")
        self.ok("set", q2, "priority", '"優先"')
        self.assertEqual(json.loads(self.ok("ready")), [g2, g1])

    def test_締切の逆算で間に合わないと警告(self):
        q = self.quest()
        a = self.goal(q, "A", estimate_min=600, deadline="2026-03-10")
        self.goal(q, "B", depends_on=a, estimate_min=600, deadline="2026-03-01")
        r = json.loads(self.ok("route-check", q))
        self.assertTrue(r["ok"])
        self.assertTrue(r["warnings"])
        self.assertLess(min(r["slack"].values()), 0)

    def test_route_checkは閉路と前提の欠けを検出する(self):
        q = self.quest()
        a = self.goal(q, "A")
        self.ok("set", a, "depends_on", '["G99"]')
        self.ng("route-check", q)

    def test_route_check_writeで順を保存(self):
        q = self.quest()
        a = self.goal(q, "A")
        b2 = self.goal(q, "B", depends_on=a)
        self.ok("route-check", q, "--write")
        self.assertEqual(self.data()["quests"][q]["route"], [a, b2])


class TestRequestsAndTick(Base):
    def req(self, name, obj):
        self.p.requests.mkdir(parents=True, exist_ok=True)
        (self.p.requests / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_apply_simple_設定と優先度と評価(self):
        q, (g,) = self.to_running()
        self.req("M20260301-0900.json", {"kind": "setting", "max_active": 2})
        self.req("M20260301-1000.json", {"kind": "setting", "max_active": 6})
        self.req("P1.json", {"kind": "priority", "quest": q, "priority": "優先"})
        self.req("G1.json", {"kind": "goal_setting", "goal": g, "careful": True})
        self.req("E1.json", {"kind": "evaluation", "quest": q, "goal": g, "score": "bad", "reason": "金額", "comment": "直す"})
        self.ok("apply-simple")
        d = self.data()
        self.assertEqual(d["limits"]["max_active"], 6)  # 新しいものが勝つ
        self.assertEqual(d["quests"][q]["priority"], "優先")
        self.assertEqual(d["goals"][g]["effort"], "高")
        self.assertEqual(len(d["feedbacks"]), 1)
        self.assertFalse(list(self.p.requests.glob("*.json")))
        self.assertEqual(len(list((self.p.requests / "済").glob("*.json"))), 5)

    def test_apply_simple_不正な設定は保留に回す(self):
        self.req("M1.json", {"kind": "setting", "max_active": 99})
        self.ok("apply-simple")
        self.assertEqual(self.data()["limits"]["max_active"], 4)
        self.assertTrue((self.p.requests / "保留" / "M1.json").exists())

    def test_apply_simple_RとUは触らない(self):
        self.req("R1.json", {"kind": "quest", "title": "新しい依頼"})
        self.req("U1.json", {"kind": "upload"})
        self.ok("apply-simple")
        self.assertEqual(len(list(self.p.requests.glob("*.json"))), 2)

    def test_取り下げ(self):
        q, (g,) = self.to_running()
        self.req("C1.json", {"kind": "cancel", "quest": q})
        self.ok("apply-simple")
        self.assertEqual(self.data()["quests"][q]["status"], "中止")

    def test_後続のある達成条件の取り下げは質問になる(self):
        q = self.quest()
        a = self.goal(q, "A")
        self.goal(q, "B", depends_on=a)
        self.req("C1.json", {"kind": "cancel", "quest": q, "goal": a})
        self.ok("apply-simple")
        d = self.data()
        self.assertEqual(d["goals"][a]["status"], "案")
        self.assertEqual(len([x for x in d["questions"] if x.get("tag") == "dependent"]), 1)

    def test_tickは推奨案がある質問を期限後に進める(self):
        q = self.quest()
        aid = self.ok("add-question", "--quest", q, "--kind", "confirm", "--text", "これで進めますか",
                      "--options", json.dumps([{"label": "はい", "recommended": True}, {"label": "いいえ"}], ensure_ascii=False),
                      "--default", "はい", "--no-block")
        self.ok("tick")
        self.assertEqual(self.data()["questions"][0]["status"], "未回答")
        os.environ["GUILD_NOW"] = "2026-03-05T09:00:00"
        self.ok("tick")
        qq = self.data()["questions"][0]
        self.assertEqual((qq["status"], qq["answer"]), ("回答済", "はい"))

    def test_tickは承認を自動で進めない(self):
        q = self.quest()
        self.goal(q)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.ok("add-question", "--quest", q, "--kind", "approval", "--scope", "route", "--text", "道のりを承認してください",
                "--options", json.dumps([{"label": "承認する"}, {"label": "やり直す"}], ensure_ascii=False))
        os.environ["GUILD_NOW"] = "2026-03-05T09:00:00"
        self.ok("tick")
        d = self.data()
        self.assertEqual(d["questions"][0]["status"], "未回答")
        self.assertEqual(d["quests"][q]["status"], "承認待ち")
        self.assertTrue(any("承認待ち" in n["text"] for n in d["notices"]))
        n = len(d["notices"])
        os.environ["GUILD_NOW"] = "2026-03-06T09:00:00"  # 3 日おきに再通知
        self.ok("tick")
        self.assertEqual(len(self.data()["notices"]), n)
        os.environ["GUILD_NOW"] = "2026-03-09T09:00:00"
        self.ok("tick")
        self.assertEqual(len(self.data()["notices"]), n + 1)

    def test_tick_実行の承認は14日で保留(self):
        q, (g,) = self.to_running()
        self.ok("add-question", "--quest", q, "--goal", g, "--kind", "approval", "--scope", "execute", "--text", "実行してよいですか")
        os.environ["GUILD_NOW"] = "2026-03-20T09:00:00"
        self.ok("tick")
        self.assertEqual(self.data()["quests"][q]["status"], "保留")

    def test_tick_推奨案のない質問は14日で保留(self):
        q = self.quest()
        self.ok("add-question", "--quest", q, "--kind", "choice", "--text", "どれにしますか",
                "--options", json.dumps([{"label": "A"}, {"label": "B"}]))
        os.environ["GUILD_NOW"] = "2026-03-10T09:00:00"
        self.ok("tick")
        self.assertEqual(self.data()["quests"][q]["status"], "受付")
        os.environ["GUILD_NOW"] = "2026-03-16T09:00:00"
        self.ok("tick")
        self.assertEqual(self.data()["quests"][q]["status"], "保留")

    def test_通知は20件まで(self):
        for i in range(25):
            self.ok("add-notice", "--text", f"知らせ{i}")
        self.assertEqual(len(self.data()["notices"]), 20)

    def test_質問は選び直せる(self):
        q = self.quest()
        aid = self.ok("add-question", "--quest", q, "--text", "どれ", "--options",
                      json.dumps([{"label": "A"}, {"label": "B"}]))
        self.ok("answer", aid, "--choice", "A")
        self.ng("answer", aid, "--choice", "B")
        self.ok("reopen", aid)
        self.ok("answer", aid, "--choice", "B")
        self.assertEqual(self.data()["questions"][0]["answer"], "B")

    def test_あとで決めるは保留(self):
        q = self.quest()
        aid = self.ok("add-question", "--quest", q, "--text", "どれ", "--options", json.dumps([{"label": "A"}, {"label": "あとで決める"}]))
        self.ok("answer", aid, "--choice", "あとで決める")
        self.assertEqual(self.data()["questions"][0]["status"], "保留")

    def test_選択肢は4個まで(self):
        q = self.quest()
        self.ng("add-question", "--quest", q, "--text", "x", "--options", json.dumps([{"label": str(i)} for i in range(5)]))

    def test_need_claude(self):
        self.assertEqual(self.ok("need-claude"), "no")
        q = self.quest()
        self.assertTrue(self.ok("need-claude").startswith("yes"))  # 受付の聞き取り
        aid = self.ok("add-question", "--quest", q, "--text", "どれ", "--options", json.dumps([{"label": "A"}, {"label": "B"}]))
        self.assertEqual(self.ok("need-claude"), "no")  # 返事待ちだけ
        self.ok("answer", aid, "--choice", "A")
        self.assertTrue(self.ok("need-claude").startswith("yes"))

    def test_need_claude_承認待ちだけならno(self):
        q = self.quest()
        self.goal(q)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        self.ok("add-question", "--quest", q, "--kind", "approval", "--scope", "route", "--text", "承認してください")
        self.assertEqual(self.ok("need-claude"), "no")

    def test_need_claude_新しい依頼(self):
        self.p.requests.mkdir(parents=True, exist_ok=True)
        (self.p.requests / "R1.json").write_text('{"kind":"quest"}', encoding="utf-8")
        self.assertIn("new_request", self.ok("need-claude"))

    def test_need_claude_出発できる達成条件(self):
        q, (g,) = self.to_running()
        self.assertIn("depart", self.ok("need-claude"))


class TestArchiveAndRender(Base):
    def test_退避(self):
        q = self.quest()
        self.ok("decide", q, "--choice", "中止")
        self.ok("set-status", q, "中止", "--who", "client")
        self.assertEqual(json.loads(self.ok("archive", "--days", "30"))["moved"], [])
        os.environ["GUILD_NOW"] = "2026-04-15T09:00:00"
        self.assertEqual(json.loads(self.ok("archive", "--days", "30"))["moved"], [q])
        self.assertNotIn(q, self.data()["quests"])
        self.assertIn(q, json.loads(self.p.archive.read_text(encoding="utf-8"))["quests"])

    def test_クエスト票(self):
        q, (g,) = self.to_running()
        text = (self.root / self.data()["quests"][q]["dir"] / "quest.md").read_text(encoding="utf-8")
        for sec in ("## 目的", "## 達成条件", "## 記録", "## あなたがすること"):
            self.assertIn(sec, text)
        self.assertIn("| 順 | 達成条件 | 締切 | いまの様子 |", text)
        self.assertIn("3月1日 09:00　あなたが道のりを承認した。", text)
        self.assertIn("順番を待っている", text)

    def test_クエスト票に内部IDを書かない(self):
        q, (g,) = self.to_running()
        self.to_confirm(q, g)
        text = (self.root / self.data()["quests"][q]["dir"] / "quest.md").read_text(encoding="utf-8")
        import re
        self.assertIsNone(re.search(r"\b[QGAF]\d+\b", text))
        self.assertIn("確認する", text)
        self.assertIn("あなたの確認を待っている", text)

    def test_記録に出る出来事(self):
        q, (g,) = self.to_running()
        self.make_ready_for_review(q, g)
        log = [e["text"] for e in self.data()["goals"][g]["log"]]
        self.assertIn("冒険者が作業を始めた。", log)
        self.assertIn("冒険者が作業を終えた。鑑定士が確かめている。", log)

    def test_log_appendは冒険日誌に追記し票に載せる(self):
        q, (g,) = self.to_running()
        rep = self.root / "rep.md"
        rep.write_text("## log\n### やったこと\n- 元データ 3 件を読んだ\n- 重複を除いた\n### 判断\n- 内部の判断\n### 未解決\n- なし\n", encoding="utf-8")
        self.ok("log-append", g, "--file", str(rep))
        d = self.root / self.data()["quests"][q]["dir"]
        self.assertTrue(list((d / "adventure log").glob("*.md")))
        text = (d / "quest.md").read_text(encoding="utf-8")
        self.assertIn("冒険者が元データ 3 件を読んだ。", text)
        self.assertNotIn("内部の判断", text)

    def test_get_summaryは30行まで(self):
        for i in range(25):
            self.quest(f"クエスト{i}")
        lines = self.ok("get", "--summary").splitlines()
        self.assertLessEqual(len(lines), 30)

    def test_render_route(self):
        q = self.quest()
        a = self.goal(q, "単価表")
        self.goal(q, "本体", depends_on=a)
        svg = self.ok("render-route", q)
        self.assertIn("<svg", svg)
        self.assertIn("<title", svg)
        self.assertIn("<desc", svg)
        self.assertIn("marker-end", svg)
        self.assertIn("2 個の達成条件", self.ok("render-route", q, "--summary"))

    def test_render_routeは値をエスケープする(self):
        q = self.quest()
        self.goal(q, "<script>alert(1)</script>")
        self.assertNotIn("<script>", self.ok("render-route", q))


class TestChecks(Base):
    def goal_with(self, body, name="成果.md"):
        q, (g,) = self.to_running()
        rel = self.write_output(q, name, body)
        self.ok("set", g, "output_path", json.dumps([rel]))
        return q, g

    def test_pre_check_OK(self):
        q, g = self.goal_with("## 事実\n- 単価は 100 円 [出典: a#1]\n## 推論\n- 安い [前提: 1] [確度: 中]\n")
        self.ok("pre-check", g)

    def test_pre_check_出典のない事実(self):
        q, g = self.goal_with("## 事実\n- 出典なし\n")
        code, out, err = cli(self.root, "pre-check", g)
        self.assertEqual(code, 1)
        self.assertIn("出典のない事実", out)

    def test_pre_check_前提のない推論(self):
        q, g = self.goal_with("## 推論\n- 高い [確度: 低]\n")
        code, out, _ = cli(self.root, "pre-check", g)
        self.assertEqual(code, 1)
        self.assertIn("前提", out)

    def test_pre_check_リンク切れと空ファイル(self):
        q, g = self.goal_with("[表](無い.xlsx)\n")
        code, out, _ = cli(self.root, "pre-check", g)
        self.assertEqual(code, 1)
        self.assertIn("リンク切れ", out)
        q2, g2 = self.goal_with("", "空.md")
        code, out, _ = cli(self.root, "pre-check", g2)
        self.assertIn("空", out)

    def test_pre_check_Officeの形式(self):
        q, (g,) = self.to_running()
        rel = self.write_output(q, "x.docx", "zipではない")
        self.ok("set", g, "output_path", json.dumps([rel]))
        code, out, _ = cli(self.root, "pre-check", g)
        self.assertEqual(code, 1)
        self.assertIn("形式", out)

    def test_pre_check_納品物がない(self):
        q, (g,) = self.to_running()
        self.ng("pre-check", g)

    def test_cross_check(self):
        q, (a, b2) = self.to_running(goals=2)
        qd = self.root / self.data()["quests"][q]["dir"] / "output"
        (qd / "a.md").write_text("## 事実\n- 単価：100円 [出典: x]\n", encoding="utf-8")
        (qd / "b.md").write_text("## 事実\n- 単価：120円 [出典: y]\n", encoding="utf-8")
        self.ok("set", a, "output_path", '["output/a.md"]')
        self.ok("set", b2, "output_path", '["output/b.md"]')
        r = json.loads(self.ok("cross-check", q))
        self.assertEqual(r["result"], "suspect")
        (qd / "b.md").write_text("## 事実\n- 単価：100円 [出典: y]\n", encoding="utf-8")
        self.assertEqual(json.loads(self.ok("cross-check", q))["result"], "clean")


class TestStorage(Base):
    def test_バックアップと復旧(self):
        self.quest("一")
        self.quest("二")
        self.quest("三")
        self.assertTrue((self.p.backup / "board.json.1").exists())
        self.assertTrue((self.p.backup / "board.json.2").exists())
        self.p.board.write_text("{壊れた", encoding="utf-8")
        err = self.ng("get", "--summary")
        self.assertIn("recover", err)
        self.ok("recover")
        self.assertEqual(len(self.data()["quests"]), 2)

    def test_世代は3つまで(self):
        for i in range(6):
            self.quest(f"q{i}")
        self.assertFalse((self.p.backup / "board.json.4").exists())

    def test_壊れたJSONは書かずに止まる(self):
        self.p.board.write_text("[]", encoding="utf-8")
        self.ng("add-quest", "--title", "x")

    def test_不明な状態を持つ盤は拒否する(self):
        d = self.data()
        d["quests"]["Q1"] = {"id": "Q1", "status": "謎", "goals": []}
        self.p.board.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        self.ng("get", "--summary")

    def test_ロックが取れないと失敗する(self):
        self.p.lock.write_text("x")
        lock = board.Lock(self.p, timeout=0.3, stale=1000)
        with self.assertRaises(board.GuildError):
            lock.__enter__()
        self.p.lock.unlink()

    def test_古いロックは捨てる(self):
        self.p.lock.write_text("x")
        os.utime(self.p.lock, (1, 1))
        self.quest()

    def test_同時に書いても壊れない(self):
        procs = [multiprocessing.Process(target=_writer, args=(self.root, 8)) for _ in range(3)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(120)
        d = self.data()
        self.assertEqual(len(d["quests"]), 24)
        self.assertEqual(d["last_ids"]["Q"], 24)

    def test_日本語がそのまま保存される(self):
        self.quest("見積書")
        self.assertIn("見積書", self.p.board.read_text(encoding="utf-8"))

    def test_updatedが更新される(self):
        self.quest()
        self.assertEqual(self.data()["updated"], "2026-03-01T09:00:00")


class TestMisc(Base):
    def test_lessons(self):
        self.ok("lessons-append", "--kind", "失敗", "--point-code", "欠落", "--text", "列が抜けた")
        self.ok("lessons-append", "--kind", "成功", "--point-code", "形式", "--text", "表で出した")
        self.assertIn("列が抜けた", self.ok("lessons-brief", "--point-code", "欠落"))
        self.assertNotIn("表で出した", self.ok("lessons-brief", "--point-code", "欠落"))

    def test_lessonsは100行まで(self):
        for i in range(105):
            self.ok("lessons-append", "--text", f"行{i}")
        self.assertEqual(len(self.p.lessons.read_text(encoding="utf-8").splitlines()), 100)
        self.assertTrue((self.p.lessons.parent / "lessons-old.md").exists())

    def test_profile_briefは10行(self):
        self.p.profile.write_text("# 人物伝\n" + "\n".join(f"- 好み{i}" for i in range(30)), encoding="utf-8")
        self.assertEqual(len(self.ok("profile-brief").splitlines()), 10)

    def test_モデルの選び方(self):
        q, (g,) = self.to_running()
        self.assertTrue(self.ok("model-for", g, "alchemist").startswith("sonnet"))
        self.assertTrue(self.ok("model-for", g, "adventurer").startswith("sonnet"))
        self.assertTrue(self.ok("model-for", g, "wizard").startswith("haiku"))
        self.ok("set", g, "effort", '"高"')
        self.assertTrue(self.ok("model-for", g, "alchemist").startswith("opus"))
        self.assertTrue(self.ok("model-for", g, "appraiser").startswith("sonnet"))  # opus は錬金術師だけ

    def test_opusは要手直し2回目の矛盾か誤りのとき(self):
        q, (g,) = self.to_running()
        self.ok("set", g, "retries", "2")
        self.ok("set", g, "findings", json.dumps([{"fix_kind": "brief", "point_code": "矛盾", "target": "x", "point": "y"}], ensure_ascii=False))
        self.assertTrue(self.ok("model-for", g, "alchemist").startswith("opus"))
        self.ok("set", g, "findings", json.dumps([{"fix_kind": "brief", "point_code": "形式", "target": "x", "point": "y"}], ensure_ascii=False))
        self.assertTrue(self.ok("model-for", g, "alchemist").startswith("sonnet"))

    def test_予算(self):
        q = self.quest()
        self.ok("set-top", "limits", json.dumps({"budget": {"max_calls": 3}}))
        self.assertTrue(self.ok("budget", "--use", "2").startswith("ok"))
        self.assertTrue(self.ok("budget", "--use", "2", "--quest", q).startswith("stop"))
        self.assertTrue(any("いったん止めました" in n["text"] for n in self.data()["notices"]))
        for _ in range(2):
            self.ok("budget", "--use", "9", "--quest", q)
        qs = [x for x in self.data()["questions"] if x.get("tag") == "budget"]
        self.assertEqual(len(qs), 1)  # 3 回続けて止まったら依頼主に聞く
        self.ok("budget", "--reset")
        self.assertTrue(self.ok("budget", "--use", "1").startswith("ok"))

    def test_既定の予算は20(self):
        self.assertEqual(self.data()["limits"]["budget"]["max_calls"], 20)

    def test_make_brief(self):
        q, (g,) = self.to_running()
        self.p.rules.mkdir(exist_ok=True)
        (self.p.rules / "adventurer.md").write_text("- R1｜x\n", encoding="utf-8")
        f = Path(self.ok("make-brief", g, "adventurer"))
        text = f.read_text(encoding="utf-8")
        self.assertIn("done_when", text)
        self.assertIn("R1", text)
        self.assertIn("input/", text)  # 素材は場所だけ
        self.assertEqual(f.name, f"{g}-adventurer.md")

    def test_錬金術師の依頼書には冒険者の報告書の場所が付き_鑑定士には付かない(self):
        q, (g,) = self.to_running()
        self.write_report(g)
        alch = Path(self.ok("make-brief", g, "alchemist")).read_text(encoding="utf-8")
        self.assertIn(f".system/reports/{g}-adventurer.md", alch)
        appr = Path(self.ok("make-brief", g, "appraiser")).read_text(encoding="utf-8")
        self.assertNotIn("adventurer.md", appr)

    def test_錬金術師の依頼書に形ごとの書き方が付く(self):
        for form, key in (("ノート", "[[ ]]"), ("テキスト", "そのまま貼れる本文"), ("回答だけ", "結論を先頭の 1 文")):
            q = self.quest()
            g = self.goal(q, "x", form=form)
            text = Path(self.ok("make-brief", g, "alchemist")).read_text(encoding="utf-8")
            self.assertIn(f"書き方（形：{form}）", text)
            self.assertIn(key, text)
            self.assertNotIn("書き方（形", Path(self.ok("make-brief", g, "appraiser")).read_text(encoding="utf-8"))

    def test_依頼の納品物の形と急ぎ度を受け取る(self):
        q = self.ok("add-quest", "--title", "x", "--form", "Excel", "--priority", "優先")
        d = self.data()["quests"][q]
        self.assertEqual((d["form_hint"], d["priority"]), ("Excel", "優先"))
        self.assertIn("納品物の形：Excel", Path(self.ok("make-brief", q, "fortune_teller")).read_text(encoding="utf-8"))
        self.ok("add-quest", "--title", "y", "--form", "その他（くわしくへ）")
        self.ng("add-quest", "--title", "z", "--form", "毛筆")

    def test_make_briefはクエスト単位でも作れる(self):
        q = self.quest()
        aid = self.ok("add-question", "--quest", q, "--text", "形式は", "--options", json.dumps([{"label": "Excel"}, {"label": "Word"}]))
        self.ok("answer", aid, "--choice", "Excel")
        text = Path(self.ok("make-brief", q, "receptionist")).read_text(encoding="utf-8")
        self.assertIn("形式は → Excel", text)
        self.assertIn(f"{q}-receptionist.md", text)

    def test_usage_log(self):
        self.ok("usage-log", "--role", "adventurer", "--model", "sonnet", "--tokens", "1200")
        row = json.loads((self.p.logs / "usage.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual((row["role"], row["model"], row["tokens"]), ("adventurer", "sonnet", 1200))

    def test_set_topの検査(self):
        self.ng("set-top", "limits", '{"max_active": 9}')
        self.ng("set-top", "quests", "{}")

    def test_versionは盤がなくても動く(self):
        code, out, _ = cli(self.root / "nowhere", "version")
        self.assertEqual((code, out.strip()), (0, board.VERSION))


class TestScreenContract(Base):
    """画面（board.html）は board.json を書かず、answers/ と requests/ にだけ書く。"""

    def screen_answer(self, aid, **kw):
        self.p.answers.mkdir(parents=True, exist_ok=True)
        rec = {"question": aid, "choice": "A", "comment": "", "time": "2026-03-01T09:00:00", "consumed": False}
        rec.update(kw)
        (self.p.answers / f"{aid}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

    def req(self, name, obj):
        self.p.requests.mkdir(parents=True, exist_ok=True)
        (self.p.requests / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_画面が書いた回答を取り込む(self):
        q = self.quest()
        aid = self.ok("add-question", "--quest", q, "--text", "どれ", "--options", json.dumps([{"label": "A"}, {"label": "B"}]))
        self.screen_answer(aid, quest=q, covers=[q], scope="none", choice="B")
        self.ok("apply-simple")
        qq = self.data()["questions"][0]
        self.assertEqual((qq["status"], qq["answer"]), ("回答済", "B"))

    def test_画面の回答で承認の辺が通る(self):
        q = self.quest()
        self.goal(q)
        self.ok("set-status", q, "分解中")
        self.ok("set-status", q, "承認待ち")
        aid = self.ok("add-question", "--quest", q, "--kind", "approval", "--scope", "route", "--text", "承認してください",
                      "--options", json.dumps([{"label": "承認する"}, {"label": "やり直す"}], ensure_ascii=False))
        self.assertEqual(self.data()["questions"][0]["diagram"], f"diagrams/route-{q}.svg")
        self.screen_answer(aid, quest=q, covers=[q], scope="route", choice="承認する")
        self.ok("set-status", q, "進行中", "--who", "client")  # 記録だけで通る

    def test_選び直す(self):
        q = self.quest()
        aid = self.ok("add-question", "--quest", q, "--text", "どれ", "--options", json.dumps([{"label": "A"}, {"label": "B"}]))
        self.screen_answer(aid, quest=q, covers=[q], scope="none", choice="A")
        self.ok("apply-simple")
        self.screen_answer(aid, reopen=True)
        self.ok("apply-simple")
        self.assertEqual(self.data()["questions"][0]["status"], "未回答")
        self.assertFalse((self.p.answers / f"{aid}.json").exists())

    def test_あとで決める(self):
        q = self.quest()
        aid = self.ok("add-question", "--quest", q, "--text", "どれ", "--options", json.dumps([{"label": "A"}, {"label": "あとで決める"}]))
        self.screen_answer(aid, quest=q, covers=[q], scope="none", choice="あとで決める")
        self.ok("apply-simple")
        self.assertEqual(self.data()["questions"][0]["status"], "保留")

    def test_保留と再開の依頼(self):
        q, _ = self.to_running()
        self.req("H1.json", {"kind": "hold", "quest": q, "action": "hold"})
        self.ok("apply-simple")
        self.assertEqual(self.data()["quests"][q]["status"], "保留")
        self.req("H2.json", {"kind": "hold", "quest": q, "action": "resume"})
        self.ok("apply-simple")
        self.assertEqual(self.data()["quests"][q]["status"], "進行中")

    def test_最終鑑定の希望(self):
        q, (g,) = self.to_running()
        self.to_confirm(q, g)
        self.approve("output", g, goal=g, quest=q)
        self.ok("set-status", g, "達成", "--who", "client")
        self.req("W1.json", {"kind": "final_review", "quest": q})
        self.ok("apply-simple")
        self.assertEqual(self.data()["quests"][q]["status"], "最終鑑定")

    def test_最終鑑定で矛盾があれば達成条件が要手直しに戻る(self):
        q, (g,) = self.to_running()
        self.to_confirm(q, g)
        self.approve("output", g, goal=g, quest=q)
        self.ok("set-status", g, "達成", "--who", "client")
        self.ok("decide", q, "--choice", "最終鑑定を頼む")
        self.ok("set-status", q, "最終鑑定", "--who", "client")
        self.ok("add-finding", g, "--fix-kind", "brief", "--point-code", "矛盾", "--target", "x", "--point", "数値が合わない")
        self.ok("set-status", q, "進行中", "--who", "appraiser", "--goals", g)
        self.assertEqual(self.data()["goals"][g]["status"], "要手直し")

    def test_道のり図のファイルができる(self):
        q = self.quest()
        self.goal(q, "単価表")
        svg = (self.p.sys / "diagrams" / f"route-{q}.svg").read_text(encoding="utf-8")
        self.assertIn("<svg", svg)
        self.assertTrue((self.p.sys / "diagrams" / f"route-{q}.txt").exists())


if __name__ == "__main__":
    unittest.main()

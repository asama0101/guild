"""計画を直し中（replan）の依頼で、受付係の質問がボードの手紙に出る。答えの取り出しも、計画がある依頼で動く。"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402
from test_board_js import extract, node_eval  # noqa: E402

QS = [{"text": "週報の読み手は誰ですか", "options": ["部長", "チーム"]}, {"text": "いつまでに必要ですか"}]


def derive_js(quest):
    """derive() を、前の答えの持ち方も含めて実行し、(label, asks の数, sent, info, me) を返す。"""
    src = ("const planList = () => [];\nconst closed = (s) => s === 'done' || s === 'skipped';\nconst TSTATE = {};\n" + extract("derive") + "\n"
           "const q = " + json.dumps(quest, ensure_ascii=False) + ";\nconst d = derive(q);\n"
           "console.log(JSON.stringify({ label: d.label, asks: d.asks.map((a) => ({ kind: a.kind, sent: a.sent })), info: d.info, me: d.me }));")
    return node_eval(src)


def quest(plan, draft, inbox):
    return {"id": "Q004", "plan": plan, "request": {"text": "週報を作る"}, "draft": draft, "inbox": inbox, "reports": [], "output": [], "archive": None, "published": []}


@unittest.skipUnless(shutil.which("node"), "node がありません")
class ReplanQuestionsTest(unittest.TestCase):
    PLAN = {"title": "週報", "status": "replan", "approved": False, "goals": []}

    def test_replan_with_questions_shows_a_questions_letter(self):
        r = derive_js(quest(self.PLAN, {"questions": QS}, []))
        self.assertEqual((r["label"], r["me"], r["info"]), ("質問あり", "質問", None))
        self.assertEqual(r["asks"], [{"kind": "questions", "sent": False}])

    def test_replan_without_questions_keeps_the_waiting_letter(self):
        for draft in (None, {"questions": []}, {"goals": []}):
            r = derive_js(quest(self.PLAN, draft, []))
            self.assertEqual((r["label"], r["info"], r["asks"]), ("計画を直し中", "replan", []), repr(draft))

    def test_old_answers_do_not_mark_new_questions_as_answered(self):
        old = [{"type": "answers", "goal": None, "choice": None, "qs": ["前回の質問 1", "前回の質問 2"]}]
        r = derive_js(quest(self.PLAN, {"questions": QS}, old))
        self.assertEqual(r["asks"], [{"kind": "questions", "sent": False}])

    def test_answers_to_the_same_questions_mark_it_answered(self):
        same = [{"type": "answers", "goal": None, "choice": None, "qs": [q["text"] for q in QS]}]
        r = derive_js(quest(self.PLAN, {"questions": QS}, same))
        self.assertEqual((r["label"], r["me"], r["asks"]), ("分解中", "—", [{"kind": "questions", "sent": True}]))
        just_sent = [{"type": "answers", "goal": None, "choice": None, "qs": None}]  # 送ったばかり（まだ取り出していない）
        self.assertTrue(derive_js(quest(self.PLAN, {"questions": QS}, just_sent))["asks"][0]["sent"])

    def test_quest_without_a_plan_is_unchanged(self):
        r = derive_js(quest(None, {"questions": QS}, []))
        self.assertEqual((r["label"], r["asks"]), ("質問あり", [{"kind": "questions", "sent": False}]))
        self.assertEqual(derive_js(quest(None, None, []))["info"], "decomposing")


class ReplanAnswersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.q = Path(guild.new_quest(self.root)["dir"])
        guild.save_json(self.q / "plan.json", {"quest": "Q001", "title": "週報", "series": "週報", "approved": False, "status": "replan", "goals": [], "history": []})
        (self.q / "inbox").mkdir(exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingest_leaves_answers_and_take_answers_takes_only_answers(self):
        (self.q / "inbox" / "a-answers.json").write_text(json.dumps({"type": "answers", "answers": [{"q": "x", "a": "y"}]}), encoding="utf-8")
        plan = guild.load_plan(self.q / "plan.json")
        report = guild.ingest(self.q / "plan.json", plan, guild.load_transitions(), commit=lambda: None)
        self.assertEqual(report["applied"], [])  # replan 中の answers は、取り込まずに残す
        self.assertTrue((self.q / "inbox" / "a-answers.json").exists())
        got = guild.take_answers(self.q)
        self.assertEqual(len(got), 1)
        self.assertTrue((self.q / "inbox" / "done" / "a-answers.json").exists())
        self.assertFalse((self.q / "inbox" / "rejected").exists())  # 計画がある依頼の、ほかの入力は捨てない

    def test_take_answers_keeps_other_inputs_when_a_plan_exists(self):
        (self.q / "inbox" / "c-decision.json").write_text(json.dumps({"type": "decision", "choice": "abort"}), encoding="utf-8")
        self.assertEqual(guild.take_answers(self.q), [])
        self.assertTrue((self.q / "inbox" / "c-decision.json").exists())


if __name__ == "__main__":
    unittest.main()


class LoaderWiringTest(unittest.TestCase):
    def test_loader_reads_the_draft_and_taken_answers_for_a_replan_quest(self):
        board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        self.assertIn("const draft = !plan || plan.status === 'replan' ?", board)
        self.assertIn("if (!plan || plan.status === 'replan') for (const f of await S.fs.list(`${q}/inbox/done`))", board)

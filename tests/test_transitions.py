"""transitions.json のテスト（SPEC 17 節）：定数・権限・到達性・SKILL.md との一致。"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import constants as C  # noqa: E402

spec = importlib.util.spec_from_file_location("board", ROOT / "skills" / "quest" / "board.py")
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)

T = json.loads((ROOT / "skills" / "quest" / "transitions.json").read_text(encoding="utf-8"))
SKILL = ROOT / "skills" / "quest" / "SKILL.md"
SVG = ROOT / "skills" / "quest" / "references" / "state-diagram.svg"


def reachable(edges, start):
    seen, todo = {start}, [start]
    while todo:
        cur = todo.pop()
        for e in edges:
            if e["from"] == cur and e["to"] not in seen:
                seen.add(e["to"])
                todo.append(e["to"])
    return seen


class TestConstants(unittest.TestCase):
    def test_board_pyの定数が定数ファイルと一致する(self):
        self.assertEqual(board.QUEST_STATES, C.QUEST_STATES)
        self.assertEqual(board.GOAL_STATES, C.GOAL_STATES)
        self.assertEqual(board.QUEST_LABELS, C.QUEST_LABELS)
        self.assertEqual(board.GOAL_LABELS, C.GOAL_LABELS)
        self.assertEqual(board.QUEST_TERMINAL, C.QUEST_TERMINAL)
        self.assertEqual(board.GOAL_TERMINAL, C.GOAL_TERMINAL)
        self.assertEqual(board.ROLE_WRITES, C.ROLE_WRITES)
        self.assertEqual(sorted(board.ACTORS), sorted(C.ACTORS + C.INTERNAL_ACTORS))
        self.assertEqual(board.FIX_KINDS, C.FIX_KINDS)
        self.assertEqual(board.POINT_CODES, C.POINT_CODES)

    def test_ラベルは全部の状態にある(self):
        self.assertEqual(sorted(C.QUEST_LABELS), sorted(C.QUEST_STATES))
        self.assertEqual(sorted(C.GOAL_LABELS), sorted(C.GOAL_STATES))


class TestTransitionsJson(unittest.TestCase):
    def edges(self):
        return [("quest", e) for e in T["quest"]] + [("goal", e) for e in T["goal"]]

    def test_版と構造(self):
        self.assertEqual(T["version"], 1)
        for kind, e in self.edges():
            for k in ("from", "to", "actor", "guards", "note", "writes"):
                self.assertIn(k, e, f"{kind} {e}")

    def test_状態名は定数にある(self):
        for e in T["quest"]:
            self.assertIn(e["from"], C.QUEST_STATES)
            self.assertIn(e["to"], C.QUEST_STATES)
        for e in T["goal"]:
            self.assertIn(e["from"], C.GOAL_STATES)
            self.assertIn(e["to"], C.GOAL_STATES)

    def test_役はすべて既知(self):
        for kind, e in self.edges():
            for a in e["actor"]:
                self.assertIn(a, C.ACTORS + C.INTERNAL_ACTORS, e)

    def test_述語は既知で_board_pyが評価できる(self):
        known = set(C.GUARD_IDS + C.EXTRA_GUARD_IDS)
        for kind, e in self.edges():
            for g in e["guards"]:
                name, _ = board.parse_guard(g)
                self.assertIn(name, known, g)
        # SPEC の述語 ID がすべて、どこかの辺で使われている（必要なものが抜けていない）
        used = {board.parse_guard(g)[0] for _, e in self.edges() for g in e["guards"]}
        for g in C.GUARD_IDS:
            self.assertIn(g, used, f"述語 {g} が transitions.json で使われていない")

    def test_approval_recordedはscope付き(self):
        for kind, e in self.edges():
            for g in e["guards"]:
                name, arg = board.parse_guard(g)
                if name == "approval_recorded":
                    self.assertIn(arg, ("route", "output", "execute"))

    def test_writesの値と権限(self):
        for kind, e in self.edges():
            for w in e["writes"]:
                self.assertIn(w, C.WRITES_VALUES)
                self.assertTrue(any(w in C.ROLE_WRITES[a] or w == "board" for a in e["actor"]),
                                f"{e['from']}→{e['to']} の {w} を書ける役がいない")
            self.assertIn("board", e["writes"])

    def test_clientの辺には選択肢がある(self):
        for kind, e in self.edges():
            if "client" in e["actor"]:
                self.assertTrue(e.get("choices"), f"{e['from']}→{e['to']}")

    def test_要手直しへの障害の辺には理由がある(self):
        e = [x for x in T["goal"] if x["from"] == "冒険中" and x["to"] == "要手直し"][0]
        self.assertEqual(sorted(e["reasons"]), sorted(board.REWORK_REASONS))

    def test_重複した辺はない(self):
        seen = set()
        for kind, e in self.edges():
            key = (kind, e["from"], e["to"], tuple(e["actor"]), tuple(e["guards"]))
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_クエストの状態にすべて到達できる(self):
        self.assertEqual(reachable(T["quest"], "受付"), set(C.QUEST_STATES))

    def test_達成条件の状態にすべて到達できる(self):
        self.assertEqual(reachable(T["goal"], "案"), set(C.GOAL_STATES))

    def test_出口のない状態は終端だけ(self):
        for kind, states, terminal in (("quest", C.QUEST_STATES, C.QUEST_TERMINAL), ("goal", C.GOAL_STATES, C.GOAL_TERMINAL)):
            for s in states:
                has_exit = any(e["from"] == s for e in T[kind])
                if s in terminal:
                    continue
                self.assertTrue(has_exit, f"{kind} の {s} に出口がない")

    def test_終端から出る辺は例外だけ(self):
        # 達成条件の達成は、最終鑑定で要手直しに戻る辺だけを持つ。クエストの終端は出口がない。
        self.assertEqual([e for e in T["quest"] if e["from"] in C.QUEST_TERMINAL], [])
        out = [e for e in T["goal"] if e["from"] == "達成"]
        self.assertEqual([(e["to"], tuple(e["actor"])) for e in out], [("要手直し", ("appraiser",))])
        self.assertEqual([e for e in T["goal"] if e["from"] == "中止"], [])

    def test_承認の辺は依頼主だけが通せる(self):
        for kind, e in self.edges():
            if any(board.parse_guard(g)[0] == "approval_recorded" for g in e["guards"]):
                self.assertEqual(e["actor"], ["client"], f"{e['from']}→{e['to']}")

    def test_納品物に書ける役(self):
        writers = {a for kind, e in self.edges() if "output" in e["writes"] for a in e["actor"]}
        self.assertTrue(writers <= {"alchemist", "smith", "workshop"})

    def test_承認前に進行中や達成へ行く辺は依頼主の承認を要する(self):
        e = [x for x in T["quest"] if (x["from"], x["to"]) == ("承認待ち", "進行中")][0]
        self.assertEqual(e["guards"], ["approval_recorded(route)"])
        e = [x for x in T["goal"] if (x["from"], x["to"]) == ("確認待ち", "達成")][0]
        self.assertIn("approval_recorded(output)", e["guards"])


class TestGeneratedFiles(unittest.TestCase):
    def test_SKILL_mdの遷移表は_transitions_jsonから作ったものと一致する(self):
        text = SKILL.read_text(encoding="utf-8")
        a, z = board.TEMPLATE_MARK
        self.assertIn(a, text)
        self.assertIn(z, text)
        body = text[text.index(a) + len(a): text.index(z)].strip("\n")
        self.assertEqual(body, board.transitions_md(T).strip("\n"))

    def test_状態図のSVGは_transitions_jsonから作ったものと一致する(self):
        self.assertEqual(SVG.read_text(encoding="utf-8"), board.transitions_svg(T) + "\n")

    def test_状態図のSVGにtitleとdescがある(self):
        svg = SVG.read_text(encoding="utf-8")
        self.assertIn("<title", svg)
        self.assertIn("<desc", svg)
        for s in C.QUEST_STATES + C.GOAL_STATES:
            self.assertIn(s, svg)

    def test_gen_transitionsのcheckは一致なら成功(self):
        code = board.main(["--root", str(ROOT), "gen-transitions", "--skill", str(SKILL), "--svg", str(SVG), "--check"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

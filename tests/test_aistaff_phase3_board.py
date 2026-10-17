"""AI 社員 Phase 3：board.html の純粋な部分（勧める対応の取り出し、クエストログ）を node で実行して確かめる。"""
import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_board_js import extract, node_eval  # noqa: E402

BOARD = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
FAKE = ("const h = (t, a, ...c) => ({ t, c: c.flat(Infinity) });\n"
        "const text = (n) => (n == null ? '' : typeof n === 'string' ? n : Array.isArray(n) ? n.map(text).join('|') : text(n.c));\n")


@unittest.skipUnless(shutil.which("node"), "node がありません")
class BoardLogicTest(unittest.TestCase):
    def test_advice_line_accepts_only_the_three_actions(self):
        funcs = "".join(extract(n) + "\n" for n in ("excerpt", "reportSection", "adviceLine"))
        code = funcs + r"""
const rep = (b) => '## 判定\nrejected\n## 勧める対応\n' + b + '\n## 次\nx';
console.log(JSON.stringify([adviceLine(rep('もう一度 — 直せる')), adviceLine(rep('計画を直す — 分け方')), adviceLine(rep('やめる — 取れない')),
  adviceLine(rep('なし')), adviceLine(rep('好きにして')), adviceLine('## 判定\npassed')]));"""
        self.assertEqual(node_eval(code), ["もう一度 — 直せる", "計画を直す — 分け方", "やめる — 取れない", "", "", ""])

    def log_text(self, clog):
        src = "const CLASS_NAMES = { wizard: '魔法使い', alchemist: '錬金術師', adventurer: '冒険者' };\n" + extract("logTab")
        data = json.dumps(clog, ensure_ascii=False)
        return node_eval(FAKE + src + "\nconst S = { clog: " + data + " };\nconsole.log(JSON.stringify(text(logTab())));")

    def test_log_tab_shows_needs_workers_blockers_followups_and_stats(self):
        clog = {"t": "2026-10-17T10:00:00+09:00", "needs_total": 2,
                "stats": {"quests": 1, "goals": 3, "done": 1, "failed": 1, "rejected": 2, "retries": 1, "replans": 0},
                "quests": [{"id": "Q001", "title": "週報の作成", "series": "週報", "label": "あなたの番", "goals": {"total": 3, "done": 1},
                            "active": [{"id": "G2", "title": "集める", "class": "alchemist", "effects": "none", "state": "running"}],
                            "needs": [{"kind": "decision", "text": "G3 の失敗の判断", "advice": {"text": "やめる — 取れない"}}],
                            "blockers": [{"goal": "G4", "because": ["G3"]}], "followups": ["来週分も作る"]}]}
        out = self.log_text(clog)
        for needle in ("あなたの番（2 件）", "鑑定士のおすすめ：やめる — 取れない", "錬金術師：G2 集める", "G4 は、G3 ができなかったため", "来週分も作る", "不合格 2 回"):
            self.assertIn(needle, out, needle)

    def test_log_tab_without_a_log_says_so(self):
        self.assertIn("まだクエストログがありません", self.log_text(None))

    def test_finished_and_aborted_quests_are_not_listed_as_in_progress(self):
        clog = {"t": "x", "needs_total": 0, "stats": {}, "quests": [
            {"id": "Q001", "title": "終わった", "label": "完了", "goals": {}, "active": [], "needs": [], "blockers": [], "followups": []},
            {"id": "Q002", "title": "動いている", "label": "進行中", "goals": {"total": 2, "done": 1}, "active": [], "needs": [], "blockers": [], "followups": []}]}
        out = self.log_text(clog)
        self.assertIn("Q002 動いている", out)
        self.assertNotIn("Q001 終わった", out)


class BoardWiringTest(unittest.TestCase):
    def test_wiring(self):
        for needle in ("['log', 'クエストログ']", "log: logTab", "S.clog = cl ? JSON.parse(cl) : null", r"[/^clog\.json$/, '.work/clog.json']",
                       "followupBox(qd)", "鑑定士のおすすめ：", "function metaEditor(", "type: 'meta', title, series", "S.seriesFilter",
                       r"split('\n')[0].slice(0, 24)", "FORMATS.some(([v]) => v === S.form['new:format'])", "targets"):
            self.assertIn(needle, BOARD, needle)


if __name__ == "__main__":
    unittest.main()

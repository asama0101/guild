"""board.html の JavaScript の構文検査（node があるときだけ）と、承認の手紙・ボードが読む plan.json のキーの契約。"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")


def script():
    return "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", BOARD, re.S))


@unittest.skipUnless(shutil.which("node"), "node がありません")
class BoardSyntaxTest(unittest.TestCase):
    def test_script_parses(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "board.js"
            f.write_text(script(), encoding="utf-8")
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)


class PlanBriefContractTest(unittest.TestCase):
    def test_approval_letter_shows_brief_check_workload_and_diff(self):
        i = BOARD.index("'aria-label': '計画の承認'")
        letter = BOARD[i:i + 1500]
        self.assertIn("planBriefBlock(qd.q.plan)", letter)
        body = BOARD[BOARD.index("function planBriefBlock"):BOARD.index("const TEXT_INPUT")]
        for key in ("p.brief", "p.check", "p.workload", "p.replan_diff", "non_goals", "assumptions", "risks",
                    "coverage", "over_deadline"):
            self.assertIn(key, body)


class NoDuplicateFunctionTest(unittest.TestCase):
    def test_no_duplicate_top_level_function(self):
        names = re.findall(r"^(?:async )?function (\w+)\(", script(), re.M)
        dup = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(dup, [], f"同名の function 宣言があります（後ろが前を上書きします）: {dup}")


def extract(name):
    """board.html のスクリプトから、トップレベルの function <name> を、波括弧の対応で切り出す。"""
    src = script()
    i = src.index(f"function {name}(")
    depth, j = 0, src.index("{", i)
    for k in range(j, len(src)):
        depth += src[k] == "{"
        depth -= src[k] == "}"
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(name)


def node_eval(code):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.js"
        f.write_text(code, encoding="utf-8")
        r = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "node がありません")
class VisibilityLogicTest(unittest.TestCase):
    def test_alive_info(self):
        code = extract("aliveInfo") + """
const now = Date.parse('2026-10-17T12:00:00+09:00'), iso = (s) => new Date(now - s * 1000).toISOString();
console.log(JSON.stringify([
  aliveInfo(null, now).cls,
  aliveInfo({ state: 'waiting', t: iso(30) }, now).cls,
  aliveInfo({ state: 'waiting', t: iso(120) }, now).cls,
  aliveInfo({ state: 'working', t: iso(300) }, now).cls,
  aliveInfo({ state: 'working', t: iso(900) }, now).cls,
  aliveInfo({ state: 'working', t: iso(-3600) }, now).cls,
  aliveInfo({ state: 'working', t: iso(4000) }, now).cls,
  aliveInfo({ state: 'waiting', t: 'x' }, now).cls,
  aliveInfo({ state: 'waiting', t: iso(30) }, now).text.includes('待機中'),
  aliveInfo({ state: 'waiting', t: iso(120) }, now).text.includes('停止中')]));"""
        self.assertEqual(node_eval(code), ["off", "on", "off", "on", "on", "off", "off", "off", True, True])

    def test_flow_issues(self):
        code = "const closed = (s) => s === 'done' || s === 'skipped';\n" + extract("flowIssues") + """
const plan = { approved: true, goals: [
  { id: 'G1', state: 'failed', deps: [] }, { id: 'G2', state: 'blocked', deps: ['G1'] }, { id: 'G3', state: 'blocked', deps: ['G2'] },
  { id: 'G4', state: 'skipped', deps: [] }, { id: 'G5', state: 'pending', deps: ['G4', 'G6'] }, { id: 'G6', state: 'running', deps: [] }] };
const by = (id) => plan.goals.find((t) => t.id === id);
console.log(JSON.stringify({
  t2: flowIssues(plan, by('G2')), t3: flowIssues(plan, by('G3')), t5: flowIssues(plan, by('G5')),
  done: flowIssues(plan, { id: 'G9', state: 'done', deps: ['G4'] }), aborted: flowIssues({ ...plan, status: 'aborted' }, by('G2')), draft: flowIssues({ approved: false, goals: plan.goals }, by('G2')) }));"""
        r = node_eval(code)
        self.assertEqual(r["t2"], ["止まっている原因：G1 ができませんでした。"])
        self.assertEqual(r["t3"], ["止まっている原因：G1 ができませんでした。"])  # 失敗の根本まで辿る
        self.assertEqual(r["t5"], ["前提 G4 はやめたので、その結果がないまま進みます。", "G6 の完了を待っています。"])
        self.assertEqual(r["done"], [])
        self.assertEqual(r["draft"], [])  # 承認前は出さない
        self.assertEqual(r["aborted"], [])  # 中止された依頼にも出さない


class VisibilityContractTest(unittest.TestCase):
    def test_heartbeat_is_mapped_and_read_outside_the_change_key(self):
        self.assertIn(r"[/^heartbeat\.json$/, '.work/heartbeat.json']", BOARD)
        self.assertIn("S.hb = hb ? JSON.parse(hb) : null", BOARD)

    def test_title_and_notification_hooks(self):
        for needle in ("function updateTitle()", "document.title = (n ?", "new Notification(", "Notification.requestPermission()", "notifyNew(prevNeeds)"):
            self.assertIn(needle, BOARD)


if __name__ == "__main__":
    unittest.main()

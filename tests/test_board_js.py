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

    def test_title_count_is_kept_and_desktop_notification_is_gone(self):
        for needle in ("function updateTitle()", "document.title = (n ?"):
            self.assertIn(needle, BOARD)
        for gone in ("new Notification(", "Notification.requestPermission()", "notifyNew", "notifyButton"):
            self.assertNotIn(gone, BOARD)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("node"), "node がありません")
class ParentDomainTest(unittest.TestCase):
    def test_parent_domain(self):
        src = re.search(r"const SHARED_HOSTS = .*?\n", script()).group(0) + re.search(r"const SECOND_LEVEL = .*?\n", script()).group(0) + extract("parentDomain")
        cases = ["www.e-stat.go.jp", "www3.boj.or.jp", "ja.wikipedia.org", "example.com", "alice.github.io", "x.y.alice.github.io", "github.io", "a.b.co.uk"]
        out = node_eval(src + f"console.log(JSON.stringify({json.dumps(cases)}.map(parentDomain)))")
        self.assertEqual(out, ["e-stat.go.jp", "boj.or.jp", "wikipedia.org", "example.com", "alice.github.io", "alice.github.io", "github.io", "b.co.uk"])


class PressingDefersRefreshTest(unittest.TestCase):
    def test_refresh_waits_while_a_button_is_held(self):
        self.assertIn("isPressing() ||", BOARD)
        for needle in ("addEventListener('pointerdown'", "addEventListener('pointerup', released", "S.pressAt = 0"):
            self.assertIn(needle, BOARD, needle)

    def test_skill_limits_parallel_roles_so_arrivals_are_taken_sooner(self):
        self.assertIn("一度に 3 つまで", (ROOT / "skills" / "quest" / "SKILL.md").read_text(encoding="utf-8"))


class PauseBoxTest(unittest.TestCase):
    def test_pause_box_checks_the_heartbeat_and_explains_the_limit(self):
        box = BOARD[BOARD.index("function pauseBox()"):BOARD.index("async function closeGuild()")]
        for needle in ("aliveInfo(S.hb, Date.now())", "印だけが残っています", "その役が返るまで", "止める作業がないので"):
            self.assertIn(needle, box, needle)
        self.assertIn("on ? h('button', { class: 'btn wax'", box)  # 動いていないときは「閉める」を出さない


class SelectOpenDefersRefreshTest(unittest.TestCase):
    def test_refresh_waits_while_a_select_is_open(self):
        for needle in ("ae.tagName === 'SELECT' && S.selAt", "addEventListener('focusin'", "S.selAt = 0"):
            self.assertIn(needle, BOARD, needle)


class AllowListLinksTest(unittest.TestCase):
    def test_allow_list_domains_are_links(self):
        card = BOARD[BOARD.index("function webCard(m)"):BOARD.index("function webTab()")]
        for needle in ("const site = (d) =>", "href: `https://${d}/`", "rel: 'noopener noreferrer'", "site(d)"):
            self.assertIn(needle, card, needle)


class WhoBadgeTest(unittest.TestCase):
    def test_goal_rows_tell_human_from_auto(self):
        row = BOARD[BOARD.index("function goalRow("):BOARD.index("function goalRow(") + 900]
        for needle in ("t.kind === 'human' ? 'me' : 'auto'", "whoBadge(t)"):
            self.assertIn(needle, row, needle)
        badge = BOARD[BOARD.index("function whoBadge("):BOARD.index("function goalRow(")]
        for needle in ("あなたが実行", "ギルドが自動（実行前に確認）"):
            self.assertIn(needle, badge, needle)


class ResultLetterRequiresRecordTest(unittest.TestCase):
    def test_yes_without_memo_or_attachment_is_stopped_before_sending(self):
        for needle in ("鑑定士が確かめること", "!(S.form[key + ':memo'] || '').trim() && !files.length", "S.form[key + ':err']", "textarea(memo, { id: k + 'memo', class: 'need' })"):
            self.assertIn(needle, BOARD, needle)


class StickyHeaderAndStaticTabsTest(unittest.TestCase):
    def test_header_and_tabs_are_one_sticky_block(self):
        for needle in (".stickyhead{position:sticky;top:0", "h('div', { class: 'stickyhead' }, banner(),", "--headh", "calc(var(--headh,70px)"):
            self.assertIn(needle, BOARD, needle)

    def test_reading_tabs_are_not_rebuilt_by_quest_updates(self):
        for needle in ("const staticTab = S.tab === 'help' || S.tab === 'obs';", "if (!force && staticTab && chromeSig() === S.chromeSig) return;", "S.chromeSig = chromeSig();"):
            self.assertIn(needle, BOARD, needle)

    def test_allow_list_shows_notes(self):
        card = BOARD[BOARD.index("function webCard(m)"):BOARD.index("function webTab()")]
        for needle in ("noteOf", "説明はまだありません", "AI の推測（事実ではありません）"):
            self.assertIn(needle, card, needle)


class FollowupActionsTest(unittest.TestCase):
    def test_followups_can_become_requests_or_be_dismissed(self):
        for needle in ("function followupList(", "依頼にする", "見送る", "見送った提案", "'guild.followups.hidden'", "function followupToRequest("):
            self.assertIn(needle, BOARD, needle)
        self.assertIn("app.style.minHeight", BOARD)  # 作り直す間にページが縮まない


class LogYesNeedsMemoTest(unittest.TestCase):
    def test_log_yes_asks_for_a_memo_in_the_same_row(self):
        row = BOARD[BOARD.index("function turnRow("):BOARD.index("function logTab(")]
        for needle in ("class: 'logmemo'", "メモ必須", "メモ（必須）", "if (ok && !note)", "メモを書いてください", "e.key === 'Enter'", "note, files: []"):
            self.assertIn(needle, row, needle)

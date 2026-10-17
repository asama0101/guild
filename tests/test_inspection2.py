"""総点検（2 回目）の指摘の修正を確かめる。"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
sys.path.insert(0, str(ROOT / "tests"))
import guild  # noqa: E402
import webaccess  # noqa: E402
from test_board_js import extract, node_eval  # noqa: E402
from test_audit_fixes import LOAD_JS  # noqa: E402

FAKE_H = ("const h = (t, a, ...c) => ({ t, c: c.flat(Infinity) });\n"
          "const text = (n) => (n == null ? '' : typeof n === 'string' ? n : Array.isArray(n) ? n.map(text).join('|') : text(n.c));\n")
BOARD_SRC = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")

TR = guild.load_transitions()
CRIT = {"viewpoint": "viewpoint 十分に具体的", "pass_line": "pass_line 十分に具体的", "check": "check 十分に具体的"}


def goal(i, state="pending", **kw):
    t = {"id": i, "title": f"{i}を調べる", "kind": "auto", "class": "wizard", "effects": "none", "deps": [], "criteria": dict(CRIT), "state": state, "retries": 0}
    t.update(kw)
    return t


@unittest.skipUnless(shutil.which("node"), "node がありません")
class BoardDatesTest(unittest.TestCase):
    def test_overdue_and_day_number_use_valid_dates(self):
        src = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        line = lambda name: re.search(rf"^const {name} = .*$", src, re.M).group(0)
        code = "\n".join(line(n) for n in ("closed", "overdue", "DAY_MS", "dayNum", "okDate")) + """
const now = new Date('2026-10-17T12:00:00').getTime();
console.log(JSON.stringify([
  overdue({ due: '2026-10-16', state: 'running' }, now),
  overdue({ due: '2026-10-17', state: 'running' }, now),
  overdue({ due: '2026-10-16', state: 'done' }, now),
  okDate('2026-10-17'), okDate('2026-13-45'), dayNum('2026-10-18') - dayNum('2026-10-17')]));"""
        self.assertEqual(node_eval(code), [True, False, False, True, False, 1])


class ReplanAcceptedTest(unittest.TestCase):
    def test_accepted_quest_cannot_take_a_replan_decision(self):
        plan = {"approved": True, "status": "active", "accepted": True, "goals": [goal("G1", "done")], "history": []}
        with self.assertRaises(guild.GuildError):
            guild.apply_input(plan, {"type": "decision", "goal": "G1", "choice": "replan"}, TR)
        self.assertTrue(plan["accepted"])
        self.assertEqual(plan["status"], "active")

    def test_replan_before_accepting_still_works(self):
        plan = {"approved": True, "status": "active", "goals": [goal("G1", "done")], "history": []}
        guild.apply_input(plan, {"type": "decision", "goal": "G1", "choice": "replan"}, TR)
        self.assertEqual((plan["status"], plan["approved"]), ("replan", False))


class AdvanceStateTest(unittest.TestCase):
    def run_advance(self, plan, goal_id, event):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.json"
            guild.save_json(path, plan)
            with self.assertRaises(guild.GuildError) as cm:
                guild.mutate_plan("advance", path, ["guild.py", "advance", str(path), goal_id, event])
            return str(cm.exception)

    def test_advance_is_refused_for_aborted_replan_and_unapproved_plans(self):
        for kw in ({"approved": True, "status": "aborted"}, {"approved": True, "status": "replan"}, {"approved": False, "status": "active"}):
            plan = {"quest": "Q001", "title": "t", **kw, "goals": [goal("G1", "running")], "history": []}
            self.assertIn("進められません", self.run_advance(plan, "G1", "submitted"), kw)


class ArchivePrefixTest(unittest.TestCase):
    def test_a_goal_does_not_take_another_goals_reports(self):
        tr = guild.load_transitions()
        self.assertTrue(guild.validate({"goals": [goal("A-B")]}, tr))  # id に - は使えない（reports/<id>-… の前方一致で、別の目標のものまで動くため）
        with tempfile.TemporaryDirectory() as d:
            q = Path(d)
            (q / "reports").mkdir()
            (q / "reports" / "G1-appraiser.md").write_text("x", encoding="utf-8")
            (q / "reports" / "G12-appraiser.md").write_text("y", encoding="utf-8")
            guild.archive_outputs({"goals": [goal("G1")]}, [], q)
            self.assertTrue((q / "reports" / "G12-appraiser.md").exists())
            self.assertFalse((q / "reports" / "G1-appraiser.md").exists())


class EvidenceDecorationTest(unittest.TestCase):
    def check(self, body):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d)
            (q / "reports").mkdir()
            (q / "reports" / "G1-appraiser.md").write_text(body, encoding="utf-8")
            guild.check_evidence({"history": []}, "G1", q)

    def test_decorated_passed_is_accepted(self):
        for body in ("## 判定\npassed\n", "## 判定\n**passed**\n", "## 判定\n- passed\n", "## 判定\n`passed`\n", "## 判定\n> Passed\n"):
            self.check(body)

    def test_other_verdicts_are_refused(self):
        for body in ("## 判定\n**rejected**\n", "## 判定\nnot passed\n", "## 判定\n\n", "判定なし"):
            with self.assertRaises(guild.GuildError, msg=body):
                self.check(body)


class ResultInputTest(unittest.TestCase):
    def plan(self):
        return {"quest": "Q001", "title": "t", "approved": True, "status": "active",
                "goals": [goal("G1", "waiting_user", kind="human", instruction="聞く")], "history": []}

    def test_bad_files_or_note_are_refused_before_the_state_moves(self):
        for extra in ({"files": 5}, {"files": ["a", 3]}, {"files": "a.txt"}, {"note": ["x"]}):
            plan = self.plan()
            plan["goals"][0].pop("class", None)
            with self.assertRaises(guild.GuildError, msg=str(extra)):
                guild.apply_input(plan, {"type": "result", "goal": "G1", "ok": True, **extra}, TR)
            self.assertEqual(plan["goals"][0]["state"], "waiting_user")

    def test_null_files_mean_none(self):
        plan = self.plan()
        guild.apply_input(plan, {"type": "result", "goal": "G1", "ok": True, "files": None}, TR)
        self.assertEqual(plan["goals"][0]["output"]["files"], [])

    def test_a_failed_report_write_is_a_warning_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            q = Path(guild.new_quest(root)["dir"])
            plan = self.plan()
            guild.save_json(q / "plan.json", plan)
            (q / "inbox").mkdir(exist_ok=True)
            (q / "inbox" / "r.json").write_text(json.dumps({"type": "result", "goal": "G1", "ok": True, "note": "済"}), encoding="utf-8")
            p = guild.load_plan(q / "plan.json")
            from unittest import mock
            with mock.patch.object(guild, "write_user_report", side_effect=OSError("ロック中")):
                report = guild.ingest(q / "plan.json", p, TR, commit=lambda: guild.save_json(q / "plan.json", p))
            self.assertEqual(len(report["applied"]), 1)
            self.assertTrue(report["warnings"])
            self.assertEqual(guild.load_plan(q / "plan.json")["goals"][0]["state"], "review")


class WebHostTest(unittest.TestCase):
    def test_hosts_that_cannot_be_answered_are_denied_without_a_letter(self):
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            for url in ("http://127.0.0.1/x", "http://localhost/", "http://[::1]/", "http://intranet/"):
                verdict, _ = webaccess.gate(gdir, url, "p")
                self.assertEqual(verdict, "deny", url)
            self.assertEqual(webaccess.pending(gdir), [])

    def test_japanese_domain_is_queued_as_punycode_and_can_be_answered(self):
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            webaccess.gate(gdir, "https://例え.jp/a", "p")
            dom = webaccess.pending(gdir)[0]["domain"]
            self.assertTrue(dom.startswith("xn--"), dom)
            data = webaccess.load(gdir)
            webaccess.apply(data, {"type": "web", "decisions": {dom: "allow"}})
            webaccess.save(gdir, data)
            self.assertEqual(webaccess.gate(gdir, "https://例え.jp/b", "p")[0], "allow")


class WebIngestOrderTest(unittest.TestCase):
    def test_answers_stay_in_the_inbox_when_saving_fails(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            inbox = gdir / ".work" / "web" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "1.json").write_text(json.dumps({"type": "web", "decisions": {"example.com": "allow"}}), encoding="utf-8")
            with mock.patch.object(webaccess, "save", side_effect=PermissionError("ロック中")):
                with self.assertRaises(PermissionError):
                    webaccess.ingest(gdir)
            self.assertTrue((inbox / "1.json").exists())
            self.assertFalse((inbox / "done").exists())
            report = webaccess.ingest(gdir)  # 次に、そのまま反映できる
            self.assertEqual(len(report["applied"]), 1)
            self.assertIn("example.com", webaccess.load(gdir)["allow"])


BOARD_SRC = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")


@unittest.skipUnless(shutil.which("node"), "node がありません")
class BoardSentStateTest(unittest.TestCase):
    def test_sent_flags_are_dropped_when_the_inbox_is_empty(self):
        code = extract("pruneSent") + r"""
const S = { sent: { 'Q001:abort': true, 'Q001:G2:result': true, 'in:Q001': true, 'Q002:approve': true, 'a:form': true } };
pruneSent({ quests: [{ id: 'Q001', q: { inbox: [] } }, { id: 'Q002', q: { inbox: [{ type: 'approve' }] } }] });
console.log(JSON.stringify(Object.keys(S.sent).sort()));"""
        self.assertEqual(node_eval(code), ["Q002:approve", "a:form"])

    def test_sent_label_names_what_was_actually_sent(self):
        code = extract("sentLabel") + r"""
const has = (inbox) => (type, goal, choice) => inbox.some((x) => x.type === type && (goal == null || x.goal === goal) && (choice == null || x.choice === choice));
console.log(JSON.stringify([
  sentLabel('approve', has([{ type: 'approve' }])), sentLabel('approve', has([{ type: 'decision', choice: 'abort' }])),
  sentLabel('approve', has([{ type: 'decision', choice: 'replan' }])), sentLabel('accept', has([{ type: 'accept' }])),
  sentLabel('accept', has([{ type: 'decision', choice: 'replan' }])), sentLabel('accept', has([]))]));"""
        self.assertEqual(node_eval(code), ["計画の承認", "中止", "計画の直し", "納品物の受け取り確認", "納品物の直し（見直し）", ""])

    def test_log_turn_list_includes_closed_quests_waiting_for_the_archive(self):
        self.assertIn("const turn = c.quests.filter((q) => (q.needs || []).length);", BOARD_SRC)

    def test_received_banner_only_for_quests_waiting_to_be_accepted(self):
        self.assertIn("m.quests.filter((x) => x.label === '受け取り待ち')", BOARD_SRC)


class SmallFixesTest(unittest.TestCase):
    def test_null_deps_are_a_validation_error_not_a_crash(self):
        plan = {"goals": [goal("G1", deps=None)]}
        self.assertTrue(any("deps" in e for e in guild.validate(plan, TR)))

    def test_only_real_request_files_count_as_requests(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            rdir = root / "guild" / ".work" / "requests"
            (rdir / "R20261010-1.json").write_text(json.dumps({"text": "x"}), encoding="utf-8")
            (rdir / "Readme.json").write_text(json.dumps({"text": "y"}), encoding="utf-8")
            self.assertEqual([x["id"] for x in guild.list_requests(root)], ["R20261010-1"])
            self.assertEqual([x["id"] for x in guild.arrivals(root) if x["kind"] == "request"], ["R20261010-1"])

    def test_wait_with_a_bad_number_is_a_guild_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(guild.main(["guild.py", "wait", d, "abc"]), 1)

    def test_reports_with_broken_bytes_do_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d)
            (q / "reports").mkdir()
            (q / "reports" / guild.OVERALL_REPORT).write_bytes("## 判定\n満たしている\n".encode("utf-8") + b"\xff\xfe")
            (q / "reports" / "G1-appraiser.md").write_bytes("## 勧める対応\nもう一度 — 直せる\n".encode("utf-8") + b"\xff")
            self.assertEqual(guild.overall_state(q), "ok")
            self.assertEqual(guild.advice_of(q, "G1")["action"], "retry")

    def test_one_broken_quest_does_not_stop_close(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            wdir = root / "guild" / ".work"
            for n, body in (("Q001", "{broken"), ("Q002", json.dumps({"accepted": True, "goals": []}))):
                (wdir / n).mkdir()
                (wdir / n / "plan.json").write_text(body, encoding="utf-8")
                (wdir / n / "prev").mkdir()
            self.assertEqual(guild.close_quests(root)["removed"], ["Q002"])

    def test_full_pending_list_is_told_honestly(self):
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            data = webaccess.load(gdir)
            data["pending"] = [{"domain": f"s{i}.example.com", "urls": [], "purposes": [], "at": "x"} for i in range(webaccess.MAX_PENDING)]
            webaccess.save(gdir, data)
            _, why = webaccess.gate(gdir, "https://new.example.org/", "p")
            self.assertNotIn("手紙で確認を出します", why)
            self.assertIn("いっぱい", why)


class UrlShapeTest(unittest.TestCase):
    def test_ambiguous_urls_are_denied_without_a_letter(self):
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            data = webaccess.load(gdir)
            data["allow"] += ["good.example", "medium.com"]
            webaccess.save(gdir, data)
            for url in ("http://evil.example\\@good.example/", "https://user:pw@good.example/", "https://good.example/a b", "https://good.example/\x00",
                        "https://good.example\\evil.example/"):
                self.assertEqual(webaccess.gate(gdir, url, "p")[0], "deny", repr(url))
            self.assertEqual(webaccess.pending(gdir), [])
            for url in ("https://www.good.example/a?x=1#y", "https://medium.com/@someone/post"):  # パスの @ は普通にある
                self.assertEqual(webaccess.gate(gdir, url, "p")[0], "allow", url)


PENDING_WORKER = """
import sys
sys.path.insert(0, sys.argv[1])
import webaccess
for i in range(10):
    webaccess.gate(sys.argv[2], "https://s%s-%d.example.com/x" % (sys.argv[3], i), "p")
"""


class WebLockTest(unittest.TestCase):
    def test_parallel_gates_keep_every_pending_entry(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            procs = [subprocess.Popen([sys.executable, "-I", "-c", PENDING_WORKER, str(ROOT / "skills" / "quest"), str(gdir), str(n)]) for n in range(3)]
            self.assertEqual([p.wait() for p in procs], [0, 0, 0])
            self.assertEqual(len(webaccess.pending(gdir)), 10 * 3)

    def test_gate_denies_when_the_lock_cannot_be_taken(self):
        with tempfile.TemporaryDirectory() as d:
            gdir = Path(d) / "guild"
            with webaccess.file_lock(webaccess.access_path(gdir)):
                with self.assertRaises(webaccess.WebError):
                    webaccess.gate(gdir, "https://new.example.org/", "p", lock_timeout=0.2)


@unittest.skipUnless(shutil.which("node"), "node がありません")
class BoardMinorTest(unittest.TestCase):
    def test_input_file_names_do_not_collide_within_a_second(self):
        src = re.search(r"^const pad = .*$", BOARD_SRC, re.M).group(0) + "\n" + re.search(r"^const stamp14 = .*$", BOARD_SRC, re.M).group(0) + "\nlet nameSeq = 0;\n" + extract("nowName")
        out = node_eval(src + "\nconst a = [nowName('result', 'G1'), nowName('result', 'G1'), nowName('result', 'G1')];\nconsole.log(JSON.stringify([new Set(a).size, a.every((n) => /^\\d{14}\\d+-result-G1\\.json$/.test(n))]));")
        self.assertEqual(out, [3, True])

    def test_jump_resets_a_series_filter_that_hides_the_target(self):
        code = extract("jumpQuest") + r"""
const S = { model: { quests: [{ id: 'Q001', q: { plan: { series: '週報' } }, title: 't' }, { id: 'Q002', q: { plan: { series: '月報' } }, title: 't' }] }, bfilter: 'all', form: {}, seriesFilter: '週報', tab: '' };
const boardBucket = () => 'run', hit = () => true, selectQuest = () => {};
jumpQuest('Q002'); const a = S.seriesFilter; S.seriesFilter = '週報'; jumpQuest('Q001');
console.log(JSON.stringify([a, S.seriesFilter]));"""
        self.assertEqual(node_eval(code), ["", "週報"])

    def test_only_decisions_make_the_web_letter_wait(self):
        files = {"config.json": "{}", "web/inbox/a.json": json.dumps({"type": "web", "add": ["a.example.com"]}),
                 "web/inbox/b.json": json.dumps({"type": "web", "decisions": {"b.example.com": "allow"}})}
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.js"
            f.write_text(LOAD_JS.replace("await loadAll();\n  const first", "console.log(JSON.stringify((await loadAll()).web.wait)); return;\n  const first", 1), encoding="utf-8")
            r = subprocess.run(["node", str(f), json.dumps(files)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), 1)

    def test_wiring(self):
        for needle in ("if (await sendArchive(", "const again = () =>", "置けたもの：", "const shownReqs = S.seriesFilter ? [] : reqs;"):
            self.assertIn(needle, BOARD_SRC, needle)


class RejectedReasonTest(unittest.TestCase):
    def test_a_rejected_input_leaves_its_reason_next_to_it(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            q = Path(guild.new_quest(root)["dir"])
            plan = {"quest": "Q001", "title": "t", "approved": True, "status": "active", "goals": [goal("G1", "pending")], "history": []}
            guild.save_json(q / "plan.json", plan)
            (q / "inbox" / "x-result.json").write_text(json.dumps({"type": "result", "goal": "G1", "ok": True}), encoding="utf-8")
            p = guild.load_plan(q / "plan.json")
            report = guild.ingest(q / "plan.json", p, TR, commit=lambda: guild.save_json(q / "plan.json", p))
            self.assertEqual(len(report["rejected"]), 1)
            reason = (q / "inbox" / "rejected" / "x-result.json.reason.txt").read_text(encoding="utf-8")
            self.assertEqual(reason, report["rejected"][0]["reason"])
            self.assertTrue((q / "inbox" / "rejected" / "x-result.json").exists())

    def test_applied_inputs_leave_no_reason_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            q = Path(guild.new_quest(root)["dir"])
            plan = {"quest": "Q001", "title": "t", "approved": False, "status": "active", "goals": [goal("G1")], "history": []}
            guild.save_json(q / "plan.json", plan)
            (q / "inbox" / "a-approve.json").write_text(json.dumps({"type": "approve"}), encoding="utf-8")
            p = guild.load_plan(q / "plan.json")
            guild.ingest(q / "plan.json", p, TR, commit=lambda: guild.save_json(q / "plan.json", p))
            self.assertEqual(list((q / "inbox" / "done").glob("*.reason.txt")), [])


@unittest.skipUnless(shutil.which("node"), "node がありません")
class BoardRejectedTest(unittest.TestCase):
    def load(self, files):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.js"
            f.write_text(LOAD_JS.replace("await loadAll();\n  const first", "const m = await loadAll(); console.log(JSON.stringify({ q: m.quests.map((x) => x.rejected), web: m.web.rejected })); return;\n  const first", 1), encoding="utf-8")
            r = subprocess.run(["node", str(f), json.dumps(files)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

    def test_loader_reads_the_newest_rejections_of_quests_and_web(self):
        files = {"config.json": "{}", "Q001/plan.json": "{}", "Q001/request.json": "{}"}
        for i in range(1, 6):
            files[f"Q001/inbox/rejected/2026101{i}-result.json.reason.txt"] = f"理由{i}"
        files["web/inbox/rejected/1.json.reason.txt"] = "ドメインの形が不正です"
        got = self.load(files)
        self.assertEqual([r["reason"] for r in got["q"][0]], ["理由5", "理由4", "理由3"])
        self.assertEqual(got["q"][0][0]["file"], "20261015-result.json")
        self.assertEqual(got["web"], [{"file": "1.json", "reason": "ドメインの形が不正です"}])

    def test_box_shows_unhidden_rejections_only(self):
        code = FAKE_H + extract("rejectedHidden") + "\n" + extract("rejectedBox") + r"""
const LS_REJ = 'x', lsGet = () => ['Q001/a.json'], lsSet = () => {}, render = () => {}, code = (t) => t;
const out = rejectedBox([{ file: 'a.json', reason: 'r1' }, { file: 'b.json', reason: 'r2' }], 'Q001');
const none = rejectedBox([{ file: 'a.json', reason: 'r1' }], 'Q001');
console.log(JSON.stringify([text(out).includes('b.json'), text(out).includes('a.json'), none]));"""
        self.assertEqual(node_eval(code), [True, False, None])


if __name__ == "__main__":
    unittest.main()

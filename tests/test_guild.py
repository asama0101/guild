import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402

TR = guild.load_transitions()
CRIT = {"viewpoint": "v", "pass_line": "p", "check": "c"}


def todo(i, kind="auto", deps=(), **kw):
    t = {"id": i, "title": i, "kind": kind, "deps": list(deps), "criteria": dict(CRIT),
         "state": "pending", "retries": 0, "output": None}
    t.update(kw)
    return t


def plan(*todos, approved=True):
    return {"quest": "Q1", "title": "t", "approved": approved, "status": "active", "todos": list(todos)}


def states(p):
    return {t["id"]: t["state"] for t in p["todos"]}


class ValidateTest(unittest.TestCase):
    def errs(self, p):
        return guild.validate(p, TR)

    def test_ok(self):
        self.assertEqual(self.errs(plan(todo("T1"), todo("T2", deps=["T1"]))), [])

    def test_missing_dep(self):
        self.assertTrue(any("T9" in e for e in self.errs(plan(todo("T1", deps=["T9"])))))

    def test_cycle(self):
        p = plan(todo("T1", deps=["T2"]), todo("T2", deps=["T1"]))
        self.assertTrue(any("循環" in e for e in self.errs(p)))

    def test_self_dep(self):
        self.assertTrue(self.errs(plan(todo("T1", deps=["T1"]))))

    def test_empty_criteria(self):
        t = todo("T1")
        t["criteria"]["pass_line"] = " "
        self.assertTrue(any("pass_line" in e for e in self.errs(plan(t))))

    def test_unknown_kind_and_state(self):
        self.assertTrue(self.errs(plan(todo("T1", kind="x"))))
        self.assertTrue(self.errs(plan(todo("T1", state="x"))))

    def test_confirm_only_auto(self):
        self.assertTrue(self.errs(plan(todo("T1", kind="human", confirm=True))))

    def test_duplicate_id(self):
        self.assertTrue(self.errs(plan(todo("T1"), todo("T1"))))


class TransitionTest(unittest.TestCase):
    def test_auto_flow(self):
        t = todo("T1")
        for ev, to in [("deps_done", "running"), ("submitted", "review"), ("passed", "done")]:
            self.assertEqual(guild.apply_event(t, ev, TR), to)

    def test_human_flow(self):
        t = todo("T1", kind="human")
        self.assertEqual(guild.apply_event(t, "deps_done", TR), "waiting_user")
        self.assertEqual(guild.apply_event(t, "submitted", TR), "review")

    def test_confirm_flow(self):
        t = todo("T1", confirm=True)
        self.assertEqual(guild.apply_event(t, "deps_done", TR), "awaiting_confirm")
        self.assertEqual(guild.apply_event(t, "confirmed", TR), "running")

    def test_undefined_transition(self):
        with self.assertRaises(guild.GuildError):
            guild.apply_event(todo("T1"), "passed", TR)

    def test_retry_then_fail(self):
        t = todo("T1", state="review")
        self.assertEqual(guild.apply_event(t, "rejected", TR), "running")
        self.assertEqual(t["retries"], 1)
        t["state"] = "review"
        guild.apply_event(t, "rejected", TR)
        t["state"] = "review"
        self.assertEqual(guild.apply_event(t, "rejected", TR), "failed")
        self.assertEqual(t["retries"], 2)

    def test_human_reject_returns_to_waiting_user(self):
        t = todo("T1", kind="human", state="review")
        self.assertEqual(guild.apply_event(t, "rejected", TR), "waiting_user")

    def test_human_reported_failed(self):
        t = todo("T1", kind="human", state="waiting_user")
        self.assertEqual(guild.apply_event(t, "reported_failed", TR), "failed")


class SyncTest(unittest.TestCase):
    def test_not_approved_does_nothing(self):
        p = plan(todo("T1"), approved=False)
        self.assertEqual(guild.sync(p, TR), [])
        self.assertEqual(states(p), {"T1": "pending"})

    def test_aborted_does_nothing(self):
        p = plan(todo("T1"))
        p["status"] = "aborted"
        self.assertEqual(guild.sync(p, TR), [])

    def test_starts_independent_todos_in_parallel(self):
        p = plan(todo("T1"), todo("T2"), todo("T3", deps=["T1", "T2"]))
        guild.sync(p, TR)
        self.assertEqual(states(p), {"T1": "running", "T2": "running", "T3": "pending"})

    def test_chain_starts_after_done(self):
        p = plan(todo("T1", state="done"), todo("T2", deps=["T1"]))
        guild.sync(p, TR)
        self.assertEqual(states(p)["T2"], "running")

    def test_failure_blocks_dependents_transitively(self):
        p = plan(todo("T1", state="failed"), todo("T2", deps=["T1"]), todo("T3", deps=["T2"]), todo("T4"))
        guild.sync(p, TR)
        self.assertEqual(states(p), {"T1": "failed", "T2": "blocked", "T3": "blocked", "T4": "running"})

    def test_skip_unblocks(self):
        p = plan(todo("T1", state="failed"), todo("T2", deps=["T1"]))
        guild.sync(p, TR)
        guild.apply_event(p["todos"][0], "skip", TR)
        guild.sync(p, TR)
        self.assertEqual(states(p), {"T1": "skipped", "T2": "running"})

    def test_human_goes_to_waiting_user(self):
        p = plan(todo("T1", kind="human"))
        guild.sync(p, TR)
        self.assertEqual(states(p)["T1"], "waiting_user")


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        (self.dir / "inbox").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, data):
        (self.dir / "inbox" / name).write_text(json.dumps(data), encoding="utf-8")

    def run_ingest(self, p):
        return guild.ingest(self.path, p, TR)

    def test_approve(self):
        p = plan(todo("T1"), approved=False)
        self.put("a.json", {"type": "approve"})
        r = self.run_ingest(p)
        self.assertTrue(p["approved"])
        self.assertEqual(r["applied"], ["a.json"])
        self.assertTrue((self.dir / "inbox" / "done" / "a.json").exists())

    def test_result_ok_and_ng(self):
        p = plan(todo("T1", kind="human", state="waiting_user"), todo("T2", kind="human", state="waiting_user"))
        self.put("a.json", {"type": "result", "todo": "T1", "ok": True, "note": "済", "files": ["x.md"]})
        self.put("b.json", {"type": "result", "todo": "T2", "ok": False})
        self.run_ingest(p)
        self.assertEqual(states(p), {"T1": "review", "T2": "failed"})
        self.assertEqual(p["todos"][0]["output"], {"note": "済", "files": ["x.md"]})

    def test_confirm(self):
        p = plan(todo("T1", state="awaiting_confirm"), todo("T2", state="awaiting_confirm"))
        self.put("a.json", {"type": "confirm", "todo": "T1", "ok": True})
        self.put("b.json", {"type": "confirm", "todo": "T2", "ok": False})
        self.run_ingest(p)
        self.assertEqual(states(p), {"T1": "running", "T2": "failed"})

    def test_decisions(self):
        p = plan(todo("T1", state="failed"))
        self.put("a.json", {"type": "decision", "todo": "T1", "choice": "skip"})
        self.run_ingest(p)
        self.assertEqual(states(p)["T1"], "skipped")
        self.put("b.json", {"type": "decision", "choice": "replan"})
        self.run_ingest(p)
        self.assertEqual((p["status"], p["approved"]), ("replan", False))
        self.put("c.json", {"type": "decision", "choice": "abort"})
        self.run_ingest(p)
        self.assertEqual(p["status"], "aborted")

    def test_drop_skips_failed_and_all_dependents(self):
        p = plan(todo("T1", state="done"), todo("T2", state="failed", deps=["T1"]),
                 todo("T3", state="blocked", deps=["T2"]), todo("T4", state="blocked", deps=["T3"]),
                 todo("T5", deps=["T1"]))
        self.put("a.json", {"type": "decision", "todo": "T2", "choice": "drop"})
        self.run_ingest(p)
        self.assertEqual(states(p), {"T1": "done", "T2": "skipped", "T3": "skipped", "T4": "skipped", "T5": "pending"})
        guild.sync(p, TR)
        self.assertEqual(states(p)["T5"], "running")  # 無関係な系統は進む

    def test_drop_requires_failed_todo(self):
        p = plan(todo("T1", state="blocked"))
        self.put("a.json", {"type": "decision", "todo": "T1", "choice": "drop"})
        self.assertEqual(len(self.run_ingest(p)["rejected"]), 1)

    def test_invalid_input_goes_to_rejected(self):
        p = plan(todo("T1"))
        before = copy.deepcopy(p)
        self.put("a.json", {"type": "result", "todo": "T1", "ok": True})  # pending では送れない
        self.put("b.json", {"type": "result", "todo": "T9", "ok": True})
        self.put("c.json", {"type": "nanika"})
        (self.dir / "inbox" / "d.json").write_text("{壊れた", encoding="utf-8")
        r = self.run_ingest(p)
        self.assertEqual(len(r["rejected"]), 4)
        self.assertEqual(p, before)
        self.assertTrue((self.dir / "inbox" / "rejected" / "d.json").exists())

    def test_no_inbox(self):
        (self.dir / "inbox").rmdir()
        self.assertEqual(self.run_ingest(plan(todo("T1"))), {"applied": [], "rejected": []})


class AdoptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        (self.dir / "reports").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, data):
        (self.dir / "reports" / "plan-draft.json").write_text(json.dumps(data), encoding="utf-8")

    def good(self):
        # 状態や承認を勝手に書いてきても、取り込み時に初期化される
        t1 = todo("T1", state="done", retries=5, output={"x": 1})
        t2 = todo("T2", kind="human", deps=["T1"])
        return {"quest": "Q1", "title": "題", "approved": True, "todos": [t1, t2]}

    def test_adopt_resets_state(self):
        self.draft(self.good())
        r = guild.adopt(self.path, TR)
        p = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(r, {"adopted": 2, "replaced": False, "carried": []})
        self.assertFalse(p["approved"])
        self.assertEqual(states(p), {"T1": "pending", "T2": "pending"})
        self.assertEqual((p["todos"][0]["retries"], p["todos"][0]["output"]), (0, None))

    def test_adopt_fills_missing_deps(self):
        d = self.good()
        del d["todos"][0]["deps"]
        self.draft(d)
        guild.adopt(self.path, TR)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["todos"][0]["deps"], [])

    def test_adopt_rejects_invalid_draft_and_writes_nothing(self):
        d = self.good()
        d["todos"][1]["deps"] = ["T9"]
        self.draft(d)
        with self.assertRaises(guild.GuildError):
            guild.adopt(self.path, TR)
        self.assertFalse(self.path.exists())

    def test_adopt_missing_draft(self):
        with self.assertRaises(guild.GuildError):
            guild.adopt(self.path, TR)

    def test_adopt_does_not_overwrite_active_plan(self):
        self.draft(self.good())
        self.path.write_text(json.dumps(plan(todo("T1"))), encoding="utf-8")
        with self.assertRaises(guild.GuildError):
            guild.adopt(self.path, TR)

    def test_adopt_replan_keeps_previous(self):
        self.draft(self.good())
        old = plan(todo("T1", state="done"))
        old["status"] = "replan"
        self.path.write_text(json.dumps(old), encoding="utf-8")
        r = guild.adopt(self.path, TR)
        self.assertTrue(r["replaced"])
        prev = json.loads((self.dir / "plan.prev.json").read_text(encoding="utf-8"))
        self.assertEqual(prev["todos"][0]["state"], "done")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["status"], "active")

    def test_adopt_cli(self):
        self.draft(self.good())
        run = lambda: subprocess.run([sys.executable, str(ROOT / "skills" / "quest" / "guild.py"), "adopt",
                                      str(self.path)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run().returncode, 0)
        self.assertEqual(run().returncode, 1)  # 2 回目は上書きしない


class HistoryTest(unittest.TestCase):
    def test_apply_event_records_only_when_plan_given(self):
        t = todo("T1")
        guild.apply_event(t, "deps_done", TR)  # plan を渡さなければ記録しない
        p = plan(todo("T1"))
        guild.apply_event(p["todos"][0], "deps_done", TR, p)
        h = p["history"]
        self.assertEqual((h[0]["id"], h[0]["event"], h[0]["from"], h[0]["to"]), ("T1", "deps_done", "pending", "running"))
        self.assertRegex(h[0]["t"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_sync_and_inputs_are_recorded(self):
        p = plan(todo("T1"), todo("T2", kind="human", deps=["T1"]), approved=False)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "inbox").mkdir()
            (Path(d) / "inbox" / "a.json").write_text(json.dumps({"type": "approve"}), encoding="utf-8")
            guild.ingest(Path(d) / "plan.json", p, TR)
        guild.sync(p, TR)
        events = [(x.get("id"), x["event"]) for x in p["history"]]
        self.assertEqual(events, [(None, "approved"), ("T1", "deps_done")])

    def test_drop_records_every_dropped_todo(self):
        p = plan(todo("T1", state="failed"), todo("T2", state="blocked", deps=["T1"]))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "inbox").mkdir()
            (Path(d) / "inbox" / "a.json").write_text(json.dumps({"type": "decision", "todo": "T1", "choice": "drop"}), encoding="utf-8")
            guild.ingest(Path(d) / "plan.json", p, TR)
        self.assertEqual([(x["id"], x["event"]) for x in p["history"]], [("T1", "skip"), ("T2", "dropped")])

    def test_adopt_starts_history(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.json"
            (Path(d) / "reports").mkdir()
            (Path(d) / "reports" / "plan-draft.json").write_text(json.dumps({"quest": "Q1", "title": "t", "todos": [todo("T1")]}), encoding="utf-8")
            guild.adopt(path, TR)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["history"][0]["event"], "adopted")


class InitAndNewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_records_python_and_is_idempotent(self):
        r = guild.init_guild(self.root)
        cfg = json.loads((self.root / "guild" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["python"], sys.executable)
        self.assertEqual(r["python"], sys.executable)
        self.assertEqual(Path(cfg["root"]), self.root.resolve())  # ボードのフルパスのコピー用
        self.assertTrue((self.root / "guild" / "archive").is_dir())
        q = guild.new_quest(self.root)
        guild.init_guild(self.root)  # 再実行しても依頼は消えない
        self.assertTrue(Path(q["dir"]).is_dir())

    def test_new_requires_init(self):
        with self.assertRaises(guild.GuildError):
            guild.new_quest(self.root)

    def test_new_numbers_quests_in_order(self):
        guild.init_guild(self.root)
        a, b = guild.new_quest(self.root), guild.new_quest(self.root)
        self.assertEqual((a["quest"], b["quest"]), ("Q001", "Q002"))
        for sub in ("reports", "output", "inbox"):
            self.assertTrue((Path(b["dir"]) / sub).is_dir())
        self.assertEqual(Path(b["plan"]), Path(b["dir"]) / "plan.json")

    def put_request(self, rid, text, files=()):
        rdir = self.root / "guild" / "requests"
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / f"{rid}.json").write_text(json.dumps({"type": "request", "text": text, "due": None,
                                                      "files": list(files)}), encoding="utf-8")

    def test_list_requests(self):
        guild.init_guild(self.root)
        self.put_request("R20261010-1130", "二つ目")
        self.put_request("R20261010-1100", "一つ目")
        (self.root / "guild" / "requests" / "R20261010-1200.json").write_text("{壊れた", encoding="utf-8")
        r = guild.list_requests(self.root)
        self.assertEqual([x["id"] for x in r], ["R20261010-1100", "R20261010-1130"])
        self.assertEqual(r[0]["text"], "一つ目")

    def test_new_takes_request_and_files(self):
        guild.init_guild(self.root)
        self.put_request("R20261010-1100", "依頼文", files=["memo.txt"])
        fdir = self.root / "guild" / "requests" / "files" / "R20261010-1100"
        fdir.mkdir(parents=True)
        (fdir / "memo.txt").write_text("素材", encoding="utf-8")
        q = guild.new_quest(self.root, "R20261010-1100")
        self.assertEqual(q["request"]["text"], "依頼文")
        self.assertTrue((Path(q["dir"]) / "request.json").exists())
        self.assertEqual((Path(q["dir"]) / "inputs" / "memo.txt").read_text(encoding="utf-8"), "素材")
        self.assertEqual(guild.list_requests(self.root), [])  # 受付待ちから消える

    def test_new_rejects_bad_or_missing_request(self):
        guild.init_guild(self.root)
        for rid in ("../config", "R1/../../x", "Rabc", "R20261010-9999"):
            with self.assertRaises(guild.GuildError):
                guild.new_quest(self.root, rid)
        self.assertEqual(guild.new_quest(self.root)["quest"], "Q001")  # 失敗しても番号は進まない

    def test_init_copies_board_and_creates_requests_dir(self):
        r = guild.init_guild(self.root)
        self.assertTrue((self.root / "guild" / "requests").is_dir())
        board = ROOT / "skills" / "quest" / "board.html"
        if board.exists():
            self.assertEqual((self.root / "guild" / "board.html").read_bytes(), board.read_bytes())
            self.assertIsNotNone(r["board"])

    def test_cli(self):
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "skills" / "quest" / "guild.py"), *a],
                                        capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run("new", str(self.root)).returncode, 1)
        self.assertEqual(run("init", str(self.root)).returncode, 0)
        r = run("new", str(self.root))
        self.assertEqual(json.loads(r.stdout)["quest"], "Q001")


class WaitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.q = guild.new_quest(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def put_inbox(self, name, data):
        (Path(self.q["dir"]) / "inbox" / name).write_text(json.dumps(data), encoding="utf-8")

    def test_arrivals_lists_inbox_and_requests(self):
        self.assertEqual(guild.arrivals(self.root), [])
        self.put_inbox("a.json", {"type": "approve"})
        (self.root / "guild" / "requests" / "R20261010-1.json").write_text("{}", encoding="utf-8")
        a = guild.arrivals(self.root)
        self.assertEqual(a, [{"kind": "inbox", "quest": "Q001", "file": "a.json"}, {"kind": "request", "id": "R20261010-1"}])

    def test_done_and_rejected_are_not_arrivals(self):
        (Path(self.q["dir"]) / "inbox" / "done").mkdir()
        (Path(self.q["dir"]) / "inbox" / "done" / "x.json").write_text("{}", encoding="utf-8")
        self.assertEqual(guild.arrivals(self.root), [])

    def test_wait_times_out(self):
        r = guild.wait_for(self.root, 0.3, interval=0.1)
        self.assertTrue(r["timeout"])
        self.assertEqual(r["arrived"], [])

    def test_wait_returns_at_once_when_something_is_there(self):
        self.put_inbox("a.json", {"type": "approve"})
        r = guild.wait_for(self.root, 5, interval=0.1)
        self.assertFalse(r["timeout"])
        self.assertLess(r["waited"], 1)

    def test_wait_notices_a_file_that_arrives_later(self):
        import threading
        threading.Timer(0.3, lambda: self.put_inbox("b.json", {"type": "approve"})).start()
        r = guild.wait_for(self.root, 5, interval=0.1)
        self.assertFalse(r["timeout"])
        self.assertEqual(r["arrived"][0]["file"], "b.json")

    def test_take_answers_moves_only_answers(self):
        self.put_inbox("a.json", {"type": "answers", "answers": [{"q": "どれ", "choice": "A", "note": ""}]})
        self.put_inbox("b.json", {"type": "approve"})
        got = guild.take_answers(self.q["dir"])
        self.assertEqual(got[0]["answers"][0]["choice"], "A")
        self.assertTrue((Path(self.q["dir"]) / "inbox" / "done" / "a.json").exists())
        # 計画がないときの approve は、受け付けられない入力。残すと wait が待たずに返り続けるので rejected/ へ
        self.assertTrue((Path(self.q["dir"]) / "inbox" / "rejected" / "b.json").exists())
        self.assertFalse((Path(self.q["dir"]) / "inbox" / "b.json").exists())

    def test_take_answers_rejects_broken_files(self):
        (Path(self.q["dir"]) / "inbox" / "c.json").write_text("{壊れた", encoding="utf-8")
        self.assertEqual(guild.take_answers(self.q["dir"]), [])
        self.assertTrue((Path(self.q["dir"]) / "inbox" / "rejected" / "c.json").exists())
        self.assertEqual(guild.arrivals(self.root), [])

    def test_arrivals_ignores_unreadable_requests(self):
        (self.root / "guild" / "requests" / "R20261010-9.json").write_text("{壊れた", encoding="utf-8")
        self.assertEqual(guild.arrivals(self.root), [])

    def test_cli_wait_and_answers(self):
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "skills" / "quest" / "guild.py"), *a], capture_output=True, text=True, encoding="utf-8")
        r = run("wait", str(self.root), "0.5")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(json.loads(r.stdout)["timeout"])
        self.assertEqual(json.loads(run("answers", self.q["dir"]).stdout), [])


class FixesTest(unittest.TestCase):
    """実際の通しで、プラグイン自身が見つけた不具合の修正。"""

    def ingest_one(self, p, data, d):
        (Path(d) / "inbox").mkdir(exist_ok=True)
        (Path(d) / "inbox" / "20261010120000-x.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return guild.ingest(Path(d) / "plan.json", p, TR)

    def test_approve_cannot_reopen_aborted_or_replan(self):
        for status in ("aborted", "replan"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as d:
                p = plan(todo("T1"), approved=False)
                p["status"] = status
                r = self.ingest_one(p, {"type": "approve"}, d)
                self.assertEqual(len(r["rejected"]), 1)
                self.assertFalse(p["approved"])
                self.assertEqual(p["status"], status)

    def test_aborted_rejects_everything_and_replan_still_allows_abort(self):
        with tempfile.TemporaryDirectory() as d:
            p = plan(todo("T1", state="awaiting_confirm", confirm=True))
            p["status"] = "aborted"
            self.assertEqual(len(self.ingest_one(p, {"type": "confirm", "todo": "T1", "ok": True}, d)["rejected"]), 1)
            self.assertEqual(p["todos"][0]["state"], "awaiting_confirm")
        with tempfile.TemporaryDirectory() as d:
            p = plan(todo("T1"))
            p["status"] = "replan"
            self.assertEqual(self.ingest_one(p, {"type": "decision", "choice": "abort"}, d)["rejected"], [])
            self.assertEqual(p["status"], "aborted")

    def test_approve_twice_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = plan(todo("T1"))  # すでに承認済み
            self.assertEqual(len(self.ingest_one(p, {"type": "approve"}, d)["rejected"]), 1)

    def test_human_result_becomes_a_report_for_the_appraiser(self):
        with tempfile.TemporaryDirectory() as d:
            p = plan(todo("T2", kind="human", state="waiting_user"))
            self.ingest_one(p, {"type": "result", "todo": "T2", "ok": False, "note": "取れなかった", "files": ["inbox/files/T2-m.txt"]}, d)
            body = (Path(d) / "reports" / "T2-user.md").read_text(encoding="utf-8")
            for needle in ("## 結果\nできなかった", "取れなかった", "- [[inbox/files/T2-m.txt]]"):
                self.assertIn(needle, body)

    def test_rejected_input_writes_no_report(self):
        with tempfile.TemporaryDirectory() as d:
            p = plan(todo("T2", kind="human", state="pending"))
            self.ingest_one(p, {"type": "result", "todo": "T2", "ok": True}, d)
            self.assertFalse((Path(d) / "reports" / "T2-user.md").exists())

    def test_next_reports_status_and_approved(self):
        p = plan(todo("T1"), approved=False)
        p["status"] = "replan"
        v = guild.next_view(p)
        self.assertEqual((v["status"], v["approved"], v["runnable"]), ("replan", False, False))

    def test_replan_carries_over_done_todos_and_history(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d)
            (q / "reports").mkdir()
            (q / "output" / "T1").mkdir(parents=True)
            (q / "output" / "T2").mkdir(parents=True)
            (q / "output" / "T1" / "a.md").write_text("T1の成果物", encoding="utf-8")
            (q / "output" / "T2" / "b.md").write_text("T2の古い成果物", encoding="utf-8")
            (q / "reports" / "T1-adventurer.md").write_text("T1の報告", encoding="utf-8")
            (q / "reports" / "T2-adventurer.md").write_text("T2の報告", encoding="utf-8")
            old = plan(todo("T1", state="done", retries=1, output={"note": "x"}), todo("T2", state="failed", deps=["T1"]))
            old["status"] = "replan"
            old["history"] = [{"t": "2026-10-10T10:00:00+09:00", "event": "adopted"}]
            (q / "plan.json").write_text(json.dumps(old), encoding="utf-8")
            new_t1 = todo("T1")                       # 題名・合格基準が同じ → 引き継ぐ
            new_t2 = todo("T2", title="別の作業", deps=["T1"])  # 題名が変わった → 引き継がない
            (q / "reports" / "plan-draft.json").write_text(json.dumps({"quest": "Q1", "title": "t", "todos": [new_t1, new_t2]}), encoding="utf-8")
            r = guild.adopt(q / "plan.json", TR)
            self.assertEqual(r["carried"], ["T1"])
            p = json.loads((q / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(states(p), {"T1": "done", "T2": "pending"})
            self.assertEqual((p["todos"][0]["retries"], p["todos"][0]["output"]), (1, {"note": "x"}))
            self.assertFalse(p["approved"])
            self.assertEqual([e["event"] for e in p["history"]], ["adopted", "replanned"])
            # 引き継いだ T1 の成果物はそのまま。引き継がない T2 の古い成果物と報告は prev/ へ
            self.assertTrue((q / "output" / "T1" / "a.md").exists())
            self.assertTrue((q / "reports" / "T1-adventurer.md").exists())
            self.assertFalse((q / "output" / "T2").exists())
            self.assertFalse((q / "reports" / "T2-adventurer.md").exists())
            moved = list((q / "prev").rglob("*"))
            self.assertTrue(any(m.name == "b.md" for m in moved) and any(m.name == "T2-adventurer.md" for m in moved))


class AcceptTest(unittest.TestCase):
    """依頼主が受け取るまで、依頼は完了にならない。"""

    def ingest_one(self, p, data, d):
        (Path(d) / "inbox").mkdir(exist_ok=True)
        (Path(d) / "inbox" / "20261010120000-accept.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return guild.ingest(Path(d) / "plan.json", p, TR)

    def test_all_done_is_not_complete_until_accepted(self):
        p = plan(todo("T1", state="done"), todo("T2", state="skipped"))
        v = guild.next_view(p)
        self.assertEqual((v["finished"], v["awaiting_accept"], v["complete"]), (True, True, False))
        p["accepted"] = True
        v = guild.next_view(p)
        self.assertEqual((v["awaiting_accept"], v["complete"]), (False, True))

    def test_accept(self):
        p = plan(todo("T1", state="done"))
        with tempfile.TemporaryDirectory() as d:
            r = self.ingest_one(p, {"type": "accept"}, d)
        self.assertEqual(len(r["applied"]), 1)
        self.assertTrue(p["accepted"])
        self.assertEqual(p["history"][-1]["event"], "accepted")

    def test_accept_rejected_before_all_done_or_twice(self):
        for pl in (plan(todo("T1", state="done"), todo("T2", state="running")),):
            if pl is None:
                continue
            with tempfile.TemporaryDirectory() as d:
                r = self.ingest_one(pl, {"type": "accept"}, d)
            self.assertEqual(len(r["rejected"]), 1)
            self.assertFalse(pl.get("accepted"))
        p = plan(todo("T1", state="done"))
        p["accepted"] = True
        with tempfile.TemporaryDirectory() as d:
            r = self.ingest_one(p, {"type": "accept"}, d)
        self.assertEqual(len(r["rejected"]), 1)

    def test_replan_instead_of_accept(self):
        p = plan(todo("T1", state="done"))
        with tempfile.TemporaryDirectory() as d:
            self.ingest_one(p, {"type": "decision", "choice": "replan", "comment": "価格の列を足して"}, d)
        self.assertEqual(p["status"], "replan")
        self.assertFalse(p.get("accepted"))


class FormatTest(unittest.TestCase):
    """納品物の形式。未対応の形式は検査で落ちる。"""

    def test_default_is_md_and_unknown_is_rejected(self):
        self.assertEqual(guild.validate(plan(todo("T1")), TR), [])
        p = plan(todo("T1"))
        p["format"] = "pptx"
        self.assertTrue(any("format" in e for e in guild.validate(p, TR)))
        p["format"] = "md"
        self.assertEqual(guild.validate(p, TR), [])

    def test_adopt_carries_format(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "Q001"
            (q / "reports").mkdir(parents=True)
            draft = {"quest": "Q001", "title": "t", "format": "md", "todos": [
                {"id": "T1", "title": "x", "kind": "auto", "deps": [], "deliverable": True,
                 "criteria": {"viewpoint": "a", "pass_line": "b", "check": "c"}}]}
            (q / "reports" / "plan-draft.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            guild.adopt(q / "plan.json", TR)
            saved = json.loads((q / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["format"], "md")
        self.assertTrue(saved["todos"][0]["deliverable"])


class TemplateTest(unittest.TestCase):
    """納品物のテンプレート。guild/templates/ の中だけを指せる。"""

    def make(self, d, template):
        q = Path(d) / "guild" / "Q001"
        (q / "reports").mkdir(parents=True)
        (Path(d) / "guild" / "templates").mkdir()
        (Path(d) / "guild" / "templates" / "週次.md").write_text("# 週次", encoding="utf-8")
        draft = {"quest": "Q001", "title": "t", "template": template, "todos": [
            {"id": "T1", "title": "x", "kind": "auto", "deps": [], "deliverable": True,
             "criteria": {"viewpoint": "a", "pass_line": "b", "check": "c"}}]}
        (q / "reports" / "plan-draft.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        return q

    def test_adopt_keeps_existing_template(self):
        with tempfile.TemporaryDirectory() as d:
            q = self.make(d, "templates/週次.md")
            guild.adopt(q / "plan.json", TR)
            saved = json.loads((q / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["template"], "templates/週次.md")

    def test_adopt_rejects_unreadable_template_format(self):
        with tempfile.TemporaryDirectory() as d:
            q = self.make(d, "templates/週次.docx")
            (Path(d) / "guild" / "templates" / "週次.docx").write_bytes(b"PK")
            with self.assertRaises(guild.GuildError):
                guild.adopt(q / "plan.json", TR)

    def test_adopt_rejects_missing_or_outside_template(self):
        for bad in ("templates/ない.md", "../config.json", "templates/../config.json", "/etc/passwd", "board.html"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as d:
                q = self.make(d, bad)
                with self.assertRaises(guild.GuildError):
                    guild.adopt(q / "plan.json", TR)


class BoardContractTest(unittest.TestCase):
    """ボード（board.html）が inbox に書く JSON を、guild.py がそのまま受け取れる。
    形は、ボードを実際に動かして書き出させたもの（承認・直す・中止・確認・結果・失敗の判断4種）。"""

    CASES = [
        ({"type": "approve"}, lambda: plan(todo("T1"), approved=False), None),
        ({"type": "decision", "choice": "replan", "comment": "T2 の前に資料共有を足して"}, lambda: plan(todo("T1"), approved=False), None),
        ({"type": "decision", "choice": "abort"}, lambda: plan(todo("T1"), approved=False), None),
        ({"type": "confirm", "todo": "T3", "ok": True}, lambda: plan(todo("T3", state="awaiting_confirm", confirm=True)), {"T3": "running"}),
        ({"type": "confirm", "todo": "T3", "ok": False}, lambda: plan(todo("T3", state="awaiting_confirm", confirm=True)), {"T3": "failed"}),
        ({"type": "result", "todo": "T2", "ok": True, "note": "済", "files": ["inbox/files/T2-memo.txt"]}, lambda: plan(todo("T2", kind="human", state="waiting_user")), {"T2": "review"}),
        ({"type": "result", "todo": "T2", "ok": False, "note": "", "files": []}, lambda: plan(todo("T2", kind="human", state="waiting_user")), {"T2": "failed"}),
        ({"type": "decision", "todo": "T2", "choice": "drop"}, lambda: plan(todo("T2", kind="human", state="failed"), todo("T3", state="blocked", deps=["T2"])), {"T2": "skipped", "T3": "skipped"}),
        ({"type": "decision", "todo": "T2", "choice": "skip"}, lambda: plan(todo("T2", kind="human", state="failed"), todo("T3", state="blocked", deps=["T2"])), {"T2": "skipped"}),
        ({"type": "decision", "choice": "replan"}, lambda: plan(todo("T2", state="failed")), None),
        ({"type": "decision", "choice": "abort"}, lambda: plan(todo("T2", state="failed")), None),
    ]

    def test_every_input_the_board_writes_is_accepted(self):
        for data, make, expect in self.CASES:
            with self.subTest(data=data):
                with tempfile.TemporaryDirectory() as d:
                    (Path(d) / "inbox").mkdir()
                    (Path(d) / "inbox" / "20261010120000-x.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    p = make()
                    r = guild.ingest(Path(d) / "plan.json", p, TR)
                    self.assertEqual(r["rejected"], [], r)
                    if expect:
                        got = states(p)
                        for k, v in expect.items():
                            self.assertEqual(got[k], v)

    def test_board_source_writes_the_same_shapes(self):
        board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        for needle in ("type: 'approve'", "type: 'decision', choice: 'replan'", "type: 'decision', choice: 'abort'", "type: 'confirm'", "type: 'result'", "choice: how"):
            self.assertIn(needle, board)


class NextViewTest(unittest.TestCase):
    def test_view(self):
        p = plan(todo("T1", state="running"), todo("T2", state="waiting_user", kind="human"),
                 todo("T3", state="blocked"), todo("T4", state="failed"))
        v = guild.next_view(p)
        self.assertEqual((v["ready"], v["waiting_user"], v["blocked"], v["failed"]),
                         (["T1"], ["T2"], ["T3"], ["T4"]))
        self.assertFalse(v["finished"])

    def test_finished_when_all_done_or_skipped(self):
        self.assertTrue(guild.next_view(plan(todo("T1", state="done"), todo("T2", state="skipped")))["finished"])


class CliAndScenarioTest(unittest.TestCase):
    """通し: 承認 → 実行 → human の結果 → 失敗 → 判断。CLI 経由で確かめる。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        p = plan(todo("T1"), todo("T2", kind="human", deps=["T1"]), todo("T3", deps=["T2"]), approved=False)
        self.path.write_text(json.dumps(p), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(ROOT / "skills" / "quest" / "guild.py"), *args],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r

    def current(self):
        return states(json.loads(self.path.read_text(encoding="utf-8")))

    def put(self, name, data):
        (self.dir / "inbox").mkdir(exist_ok=True)
        (self.dir / "inbox" / name).write_text(json.dumps(data), encoding="utf-8")

    def test_full_scenario(self):
        self.cli("validate", str(self.path))
        self.cli("sync", str(self.path))
        self.assertEqual(self.current()["T1"], "pending")  # 承認前は進まない
        self.put("1.json", {"type": "approve"})
        self.cli("ingest", str(self.path))
        self.cli("sync", str(self.path))
        self.assertEqual(self.current(), {"T1": "running", "T2": "pending", "T3": "pending"})
        self.cli("advance", str(self.path), "T1", "submitted")
        self.cli("advance", str(self.path), "T1", "passed")
        self.cli("sync", str(self.path))
        self.assertEqual(self.current()["T2"], "waiting_user")
        self.put("2.json", {"type": "result", "todo": "T2", "ok": False})
        self.cli("ingest", str(self.path))
        self.cli("sync", str(self.path))
        self.assertEqual(self.current(), {"T1": "done", "T2": "failed", "T3": "blocked"})
        self.put("3.json", {"type": "decision", "todo": "T2", "choice": "skip"})
        self.cli("ingest", str(self.path))
        self.cli("sync", str(self.path))
        self.assertEqual(self.current(), {"T1": "done", "T2": "skipped", "T3": "running"})

    def test_errors_exit_1(self):
        self.cli("advance", str(self.path), "T1", "passed", ok=False)
        self.cli("advance", str(self.path), "T9", "passed", ok=False)
        self.put("x.json", {"type": "nanika"})
        self.cli("ingest", str(self.path), ok=False)
        self.cli("validate", str(self.dir / "none.json"), ok=False)


class ArchiveTest(unittest.TestCase):
    """書庫（guild/archive/）。項目は1つ1ファイル、索引は guild.py が作る。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.adir = self.root / "guild" / "archive"
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def cand(self, cid="C1", **kw):
        c = {"id": cid, "type": "term", "name": "WVS2", "aliases": ["Wide Area Virtual Switch 2"], "summary": "KDDI の広域仮想スイッチ",
             "body": "拠点間を1つのネットワークにつなぐサービス。", "confidence": "sourced", "source": "https://example.com (2026-10-10)"}
        c.update(kw)
        return c

    def draft(self, *cands):
        (self.q / "reports" / "archive-draft.json").write_text(json.dumps({"quest": "Q001", "candidates": list(cands)}, ensure_ascii=False), encoding="utf-8")

    def archive_json(self):
        return json.loads((self.q / "archive.json").read_text(encoding="utf-8"))

    def put_inbox(self, name, data):
        d = self.adir / "inbox"
        d.mkdir(exist_ok=True)
        (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def entry(self, **kw):
        e = {"type": "term", "name": "x", "summary": "s", "body": "", "confidence": "guess", "source": ""}
        e.update(kw)
        return e

    def test_init_makes_archive_and_keeps_items(self):
        for sub in ("terms", "flows", "facts", "lessons", "inbox"):
            self.assertTrue((self.adir / sub).is_dir(), sub)
        self.assertTrue((self.adir / "index.md").is_file())
        self.assertFalse((self.root / "guild" / "knowledge").exists())
        guild.write_entry(self.adir, self.entry(name="A", confidence="confirmed", source="x"))
        guild.init_guild(self.root)
        self.assertTrue((self.adir / "terms" / "A.md").is_file())

    def test_entry_roundtrip_and_safe_name(self):
        rel = guild.write_entry(self.adir, self.entry(type="fact", name="料金/月額: 200M?", aliases=["a,b"], summary="行1\n行2", body="本文", confidence="sourced", source="u"))
        self.assertTrue(rel.startswith("facts/"))
        self.assertNotIn("/", rel[len("facts/"):])
        e = guild.read_entry(self.adir / rel)
        self.assertEqual((e["name"], e["type"], e["confidence"], e["status"]), ("料金/月額: 200M?", "fact", "sourced", "active"))
        self.assertEqual(e["summary"], "行1 行2")
        self.assertEqual(e["aliases"], ["a,b"])
        self.assertIn('aliases: ["a,b"]', (self.adir / rel).read_text(encoding="utf-8"))
        self.assertEqual(e["body"].strip(), "本文")
        with self.assertRaises(guild.GuildError):
            guild.write_entry(self.adir, self.entry(name=".."))
        with self.assertRaises(guild.GuildError):
            guild.write_entry(self.adir, self.entry(type="nanika"))

    def test_same_file_name_gets_suffix(self):
        a = guild.write_entry(self.adir, self.entry(name="a/b"))
        b = guild.write_entry(self.adir, self.entry(name="a:b"))
        self.assertNotEqual(a, b)

    def test_index_lists_active_only_and_hides_lessons(self):
        guild.write_entry(self.adir, self.entry(name="生きている"))
        guild.write_entry(self.adir, self.entry(name="食い違い", status="要確認"))
        guild.write_entry(self.adir, self.entry(name="廃止の語", status="廃止"))
        guild.write_entry(self.adir, self.entry(type="lesson", name="心得ひとつ"))
        guild.rebuild_index(self.adir)
        idx = (self.adir / "index.md").read_text(encoding="utf-8")
        self.assertIn("生きている", idx)
        self.assertIn("[[terms/生きている]]", idx)
        self.assertIn("食い違い", idx)
        self.assertNotIn("廃止の語", idx)
        self.assertNotIn("心得ひとつ", idx)

    def test_find_entry_by_name_or_alias_case_insensitive(self):
        rel = guild.write_entry(self.adir, self.entry(name="WVS2", aliases=["Wide Area Virtual Switch 2"]))
        self.assertEqual(guild.find_entry(self.adir, "term", ["wvs2"]), rel)
        self.assertEqual(guild.find_entry(self.adir, "term", ["x", "WIDE AREA VIRTUAL SWITCH 2"]), rel)
        self.assertIsNone(guild.find_entry(self.adir, "fact", ["WVS2"]))
        self.assertIsNone(guild.find_entry(self.adir, "term", ["別物"]))

    def test_propose_registers_lessons_and_holds_the_rest(self):
        self.draft(self.cand("C1"), self.cand("C2", type="lesson", name="鑑定士はウェブを開けない", aliases=[], summary="出典照合が未検証"))
        r = guild.archive_propose(self.q)
        self.assertEqual(r["status"], "proposed")
        self.assertEqual(r["pending"], ["C1"])
        self.assertEqual(len(r["registered"]), 1)
        self.assertTrue((self.adir / r["registered"][0]).is_file())
        self.assertFalse((self.adir / "terms" / "WVS2.md").exists())  # 確認前は登録しない
        self.assertEqual(self.archive_json()["status"], "proposed")

    def test_propose_with_only_lessons_is_done(self):
        self.draft(self.cand("C1", type="lesson", name="心得", aliases=[]))
        self.assertEqual(guild.archive_propose(self.q)["status"], "done")

    def test_propose_without_draft_is_done_and_empty(self):
        r = guild.archive_propose(self.q)
        self.assertEqual((r["status"], r["pending"], r["registered"]), ("done", [], []))

    def test_propose_rejects_bad_candidates(self):
        for bad in ({"type": "nanika"}, {"confidence": "sure"}, {"name": ""}, {"source": ""}, {"summary": ""}):
            self.draft(self.cand(**bad))
            with self.assertRaises(guild.GuildError, msg=str(bad)):
                guild.archive_propose(self.q)
        self.draft(self.cand(confidence="guess", source=""))  # 推測は出典なしでよい
        guild.archive_propose(self.q)
        self.draft(*[self.cand(f"C{i}", name=f"n{i}") for i in range(13)])
        with self.assertRaises(guild.GuildError):
            guild.archive_propose(self.q)

    def test_propose_turns_duplicate_into_update(self):
        rel = guild.write_entry(self.adir, self.entry(name="wvs2", summary="古い説明", confidence="sourced", source="u"))
        self.draft(self.cand("C1"))
        guild.archive_propose(self.q)
        self.assertEqual(self.archive_json()["candidates"][0]["update_of"], rel)

    def test_decide_registers_chosen_only_and_updates_index(self):
        self.draft(self.cand("C1"), self.cand("C2", name="DX", aliases=[], summary="s2"))
        guild.archive_propose(self.q)
        guild.archive_decide(self.q, {"type": "archive", "decisions": {"C1": "register", "C2": "skip"}})
        e = guild.read_entry(self.adir / "terms" / "WVS2.md")
        self.assertEqual((e["confidence"], e["status"]), ("sourced", "active"))
        self.assertFalse((self.adir / "terms" / "DX.md").exists())
        self.assertIn("WVS2", (self.adir / "index.md").read_text(encoding="utf-8"))
        self.assertEqual(self.archive_json()["status"], "done")

    def test_decide_twice_or_without_proposal_is_error(self):
        with self.assertRaises(guild.GuildError):
            guild.archive_decide(self.q, {"type": "archive", "decisions": {}})
        self.draft(self.cand("C1"))
        guild.archive_propose(self.q)
        guild.archive_decide(self.q, {"type": "archive", "decisions": {"C1": "register"}})
        with self.assertRaises(guild.GuildError):
            guild.archive_decide(self.q, {"type": "archive", "decisions": {"C1": "register"}})
        self.assertEqual(len(list((self.adir / "terms").glob("*.md"))), 1)

    def test_decide_update_replaces_and_conflict_appends(self):
        rel = guild.write_entry(self.adir, self.entry(type="fact", name="月額", summary="旧", body="旧本文", confidence="confirmed", source="old"))
        self.draft(self.cand("C1", type="fact", name="月額", aliases=[], summary="新", body="新本文"))
        guild.archive_propose(self.q)
        guild.archive_decide(self.q, {"type": "archive", "decisions": {"C1": "register"}})
        e = guild.read_entry(self.adir / rel)
        self.assertEqual((e["summary"], e["confidence"], e["status"]), ("新", "confirmed", "active"))  # 確度は下げない
        self.assertIn("新本文", e["body"])
        # 食い違いは上書きせず、両方を残して 要確認 にする
        self.draft(self.cand("C1", type="fact", name="月額", aliases=[], summary="食い違う値", body="別の値", conflict=True))
        guild.archive_propose(self.q)
        guild.archive_decide(self.q, {"type": "archive", "decisions": {"C1": "register"}})
        e = guild.read_entry(self.adir / rel)
        self.assertEqual(e["status"], "要確認")
        self.assertIn("新本文", e["body"])
        self.assertIn("別の値", e["body"])

    def test_ingest_handles_archive_even_when_quest_aborted(self):
        self.draft(self.cand("C1"))
        guild.archive_propose(self.q)
        p = plan(todo("T1"))
        p["status"] = "aborted"
        guild.save_plan(self.q / "plan.json", p)
        (self.q / "inbox" / "a-archive.json").write_text(json.dumps({"type": "archive", "decisions": {"C1": "register"}}), encoding="utf-8")
        r = guild.ingest(self.q / "plan.json", guild.load_json(self.q / "plan.json"), TR)
        self.assertEqual(r["rejected"], [])
        self.assertTrue((self.adir / "terms" / "WVS2.md").is_file())
        self.assertTrue((self.q / "inbox" / "done" / "a-archive.json").is_file())

    def test_archive_ingest_entry_promote_deprecate(self):
        self.put_inbox("1-entry.json", {"type": "entry", "entry": {"type": "flow", "name": "経費精算", "aliases": ["精算"], "summary": "申請から承認まで", "body": "1. 申請 2. 承認", "source": "経理部"}})
        r = guild.archive_ingest(self.root)
        self.assertEqual((len(r["applied"]), r["rejected"]), (1, []))
        e = guild.read_entry(self.adir / "flows" / "経費精算.md")
        self.assertEqual(e["confidence"], "confirmed")  # 依頼主が入れたものは確認済み
        rel = guild.write_entry(self.adir, self.entry(name="推測語"))
        self.put_inbox("2-promote.json", {"type": "promote", "path": rel})
        self.put_inbox("3-dep.json", {"type": "deprecate", "path": "flows/経費精算.md", "reason": "廃止された"})
        guild.archive_ingest(self.root)
        self.assertEqual(guild.read_entry(self.adir / rel)["confidence"], "confirmed")
        d = guild.read_entry(self.adir / "flows" / "経費精算.md")
        self.assertEqual(d["status"], "廃止")
        self.assertIn("廃止された", d["body"])
        self.assertNotIn("経費精算", (self.adir / "index.md").read_text(encoding="utf-8"))

    def test_archive_ingest_edit_and_duplicate(self):
        self.put_inbox("1.json", {"type": "entry", "entry": {"type": "term", "name": "KPI", "summary": "s", "body": "b", "source": ""}})
        guild.archive_ingest(self.root)
        self.put_inbox("2.json", {"type": "entry", "entry": {"type": "term", "name": "kpi", "summary": "別", "body": "b", "source": ""}})
        r = guild.archive_ingest(self.root)
        self.assertEqual(len(r["rejected"]), 1)  # 同名は新規にできない
        self.put_inbox("3.json", {"type": "entry", "update_of": "terms/KPI.md", "entry": {"type": "term", "name": "KPI", "summary": "編集後", "body": "b2", "source": ""}})
        guild.archive_ingest(self.root)
        self.assertEqual(guild.read_entry(self.adir / "terms" / "KPI.md")["summary"], "編集後")

    def test_archive_ingest_rejects_bad_input_without_stopping(self):
        d = self.adir / "inbox"
        (d / "0-broken.json").write_text("{not json", encoding="utf-8")
        self.put_inbox("1-unknown.json", {"type": "nanika"})
        self.put_inbox("2-escape.json", {"type": "promote", "path": "../../config.json"})
        self.put_inbox("3-nofile.json", {"type": "promote", "path": "terms/ない.md"})
        self.put_inbox("4-ok.json", {"type": "entry", "entry": {"type": "term", "name": "ok", "summary": "s", "body": "", "source": ""}})
        r = guild.archive_ingest(self.root)
        self.assertEqual((len(r["applied"]), len(r["rejected"])), (1, 4))
        self.assertEqual(list(d.glob("*.json")), [])
        self.assertTrue((self.root / "guild" / "config.json").is_file())

    def test_arrivals_include_archive_inbox(self):
        self.assertFalse([a for a in guild.arrivals(self.root) if a["kind"] == "archive"])
        self.put_inbox("1.json", {"type": "promote", "path": "terms/x.md"})
        self.assertEqual([a["file"] for a in guild.arrivals(self.root) if a["kind"] == "archive"], ["1.json"])

    def test_adopt_keeps_archive_used(self):
        (self.q / "reports" / "plan-draft.json").write_text(json.dumps({"quest": "Q1", "title": "t", "todos": [todo("T1")], "archive_used": ["terms/WVS2.md"]}), encoding="utf-8")
        guild.adopt(self.q / "plan.json", TR)
        self.assertEqual(guild.load_json(self.q / "plan.json")["archive_used"], ["terms/WVS2.md"])

    def test_cli_archive_commands(self):
        script = str(ROOT / "skills" / "quest" / "guild.py")
        self.draft(self.cand("C1"))
        out = subprocess.run([sys.executable, script, "archive-propose", str(self.q)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["pending"], ["C1"])
        out = subprocess.run([sys.executable, script, "archive-ingest", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()

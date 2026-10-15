import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402
import webaccess  # noqa: E402

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
        rdir = self.root / "guild" / ".work" / "requests"
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / f"{rid}.json").write_text(json.dumps({"type": "request", "text": text, "due": None,
                                                      "files": list(files)}), encoding="utf-8")

    def test_list_requests(self):
        guild.init_guild(self.root)
        self.put_request("R20261010-1130", "二つ目")
        self.put_request("R20261010-1100", "一つ目")
        (self.root / "guild" / ".work" / "requests" / "R20261010-1200.json").write_text("{壊れた", encoding="utf-8")
        r = guild.list_requests(self.root)
        self.assertEqual([x["id"] for x in r], ["R20261010-1100", "R20261010-1130"])
        self.assertEqual(r[0]["text"], "一つ目")

    def test_new_takes_request_and_files(self):
        guild.init_guild(self.root)
        self.put_request("R20261010-1100", "依頼文", files=["memo.txt"])
        fdir = self.root / "guild" / ".work" / "requests" / "files" / "R20261010-1100"
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
        self.assertTrue((self.root / "guild" / ".work" / "requests").is_dir())
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
        (self.root / "guild" / ".work" / "requests" / "R20261010-1.json").write_text("{}", encoding="utf-8")
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
        (self.root / "guild" / ".work" / "requests" / "R20261010-9.json").write_text("{壊れた", encoding="utf-8")
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
        q = Path(d) / "guild" / ".work" / "Q001"
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
        ({"type": "due", "todo": "T1", "due": "2026-10-20"}, lambda: plan(todo("T1", state="running")), {"T1": "running"}),
        ({"type": "due", "todo": "T1", "due": None}, lambda: plan(todo("T1"), approved=False), {"T1": "pending"}),
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
        for needle in ("type: 'approve'", "type: 'decision', choice: 'replan'", "type: 'decision', choice: 'abort'", "type: 'confirm'", "type: 'result'", "choice: how", "type: 'due'", "type: 'retype'", "type: 'web', decisions:", "type: 'web', remove:", "type: 'web', add:"):
            self.assertIn(needle, board)


class DueTest(unittest.TestCase):
    """Todo の期限。入力 type=due で設定・変更・解除でき、plan.json を書くのは guild.py だけ。"""

    def ingest(self, p, data):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "inbox").mkdir()
            (Path(d) / "inbox" / "20261010120000-due-T1.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return guild.ingest(Path(d) / "plan.json", p, TR)

    def test_set_change_and_clear(self):
        p = plan(todo("T1", state="running"))
        self.assertEqual(self.ingest(p, {"type": "due", "todo": "T1", "due": "2026-10-20"})["rejected"], [])
        self.assertEqual(p["todos"][0]["due"], "2026-10-20")
        self.ingest(p, {"type": "due", "todo": "T1", "due": "2026-10-25"})
        self.assertEqual(p["todos"][0]["due"], "2026-10-25")
        self.ingest(p, {"type": "due", "todo": "T1", "due": None})
        self.assertIsNone(p["todos"][0]["due"])
        self.assertEqual([e["event"] for e in p["history"]], ["due", "due", "due"])
        self.assertNotIn("id", p["history"][0])  # タイムラインは id を持つ記録を状態の変化として読む

    def test_unapproved_plan_accepts_due(self):
        p = plan(todo("T1"), approved=False)
        self.assertEqual(self.ingest(p, {"type": "due", "todo": "T1", "due": "2026-10-20"})["rejected"], [])

    def test_bad_dates_are_rejected_and_plan_is_unchanged(self):
        for bad in ("2026-13-40", "", 20261020, "20261020", "2026-10-2", "2026-02-30"):
            with self.subTest(bad=bad):
                p = plan(todo("T1", due="2026-10-20"))
                r = self.ingest(p, {"type": "due", "todo": "T1", "due": bad})
                self.assertEqual(len(r["rejected"]), 1)
                self.assertEqual(p["todos"][0]["due"], "2026-10-20")

    def test_unknown_todo_and_aborted_plan_are_rejected(self):
        p = plan(todo("T1"))
        self.assertEqual(len(self.ingest(p, {"type": "due", "todo": "T9", "due": "2026-10-20"})["rejected"]), 1)
        p["status"] = "aborted"
        self.assertEqual(len(self.ingest(p, {"type": "due", "todo": "T1", "due": "2026-10-20"})["rejected"]), 1)

    def test_validate_checks_due(self):
        self.assertEqual(guild.validate(plan(todo("T1", due="2026-10-20"), todo("T2", due=None)), TR), [])
        self.assertTrue(any("T1" in e and "due" in e for e in guild.validate(plan(todo("T1", due="10/20")), TR)))

    def test_adopt_keeps_due_from_the_draft(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "Q001"
            (q / "reports").mkdir(parents=True)
            (q / "reports" / "plan-draft.json").write_text(json.dumps({"quest": "Q001", "title": "t", "todos": [
                {"id": "T1", "title": "a", "kind": "auto", "deps": [], "criteria": CRIT, "due": "2026-10-20"}]}), encoding="utf-8")
            guild.adopt(q / "plan.json", TR)
            self.assertEqual(guild.load_json(q / "plan.json")["todos"][0]["due"], "2026-10-20")


class RoleModelsTest(unittest.TestCase):
    """ヘルプに書く各役のモデルが、agents/*.md の model と一致する。"""

    def test_board_matches_agents(self):
        board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        block = board.split("const ROLE_MODELS = {", 1)[1].split("};", 1)[0]
        shown = dict((a, m) for a, _, m in re.findall(r"(\w+): \['([^']+)', '(\w+)'\]", block))
        agents = {}
        for f in (ROOT / "agents").glob("*.md"):
            m = re.search(r"^model: (\w+)$", f.read_text(encoding="utf-8"), re.M)
            self.assertIsNotNone(m, f.name)
            agents[f.stem] = m.group(1)
        self.assertEqual(shown, agents)


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
        d = self.root / "guild" / ".work" / "archive-inbox"
        d.mkdir(exist_ok=True)
        (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def entry(self, **kw):
        e = {"type": "term", "name": "x", "summary": "s", "body": "", "confidence": "guess", "source": ""}
        e.update(kw)
        return e

    def test_init_makes_archive_and_keeps_items(self):
        for sub in ("terms", "flows", "facts", "personal", "lessons"):
            self.assertTrue((self.adir / sub).is_dir(), sub)
        self.assertTrue((self.adir / "index.md").is_file())
        self.assertFalse((self.root / "guild" / "knowledge").exists())
        guild.write_entry(self.adir, self.entry(name="A", confidence="confirmed", source="x"))
        guild.init_guild(self.root)
        self.assertTrue((self.adir / "terms" / "A.md").is_file())

    def test_personal_is_a_type_in_index_and_propose(self):
        self.assertEqual(guild.ARCHIVE_DIRS["personal"], "personal")
        guild.write_entry(self.adir, self.entry(type="personal", name="文体", summary="敬体で簡潔に", confidence="confirmed", source="依頼主の登録"))
        guild.rebuild_index(self.adir)
        idx = (self.adir / "index.md").read_text(encoding="utf-8")
        self.assertIn("## 個人", idx)
        self.assertIn("[[personal/文体]]", idx)
        self.draft(self.cand("C1", type="personal", name="役職", aliases=[], summary="情報システム部の課長", confidence="guess", source=""))
        self.assertEqual(guild.archive_propose(self.q)["pending"], ["C1"])  # 心得と違い、確認の手紙を通る

    def test_init_adds_personal_to_an_old_archive(self):
        import shutil as sh
        sh.rmtree(self.adir / "personal")
        guild.init_guild(self.root)
        self.assertTrue((self.adir / "personal").is_dir())

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

    def retype(self, path, to):
        self.put_inbox("20261011-retype.json", {"type": "retype", "path": path, "to": to})
        return guild.archive_ingest(self.root)

    def test_retype_moves_the_file_keeps_fields_and_updates_index(self):
        rel = guild.write_entry(self.adir, self.entry(name="料金", summary="s", body="本文", confidence="sourced", source="https://x (2026-10-01)", aliases=["fee"]))
        old = guild.read_entry(self.adir / rel)
        r = self.retype(rel, "fact")
        self.assertEqual(r["rejected"], [], r)
        self.assertFalse((self.adir / rel).exists())
        new = guild.read_entry(self.adir / "facts" / "料金.md")
        self.assertEqual(new["type"], "fact")
        for k in ("confidence", "confirmed", "source", "status", "body", "aliases", "summary"):
            self.assertEqual(new[k], old[k], k)
        idx = (self.adir / "index.md").read_text(encoding="utf-8")
        self.assertIn("[[facts/料金]]", idx)
        self.assertNotIn("[[terms/料金]]", idx)

    def test_retype_rejects_a_same_name_item_in_the_target(self):
        guild.write_entry(self.adir, self.entry(type="fact", name="料金", summary="別", confidence="guess"))
        rel = guild.write_entry(self.adir, self.entry(name="料金", summary="s", aliases=["fee"]))
        r = self.retype(rel, "fact")
        self.assertEqual(len(r["rejected"]), 1)
        self.assertTrue((self.adir / rel).exists())

    def test_retype_uses_a_serial_file_name_when_only_the_file_name_collides(self):
        guild.write_entry(self.adir, self.entry(type="fact", name="別の項目", summary="x"), "facts/料金.md")  # ファイル名だけ同じ
        rel = guild.write_entry(self.adir, self.entry(name="料金", summary="s"))
        self.assertEqual(self.retype(rel, "fact")["rejected"], [])
        self.assertEqual(guild.read_entry(self.adir / "facts" / "料金.md")["name"], "別の項目")
        self.assertEqual(guild.read_entry(self.adir / "facts" / "料金-2.md")["name"], "料金")

    def test_retype_rejects_bad_requests_and_changes_nothing(self):
        rel = guild.write_entry(self.adir, self.entry(name="A", summary="s"))
        les = guild.write_entry(self.adir, self.entry(type="lesson", name="L", summary="s"))
        dep = guild.write_entry(self.adir, dict(self.entry(name="D", summary="s"), status="廃止"))
        for path, to in ((rel, "term"), (rel, "lesson"), (rel, "nonsense"), (les, "term"), (dep, "fact"), ("terms/none.md", "fact"), ("../x.md", "fact")):
            with self.subTest(path=path, to=to):
                self.assertEqual(len(self.retype(path, to)["rejected"]), 1)
        self.assertTrue((self.adir / rel).exists() and (self.adir / les).exists() and (self.adir / dep).exists())

    def test_retype_rolls_back_the_new_file_when_the_old_one_cannot_be_removed(self):
        from unittest import mock
        rel = guild.write_entry(self.adir, self.entry(name="料金", summary="s"))
        real_unlink = Path.unlink

        def fake(self_, *a, **k):
            if self_.name == "料金.md" and self_.parent.name == "terms":
                raise PermissionError("locked")
            return real_unlink(self_, *a, **k)
        with mock.patch.object(Path, "unlink", fake):
            r = self.retype(rel, "fact")
        self.assertEqual(len(r["rejected"]), 1)
        self.assertTrue((self.adir / rel).exists())
        self.assertFalse((self.adir / "facts" / "料金.md").exists())  # 重複して残らない

    def test_rejected_archive_input_leaves_its_reason_for_the_board(self):
        rel = guild.write_entry(self.adir, self.entry(name="A", summary="s"))
        r = self.retype(rel, "term")  # 同じ種類
        self.assertEqual(len(r["rejected"]), 1)
        reason = (self.root / "guild" / ".work" / "archive-inbox" / "rejected" / "20261011-retype.json.reason.txt").read_text(encoding="utf-8")
        self.assertIn("同じ種類", reason)

    def test_archive_ingest_rejects_bad_input_without_stopping(self):
        d = self.root / "guild" / ".work" / "archive-inbox"
        d.mkdir(parents=True, exist_ok=True)
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


class WebAccessTest(unittest.TestCase):
    """冒険者の WebFetch の許可（許可リスト・今回だけ・不許可・止めた URL の手紙）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        guild.init_guild(self.root)
        self.gdir = self.root / "guild"

    def send(self, name, obj):
        d = self.gdir / ".work" / "web" / "inbox"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_unknown_domain_is_denied_and_queued(self):
        v, reason = webaccess.gate(self.gdir, "https://Example.go.jp/a")
        self.assertEqual(v, "deny")
        self.assertIn("許可待ち：https://Example.go.jp/a", reason)
        self.assertEqual([p["domain"] for p in webaccess.pending(self.gdir)], ["example.go.jp"])

    def test_same_domain_is_queued_once_with_urls(self):
        webaccess.gate(self.gdir, "https://a.example.jp/1")
        webaccess.gate(self.gdir, "https://a.example.jp/2")
        webaccess.gate(self.gdir, "https://a.example.jp/2")
        p = webaccess.pending(self.gdir)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]["urls"], ["https://a.example.jp/1", "https://a.example.jp/2"])

    def test_non_http_url_is_denied_without_queue(self):
        for u in ("file:///etc/passwd", "ftp://a.example.jp/", "", "not a url"):
            self.assertEqual(webaccess.gate(self.gdir, u)[0], "deny")
        self.assertEqual(webaccess.pending(self.gdir), [])

    def test_allow_covers_subdomains_but_not_lookalikes(self):
        self.send("1.json", {"type": "web", "add": ["go.jp"]})
        self.assertEqual(webaccess.ingest(self.gdir)["rejected"], [])
        self.assertEqual(webaccess.gate(self.gdir, "https://www.go.jp/x")[0], "allow")
        self.assertEqual(webaccess.gate(self.gdir, "https://go.jp/x")[0], "allow")
        self.assertEqual(webaccess.gate(self.gdir, "https://evilgo.jp/x")[0], "deny")
        self.assertEqual(webaccess.gate(self.gdir, "https://go.jp.evil.com/x")[0], "deny")

    def test_decisions_allow_once_deny_clear_pending(self):
        for d in ("a.example.jp", "b.example.jp", "c.example.jp"):
            webaccess.gate(self.gdir, f"https://{d}/")
        self.send("1.json", {"type": "web", "decisions": {"a.example.jp": "allow", "b.example.jp": "once", "c.example.jp": "deny"}})
        self.assertEqual(webaccess.ingest(self.gdir)["rejected"], [])
        self.assertEqual(webaccess.pending(self.gdir), [])
        self.assertEqual(webaccess.gate(self.gdir, "https://a.example.jp/")[0], "allow")
        self.assertEqual(webaccess.gate(self.gdir, "https://b.example.jp/")[0], "allow")
        v, reason = webaccess.gate(self.gdir, "https://c.example.jp/")
        self.assertEqual(v, "deny")
        self.assertIn("許可しませんでした", reason)
        self.assertEqual(webaccess.pending(self.gdir), [])  # 不許可のドメインは、また手紙にならない

    def test_reset_clears_once_and_denied_only(self):
        self.send("1.json", {"type": "web", "add": ["keep.example.jp"], "decisions": {"b.example.jp": "once", "c.example.jp": "deny"}})
        webaccess.ingest(self.gdir)
        r = webaccess.reset(self.gdir)
        self.assertEqual(r, {"cleared": {"once": ["b.example.jp"], "denied": ["c.example.jp"]}, "allow": ["keep.example.jp"]})
        self.assertEqual(webaccess.gate(self.gdir, "https://keep.example.jp/")[0], "allow")
        self.assertEqual(webaccess.gate(self.gdir, "https://b.example.jp/")[0], "deny")
        self.assertEqual([p["domain"] for p in webaccess.pending(self.gdir)], ["b.example.jp"])

    def test_remove_and_bad_input_is_rejected_with_reason(self):
        self.send("1.json", {"type": "web", "add": ["x.example.jp"]})
        self.send("2.json", {"type": "web", "remove": ["x.example.jp"]})
        self.send("3.json", {"type": "web", "add": ["bad domain"]})
        self.send("4.json", {"type": "web", "decisions": {"y.example.jp": "maybe"}})
        self.send("5.json", {"type": "other"})
        r = webaccess.ingest(self.gdir)
        self.assertEqual(len(r["applied"]), 2)
        self.assertEqual([x["file"] for x in r["rejected"]], ["3.json", "4.json", "5.json"])
        self.assertEqual(webaccess.load(self.gdir)["allow"], [])
        self.assertTrue((self.gdir / ".work" / "web" / "inbox" / "rejected" / "3.json.reason.txt").is_file())
        self.assertEqual(list((self.gdir / ".work" / "web" / "inbox").glob("*.json")), [])

    def test_arrivals_include_web_inbox(self):
        self.assertFalse([a for a in guild.arrivals(self.root) if a["kind"] == "web"])
        self.send("1.json", {"type": "web", "add": ["a.example.jp"]})
        self.assertEqual([a["file"] for a in guild.arrivals(self.root) if a["kind"] == "web"], ["1.json"])

    def test_cli_commands(self):
        script = str(ROOT / "skills" / "quest" / "guild.py")
        webaccess.gate(self.gdir, "https://a.example.jp/")
        out = subprocess.run([sys.executable, script, "web-pending", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(out.stdout)[0]["domain"], "a.example.jp")
        self.send("1.json", {"type": "web", "decisions": {"a.example.jp": "once"}})
        out = subprocess.run([sys.executable, script, "web-ingest", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        out = subprocess.run([sys.executable, script, "web-reset", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(out.stdout)["cleared"]["once"], ["a.example.jp"])


class WebGateHookTest(unittest.TestCase):
    """hooks/web_gate.py: 冒険者の WebFetch だけを判定し、止めるときは deny を返す。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        guild.init_guild(self.root)

    def run_hook(self, payload):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root))
        return subprocess.run([sys.executable, "-I", str(ROOT / "hooks" / "web_gate.py")], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(self.root))

    def test_adventurer_unknown_domain_is_denied(self):
        r = self.run_hook({"agent_type": "guild:adventurer", "tool_input": {"url": "https://a.example.jp/"}})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual((out["hookEventName"], out["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("許可待ち", out["permissionDecisionReason"])
        self.assertEqual(webaccess.pending(self.root / "guild")[0]["domain"], "a.example.jp")

    def test_adventurer_allowed_domain_passes_silently(self):
        webaccess.save(self.root / "guild", dict(webaccess.load(self.root / "guild"), allow=["example.jp"]))
        r = self.run_hook({"agent_type": "guild:adventurer", "tool_input": {"url": "https://a.example.jp/"}})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_other_callers_are_not_judged(self):
        for payload in ({"tool_input": {"url": "https://a.example.jp/"}},
                        {"agent_type": "guild:appraiser", "tool_input": {"url": "https://a.example.jp/"}},
                        {"agent_type": "other:adventurer-x", "tool_input": {"url": "https://a.example.jp/"}}):
            r = self.run_hook(payload)
            self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(webaccess.pending(self.root / "guild"), [])

    def test_no_guild_folder_or_bad_input_is_silent(self):
        with tempfile.TemporaryDirectory() as other:
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
            r = subprocess.run([sys.executable, "-I", str(ROOT / "hooks" / "web_gate.py")], input=json.dumps({"agent_type": "guild:adventurer", "cwd": other, "tool_input": {"url": "https://a.example.jp/"}}), capture_output=True, text=True, encoding="utf-8", env=env, cwd=other)
            self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = self.run_hook("not a dict")
        self.assertEqual(r.returncode, 0)

    def test_shell_wrapper_runs_the_hook(self):
        import shutil
        sh = shutil.which("sh")
        if not sh:
            self.skipTest("sh がありません")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root))
        r = subprocess.run([sh, str(ROOT / "hooks" / "web_gate.sh")], input=json.dumps({"agent_type": "guild:adventurer", "tool_input": {"url": "https://a.example.jp/"}}), capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")


class PiledLettersTest(unittest.TestCase):
    """『あなたの番』の手紙が溜まったとき、wait / ingest / next が止まらないこと。"""

    def test_many_letters_do_not_stall_autonomous_todos(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            qs = [guild.new_quest(root) for _ in range(3)]
            for q in qs:
                p = plan(*[todo(f"H{i}", kind="human", state="waiting_user") for i in range(1, 11)],
                         todo("A1", state="running"))
                (Path(q["dir"]) / "plan.json").write_text(json.dumps(p), encoding="utf-8")
            # 1つの依頼の人の Todo 10件に、手紙を溜めずに放置しても、自動の A1 は ready のまま
            for q in qs:
                v = guild.next_view(json.loads((Path(q["dir"]) / "plan.json").read_text(encoding="utf-8")))
                self.assertEqual(v["ready"], ["A1"])
                self.assertEqual(len(v["waiting_user"]), 10)
            # 依頼主が全部に答えを返しても、1回の ingest で全部を取り込み、arrivals が空になる
            q = qs[0]
            for i in range(1, 11):
                (Path(q["dir"]) / "inbox").joinpath(f"{i:02d}.json").write_text(
                    json.dumps({"type": "result", "todo": f"H{i}", "ok": True, "note": "", "files": []}), encoding="utf-8")
            self.assertEqual(len(guild.arrivals(root)), 10)
            self.assertLess(guild.wait_for(root, 5, interval=0.1)["waited"], 1)
            path = Path(q["dir"]) / "plan.json"
            plan_ = json.loads(path.read_text(encoding="utf-8"))
            rep = guild.ingest(path, plan_, TR)
            self.assertEqual((len(rep["applied"]), rep["rejected"]), (10, []))
            self.assertEqual(guild.arrivals(root), [])
            self.assertEqual(guild.next_view(plan_)["review"], [f"H{i}" for i in range(1, 11)])


class McpContractTest(unittest.TestCase):
    """MCP は同梱しない。斥候は環境の Playwright MCP（サーバー名 playwright）を使い、init が先に確認する。"""

    def test_no_bundled_mcp(self):
        self.assertFalse((ROOT / ".mcp.json").exists())

    def test_scout_uses_environment_playwright(self):
        head = (ROOT / "agents" / "scout.md").read_text(encoding="utf-8").split("---")[1]
        tools = re.search(r"^tools:(.*)$", head, re.M).group(1)
        for name in ("navigate", "snapshot", "wait_for", "press_key", "take_screenshot", "tabs", "close"):
            self.assertIn(f"mcp__playwright__browser_{name}", tools)
        self.assertNotIn("plugin_guild_browser", tools)

    def test_init_skill_checks_the_mcp_first(self):
        s = (ROOT / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("mcp__playwright__browser_navigate", s)
        self.assertLess(s.index("mcp__playwright__browser_navigate"), s.index("使える Python を探す"))


if __name__ == "__main__":
    unittest.main()


class WorkDirTest(unittest.TestCase):
    """機械用のファイルは guild/.work/ に置く（Obsidian に出さない）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.g = self.root / "guild"

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_and_new_use_work(self):
        self.assertTrue((self.g / ".work" / "requests").is_dir())
        self.assertFalse((self.g / "requests").exists())
        q = guild.new_quest(self.root)
        self.assertEqual(Path(q["dir"]), self.g / ".work" / "Q001")
        self.assertEqual(guild.gdir_of(q["dir"]), self.g)
        self.assertFalse((self.g / "Q001").exists())

    def test_arrivals_read_work(self):
        q = Path(guild.new_quest(self.root)["dir"])
        (q / "inbox" / "a.json").write_text("{}", encoding="utf-8")
        (self.g / ".work" / "requests" / "R20261010-1.json").write_text("{}", encoding="utf-8")
        (self.g / ".work" / "archive-inbox").mkdir()
        (self.g / ".work" / "archive-inbox" / "b.json").write_text("{}", encoding="utf-8")
        (self.g / ".work" / "web" / "inbox").mkdir(parents=True)
        (self.g / ".work" / "web" / "inbox" / "c.json").write_text("{}", encoding="utf-8")
        kinds = sorted((a["kind"], a.get("file") or a.get("id")) for a in guild.arrivals(self.root))
        self.assertEqual(kinds, [("archive", "b.json"), ("inbox", "a.json"), ("request", "R20261010-1"), ("web", "c.json")])

    def test_web_access_lives_in_work(self):
        webaccess.save(self.g, dict(webaccess.load(self.g), allow=["example.jp"]))
        self.assertTrue((self.g / ".work" / "web" / "access.json").is_file())
        self.assertFalse((self.g / "web").exists())

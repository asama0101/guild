"""Phase 1（信頼性の土台）：排他ロック、保存と移動の順序、replan の引き継ぎ、終了条件のコード化。"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402

TR = guild.load_transitions()
GUILD_PY = str(ROOT / "skills" / "quest" / "guild.py")
CRIT = {"viewpoint": "v", "pass_line": "p", "check": "c"}


def goal(i, kind="auto", deps=(), **kw):
    t = {"id": i, "title": i, "kind": kind, "deps": list(deps), "criteria": dict(CRIT),
         "state": "pending", "retries": 0, "output": None}
    if kind == "auto":
        t["class"] = "wizard"
    t.update(kw)
    return t


def plan(*goals, approved=True, **kw):
    return {"quest": "Q1", "title": "t", "approved": approved, "status": "active", "goals": list(goals), **kw}


def draft_json(d):
    d = json.loads(json.dumps(d))
    if d["goals"] and not any(t.get("deliverable") for t in d["goals"]):
        d["goals"][-1]["deliverable"] = True
    return json.dumps(d, ensure_ascii=False)


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class LockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_parallel_advance_keeps_every_update(self):
        n = 8
        write(self.path, plan(*[goal(f"T{i}", state="running") for i in range(n)]))
        procs = [subprocess.Popen([sys.executable, GUILD_PY, "advance", str(self.path), f"T{i}", "submitted"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(n)]
        outs = [p.communicate() + (p.returncode,) for p in procs]
        self.assertTrue(all(o[2] == 0 for o in outs), outs)
        p = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual({t["state"] for t in p["goals"]}, {"review"})
        self.assertFalse(Path(str(self.path) + ".lock").exists())

    def test_lock_released_after_use(self):
        with guild.plan_lock(self.path):
            self.assertTrue(Path(str(self.path) + ".lock").exists())
        self.assertFalse(Path(str(self.path) + ".lock").exists())

    def test_lock_released_on_error(self):
        with self.assertRaises(RuntimeError):
            with guild.plan_lock(self.path):
                raise RuntimeError("x")
        self.assertFalse(Path(str(self.path) + ".lock").exists())

    def test_stale_lock_is_taken_over(self):
        lock = Path(str(self.path) + ".lock")
        lock.write_text("123", encoding="utf-8")
        old = time.time() - guild.LOCK_STALE - 5
        os.utime(lock, (old, old))
        with guild.plan_lock(self.path):
            pass
        self.assertFalse(lock.exists())

    def test_fresh_lock_times_out(self):
        lock = Path(str(self.path) + ".lock")
        lock.write_text("123", encoding="utf-8")
        with mock.patch.object(guild, "LOCK_TIMEOUT", 0.3):
            with self.assertRaises(guild.GuildError):
                with guild.plan_lock(self.path):
                    pass
        self.assertTrue(lock.exists())  # 他人のロックは壊さない

    def test_save_plan_retries_permission_error(self):
        real = os.replace
        calls = {"n": 0}

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("locked")
            return real(a, b)

        with mock.patch.object(guild.os, "replace", flaky):
            guild.save_plan(self.path, {"a": 1})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual([p.name for p in self.dir.iterdir()], ["plan.json"])  # tmp が残らない

    def test_save_plan_tmp_name_is_per_process(self):
        seen = []
        real = os.replace
        with mock.patch.object(guild.os, "replace", lambda a, b: (seen.append(str(a)), real(a, b))[1]):
            guild.save_plan(self.path, {"a": 1})
        self.assertIn(str(os.getpid()), seen[0])


class IngestOrderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        (self.dir / "inbox").mkdir()
        self.p = plan(goal("G1", state="waiting_user", kind="human"), approved=True)
        write(self.path, self.p)
        write(self.dir / "inbox" / "a.json", {"type": "result", "goal": "G1", "ok": True, "note": "n"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_input_stays_in_inbox_until_plan_is_saved(self):
        def boom():
            raise OSError("disk")

        with self.assertRaises(OSError):
            guild.ingest(self.path, self.p, TR, commit=boom)
        self.assertTrue((self.dir / "inbox" / "a.json").exists())
        self.assertFalse((self.dir / "inbox" / "done").exists())

    def test_input_moves_after_commit(self):
        order = []
        report = guild.ingest(self.path, self.p, TR, commit=lambda: order.append(
            (self.dir / "inbox" / "a.json").exists()))
        self.assertEqual(order, [True])  # commit の時点では、まだ inbox にある
        self.assertEqual(report["applied"], ["a.json"])
        self.assertTrue((self.dir / "inbox" / "done" / "a.json").exists())

    def test_without_commit_still_moves(self):
        guild.ingest(self.path, self.p, TR)
        self.assertTrue((self.dir / "inbox" / "done" / "a.json").exists())

    def test_cli_saves_plan_and_moves_input(self):
        r = subprocess.run([sys.executable, GUILD_PY, "ingest", str(self.path)], capture_output=True,
                           text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["goals"][0]["state"], "review")
        self.assertTrue((self.dir / "inbox" / "done" / "a.json").exists())


class AdoptOrderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        (self.dir / "reports").mkdir()
        (self.dir / "output" / "G1").mkdir(parents=True)
        (self.dir / "output" / "G1" / "x.md").write_text("x", encoding="utf-8")
        old = plan(goal("G1", state="done"), status="replan")
        write(self.path, old)
        (self.dir / "reports" / "plan-draft.json").write_text(draft_json(
            {"quest": "Q1", "title": "t", "goals": [goal("G1", criteria={**CRIT, "check": "changed"})]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_outputs_stay_when_save_fails(self):
        with mock.patch.object(guild, "save_plan", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                guild.adopt(self.path, TR)
        self.assertTrue((self.dir / "output" / "G1" / "x.md").exists())
        self.assertFalse((self.dir / "prev").exists())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["status"], "replan")

    def test_outputs_move_to_prev_after_save(self):
        guild.adopt(self.path, TR)
        self.assertFalse((self.dir / "output" / "G1").exists())
        moved = list((self.dir / "prev").glob("*/output/G1/x.md"))
        self.assertEqual(len(moved), 1)


class CarryOverTest(unittest.TestCase):
    def adopt(self, old, new_goals):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "reports").mkdir()
            write(d / "plan.json", old)
            (d / "reports" / "plan-draft.json").write_text(draft_json({"quest": "Q1", "title": "t", "goals": new_goals}), encoding="utf-8")
            return guild.adopt(d / "plan.json", TR)["carried"]

    def old(self):
        return plan(goal("G1", state="done"), goal("G2", state="done", deps=["G1"]),
                    goal("G3", state="done", deps=["G2"]), status="replan")

    def test_unchanged_chain_is_carried(self):
        new = [goal("G1"), goal("G2", deps=["G1"]), goal("G3", deps=["G2"])]
        self.assertEqual(self.adopt(self.old(), new), ["G1", "G2", "G3"])

    def test_downstream_of_changed_upstream_is_not_carried(self):
        new = [goal("G1", criteria={**CRIT, "check": "new"}), goal("G2", deps=["G1"]), goal("G3", deps=["G2"])]
        self.assertEqual(self.adopt(self.old(), new), [])

    def test_changed_deps_is_not_carried(self):
        new = [goal("G1"), goal("G2"), goal("G3", deps=["G2"])]  # G2 の deps が変わった
        self.assertEqual(self.adopt(self.old(), new), ["G1"])


class NextViewArchiveTest(unittest.TestCase):
    def test_archive_state_in_next(self):
        p = plan(goal("G1", state="done"), accepted=True)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            v = guild.next_view(p, d)
            self.assertEqual((v["archive"], v["needs_archive"], v["closed"]), ("none", True, False))
            write(d / "archive.json", {"status": "proposed"})
            v = guild.next_view(p, d)
            self.assertEqual((v["archive"], v["needs_archive"], v["closed"]), ("proposed", False, False))
            write(d / "archive.json", {"status": "done"})
            v = guild.next_view(p, d)
            self.assertEqual((v["archive"], v["needs_archive"], v["closed"]), ("done", False, True))

    def test_broken_archive_json_counts_as_proposed(self):
        p = plan(goal("G1", state="done"), accepted=True)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "archive.json").write_text("{", encoding="utf-8")
            self.assertEqual(guild.next_view(p, Path(d))["archive"], "proposed")  # 終わらない側に倒す

    def test_aborted_needs_archive(self):
        p = plan(goal("G1", state="failed"), status="aborted")
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(guild.next_view(p, Path(d))["needs_archive"])

    def test_active_quest_is_never_closed(self):
        p = plan(goal("G1", state="running"))
        with tempfile.TemporaryDirectory() as d:
            write(Path(d) / "archive.json", {"status": "done"})
            v = guild.next_view(p, Path(d))
            self.assertEqual((v["needs_archive"], v["closed"]), (False, False))

    def test_cli_next_includes_archive(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            write(d / "plan.json", plan(goal("G1", state="done"), accepted=True))
            r = subprocess.run([sys.executable, GUILD_PY, "next", str(d / "plan.json")], capture_output=True,
                               text=True, encoding="utf-8")
            self.assertEqual(json.loads(r.stdout)["archive"], "none")


class ReviewFixesTest(unittest.TestCase):
    """Phase 1 のレビューで見つかった穴の回帰テスト。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_steal_does_not_remove_fresh_lock(self):
        lock = Path(str(self.path) + ".lock")
        lock.write_text("1", encoding="utf-8")
        guild._steal_stale(lock)  # 取り上げ役が古さを確かめ直すので、新しいロックは消さない
        self.assertTrue(lock.exists())
        self.assertFalse(Path(str(lock) + ".steal").exists())

    def test_steal_removes_stale_lock(self):
        lock = Path(str(self.path) + ".lock")
        lock.write_text("1", encoding="utf-8")
        old = time.time() - guild.LOCK_STALE - 5
        os.utime(lock, (old, old))
        guild._steal_stale(lock)
        self.assertFalse(lock.exists())

    def test_release_failure_is_swallowed(self):
        real = Path.unlink

        def flaky(self_, missing_ok=False):
            if self_.name.endswith(".lock"):
                raise PermissionError("held")
            return real(self_, missing_ok=missing_ok)

        with mock.patch.object(guild, "REPLACE_TRIES", 2), mock.patch.object(Path, "unlink", flaky):
            with guild.plan_lock(self.path):
                pass  # 解除に失敗しても、例外にならない

    def test_contended_lock_waits_then_proceeds(self):
        import threading
        order = []
        started = threading.Event()

        def holder():
            with guild.plan_lock(self.path):
                started.set()
                time.sleep(0.4)
                order.append("holder")

        t = threading.Thread(target=holder)
        t.start()
        started.wait()
        t0 = time.monotonic()
        with guild.plan_lock(self.path):
            order.append("waiter")
        t.join()
        self.assertEqual(order, ["holder", "waiter"])
        self.assertGreater(time.monotonic() - t0, 0.2)  # 実際に待った

    def test_ingest_move_failure_becomes_warning(self):
        (self.dir / "inbox").mkdir()
        p = plan(goal("G1", state="waiting_user", kind="human"))
        write(self.path, p)
        write(self.dir / "inbox" / "a.json", {"type": "result", "goal": "G1", "ok": True, "note": "n"})
        saved = []
        with mock.patch.object(guild.shutil, "move", side_effect=OSError("held")):
            r = guild.ingest(self.path, p, TR, commit=lambda: saved.append(True))
        self.assertEqual(saved, [True])
        self.assertEqual(r["applied"], ["a.json"])
        self.assertEqual(len(r["warnings"]), 1)

    def test_adopt_archive_failure_becomes_warning(self):
        (self.dir / "reports").mkdir()
        write(self.path, plan(goal("G1", state="done"), status="replan"))
        (self.dir / "reports" / "plan-draft.json").write_text(draft_json({"quest": "Q1", "title": "t", "goals": [goal("G1")]}), encoding="utf-8")
        with mock.patch.object(guild, "archive_outputs", side_effect=OSError("held")):
            r = guild.adopt(self.path, TR)
        self.assertEqual(r["adopted"], 1)
        self.assertEqual(len(r["warnings"]), 1)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["status"], "active")

    def test_save_plan_cleans_tmp_when_write_fails(self):
        class Boom:
            pass

        with self.assertRaises(TypeError):
            guild.save_plan(self.path, {"a": Boom()})  # JSON にできない
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_carry_over_terminates_on_cycle_and_unknown_dep(self):
        old = plan(goal("G1", state="done", deps=["G2"]), goal("G2", state="done", deps=["G1"]),
                   goal("G3", state="done", deps=["G9"]))
        new = plan(goal("G1", deps=["G2"]), goal("G2", deps=["G1"]), goal("G3", deps=["G9"]))
        self.assertEqual(guild.carry_over(new, old), [])


if __name__ == "__main__":
    unittest.main()

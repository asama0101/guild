"""Phase 3（消化と検証）：鑑定士の証拠ゲート、failed からの retry、Todo ごとの max_retries。"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402

TR = guild.load_transitions()
GUILD_PY = str(ROOT / "skills" / "quest" / "guild.py")
CRIT = {"viewpoint": "v", "pass_line": "p", "check": "c"}


def todo(i, kind="auto", deps=(), **kw):
    t = {"id": i, "title": i, "kind": kind, "deps": list(deps), "criteria": dict(CRIT),
         "state": "pending", "retries": 0, "output": None}
    t.update(kw)
    return t


def plan(*todos, approved=True, **kw):
    return {"quest": "Q1", "title": "t", "approved": approved, "status": "active", "todos": list(todos), **kw}


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def run(*args):
    r = subprocess.run([sys.executable, GUILD_PY, *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


class EvidenceGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        (self.dir / "reports").mkdir()
        self.p = plan(todo("T1", state="review"), history=[
            {"t": guild.now(), "id": "T1", "event": "submitted", "from": "running", "to": "review"}])
        write(self.path, self.p)
        self.report = self.dir / "reports" / "T1-appraiser.md"

    def tearDown(self):
        self.tmp.cleanup()

    def test_passed_without_report_is_refused(self):
        code, _, err = run("advance", self.path, "T1", "passed")
        self.assertEqual(code, 1)
        self.assertIn("T1-appraiser.md", err)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["todos"][0]["state"], "review")

    def test_passed_with_fresh_report_is_accepted(self):
        self.report.write_text("## 判定\npassed\n", encoding="utf-8")
        code, out, err = run("advance", self.path, "T1", "passed")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["todos"][0]["state"], "done")

    def test_report_older_than_submission_is_refused(self):
        self.report.write_text("## 判定\npassed\n", encoding="utf-8")
        old = time.time() - 3600
        os.utime(self.report, (old, old))
        code, _, err = run("advance", self.path, "T1", "passed")
        self.assertEqual(code, 1)
        self.assertIn("古い", err)

    def test_empty_report_is_refused(self):
        self.report.write_text("", encoding="utf-8")
        self.assertEqual(run("advance", self.path, "T1", "passed")[0], 1)

    def test_rejected_needs_no_report(self):
        self.assertEqual(run("advance", self.path, "T1", "rejected")[0], 0)

    def test_old_plan_without_history_only_needs_existence(self):
        del self.p["history"]
        write(self.path, self.p)
        old = time.time() - 3600
        self.report.write_text("## 判定" + chr(10) + "passed", encoding="utf-8")
        os.utime(self.report, (old, old))
        self.assertEqual(run("advance", self.path, "T1", "passed")[0], 0)

    def test_report_verdict_must_be_passed(self):
        for word in ("rejected", "needs_scout"):
            self.report.write_text("## 判定" + chr(10) + word + chr(10), encoding="utf-8")
            code, _, err = run("advance", self.path, "T1", "passed")
            self.assertEqual(code, 1, word)
            self.assertIn("passed", err)

    def test_report_without_verdict_heading_is_refused(self):
        self.report.write_text("できました", encoding="utf-8")
        self.assertEqual(run("advance", self.path, "T1", "passed")[0], 1)

    def test_state_error_is_reported_before_evidence(self):
        p = plan(todo("T1", state="running"))
        write(self.path, p)
        _, _, err = run("advance", self.path, "T1", "passed")
        self.assertIn("running", err)

    def test_check_evidence_function(self):
        with self.assertRaises(guild.GuildError):
            guild.check_evidence(self.p, "T1", self.dir)
        self.report.write_text("## 判定" + chr(10) + "passed", encoding="utf-8")
        guild.check_evidence(self.p, "T1", self.dir)  # 例外にならない


class PerTodoRetryLimitTest(unittest.TestCase):
    def test_default_limit_is_shared(self):
        t = todo("T1", state="review", retries=1)
        self.assertEqual(guild.apply_event(t, "rejected", TR), "running")
        t = todo("T1", state="review", retries=2)
        self.assertEqual(guild.apply_event(t, "rejected", TR), "failed")

    def test_todo_limit_overrides(self):
        t = todo("T1", state="review", retries=0, max_retries=0)
        self.assertEqual(guild.apply_event(t, "rejected", TR), "failed")
        t = todo("T1", state="review", retries=3, max_retries=4)
        self.assertEqual(guild.apply_event(t, "rejected", TR), "running")

    def test_validate_checks_max_retries(self):
        for bad in (-1, "2", 1.5, 6, True):
            p = plan(todo("T1", max_retries=bad))
            self.assertTrue(any("max_retries" in e for e in guild.validate(p, TR)), bad)
        self.assertEqual(guild.validate(plan(todo("T1", max_retries=3)), TR), [])


class RetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "plan.json"
        (self.dir / "inbox").mkdir()
        (self.dir / "reports").mkdir()
        (self.dir / "output" / "T1").mkdir(parents=True)
        (self.dir / "output" / "T1" / "a.md").write_text("old", encoding="utf-8")
        (self.dir / "reports" / "T1-adventurer.md").write_text("old", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def ingest(self, p, data):
        write(self.path, p)
        write(self.dir / "inbox" / "a.json", data)
        return guild.ingest(self.path, p, TR)

    def test_retry_returns_failed_auto_todo_to_running_and_resets_count(self):
        p = plan(todo("T1", state="failed", retries=2), todo("T2", deps=["T1"], state="blocked"))
        r = self.ingest(p, {"type": "decision", "todo": "T1", "choice": "retry"})
        self.assertEqual(r["rejected"], [])
        t = p["todos"][0]
        self.assertEqual((t["state"], t["retries"]), ("running", 0))
        self.assertEqual(p["todos"][1]["state"], "blocked")  # 後続は T1 が済むまで止まったまま

    def test_retry_archives_old_output_after_commit(self):
        p = plan(todo("T1", state="failed", retries=2))
        write(self.path, p)
        write(self.dir / "inbox" / "a.json", {"type": "decision", "todo": "T1", "choice": "retry"})
        seen = []
        guild.ingest(self.path, p, TR, commit=lambda: seen.append((self.dir / "output" / "T1").exists()))
        self.assertEqual(seen, [True])  # 保存の時点では、まだ動かしていない
        self.assertFalse((self.dir / "output" / "T1").exists())
        self.assertEqual(len(list((self.dir / "prev").glob("*/output/T1/a.md"))), 1)
        self.assertEqual(len(list((self.dir / "prev").glob("*/reports/T1-adventurer.md"))), 1)

    def test_retry_of_declined_confirm_todo_asks_again(self):
        p = plan(todo("T1", state="failed", confirm=True))
        self.ingest(p, {"type": "decision", "todo": "T1", "choice": "retry"})
        self.assertEqual(p["todos"][0]["state"], "awaiting_confirm")

    def test_retry_of_human_todo_waits_for_the_user(self):
        p = plan(todo("T1", kind="human", state="failed"))
        self.ingest(p, {"type": "decision", "todo": "T1", "choice": "retry"})
        self.assertEqual(p["todos"][0]["state"], "waiting_user")

    def test_retry_only_from_failed(self):
        p = plan(todo("T1", state="running"))
        r = self.ingest(p, {"type": "decision", "todo": "T1", "choice": "retry"})
        self.assertEqual(len(r["rejected"]), 1)
        self.assertEqual(p["todos"][0]["state"], "running")

    def test_retry_is_recorded_in_history(self):
        p = plan(todo("T1", state="failed"))
        self.ingest(p, {"type": "decision", "todo": "T1", "choice": "retry"})
        self.assertTrue(any(h.get("event") == "retry" and h.get("id") == "T1" for h in p["history"]))


class BoardRetryContractTest(unittest.TestCase):
    def test_decision_letter_offers_retry_and_shows_limit(self):
        board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        i = board.index("'aria-label': '失敗の判断'")
        letter = board[i:i + 3500]
        self.assertIn("'retry'", letter)
        self.assertIn("上限", letter)


if __name__ == "__main__":
    unittest.main()

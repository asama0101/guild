"""Phase 4・5：稼働の印（heartbeat）、効果の測定（stats）。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
import guild  # noqa: E402

GUILD_PY = str(ROOT / "skills" / "quest" / "guild.py")


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class HeartbeatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "guild" / ".work").mkdir(parents=True)
        self.hb = self.root / "guild" / ".work" / "heartbeat.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_wait_writes_waiting_heartbeat(self):
        r = guild.wait_for(self.root, 0.3, interval=0.05)  # 何も届かない
        self.assertTrue(r["timeout"])
        d = json.loads(self.hb.read_text(encoding="utf-8"))
        self.assertEqual(d["state"], "waiting")
        self.assertIn("t", d)

    def test_wait_marks_working_when_arrivals_exist(self):
        q = self.root / "guild" / ".work" / "Q001"
        write(q / "plan.json", {"quest": "Q001", "goals": []})
        write(q / "inbox" / "a.json", {"type": "approve"})
        r = guild.wait_for(self.root, 5, interval=0.05)
        self.assertFalse(r["timeout"])
        self.assertEqual(json.loads(self.hb.read_text(encoding="utf-8"))["state"], "working")

    def test_arrivals_cli_marks_working(self):
        r = subprocess.run([sys.executable, GUILD_PY, "arrivals", str(self.root)], capture_output=True, text=True,
                           encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.hb.read_text(encoding="utf-8"))["state"], "working")

    def test_heartbeat_failure_never_breaks_the_command(self):
        with tempfile.TemporaryDirectory() as d:
            guild.beat(d, "waiting")  # guild/ がないルートでも、例外にならない


class StatsTest(unittest.TestCase):
    def test_stats_counts_from_history(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root / "guild" / ".work" / "Q001" / "plan.json", {
                "quest": "Q001", "status": "active", "approved": True,
                "goals": [{"id": "G1", "state": "done"}, {"id": "G2", "state": "failed"}, {"id": "G3", "state": "skipped"}],
                "history": [
                    {"t": "x", "event": "adopted"},
                    {"t": "x", "id": "G1", "event": "rejected", "from": "review", "to": "running"},
                    {"t": "x", "id": "G1", "event": "rejected", "from": "review", "to": "running"},
                    {"t": "x", "id": "G2", "event": "rejected", "from": "review", "to": "failed"},
                    {"t": "x", "id": "G2", "event": "retry", "from": "failed", "to": "running"},
                    {"t": "x", "event": "replanned", "carried": ["G1"]}]})
            write(root / "guild" / ".work" / "Q002" / "plan.json", {
                "quest": "Q002", "status": "aborted", "approved": True,
                "goals": [{"id": "G1", "state": "done"}], "history": []})
            s = guild.stats(root)
            q1 = next(q for q in s["quests"] if q["id"] == "Q001")
            self.assertEqual((q1["goals"], q1["done"], q1["failed"], q1["skipped"]), (3, 1, 1, 1))
            self.assertEqual((q1["rejected"], q1["retries"], q1["replans"]), (3, 1, 1))
            self.assertEqual(s["total"]["quests"], 2)
            self.assertEqual(s["total"]["rejected"], 3)
            self.assertEqual(s["total"]["aborted"], 1)
            self.assertEqual(s["total"]["rejected_per_goal"], round(3 / 4, 2))

    def test_stats_ignores_broken_plan_and_empty(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "guild" / ".work" / "Q001").mkdir(parents=True)
            (root / "guild" / ".work" / "Q001" / "plan.json").write_text("{", encoding="utf-8")
            s = guild.stats(root)
            self.assertEqual(s["total"]["quests"], 0)
            self.assertEqual(s["total"]["rejected_per_goal"], 0)

    def test_stats_cli(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, GUILD_PY, "stats", d], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("total", json.loads(r.stdout))


if __name__ == "__main__":
    unittest.main()

"""AI 社員 Phase 1：目標（goals）への改名、旧形式の検出。"""
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


class LegacyFormatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plan = Path(self.tmp.name) / "plan.json"
        write(self.plan, {"quest": "Q001", "approved": True, "todos": [{"id": "T1", "state": "pending", "kind": "auto"}]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_plan_rejects_legacy_todos(self):
        with self.assertRaises(guild.GuildError) as cm:
            guild.load_plan(self.plan)
        self.assertIn("旧形式", str(cm.exception))
        self.assertIn("goals", str(cm.exception))

    def test_load_plan_accepts_goals(self):
        write(self.plan, {"quest": "Q001", "goals": []})
        self.assertEqual(guild.load_plan(self.plan)["goals"], [])

    def test_cli_commands_refuse_legacy_plan_with_a_clear_message(self):
        for cmd in ("validate", "next", "sync"):
            r = subprocess.run([sys.executable, GUILD_PY, cmd, str(self.plan)], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(r.returncode, 0, cmd)
            self.assertIn("旧形式", r.stdout + r.stderr, cmd)

    def test_stats_skips_legacy_plan(self):
        root = Path(self.tmp.name) / "proj"
        write(root / "guild" / ".work" / "Q001" / "plan.json", {"quest": "Q001", "todos": []})
        self.assertEqual(guild.stats(root)["total"]["quests"], 0)


if __name__ == "__main__":
    unittest.main()

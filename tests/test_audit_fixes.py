"""監査（ponytail-audit）の指摘の修正を確かめる。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEST = str(ROOT / "skills" / "quest")
HOOKS = str(ROOT / "hooks")
sys.path.insert(0, QUEST)
import guild  # noqa: E402

CRIT = {"viewpoint": "a", "pass_line": "b", "check": "c"}


def plan_with(goal_id):
    return {"goals": [{"id": goal_id, "kind": "human", "state": "pending", "criteria": CRIT, "deps": []}]}


class GoalIdTest(unittest.TestCase):
    def test_unsafe_goal_ids_are_rejected(self):
        tr = guild.load_transitions()
        for bad in ("../../evil", "a/b", "a\\b", ".", "..", "G 1", "", "G" * 21):
            self.assertTrue(guild.validate(plan_with(bad), tr), repr(bad))

    def test_normal_goal_ids_pass(self):
        tr = guild.load_transitions()
        for ok in ("G1", "G12", "T1", "goal-1", "g_2"):
            self.assertEqual(guild.validate(plan_with(ok), tr), [], ok)


WORKER = """
import sys
sys.path.insert(0, sys.argv[1])
import webaccess
bad = 0
for i in range(20):
    try:
        webaccess.gate(sys.argv[2], "https://s%s-%d.example.com/x" % (sys.argv[3], i), "p")
    except Exception:
        bad += 1
sys.exit(1 if bad else 0)
"""

CRASHING_HOOK = """
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import webaccess
webaccess.gate = lambda *a: 1 / 0
import web_gate
sys.exit(web_gate.main())
"""


class WebGateTest(unittest.TestCase):
    def test_parallel_gates_do_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            procs = [subprocess.Popen([sys.executable, "-I", "-c", WORKER, QUEST, str(Path(d) / "guild"), str(n)]) for n in range(3)]
            self.assertEqual([p.wait() for p in procs], [0, 0, 0])

    def test_hook_denies_wizard_when_gate_crashes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "guild" / ".work").mkdir(parents=True)
            (Path(d) / "guild" / ".work" / "config.json").write_text("{}", encoding="utf-8")
            payload = json.dumps({"agent_type": "guild:wizard", "cwd": d, "tool_input": {"url": "https://example.com/", "prompt": "p"}})
            out = subprocess.run([sys.executable, "-I", "-c", CRASHING_HOOK, QUEST, HOOKS], input=payload.encode("utf-8"), capture_output=True,
                                 env={"CLAUDE_PROJECT_DIR": d, "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})
            self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
            self.assertEqual(json.loads(out.stdout.decode("utf-8"))["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()

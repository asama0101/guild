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


class StaleDraftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.q = Path(guild.new_quest(self.root)["dir"])
        self.tr = guild.load_transitions()

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, plan, obj):
        guild.save_plan(self.q / "plan.json", plan)
        (self.q / "inbox").mkdir(exist_ok=True)
        (self.q / "inbox" / "x.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        p = guild.load_plan(self.q / "plan.json")
        guild.ingest(self.q / "plan.json", p, self.tr, commit=lambda: guild.save_plan(self.q / "plan.json", p))

    def goal(self):
        return {"id": "G1", "title": "調べる", "kind": "auto", "class": "wizard", "effects": "none", "deps": [], "criteria": {k: k + " 十分に具体的" for k in guild.CRITERIA_KEYS}, "state": "done", "retries": 0}

    def check(self, plan, obj):
        draft = self.q / "reports" / "plan-draft.json"
        draft.write_text(json.dumps({"goals": [self.goal()]}), encoding="utf-8")
        self.send(plan, obj)
        self.assertFalse(draft.exists())
        self.assertTrue((self.q / "reports" / "plan-draft.prev.json").exists())
        with self.assertRaises(guild.GuildError):  # 受付係が書き直していないので、古い下書きは採用されない
            guild.adopt(self.q / "plan.json", self.tr)

    def test_reopen_retires_the_old_draft(self):
        plan = {"quest": "Q001", "title": "週報", "approved": True, "status": "active", "accepted": True, "goals": [self.goal()], "history": []}
        self.check(plan, {"type": "reopen", "comment": "直したい"})

    def test_replan_decision_retires_the_old_draft(self):
        g = self.goal()
        g["state"] = "failed"
        plan = {"quest": "Q001", "title": "週報", "approved": True, "status": "active", "goals": [g], "history": []}
        self.check(plan, {"type": "decision", "goal": "G1", "choice": "replan"})


if __name__ == "__main__":
    unittest.main()

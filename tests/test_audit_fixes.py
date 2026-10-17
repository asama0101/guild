"""監査（ponytail-audit）の指摘の修正を確かめる。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "quest"))
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


if __name__ == "__main__":
    unittest.main()

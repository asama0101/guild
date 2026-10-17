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

    def test_arrivals_ignore_the_inbox_of_a_legacy_quest(self):
        root = Path(self.tmp.name) / "proj"
        q = root / "guild" / ".work" / "Q001"
        write(q / "plan.json", {"quest": "Q001", "todos": []})
        write(q / "inbox" / "a.json", {"type": "decision", "choice": "abort"})
        q2 = root / "guild" / ".work" / "Q002"
        write(q2 / "plan.json", {"quest": "Q002", "goals": []})
        write(q2 / "inbox" / "b.json", {"type": "approve"})
        self.assertEqual([a["quest"] for a in guild.arrivals(root) if a["kind"] == "inbox"], ["Q002"])

    def test_board_does_not_break_on_a_legacy_plan(self):
        board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        self.assertIn("p && !Array.isArray(p.goals)", board)
        self.assertIn("qd.info === 'legacy'", board)
        self.assertNotIn("S.open目標", board)


CRIT = {"viewpoint": "v", "pass_line": "p", "check": "c"}


def mk(i, kind="auto", **kw):
    t = {"id": i, "title": i, "kind": kind, "deps": [], "criteria": dict(CRIT), "state": "pending"}
    t.update(kw)
    return t


class ClassTest(unittest.TestCase):
    def errs(self, *goals):
        return guild.validate({"goals": list(goals)}, guild.load_transitions())

    def test_auto_goal_needs_a_known_class(self):
        for c in guild.CLASSES:
            self.assertEqual(self.errs(mk("G1", **{"class": c})), [], c)
        self.assertTrue(any("class" in e for e in self.errs(mk("G1"))))
        self.assertTrue(any("class" in e for e in self.errs(mk("G1", **{"class": "sage"}))))
        self.assertTrue(any("class" in e for e in self.errs(mk("G1", **{"class": None}))))

    def test_human_goal_must_not_have_a_class(self):
        self.assertEqual(self.errs(mk("G1", "human")), [])
        self.assertTrue(any("class" in e for e in self.errs(mk("G1", "human", **{"class": "wizard", "effects": "none"}))))

    def test_classes_are_the_three_executors(self):
        self.assertEqual(guild.CLASSES, ("wizard", "alchemist", "adventurer"))

    def test_next_groups_ready_goals_by_class(self):
        plan = {"quest": "Q1", "approved": True, "status": "active", "goals": [
            mk("G1", state="running", **{"class": "wizard", "effects": "none"}), mk("G2", state="running", **{"class": "alchemist", "effects": "none"}),
            mk("G3", state="running", **{"class": "wizard", "effects": "none"}), mk("G4", state="pending", **{"class": "adventurer"}),
            mk("G5", "human", state="waiting_user")]}
        v = guild.next_view(plan)
        self.assertEqual(v["ready_by_class"], {"wizard": ["G1", "G3"], "alchemist": ["G2"], "adventurer": []})
        self.assertEqual(v["ready"], ["G1", "G2", "G3"])


class InitLayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_lives_under_work_and_nothing_else_is_added_to_guild_root(self):
        r = guild.init_guild(self.root)
        g = self.root / "guild"
        self.assertTrue((g / ".work" / "config.json").is_file())
        self.assertFalse((g / "config.json").exists())
        visible = sorted(p.name for p in g.iterdir() if not p.name.startswith("."))
        self.assertEqual(visible, ["archive", "board.html", "deliverables", "inputs"])
        self.assertEqual(json.loads((g / ".work" / "config.json").read_text(encoding="utf-8"))["python"], r["python"])

    def test_init_moves_a_legacy_config(self):
        g = self.root / "guild"
        write(g / "config.json", {"python": "legacy-python", "root": "x"})
        guild.init_guild(self.root)
        self.assertFalse((g / "config.json").exists())
        cfg = json.loads((g / ".work" / "config.json").read_text(encoding="utf-8"))
        self.assertNotEqual(cfg["python"], "legacy-python")  # init が今の Python に更新する

    def test_legacy_layout_is_still_accepted_before_reinit(self):
        g = self.root / "guild"
        write(g / "config.json", {"python": "p"})
        (g / "inputs").mkdir(parents=True)
        self.assertIsNotNone(guild.inputs_list(self.root))  # 旧配置でも、init の再実行までは動く

    def test_init_places_the_default_codex_and_keeps_project_additions(self):
        guild.init_guild(self.root)
        cdir = self.root / "guild" / ".work" / "codex"
        default = cdir / "default.md"
        self.assertTrue(default.is_file())
        self.assertEqual(default.read_text(encoding="utf-8"), (ROOT / "skills" / "quest" / "codex.md").read_text(encoding="utf-8"))
        (cdir / "project.md").write_text("# 追記\nメモ\n", encoding="utf-8")
        default.write_text("古い", encoding="utf-8")
        guild.init_guild(self.root)
        self.assertEqual((cdir / "project.md").read_text(encoding="utf-8"), "# 追記\nメモ\n")  # 追記は消えない
        self.assertNotEqual(default.read_text(encoding="utf-8"), "古い")  # 既定は最新に戻る


class WebGateTargetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, agent, url="https://unknown.example/x"):
        import os
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root))
        data = json.dumps({"agent_type": agent, "tool_input": {"url": url}, "cwd": str(self.root)})
        r = subprocess.run([sys.executable, str(ROOT / "hooks" / "web_gate.py")], input=data, capture_output=True, text=True,
                           encoding="utf-8", env=env)
        return r.stdout.strip()

    def test_only_the_wizard_is_gated(self):
        self.assertIn("deny", self.run_hook("guild:wizard"))
        for other in ("guild:adventurer", "guild:alchemist", "guild:appraiser", "guild:receptionist", ""):
            self.assertEqual(self.run_hook(other), "", other)

    def test_hook_finds_a_legacy_guild_folder_too(self):
        g = self.root / "guild"
        (g / ".work" / "config.json").rename(g / "config.json")
        self.assertIn("deny", self.run_hook("guild:wizard"))


class AgentFilesTest(unittest.TestCase):
    ROLES = {"receptionist": "opus", "wizard": "sonnet", "alchemist": "sonnet", "adventurer": "sonnet", "appraiser": "sonnet", "librarian": "sonnet"}

    def front(self, name):
        text = (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")
        head = text.split("---")[1]
        return {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in head.strip().splitlines() if ":" in l)}, text

    def test_exactly_the_six_roles_exist(self):
        self.assertEqual(sorted(p.stem for p in (ROOT / "agents").glob("*.md")), sorted(self.ROLES))

    def test_names_and_models(self):
        for name, model in self.ROLES.items():
            f, _ = self.front(name)
            self.assertEqual(f["name"], name)
            self.assertEqual(f["model"], model, name)

    def test_only_the_wizard_has_webfetch_and_the_alchemist_has_no_web(self):
        for name in self.ROLES:
            tools = self.front(name)[0]["tools"]
            self.assertEqual("WebFetch" in tools, name in ("wizard", "appraiser"), name)
            self.assertEqual("WebSearch" in tools, name == "wizard", name)
        self.assertNotIn("Web", self.front("alchemist")[0]["tools"])
        self.assertIn("playwright", self.front("adventurer")[0]["tools"])

    def test_every_role_reads_the_codex_first(self):
        for name in self.ROLES:
            text = self.front(name)[1]
            self.assertIn(".work/codex/default.md", text, name)
            self.assertIn(".work/codex/project.md", text, name)

    def test_old_role_names_are_gone(self):
        for f in (ROOT / "agents").glob("*.md"):
            text = f.read_text(encoding="utf-8")
            for old in ("cartographer", "地図師", "scout", "斥候", "needs_browser", "needs_scout"):
                self.assertNotIn(old, text, f"{f.name}: {old}")

    def test_codex_exists_and_covers_the_common_rules(self):
        text = (ROOT / "skills" / "quest" / "codex.md").read_text(encoding="utf-8")
        for needle in ("秘密情報", "確認の印", "未確認", "書庫"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main()

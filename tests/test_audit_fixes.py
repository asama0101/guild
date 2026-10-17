"""監査（ponytail-audit）の指摘の修正を確かめる。"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEST = str(ROOT / "skills" / "quest")
HOOKS = str(ROOT / "hooks")
sys.path.insert(0, QUEST)
import guild  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))
from test_board_js import extract, node_eval, script as board_script  # noqa: E402

CRIT = {"viewpoint": "a", "pass_line": "b", "check": "c"}


def plan_with(goal_id):
    return {"goals": [{"id": goal_id, "kind": "human", "state": "pending", "criteria": CRIT, "deps": []}]}


class GoalIdTest(unittest.TestCase):
    def test_unsafe_goal_ids_are_rejected(self):
        tr = guild.load_transitions()
        for bad in ("../../evil", "a/b", "a\\b", ".", "..", "G 1", "", "G" * 21, "A-B"):
            self.assertTrue(guild.validate(plan_with(bad), tr), repr(bad))

    def test_normal_goal_ids_pass(self):
        tr = guild.load_transitions()
        for ok in ("G1", "G12", "T1", "goal_1", "g_2"):
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
        guild.save_json(self.q / "plan.json", plan)
        (self.q / "inbox").mkdir(exist_ok=True)
        (self.q / "inbox" / "x.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        p = guild.load_plan(self.q / "plan.json")
        guild.ingest(self.q / "plan.json", p, self.tr, commit=lambda: guild.save_json(self.q / "plan.json", p))

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


class ArchiveDecideTest(unittest.TestCase):
    def test_retry_after_a_crash_does_not_duplicate_entries(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            q = Path(guild.new_quest(root)["dir"])
            cands = [{"id": f"C{i}", "type": "term", "name": f"用語{i}", "summary": "説明", "confidence": "guess", "body": "本文"} for i in (1, 2)]
            guild.save_json(q / "archive.json", {"status": "proposed", "candidates": cands, "registered": [], "codex_proposals": [], "decided": {}})
            answer = {"type": "archive", "decisions": {"C1": "register", "C2": "register"}}
            real, calls = guild.apply_candidate, []

            def flaky(*a, **k):
                calls.append(1)
                if len(calls) == 2:
                    raise OSError("同期中")
                return real(*a, **k)

            with mock.patch.object(guild, "apply_candidate", flaky):
                with self.assertRaises(OSError):
                    guild.archive_decide(q, answer)
            guild.archive_decide(q, answer)
            names = sorted(p.name for p in (root / "guild" / "archive").glob("*.md") if p.name != "index.md")
            self.assertEqual(names, ["用語1.md", "用語2.md"])
            self.assertEqual(guild.archive_state(q), "done")

    def test_entries_and_index_are_written_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            adir = Path(d)
            with mock.patch.object(guild, "write_text_atomic", wraps=guild.write_text_atomic) as w:
                guild.write_entry(adir, {"type": "term", "name": "用語", "summary": "説明", "confidence": "guess"})
                guild.rebuild_index(adir)
            self.assertEqual(len(w.call_args_list), 2)


class ArrivalsCostTest(unittest.TestCase):
    def test_quests_without_incoming_files_are_not_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guild.init_guild(root)
            quiet, busy = Path(guild.new_quest(root)["dir"]), Path(guild.new_quest(root)["dir"])
            (busy / "inbox" / "a.json").write_text("{}", encoding="utf-8")
            seen = []
            with mock.patch.object(guild, "is_legacy_plan", lambda p: seen.append(Path(p).parent.name) or False):
                got = guild.arrivals(root)
            self.assertEqual(seen, [busy.name])
            self.assertEqual([x["quest"] for x in got if x["kind"] == "inbox"], [busy.name])


LOAD_JS = r"""
const calls = { read: {} };
const files = JSON.parse(process.argv[2]);
const kids = (p) => { const pre = p ? p + '/' : '', seen = new Map();
  for (const k of Object.keys(files)) if (k.startsWith(pre)) { const rest = k.slice(pre.length), n = rest.split('/')[0]; seen.set(n, rest.includes('/') ? 'dir' : 'file'); }
  return [...seen].map(([name, kind]) => kind === 'file' ? { name, kind, mtime: 1000 } : { name, kind }); };
const S = { qcache: {}, fs: {
  list: async (p) => kids(p === '.work' ? '' : p),
  readText: async (p) => { calls.read[p] = (calls.read[p] || 0) + 1; return p in files ? files[p] : null; } } };
const parseJSON = JSON.parse, parseEntry = () => null;
const OVERALL_REPORT = 'overall-receptionist.md';
""" + "async " + extract("readJSON") + "\nasync " + extract("listFilesDeep") + "\nasync " + extract("loadAll") + r"""
(async () => {
  await loadAll();
  const first = Object.keys(calls.read).filter((k) => k.startsWith('Q001/')).length;
  calls.read = {};
  await loadAll();
  const second = Object.keys(calls.read).filter((k) => k.startsWith('Q001/')).length;
  console.log(JSON.stringify({ first, second }));
})();
"""


@unittest.skipUnless(__import__("shutil").which("node"), "node がありません")
class BoardLoadCostTest(unittest.TestCase):
    def run_load(self, files):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.js"
            f.write_text(LOAD_JS, encoding="utf-8")
            r = subprocess.run(["node", str(f), json.dumps(files)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

    def test_closed_quest_is_not_read_again(self):
        files = {"config.json": "{}", "Q001/plan.json": json.dumps({"accepted": True, "goals": []}), "Q001/request.json": "{}",
                 "Q001/archive.json": json.dumps({"status": "done"}), "Q001/reports/a.md": "x"}
        got = self.run_load(files)
        self.assertGreater(got["first"], 0)
        self.assertEqual(got["second"], 0)

    def test_open_quest_is_read_every_time(self):
        files = {"config.json": "{}", "Q001/plan.json": json.dumps({"approved": True, "goals": []}), "Q001/request.json": "{}"}
        self.assertGreater(self.run_load(files)["second"], 0)

    def test_closed_quest_is_read_again_when_an_input_arrives(self):
        files = {"config.json": "{}", "Q001/plan.json": json.dumps({"accepted": True, "goals": []}), "Q001/request.json": "{}",
                 "Q001/archive.json": json.dumps({"status": "done"}), "Q001/inbox/x.json": json.dumps({"type": "reopen"})}
        self.assertGreater(self.run_load(files)["second"], 0)


@unittest.skipUnless(__import__("shutil").which("node"), "node がありません")
class SharedHostTest(unittest.TestCase):
    def test_user_content_hosts_are_split_per_user(self):
        script = board_script()
        src = "".join(re.search(rf"const {n} = .*?\n", script).group(0) for n in ("SHARED_HOSTS", "SECOND_LEVEL")) + extract("parentDomain")
        cases = ["alice.tumblr.com", "bob.hatenablog.com", "carol.hateblo.jp", "x.glitch.me", "pub-1.r2.dev", "shop.myshopify.com", "d.wixsite.com", "p.webflow.io", "q.surge.sh"]
        out = node_eval(src + f"console.log(JSON.stringify({json.dumps(cases)}.map(parentDomain)))")
        self.assertEqual(out, cases)


if __name__ == "__main__":
    unittest.main()

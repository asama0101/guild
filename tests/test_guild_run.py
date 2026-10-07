"""guild-run.py のテスト（SPEC 17 節の 0.3 分）。Claude は呼ばず、偽の実行ファイルで試す。"""
import contextlib
import datetime
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEST = ROOT / "skills" / "quest"

spec = importlib.util.spec_from_file_location("guild_run", QUEST / "guild-run.py")
gr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gr)

NOW = "2026-03-01T09:00:00"

FAKE_PY = """\
import json, os, subprocess, sys
out = os.environ.get("FAKE_OUT")
if out:
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
touch = os.environ.get("FAKE_TOUCH")
if touch:
    env = dict(os.environ, GUILD_NOW=touch)
    subprocess.run([sys.executable, os.environ["FAKE_BOARD"], "--root", os.environ["FAKE_ROOT"],
                    "add-notice", "--text", "進めた"], env=env, check=True)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gr.main(list(args))
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "guild"
        self.root.mkdir()
        self._env = dict(os.environ)
        os.environ["GUILD_NOW"] = NOW
        sysd = self.root / ".system"
        for args in (["init-board"],):
            r = subprocess.run([sys.executable, str(QUEST / "board.py"), "--root", str(self.root), *args],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
        shutil.copy(QUEST / "board.py", sysd / "board.py")
        shutil.copy(QUEST / "transitions.json", sysd / "transitions.json")
        self.auto = sysd / "auto"
        self.logs = sysd / "logs"
        self.board_py = sysd / "board.py"
        # 偽の claude
        (base / "fake.py").write_text(FAKE_PY, encoding="utf-8")
        if os.name == "nt":
            self.fake = base / "claude.bat"
            self.fake.write_text(f'@echo off\r\n"{sys.executable}" "{base / "fake.py"}" %*\r\n', encoding="utf-8")
        else:
            self.fake = base / "claude.sh"
            self.fake.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{base / "fake.py"}" "$@"\n', encoding="utf-8")
            self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.calls = base / "calls.jsonl"
        os.environ.update(GUILD_CLAUDE=str(self.fake), FAKE_OUT=str(self.calls), FAKE_BOARD=str(self.board_py),
                          FAKE_ROOT=str(self.root), PYTHONUTF8="1")
        for k in ("FAKE_TOUCH", "FAKE_EXIT"):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def board(self, *args):
        r = subprocess.run([sys.executable, str(self.board_py), "--root", str(self.root), *args],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def need(self):
        self.board("add-quest", "--title", "見積書", "--detail", "見積書を作る")  # 受付のクエスト -> yes

    def called(self):
        if not self.calls.exists():
            return []
        return [json.loads(x) for x in self.calls.read_text(encoding="utf-8").splitlines()]

    def board_data(self):
        return json.loads((self.root / ".system" / "board.json").read_text(encoding="utf-8"))

    def usage(self):
        f = self.logs / "usage.jsonl"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


class TestAllow(unittest.TestCase):
    def test_parse(self):
        text = "# 見出し\nRead  # 読む\n\n   \nBash(python:*)\n  Glob\n#Write\n"
        self.assertEqual(gr.parse_allow(text), ["Read", "Bash(python:*)", "Glob"])

    def test_bundled_allow(self):
        tools = gr.parse_allow((QUEST / "allow.txt").read_text(encoding="utf-8"))
        for t in ("Read", "Glob", "Grep", "Write", "Edit", "Agent", "Skill", "Bash(python:*)", "Bash(py:*)",
                  "WebSearch", "WebFetch"):
            self.assertIn(t, tools)
        self.assertNotIn("Bash", tools)


class TestRun(Base):
    def test_no_need_does_not_call_claude(self):
        code, _, _ = run("--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(self.called(), [])
        self.assertFalse((self.auto / "run.lock").exists())
        u = self.usage()
        self.assertEqual(len(u), 1)
        self.assertEqual((u[0]["role"], u[0]["claude_called"], u[0]["result"]), ("guild-run", False, "no-need"))

    def test_yes_calls_claude_with_args(self):
        self.need()
        code, _, _ = run("--root", str(self.root), "--model", "opus")
        self.assertEqual(code, 0)
        calls = self.called()
        self.assertEqual(len(calls), 1)
        a = calls[0]
        self.assertEqual(a[0], "-p")
        self.assertEqual(a[1], "/guild:quest auto")
        self.assertEqual(a[a.index("--model") + 1], "opus")
        tools = a[a.index("--allowedTools") + 1]
        self.assertIn("Read", tools)
        self.assertIn("Bash(python:*)", tools)
        self.assertNotIn("#", tools)
        self.assertFalse((self.auto / "run.lock").exists())
        self.assertTrue(self.usage()[0]["claude_called"])

    def test_default_model_sonnet(self):
        self.need()
        run("--root", str(self.root))
        a = self.called()[0]
        self.assertEqual(a[a.index("--model") + 1], "sonnet")

    def test_fresh_lock_does_nothing(self):
        self.need()
        self.auto.mkdir(parents=True, exist_ok=True)
        (self.auto / "run.lock").write_text(json.dumps({"created": "2026-03-01T08:30:00"}), encoding="utf-8")
        code, _, _ = run("--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(self.called(), [])
        self.assertTrue((self.auto / "run.lock").exists())
        runlog = sorted(self.logs.glob("run-*.log"))[-1].read_text(encoding="utf-8")
        self.assertIn("錠あり", runlog)

    def test_old_lock_is_discarded(self):
        self.need()
        self.auto.mkdir(parents=True, exist_ok=True)
        (self.auto / "run.lock").write_text(json.dumps({"created": "2026-03-01T07:59:59"}), encoding="utf-8")
        code, _, _ = run("--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.called()), 1)
        self.assertFalse((self.auto / "run.lock").exists())

    def test_failure_keeps_lock_for_an_hour(self):
        self.need()
        os.environ["FAKE_EXIT"] = "3"
        code, _, _ = run("--root", str(self.root))
        self.assertNotEqual(code, 0)
        self.assertTrue((self.auto / "run.lock").exists())
        self.assertEqual(self.usage()[0]["result"], "failed")
        # 30 分後：錠が効いて、何もしない
        os.environ["GUILD_NOW"] = "2026-03-01T09:30:00"
        os.environ["FAKE_EXIT"] = "0"
        code, _, _ = run("--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.called()), 1)
        # 1 時間後：捨てて、再び動く
        os.environ["GUILD_NOW"] = "2026-03-01T10:00:00"
        code, _, _ = run("--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.called()), 2)
        self.assertFalse((self.auto / "run.lock").exists())

    def test_claude_missing_fails_and_notifies(self):
        self.need()
        os.environ["GUILD_CLAUDE"] = str(Path(self.tmp.name) / "nothing-here")
        code, _, _ = run("--root", str(self.root))
        self.assertNotEqual(code, 0)
        self.assertTrue((self.auto / "run.lock").exists())
        self.assertTrue(any("claude" in n.get("text", "") for n in self.board_data().get("notices", [])))

    def test_usage_write_failure_is_not_failure(self):
        self.need()
        # usage.jsonl をフォルダにして、書けなくする
        (self.logs / "usage.jsonl").mkdir(parents=True, exist_ok=True)
        code, _, _ = run("--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.called()), 1)
        self.assertFalse((self.auto / "run.lock").exists())

    def test_usage_rotation_over_90_days(self):
        self.logs.mkdir(parents=True, exist_ok=True)
        old = {"time": "2025-11-15T10:00:00", "role": "guild-run", "model": "", "tokens": 5}
        old2 = {"time": "2025-11-20T10:00:00", "role": "alchemist", "model": "sonnet", "tokens": 7}
        recent = {"time": "2026-02-20T10:00:00", "role": "guild-run", "model": "", "tokens": 0}
        (self.logs / "usage.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in (old, old2, recent)), encoding="utf-8")
        run("--root", str(self.root))
        agg = json.loads((self.logs / "usage-202511.json").read_text(encoding="utf-8"))
        self.assertEqual(agg["count"], 2)
        self.assertEqual(agg["tokens"], 12)
        rows = self.usage()
        self.assertNotIn("2025-11-15T10:00:00", [r["time"] for r in rows])
        self.assertIn("2026-02-20T10:00:00", [r["time"] for r in rows])
        self.assertEqual(len(rows), 2)  # recent と今回の 1 行

    def test_run_logs_capped_at_30(self):
        self.logs.mkdir(parents=True, exist_ok=True)
        for i in range(35):
            (self.logs / f"run-2026010{i // 10}T0{i % 10}0000.log").write_text("x", encoding="utf-8")
        for i in range(3):
            os.environ["GUILD_NOW"] = f"2026-03-01T09:0{i}:00"
            run("--root", str(self.root))
        files = sorted(self.logs.glob("run-*.log"))
        self.assertEqual(len(files), 30)
        self.assertTrue(files[-1].name.startswith("run-20260301T090200"))


class TestStop(Base):
    def test_two_no_progress_runs_stop_and_resume(self):
        self.need()
        run("--root", str(self.root))
        self.assertFalse((self.auto / "stopped.json").exists())
        run("--root", str(self.root))
        self.assertTrue((self.auto / "stopped.json").exists())
        self.assertEqual(len(self.called()), 2)
        texts = [n.get("text", "") for n in self.board_data().get("notices", [])]
        self.assertIn("自動実行を止めました。進まない状態が続いています。", texts)
        # 止まっている間は何もしない
        code, _, _ = run("--root", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.called()), 2)
        # 再開
        code, _, _ = run("--root", str(self.root), "--resume")
        self.assertEqual(code, 0)
        self.assertFalse((self.auto / "stopped.json").exists())
        run("--root", str(self.root))
        self.assertEqual(len(self.called()), 3)

    def test_progress_resets_counter(self):
        self.need()
        run("--root", str(self.root))  # 進捗なし 1 回目
        os.environ["FAKE_TOUCH"] = "2027-01-01T00:00:00"  # 今度は updated が変わる
        run("--root", str(self.root))
        self.assertFalse((self.auto / "stopped.json").exists())
        os.environ.pop("FAKE_TOUCH")
        run("--root", str(self.root))  # 進捗なし 1 回目（やり直し）
        self.assertFalse((self.auto / "stopped.json").exists())
        run("--root", str(self.root))  # 2 回続いた
        self.assertTrue((self.auto / "stopped.json").exists())

    def test_apply_simple_alone_is_not_progress(self):
        # 回ごとに GUILD_NOW を進めても（apply-simple/tick が updated を変えても）、Claude の前後で比べるので進捗にならない
        self.need()
        run("--root", str(self.root))
        os.environ["GUILD_NOW"] = "2026-03-01T10:00:00"
        run("--root", str(self.root))
        self.assertTrue((self.auto / "stopped.json").exists())


class TestScheduler(Base):
    def test_windows_args(self):
        script, py = Path("C:/g/.system/auto/guild-run.py"), "C:/Python/python.exe"
        cmd = gr.schedule_args("windows", 30, script, Path("C:/g"), py)
        self.assertEqual(cmd[:2], ["schtasks", "/Create"])
        self.assertEqual(cmd[cmd.index("/SC") + 1], "MINUTE")
        self.assertEqual(cmd[cmd.index("/MO") + 1], "30")
        self.assertEqual(cmd[cmd.index("/TN") + 1], "guild-run")
        tr = cmd[cmd.index("/TR") + 1]
        self.assertIn("guild-run.py", tr)
        self.assertIn("--root", tr)
        self.assertIn("/F", cmd)

    def test_cron_line(self):
        line = gr.schedule_args("cron", 60, Path("/g/.system/auto/guild-run.py"), Path("/g"), "/usr/bin/python3")
        self.assertTrue(line.startswith("0 */1 * * * "))
        self.assertIn("guild-run.py", line)
        self.assertTrue(line.endswith("# guild-run"))
        self.assertTrue(gr.schedule_args("cron", 15, Path("/s"), Path("/g"), "p").startswith("*/15 * * * * "))
        with self.assertRaises(ValueError):
            gr.schedule_args("cron", 90, Path("/s"), Path("/g"), "p")

    def test_cron_replace_keeps_others_and_replaces_guild(self):
        cur = "0 1 * * * backup\n*/5 * * * * old guild-run.py # guild-run\n"
        new = gr.cron_replace(cur, "0 */1 * * * new # guild-run")
        self.assertEqual(new, "0 1 * * * backup\n0 */1 * * * new # guild-run\n")
        self.assertEqual(gr.cron_replace(cur, None), "0 1 * * * backup\n")

    def test_dry_run_prints_only(self):
        code, out, _ = run("--root", str(self.root), "--install", "--every", "20", "--dry-run", "--platform",
                           "windows")
        self.assertEqual(code, 0)
        self.assertIn("schtasks", out)
        self.assertIn("/Create", out)
        self.assertIn("20", out)
        code, out, _ = run("--root", str(self.root), "--install", "--dry-run", "--platform", "cron")
        self.assertEqual(code, 0)
        self.assertIn("0 */1 * * *", out)
        self.assertIn("# guild-run", out)
        code, out, _ = run("--root", str(self.root), "--uninstall", "--dry-run", "--platform", "windows")
        self.assertIn("/Delete", out)
        code, out, _ = run("--root", str(self.root), "--uninstall", "--dry-run", "--platform", "cron")
        self.assertEqual(code, 0)

    def test_install_default_every_is_60(self):
        code, out, _ = run("--root", str(self.root), "--install", "--dry-run", "--platform", "windows")
        self.assertIn("60", out)


if __name__ == "__main__":
    unittest.main()

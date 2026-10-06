"""guild-run.py の純関数テスト（実プロセス・実スケジューラは呼ばない）。"""
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "skills" / "auto" / "guild-run.py"
_spec = importlib.util.spec_from_file_location("guild_run", _SRC)
gr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gr)


def _age(path, hours):
    t = time.time() - hours * 3600
    os.utime(path, (t, t))


class TestLock(unittest.TestCase):
    def test_fresh_and_stale(self):
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d) / "run.lock"
            self.assertFalse(gr.lock_is_fresh(lock))  # 無い
            lock.touch()
            self.assertTrue(gr.lock_is_fresh(lock))
            self.assertEqual(gr.LOCK_HOURS, 1)
            _age(lock, 0.9)
            self.assertTrue(gr.lock_is_fresh(lock))
            _age(lock, 1.1)
            self.assertFalse(gr.lock_is_fresh(lock))


class TestSkip(unittest.TestCase):
    def test_has_work(self):
        with tempfile.TemporaryDirectory() as d:
            sysd, auto = Path(d), Path(d) / "auto"
            auto.mkdir()
            self.assertFalse(gr.has_work(sysd, auto))
            (sysd / "requests" / "済").mkdir(parents=True)
            (sysd / "requests" / "済" / "a.json").touch()  # 直下ではない
            (sysd / "answers").mkdir()
            (sysd / "answers" / "a.txt").touch()  # json ではない
            self.assertFalse(gr.has_work(sysd, auto))
            (sysd / "feedback").mkdir()
            (sysd / "feedback" / "f.json").touch()
            self.assertTrue(gr.has_work(sysd, auto))
            (sysd / "feedback" / "f.json").unlink()
            (auto / "resume").touch()
            self.assertTrue(gr.has_work(sysd, auto))


class TestAllow(unittest.TestCase):
    def test_parse(self):
        text = "# c\nRead\n\n  Write  \n# x\nBash(mv:*)\n"
        self.assertEqual(gr.parse_allow(text), "Read,Write,Bash(mv:*)")


class TestPrune(unittest.TestCase):
    def test_keep_newest_30(self):
        with tempfile.TemporaryDirectory() as d:
            logs = Path(d)
            for i in range(33):
                (logs / f"run-20260101-{i:04d}.log").touch()
            (logs / "last.json").touch()
            gr.prune_logs(logs)
            left = sorted(p.name for p in logs.glob("run-*.log"))
            self.assertEqual(len(left), 30)
            self.assertNotIn("run-20260101-0000.log", left)
            self.assertNotIn("run-20260101-0002.log", left)
            self.assertIn("run-20260101-0003.log", left)
            self.assertTrue((logs / "last.json").exists())


class TestCron(unittest.TestCase):
    def test_expr(self):
        self.assertEqual(gr.cron_expr(60), "0 * * * *")
        self.assertEqual(gr.cron_expr(5), "*/5 * * * *")

    def test_replace_and_remove(self):
        vault = "/v/a"
        old = f"0 1 * * * other\n*/5 * * * * x # guild:{vault}\n*/5 * * * * y # guild:/v/b\n"
        new = gr.cron_replace(old, vault, f"*/10 * * * * z # guild:{vault}")
        self.assertEqual(new.count(f"# guild:{vault}"), 1)
        self.assertIn("*/10 * * * * z", new)
        self.assertIn("# guild:/v/b", new)
        self.assertIn("0 1 * * * other", new)
        self.assertNotIn("*/5 * * * * x", new)
        removed = gr.cron_remove(new, vault)
        self.assertNotIn(f"# guild:{vault}", removed)
        self.assertIn("# guild:/v/b", removed)
        self.assertTrue(removed.endswith("\n"))
        # 前方一致の別 vault を巻き込まない
        self.assertIn("# guild:/v/ab", gr.cron_remove("a # guild:/v/ab\n", vault))

    def test_replace_empty(self):
        self.assertEqual(gr.cron_replace("", "/v", "L # guild:/v"), "L # guild:/v\n")


class TestPlatform(unittest.TestCase):
    def test_kind(self):
        self.assertEqual(gr.scheduler_kind("win32"), "windows")
        self.assertEqual(gr.scheduler_kind("darwin"), "mac")
        self.assertEqual(gr.scheduler_kind("linux"), "linux")

    def test_monkeypatch_sys_platform(self):
        orig = gr.sys.platform
        try:
            gr.sys.platform = "win32"
            self.assertEqual(gr.current_os(), "windows")
            gr.sys.platform = "darwin"
            self.assertEqual(gr.current_os(), "mac")
        finally:
            gr.sys.platform = orig

    def test_windows_pythonw(self):
        with tempfile.TemporaryDirectory() as d:
            py = Path(d) / "python.exe"
            py.touch()
            self.assertEqual(Path(gr.windows_runner(str(py))).name, "python.exe")
            (Path(d) / "pythonw.exe").touch()
            self.assertEqual(Path(gr.windows_runner(str(py))).name, "pythonw.exe")

    def test_schtasks_args_are_list(self):
        args = gr.schtasks_create_args("guild-v", 5, "C:/py/pythonw.exe", "C:/v/guild-run.py")
        self.assertIsInstance(args, list)
        self.assertEqual(args[0], "schtasks")
        self.assertEqual(args[args.index("/TN") + 1], "guild-v")
        self.assertEqual(args[args.index("/MO") + 1], "5")


class TestFindPython(unittest.TestCase):
    def test_store_stub(self):
        self.assertTrue(gr.is_store_stub(9009, ""))
        self.assertTrue(gr.is_store_stub(1, "Python was not found; run without arguments to install from the Microsoft Store"))
        self.assertFalse(gr.is_store_stub(0, "Python 3.12.1"))

    def test_order_and_stub_skip(self):
        calls = []

        def runner(cmd):
            calls.append(cmd)
            if cmd == ["py", "-3"]:
                return None  # 未インストール
            if cmd == ["python3"]:
                return (9009, "")  # Store スタブ
            return (0, "Python 3.11.0")

        self.assertEqual(gr.find_python(runner), ["python"])
        self.assertEqual(calls, [["py", "-3"], ["python3"], ["python"]])

    def test_first_wins_and_none(self):
        self.assertEqual(gr.find_python(lambda c: (0, "Python 3.12")), ["py", "-3"])
        self.assertIsNone(gr.find_python(lambda c: None))


class TestVenv(unittest.TestCase):
    def test_read(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "board.json"
            self.assertIsNone(gr.read_venv_python(b))
            b.write_text("{broken", encoding="utf-8")
            self.assertIsNone(gr.read_venv_python(b))
            b.write_text(json.dumps({"a": 1}), encoding="utf-8")
            self.assertIsNone(gr.read_venv_python(b))
            b.write_text(json.dumps({"venv_python": "/x/bin/python"}), encoding="utf-8")
            self.assertEqual(gr.read_venv_python(b), "/x/bin/python")


class TestStatus(unittest.TestCase):
    def test_mismatch(self):
        self.assertIsNone(gr.status_mismatch(True, True))
        self.assertIsNone(gr.status_mismatch(False, False))
        self.assertIn("登録", gr.status_mismatch(True, False))
        self.assertIn("auto.json", gr.status_mismatch(False, True))


class TestRunFlow(unittest.TestCase):
    def _vault(self, d):
        auto = Path(d) / "guild" / ".system" / "auto"
        auto.mkdir(parents=True)
        (auto / "allow.txt").write_text("# c\nRead\nWrite\n", encoding="utf-8")
        return auto

    def test_skipped_writes_last(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._vault(d)
            rc = gr.run(auto, runner=lambda *a, **k: self.fail("呼ばれない"))
            self.assertEqual(rc, 0)
            last = json.loads((auto.parent / "logs" / "last.json").read_text(encoding="utf-8"))
            self.assertEqual((last["ok"], last["skipped"]), (True, True))

    def test_success_clears_resume_and_lock(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._vault(d)
            (auto / "resume").touch()
            seen = {}

            def runner(cmd, logfile, cwd):
                seen.update(cmd=cmd, cwd=cwd, lock=(auto / "run.lock").exists())
                return 0

            self.assertEqual(gr.run(auto, runner=runner), 0)
            self.assertEqual(seen["cmd"][0], "claude")
            self.assertIn("Read,Write", seen["cmd"])
            self.assertEqual(Path(seen["cwd"]), Path(d))
            self.assertTrue(seen["lock"])
            self.assertFalse((auto / "run.lock").exists())
            self.assertFalse((auto / "resume").exists())

    def test_failure_keeps_resume_and_exception_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._vault(d)
            (auto / "resume").touch()
            self.assertEqual(gr.run(auto, runner=lambda c, l, w: 3), 3)
            self.assertTrue((auto / "resume").exists())
            self.assertFalse((auto / "run.lock").exists())

            def boom(c, l, w):
                raise RuntimeError("kaboom")

            self.assertNotEqual(gr.run(auto, runner=boom), 0)
            self.assertFalse((auto / "run.lock").exists())
            logs = list((auto.parent / "logs").glob("run-*.log"))
            self.assertTrue(any("kaboom" in p.read_text(encoding="utf-8") for p in logs))


_OK_JSON = json.dumps({
    "type": "result", "is_error": False, "result": "全部片付けました", "num_turns": 7,
    "total_cost_usd": 0.1234,
    "usage": {"input_tokens": 100, "output_tokens": 50,
              "cache_read_input_tokens": 900, "cache_creation_input_tokens": 30},
}, ensure_ascii=False)


class TestUsage(unittest.TestCase):
    NOW = gr.datetime(2026, 10, 6, 12, 30)

    def test_parse_normal(self):
        d = gr.parse_claude_json(_OK_JSON)
        self.assertEqual(d["result"], "全部片付けました")
        rec = gr.usage_record(self.NOW, True, d)
        self.assertEqual(rec, {
            "time": "2026-10-06 12:30", "ok": True, "input_tokens": 100, "output_tokens": 50,
            "cache_read_input_tokens": 900, "cache_creation_input_tokens": 30,
            "cost_usd": 0.1234, "turns": 7})

    def test_missing_keys_are_null(self):
        d = gr.parse_claude_json(json.dumps({"result": "x", "usage": {"input_tokens": 5}}))
        rec = gr.usage_record(self.NOW, True, d)
        self.assertEqual(rec["input_tokens"], 5)
        for k in ("output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                  "cost_usd", "turns"):
            self.assertIsNone(rec[k])
        d = gr.parse_claude_json(json.dumps({"result": "x"}))  # usage 自体が無い
        self.assertIsNone(gr.usage_record(self.NOW, True, d)["input_tokens"])

    def test_not_json(self):
        self.assertIsNone(gr.parse_claude_json("Error: boom"))
        self.assertIsNone(gr.parse_claude_json(""))
        self.assertIsNone(gr.parse_claude_json("[1, 2]"))
        self.assertEqual(gr.usage_record(self.NOW, False, None),
                         {"time": "2026-10-06 12:30", "ok": False})

    def test_json_line_after_noise(self):
        d = gr.parse_claude_json("warn\n" + _OK_JSON + "\nstderr text\n")
        self.assertEqual(d["num_turns"], 7)


class TestUsageViaRun(unittest.TestCase):
    def _vault(self, d):
        auto = Path(d) / "guild" / ".system" / "auto"
        auto.mkdir(parents=True)
        (auto / "allow.txt").write_text("Read\n", encoding="utf-8")
        (auto / "resume").touch()
        return auto

    def _usage(self, auto):
        f = auto.parent / "logs" / "usage.jsonl"
        return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]

    def test_json_run_writes_usage_and_readable_log(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._vault(d)
            seen = {}

            def runner(cmd, logfile, cwd):
                seen["cmd"] = cmd
                Path(logfile).write_text(_OK_JSON, encoding="utf-8")
                return 0

            self.assertEqual(gr.run(auto, runner=runner), 0)
            self.assertEqual(seen["cmd"][seen["cmd"].index("--output-format") + 1], "json")
            rows = self._usage(auto)
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["ok"], rows[0]["input_tokens"], rows[0]["turns"]), (True, 100, 7))
            log = next((auto.parent / "logs").glob("run-*.log")).read_text(encoding="utf-8")
            self.assertIn("全部片付けました", log)
            self.assertNotIn("total_cost_usd", log)
            self.assertFalse((auto / "resume").exists())  # 既存の動き

    def test_non_json_keeps_raw_log_and_minimal_usage(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._vault(d)

            def runner(cmd, logfile, cwd):
                Path(logfile).write_text("Error: something broke\n", encoding="utf-8")
                return 2

            self.assertEqual(gr.run(auto, runner=runner), 2)
            rows = self._usage(auto)
            self.assertEqual(set(rows[0]), {"time", "ok"})
            self.assertFalse(rows[0]["ok"])
            log = next((auto.parent / "logs").glob("run-*.log")).read_text(encoding="utf-8")
            self.assertIn("something broke", log)
            self.assertTrue((auto / "resume").exists())

    def test_usage_failure_does_not_fail_run(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._vault(d)
            (auto.parent / "logs").mkdir()
            (auto.parent / "logs" / "usage.jsonl").mkdir()  # 書けない
            self.assertEqual(gr.run(auto, runner=lambda c, l, w: 0), 0)
            self.assertFalse((auto / "resume").exists())


class TestPathTxt(unittest.TestCase):
    def test_save_and_run_reads(self):
        with tempfile.TemporaryDirectory() as d:
            gr.save_path(d, "linux", "/a:/b")
            self.assertEqual((Path(d) / "path.txt").read_text(encoding="utf-8"), "/a:/b\n")

    def test_windows_not_written(self):
        with tempfile.TemporaryDirectory() as d:
            gr.save_path(d, "win32", "C:\\x")
            self.assertFalse((Path(d) / "path.txt").exists())

    def _read(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "path.txt"
            p.write_text(text, encoding="utf-8")
            return gr.read_path_txt(p)

    def test_read_empty(self):
        self.assertIsNone(self._read(""))

    def test_read_blank_only(self):
        self.assertIsNone(self._read("  \n\n \t\n"))

    def test_read_skips_leading_blank(self):
        self.assertEqual(self._read("\n/a:/b\n"), "/a:/b")

    def test_read_normal(self):
        self.assertEqual(self._read("/a:/b\n"), "/a:/b")

    def test_run_empty_path_txt_keeps_path(self):
        with tempfile.TemporaryDirectory() as d:
            auto = Path(d) / "guild" / ".system" / "auto"
            auto.mkdir(parents=True)
            (auto / "path.txt").write_text("", encoding="utf-8")
            orig = os.environ["PATH"]
            try:
                gr.run(auto)
                self.assertEqual(os.environ["PATH"], orig)
                self.assertTrue((Path(d) / "guild" / ".system" / "logs" / "last.json").exists())
            finally:
                os.environ["PATH"] = orig

    def test_run_applies_path_txt(self):
        with tempfile.TemporaryDirectory() as d:
            auto = Path(d) / "guild" / ".system" / "auto"
            auto.mkdir(parents=True)
            (auto / "path.txt").write_text("/zzz:/yyy\n", encoding="utf-8")
            orig = os.environ["PATH"]
            try:
                gr.run(auto)
                self.assertEqual(os.environ["PATH"], "/zzz:/yyy")
            finally:
                os.environ["PATH"] = orig


class TestCronLine(unittest.TestCase):
    def test_rejects_control_chars(self):
        for bad in ("a\nb", "a\rb", "a\0b"):
            for pos in range(3):
                args = ["/py", "/s.py", "/v"]
                args[pos] = bad
                with self.assertRaises(ValueError):
                    gr.cron_line(5, *args)

    def test_percent_escaped(self):
        line = gr.cron_line(5, "/py", "/s.py", "/v/100%")
        self.assertIn("\\%", line)
        self.assertNotIn("100%", line.replace("\\%", ""))

    def test_quotes_special_paths(self):
        line = gr.cron_line(5, "/my py/$(x)/python", "/s `id`.py", "/v")
        self.assertIn("'/my py/$(x)/python'", line)
        self.assertIn("'/s `id`.py'", line)
        self.assertTrue(line.endswith("# guild:/v"))


class TestSchtasksQuote(unittest.TestCase):
    def test_rejects_quote(self):
        with self.assertRaises(ValueError):
            gr.schtasks_create_args("t", 5, 'C:/a"b/py.exe', "C:/s.py")
        with self.assertRaises(ValueError):
            gr.schtasks_create_args("t", 5, "C:/py.exe", 'C:/s".py')


class TestInstallFlow(unittest.TestCase):
    def setUp(self):
        self._plat, self._run = gr.sys.platform, gr.subprocess.run
        self.calls = []
        self.crontab = ""

    def tearDown(self):
        gr.sys.platform, gr.subprocess.run = self._plat, self._run

    def _fake(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "crontab" and cmd[1] == "-l":
            return gr.subprocess.CompletedProcess(cmd, 0, self.crontab, "")
        if cmd[0] == "crontab":
            self.crontab = kw["input"]
        return gr.subprocess.CompletedProcess(cmd, 0, "", "")

    def _auto(self, d):
        auto = Path(d) / "vault" / "guild" / ".system" / "auto"
        auto.mkdir(parents=True)
        return auto

    def test_windows_install_list_args(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._auto(d)
            gr.sys.platform = "win32"
            gr.subprocess.run = self._fake
            gr.install(auto, 5)
            self.assertIsInstance(self.calls[0], list)
            self.assertEqual(self.calls[0][0], "schtasks")
            self.assertFalse((auto / "path.txt").exists())

    def test_linux_install_replaces_and_saves_path(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._auto(d)
            gr.sys.platform = "linux"
            gr.subprocess.run = self._fake
            gr.install(auto, 5)
            gr.install(auto, 10)
            marks = [l for l in self.crontab.splitlines() if l.endswith(f"# guild:{Path(d) / 'vault'}")]
            self.assertEqual(len(marks), 1)
            self.assertTrue(marks[0].startswith("*/10 "))
            self.assertEqual((auto / "path.txt").read_text(encoding="utf-8").strip(), os.environ["PATH"])

    def test_linux_uninstall_only_marker(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._auto(d)
            gr.sys.platform = "linux"
            gr.subprocess.run = self._fake
            self.crontab = "0 1 * * * other\n"
            gr.install(auto, 5)
            gr.uninstall(auto)
            self.assertEqual(self.crontab, "0 1 * * * other\n")

    def test_status_windows_query(self):
        with tempfile.TemporaryDirectory() as d:
            auto = self._auto(d)
            gr.sys.platform = "win32"
            gr.subprocess.run = self._fake
            gr.status(auto)
            self.assertEqual(self.calls[0][:2], ["schtasks", "/Query"])


class TestModelAndSimple(unittest.TestCase):
    def test_build_cmd_model(self):
        self.assertNotIn("--model", gr.build_cmd("claude", "Read"))
        self.assertNotIn("--model", gr.build_cmd("claude", "Read", "bad model; rm"))
        cmd = gr.build_cmd("claude", "Read", "sonnet")
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")

    def _vault(self, d):
        auto = Path(d) / "vault" / "guild" / ".system" / "auto"
        auto.mkdir(parents=True)
        sysd = auto.parent
        (auto / "allow.txt").write_text("Read\n", encoding="utf-8")
        (sysd / "requests").mkdir()
        (sysd / "board.json").write_text(json.dumps({"max_active": 4, "studies": [], "quests": [],
                                                      "questions": [], "notices": []}), encoding="utf-8")
        src = Path(_SRC).parent.parent / "quest" / "board.py"
        (sysd / "board.py").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return auto, sysd

    def test_setting_only_skips_claude(self):
        with tempfile.TemporaryDirectory() as d:
            auto, sysd = self._vault(d)
            (sysd / "requests" / "M20261006100000.json").write_text(
                json.dumps({"kind": "setting", "key": "max_active", "value": 7, "posted": "x"}), encoding="utf-8")
            called = []
            code = gr.run(auto, runner=lambda *a: called.append(a) or 0)
            self.assertEqual(code, 0)
            self.assertEqual(called, [])
            self.assertEqual(json.loads((sysd / "board.json").read_text(encoding="utf-8"))["max_active"], 7)
            self.assertTrue(json.loads((sysd / "logs" / "last.json").read_text(encoding="utf-8"))["skipped"])
            self.assertFalse((auto / "run.lock").exists())

    def test_real_request_still_calls_claude_with_model(self):
        with tempfile.TemporaryDirectory() as d:
            auto, sysd = self._vault(d)
            (sysd / "auto.json").write_text(json.dumps({"model": "opus"}), encoding="utf-8")
            (sysd / "requests" / "R1.json").write_text(json.dumps({"kind": "quest"}), encoding="utf-8")
            seen = []
            gr.run(auto, runner=lambda cmd, log, cwd: seen.append(cmd) or 0)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][seen[0].index("--model") + 1], "opus")

    def test_missing_board_py_is_fine(self):
        with tempfile.TemporaryDirectory() as d:
            auto, sysd = self._vault(d)
            (sysd / "board.py").unlink()
            self.assertEqual(gr.apply_simple_requests(sysd), 0)


if __name__ == "__main__":
    unittest.main()

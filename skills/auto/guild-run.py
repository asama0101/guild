#!/usr/bin/env python3
"""Guild 自動実行（Windows / Mac / Linux 共通）。

<vault>/guild/.system/auto/ に置かれ、スケジューラから起動される。
サブコマンド: run（既定）| install [--every MIN] | uninstall | status
標準ライブラリのみ。OS 判定は sys.platform だけに頼る。
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

LOCK_HOURS = 3
KEEP_LOGS = 30
PROMPT = "/guild:quest auto"


# ---------- 純関数 ----------

def lock_is_fresh(lock, hours=LOCK_HOURS):
    """lock が存在し、hours 時間以内に更新されていれば True。"""
    try:
        return time.time() - Path(lock).stat().st_mtime < hours * 3600
    except OSError:
        return False


def has_work(sys_dir, auto_dir):
    """requests/answers/feedback 直下の *.json か resume があれば True。"""
    if (Path(auto_dir) / "resume").exists():
        return True
    return any(
        next((Path(sys_dir) / n).glob("*.json"), None) is not None
        for n in ("requests", "answers", "feedback")
        if (Path(sys_dir) / n).is_dir()
    )


def parse_allow(text):
    """allow.txt を、# 行と空行を除いて , で連結する。"""
    items = [s.strip() for s in text.splitlines()]
    return ",".join(s for s in items if s and not s.startswith("#"))


def prune_logs(logs, keep=KEEP_LOGS):
    """run-*.log を名前の新しい順に keep 個残し、古いものを消す。"""
    for p in sorted(Path(logs).glob("run-*.log"), reverse=True)[keep:]:
        p.unlink(missing_ok=True)


def cron_expr(every_min):
    return "0 * * * *" if every_min >= 60 else f"*/{every_min} * * * *"


def _marker(vault):
    # cron では % が改行扱いになるため、行内と同じ形（\%）で比較できるよう揃える
    return "# guild:" + str(vault).replace("%", "\\%")


def _check_plain(**values):
    """改行・CR・NUL などの制御文字を含む値を拒否する（crontab 行の注入防止）。"""
    for name, v in values.items():
        if re.search(r"[\x00-\x1f\x7f]", str(v)):
            raise ValueError(f"{name} に制御文字が含まれている: {v!r}")


def cron_line(every_min, py, script, vault):
    """crontab の 1 行を組み立てる。制御文字は ValueError、値は shlex.quote、% は \\% にする。"""
    _check_plain(venv_python=py, script=script, vault=vault)
    cmd = f"{shlex.quote(str(py))} {shlex.quote(str(script))}".replace("%", "\\%")
    return f"{cron_expr(every_min)} {cmd} {_marker(vault)}"


def save_path(auto_dir, platform, path):
    """cron は PATH が短いので、install 時の PATH を path.txt に残す。Windows は環境継承のため書かない。"""
    if platform != "win32":
        (Path(auto_dir) / "path.txt").write_text(path + "\n", encoding="utf-8")


def cron_remove(text, vault):
    """目印行（末尾が # guild:<vault>）だけを取り除く。"""
    keep = [l for l in text.splitlines() if not l.rstrip().endswith(_marker(vault))]
    return "\n".join(keep) + "\n" if keep else ""


def cron_replace(text, vault, line):
    """既存の目印行を消して line を末尾に足す（重複登録しない）。"""
    return cron_remove(text, vault) + line + "\n"


def scheduler_kind(platform):
    if platform == "win32":
        return "windows"
    return "mac" if platform == "darwin" else "linux"


def current_os():
    return scheduler_kind(sys.platform)


def windows_runner(python_exe):
    """同じ階層に pythonw.exe があればそれを、無ければ渡された python.exe を返す。"""
    w = Path(python_exe).with_name("pythonw.exe")
    return str(w) if w.exists() else str(python_exe)


def schtasks_create_args(task, every_min, runner_exe, script):
    """シェルを経由させず subprocess に渡す list 引数（/TN が MSYS のパス変換を受けないため）。"""
    if '"' in str(runner_exe) or '"' in str(script):
        raise ValueError(f'パスに " を含められない: {runner_exe} / {script}')
    return ["schtasks", "/Create", "/TN", task, "/SC", "MINUTE", "/MO", str(every_min),
            "/TR", f'"{runner_exe}" "{script}"', "/F"]


def is_store_stub(returncode, output):
    """`--version` が正常に Python を名乗らなければ Microsoft Store スタブ等とみなす。"""
    return not (returncode == 0 and output.strip().startswith("Python"))


def find_python(runner):
    """py -3 → python3 → python の順で、本物の Python のコマンドを返す。runner(cmd)->(rc, out)|None。"""
    for cmd in (["py", "-3"], ["python3"], ["python"]):
        r = runner(cmd)
        if r is not None and not is_store_stub(*r):
            return cmd
    return None


def _probe(cmd):
    try:
        p = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def read_venv_python(board_json):
    """board.json の venv_python を返す。無い・壊れていれば None。"""
    try:
        v = json.loads(Path(board_json).read_text(encoding="utf-8")).get("venv_python")
    except (OSError, ValueError, AttributeError):
        return None
    return v or None


def status_mismatch(enabled, registered):
    """auto.json の enabled と実際の登録の食い違いを文章で返す。無ければ None。"""
    if enabled and not registered:
        return "auto.json は有効だが、スケジューラの登録が見つからない（/guild:auto 始める で入れ直す）"
    if registered and not enabled:
        return "スケジューラの登録が残っているが、auto.json は停止中"
    return None


# ---------- 実行 ----------

def _paths(auto):
    auto = Path(auto)
    sysd = auto.parent
    return auto, sysd, sysd.parent.parent, sysd / "logs"


def read_path_txt(path):
    """path.txt の先頭の非空行を返す。ファイルが無い・空・空白のみなら None。"""
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return line.strip()
    return None


def _write_last(logs, now, ok, skipped):
    (logs / "last.json").write_text(
        json.dumps({"time": now.strftime("%Y-%m-%d %H:%M"), "ok": ok, "skipped": skipped}),
        encoding="utf-8")


def _real_runner(cmd, logfile, cwd):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with open(logfile, "wb") as f:
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=cwd,
                              creationflags=flags).returncode


def run(auto_dir, runner=_real_runner):
    """1 回分の自動実行。終了コードを返す。"""
    auto, sysd, vault, logs = _paths(auto_dir)
    logs.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    log = logs / f"run-{now.strftime('%Y%m%d-%H%M')}.log"
    lock, resume = auto / "run.lock", auto / "resume"
    new_path = read_path_txt(auto / "path.txt")  # cron の PATH は短いため
    if new_path:
        os.environ["PATH"] = new_path
    if lock.exists():
        if lock_is_fresh(lock):
            return 0
        lock.unlink(missing_ok=True)
    if not has_work(sysd, auto):
        _write_last(logs, now, True, True)
        return 0
    lock.touch()
    resume.touch()
    code = 1
    try:
        allow = parse_allow((auto / "allow.txt").read_text(encoding="utf-8"))
        cfile = auto / "claude.txt"
        lines = cfile.read_text(encoding="utf-8").splitlines() if cfile.is_file() else []
        claude = lines[0].strip() if lines and lines[0].strip() else "claude"
        cmd = [claude, "-p", PROMPT, "--permission-mode", "acceptEdits", "--allowedTools", allow]
        code = runner(cmd, log, str(vault))
        if code == 0:
            resume.unlink(missing_ok=True)
        _write_last(logs, now, code == 0, False)
    except Exception:
        # 握り潰さず、ログ末尾に traceback を残す（pythonw では標準エラーが見えない）
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n" + traceback.format_exc())
        _write_last(logs, now, False, False)
        code = 1
    finally:
        lock.unlink(missing_ok=True)
    prune_logs(logs)
    return code


# ---------- スケジューラ操作（実プロセスを呼ぶ。テスト対象外） ----------

def _task_name(vault):
    return f"guild-{vault.name}"


def _crontab_get():
    p = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def _crontab_set(text):
    subprocess.run(["crontab", "-"], input=text, text=True, check=True)


def _write_auto_json(sysd, data):
    (sysd / "auto.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_auto_json(sysd):
    try:
        return json.loads((sysd / "auto.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def install(auto_dir, every_min):
    auto, sysd, vault, _ = _paths(auto_dir)
    script = Path(__file__).resolve()
    py = read_venv_python(sysd / "board.json") or sys.executable
    kind = current_os()
    if kind == "windows":
        task = _task_name(vault)
        args = schtasks_create_args(task, every_min, windows_runner(py), script)
        subprocess.run(args, check=True)
    else:
        task = _marker(vault)
        line = cron_line(every_min, py, script, vault)
        _crontab_set(cron_replace(_crontab_get(), str(vault), line))
        save_path(auto, sys.platform, os.environ.get("PATH", ""))
    _write_auto_json(sysd, {"enabled": True, "every_min": every_min, "os": kind, "task": task,
                            "since": datetime.now().strftime("%Y-%m-%d %H:%M")})


def uninstall(auto_dir):
    auto, sysd, vault, _ = _paths(auto_dir)
    if current_os() == "windows":
        subprocess.run(["schtasks", "/Delete", "/TN", _task_name(vault), "/F"])
    else:
        _crontab_set(cron_remove(_crontab_get(), str(vault)))
    data = _read_auto_json(sysd)
    data["enabled"] = False
    _write_auto_json(sysd, data)


def status(auto_dir):
    auto, sysd, vault, _ = _paths(auto_dir)
    if current_os() == "windows":
        registered = subprocess.run(["schtasks", "/Query", "/TN", _task_name(vault)],
                                    capture_output=True).returncode == 0
    else:
        registered = any(l.rstrip().endswith(_marker(vault)) for l in _crontab_get().splitlines())
    data = _read_auto_json(sysd)
    out = {"registered": registered, "auto_json": data,
           "mismatch": status_mismatch(bool(data.get("enabled")), registered)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Guild 自動実行")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run")
    ins = sub.add_parser("install")
    ins.add_argument("--every", type=int, default=5, metavar="MIN")
    sub.add_parser("uninstall")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    auto = Path(__file__).resolve().parent
    if a.cmd == "install":
        try:
            install(auto, a.every)
        except ValueError as e:
            print(f"install を中止: {e}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "uninstall":
        uninstall(auto)
        return 0
    if a.cmd == "status":
        return status(auto)
    return run(auto)


if __name__ == "__main__":
    sys.exit(main())

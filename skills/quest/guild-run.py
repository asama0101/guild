#!/usr/bin/env python3
"""guild の自動実行（SPEC 14 節）。<guild>/.system/auto/guild-run.py に置いて、OS のスケジューラから呼ぶ。

1 回の実行：錠 -> board.py apply-simple -> board.py need-claude -> （yes のときだけ）claude -p "/guild:quest auto"。
標準ライブラリだけで動く。
"""
import argparse
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

LOCK_SECONDS = 3600
USAGE_DAYS = 90
MAX_RUN_LOGS = 30
MAX_NO_PROGRESS = 2
TASK_NAME = "guild-run"
CRON_MARK = "# guild-run"
NOTICE_STOP = "自動実行を止めました。進まない状態が続いています。"
HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- 基本
def now():
    env = os.environ.get("GUILD_NOW")
    if env:
        return datetime.datetime.fromisoformat(env)
    return datetime.datetime.now().replace(microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def find_root(arg):
    return Path(arg) if arg else HERE.parent.parent


class Ctx:
    def __init__(self, root):
        self.root = Path(root)
        self.sys = self.root / ".system"
        self.auto = self.sys / "auto"
        self.logs = self.sys / "logs"
        self.lock = self.auto / "run.lock"
        self.stopped = self.auto / "stopped.json"
        self.state = self.auto / "state.json"
        self.board_py = self.sys / "board.py"
        self.board_json = self.sys / "board.json"
        self.lines = []

    def log(self, msg):
        self.lines.append(f"[{iso(now())}] {msg}")

    def python(self):
        f = self.sys / "python.txt"
        try:
            s = f.read_text(encoding="utf-8").strip()
            if s:
                return s
        except OSError:
            pass
        return sys.executable


# ---------------------------------------------------------------- allow.txt
def parse_allow(text):
    tools = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            tools.append(line)
    return tools


def load_allow(ctx):
    for p in (ctx.auto / "allow.txt", HERE / "allow.txt"):
        if p.exists():
            return parse_allow(p.read_text(encoding="utf-8"))
    return []


# ---------------------------------------------------------------- 錠
def take_lock(ctx):
    """錠を取れたら True。新しい錠（1 時間未満）があれば False。"""
    ctx.auto.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(ctx.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if lock_age(ctx) < LOCK_SECONDS:
                return False
            ctx.log("古い錠（1 時間以上）を捨てました")
            try:
                ctx.lock.unlink()
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"created": iso(now()), "pid": os.getpid()}, f)
        return True
    return False


def lock_age(ctx):
    try:
        created = datetime.datetime.fromisoformat(json.loads(ctx.lock.read_text(encoding="utf-8"))["created"])
    except (OSError, ValueError, KeyError, TypeError):
        # 壊れた錠は、ファイルの更新時刻で見る
        try:
            created = datetime.datetime.fromtimestamp(ctx.lock.stat().st_mtime)
        except OSError:
            return LOCK_SECONDS
    return (now() - created).total_seconds()


def release_lock(ctx):
    try:
        ctx.lock.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- 状態
def read_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def board_updated(ctx):
    d = read_json(ctx.board_json, {})
    return d.get("updated") if isinstance(d, dict) else None


def run_board(ctx, *args):
    cmd = [ctx.python(), str(ctx.board_py), "--root", str(ctx.root), *args]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                       timeout=600)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


# ---------------------------------------------------------------- 記録（失敗しても回は失敗にしない）
def write_usage(ctx, result, called):
    try:
        ctx.logs.mkdir(parents=True, exist_ok=True)
        row = {"time": iso(now()), "role": "guild-run", "model": "", "tokens": 0, "quest": None, "goal": None,
               "result": result, "claude_called": bool(called)}
        with open(ctx.logs / "usage.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        ctx.log(f"usage.jsonl に書けませんでした（回は続けます）: {e}")


def rotate_usage(ctx):
    """90 日より古い行を、月ごとの usage-YYYYMM.json にまとめる。"""
    try:
        f = ctx.logs / "usage.jsonl"
        if not f.exists():
            return
        limit = now() - datetime.timedelta(days=USAGE_DAYS)
        keep, old = [], {}
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                t = datetime.datetime.fromisoformat(row["time"])
            except (ValueError, KeyError, TypeError):
                keep.append(line)
                continue
            if t < limit:
                old.setdefault(t.strftime("%Y%m"), []).append(row)
            else:
                keep.append(line)
        if not old:
            return
        for ym, rows in old.items():
            p = ctx.logs / f"usage-{ym}.json"
            agg = read_json(p, None) or {"month": f"{ym[:4]}-{ym[4:]}", "count": 0, "tokens": 0, "by_role": {},
                                        "by_model": {}}
            for r in rows:
                agg["count"] += 1
                try:
                    agg["tokens"] += int(r.get("tokens") or 0)
                except (TypeError, ValueError):
                    pass
                for key, name in (("by_role", "role"), ("by_model", "model")):
                    k = str(r.get(name) or "")
                    agg[key][k] = agg[key].get(k, 0) + 1
            p.write_text(json.dumps(agg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        f.write_text("".join(x + "\n" for x in keep), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        ctx.log(f"usage の集計に失敗しました（回は続けます）: {e}")


def write_run_log(ctx):
    try:
        ctx.logs.mkdir(parents=True, exist_ok=True)
        name = f"run-{now().strftime('%Y%m%dT%H%M%S')}.log"
        with open(ctx.logs / name, "a", encoding="utf-8") as f:
            f.write("\n".join(ctx.lines) + "\n")
        files = sorted(ctx.logs.glob("run-*.log"))
        for old in files[:-MAX_RUN_LOGS]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 1 回の実行
def find_claude():
    env = os.environ.get("GUILD_CLAUDE")
    if env:
        return env if (Path(env).exists() or shutil.which(env)) else None
    return shutil.which("claude")


def build_claude_cmd(exe, model, tools):
    return [exe, "-p", "/guild:quest auto", "--model", model, "--allowedTools", " ".join(tools)]


def notice(ctx, text):
    try:
        run_board(ctx, "add-notice", "--text", text)
    except Exception as e:  # noqa: BLE001
        ctx.log(f"知らせを出せませんでした: {e}")


def execute(ctx, model):
    """(終了コード, 結果, Claude を呼んだか, 錠を消すか)"""
    if not ctx.board_py.exists() or not ctx.board_json.exists():
        ctx.log(f"board.py か board.json が見つかりません: {ctx.sys}")
        return 1, "failed", False, False
    code, out, err = run_board(ctx, "apply-simple")
    ctx.log(f"apply-simple: {code} {out or err}")
    if code != 0:
        return 1, "failed", False, False
    before = board_updated(ctx)  # apply-simple の後の値。取り込みだけでは進捗にしない
    code, out, err = run_board(ctx, "need-claude")
    ctx.log(f"need-claude: {code} {out or err}")
    if code != 0:
        return 1, "failed", False, False
    if out.split(":", 1)[0].strip() != "yes":
        ctx.log("Claude を呼ぶ作業がないため、終わります")
        return 0, "no-need", False, True
    exe = find_claude()
    if not exe:
        ctx.log("claude の実行ファイルが見つかりません")
        notice(ctx, "自動実行で claude が見つかりませんでした。claude をインストールするか、GUILD_CLAUDE を設定してください。")
        return 1, "claude-missing", False, False
    cmd = build_claude_cmd(exe, model, load_allow(ctx) + [f"Bash({ctx.python()}:*)"])
    ctx.log("claude を呼びます: " + " ".join(cmd[:5]))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(ctx.root), timeout=6 * 3600)
        ctx.log(f"claude: 終了コード {r.returncode}")
        if r.stdout:
            ctx.log(r.stdout.strip()[-2000:])
        if r.stderr:
            ctx.log("stderr: " + r.stderr.strip()[-2000:])
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        ctx.log(f"claude を実行できませんでした: {e}")
        ok = False
    # 進捗：Claude を呼んだ回の前後で updated が変わったか
    st = read_json(ctx.state, {})
    after = board_updated(ctx)
    if after != before:
        st["no_progress"] = 0
    else:
        st["no_progress"] = int(st.get("no_progress", 0)) + 1
        ctx.log(f"進捗なし（{st['no_progress']} 回）")
    try:
        ctx.state.write_text(json.dumps(st, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass
    if st["no_progress"] >= MAX_NO_PROGRESS:
        ctx.stopped.write_text(json.dumps({"stopped": iso(now()), "reason": "no-progress"}, ensure_ascii=False)
                               + "\n", encoding="utf-8")
        notice(ctx, NOTICE_STOP)
        ctx.log("進捗のない回が続いたため、自動実行を止めました")
    return (0, "ok", True, True) if ok else (1, "failed", True, False)


def run_once(root, model="sonnet"):
    ctx = Ctx(root)
    if ctx.stopped.exists():
        ctx.log("停止中（stopped.json あり）。--resume で再開できます")
        write_run_log(ctx)
        return 0
    if not take_lock(ctx):
        ctx.log("錠あり：何もしません")
        write_usage(ctx, "locked", False)
        write_run_log(ctx)
        return 0
    code, result, called, unlock = 1, "failed", False, False
    try:
        code, result, called, unlock = execute(ctx, model)
    except Exception as e:  # noqa: BLE001
        ctx.log(f"例外: {e}")
    finally:
        if unlock:
            release_lock(ctx)
        else:
            ctx.log("失敗した回のため、錠を 1 時間残します")
        write_usage(ctx, result, called)
        rotate_usage(ctx)
        write_run_log(ctx)
    return code


def resume(root):
    ctx = Ctx(root)
    for p in (ctx.stopped, ctx.state):
        try:
            p.unlink()
        except OSError:
            pass
    release_lock(ctx)
    print("自動実行を再開できる状態にしました")
    return 0


# ---------------------------------------------------------------- スケジューラ
def schedule_args(kind, every, script, root, python):
    """登録コマンドを組み立てる。kind は windows か cron。cron は crontab に足す 1 行を返す。"""
    every = int(every)
    if every < 1:
        raise ValueError("--every は 1 以上の分で指定してください")
    if kind == "windows":
        if every > 1439:
            raise ValueError("Windows では --every は 1439 分までです")
        tr = f'"{python}" "{script}" --root "{root}"'
        return ["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(every), "/TN", TASK_NAME, "/TR", tr]
    if every < 60:
        spec = f"*/{every} * * * *"
    elif every % 60 == 0 and every <= 1440:
        h = every // 60
        spec = "0 0 * * *" if h == 24 else f"0 */{h} * * *"
    else:
        raise ValueError("cron では 60 分以上のとき、--every は 60 の倍数（1440 まで）にしてください")
    return f"{spec} {shlex.quote(python)} {shlex.quote(str(script))} --root {shlex.quote(str(root))} {CRON_MARK}"


def uninstall_args(kind):
    if kind == "windows":
        return ["schtasks", "/Delete", "/F", "/TN", TASK_NAME]
    return None


def cron_replace(current, line):
    keep = [x for x in current.splitlines() if CRON_MARK not in x]
    if line:
        keep.append(line)
    return "\n".join(keep) + ("\n" if keep else "")


def scheduler(a, root):
    kind = a.platform or ("windows" if os.name == "nt" else "cron")
    script = Path(__file__).resolve()
    python = Ctx(root).python()
    install = a.install
    if kind == "windows":
        cmd = schedule_args("windows", a.every, script, root, python) if install else uninstall_args("windows")
        if a.dry_run:
            print(subprocess.list2cmdline(cmd))
            return 0
        return subprocess.run(cmd).returncode
    line = schedule_args("cron", a.every, script, root, python) if install else None
    if a.dry_run:
        print(line if install else f"crontab から {CRON_MARK} の行を外します")
        return 0
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    current = r.stdout if r.returncode == 0 else ""
    return subprocess.run(["crontab", "-"], input=cron_replace(current, line), text=True).returncode


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="guild 自動実行")
    ap.add_argument("--root", help="guild フォルダ（既定：このファイルの 3 つ上）")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--install", action="store_true", help="スケジューラに登録する")
    ap.add_argument("--uninstall", action="store_true", help="スケジューラから外す")
    ap.add_argument("--every", type=int, default=60, help="登録の間隔（分）")
    ap.add_argument("--dry-run", action="store_true", help="登録コマンドを表示だけにする")
    ap.add_argument("--platform", choices=["windows", "cron"], help="（テスト用）登録先を指定する")
    ap.add_argument("--resume", action="store_true", help="停止を解いて再開する")
    a = ap.parse_args(argv)
    root = find_root(a.root)
    try:
        if a.resume:
            return resume(root)
        if a.install or a.uninstall:
            return scheduler(a, root)
        return run_once(root, a.model)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

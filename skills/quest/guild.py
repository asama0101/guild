#!/usr/bin/env python3
"""guild の実行エンジン（標準ライブラリだけ）。

plan.json を書けるのはこのファイルだけ。遷移は transitions.json で決め、定義にない遷移はエラー。
使い方: guild.py {adopt|validate|sync|next|ingest} PLAN / guild.py advance PLAN ID EVENT
adopt は PLAN と同じフォルダの reports/plan-draft.json から PLAN を作る（承認前の状態で）。
guild.py init ROOT: ROOT/guild/ と config.json（この Python のパス）を作る。
guild.py new ROOT [R…]: ROOT/guild/ に次の依頼のフォルダ（Q001…）を作る。R… を渡すと、ボードが保存した受付待ちの依頼を取り込む。
guild.py requests ROOT: 受付待ちの依頼を一覧する。
guild.py arrivals ROOT: ボードから届いて、まだ取り込んでいない入力と依頼を一覧する。
guild.py wait ROOT [秒]: 届くまで待つ（既定 540 秒）。届いていれば、すぐ返す。
guild.py answers QDIR: 計画がない依頼の、質問への回答（type が answers）を取り出す。
エラーは終了コード 1。
"""
import datetime
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 納品物の形式（拡張子）。作れるようになったものから足す
FORMATS = {"md": ".md"}
SATISFIED = ("done", "skipped")
CRITERIA_KEYS = ("viewpoint", "pass_line", "check")


class GuildError(Exception):
    pass


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise GuildError(f"{path} を読めません: {e}")


def save_plan(path, plan):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_transitions(path=None):
    return load_json(path or HERE / "transitions.json")


def todo_map(plan):
    return {t["id"]: t for t in plan.get("todos", [])}


def effective(tr, kind):
    """種別ごとの遷移表。差分は (from, event) が同じ共通の遷移をすべて置き換える。"""
    over = tr["kinds"].get(kind, {}).get("override", [])
    keys = {(o["from"], o["event"]) for o in over}
    return [t for t in tr["transitions"] if (t["from"], t["event"]) not in keys] + over


def guard_ok(name, todo, tr):
    if name is None:
        return True
    left = todo.get("retries", 0) < tr.get("max_retries", 0)
    return {"confirm": bool(todo.get("confirm")), "no_confirm": not todo.get("confirm"),
            "retries_left": left, "no_retries_left": not left}[name]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def note(plan, **kw):
    """状態の移り変わりの記録（ボードのタイムラインが読む）。plan.json の history に追記する。"""
    if plan is not None:
        plan.setdefault("history", []).append({"t": now(), **kw})


def apply_event(todo, event, tr, plan=None):
    for t in effective(tr, todo["kind"]):
        if t["from"] == todo["state"] and t["event"] == event and guard_ok(t.get("guard"), todo, tr):
            if event == "rejected" and t["to"] != "failed":
                todo["retries"] = todo.get("retries", 0) + 1
            before = todo["state"]
            todo["state"] = t["to"]
            note(plan, id=todo["id"], event=event, **{"from": before, "to": t["to"]})
            return t["to"]
    raise GuildError(f"{todo['id']}: 状態 {todo['state']} では {event} できません")


def validate(plan, tr):
    errs = []
    todos = plan.get("todos")
    if not isinstance(todos, list) or not todos:
        return ["todos がありません"]
    if plan.get("format", "md") not in FORMATS:
        errs.append(f"format が未対応です: {plan.get('format')}（対応: {', '.join(FORMATS)}）")
    ids = [t.get("id") for t in todos]
    if len(set(ids)) != len(ids) or None in ids:
        errs.append("id が重複しているか、欠けています")
    for t in todos:
        i = t.get("id")
        if t.get("kind") not in tr["kinds"]:
            errs.append(f"{i}: kind が不明です: {t.get('kind')}")
        if t.get("state") not in tr["states"]:
            errs.append(f"{i}: state が不明です: {t.get('state')}")
        c = t.get("criteria") or {}
        for k in CRITERIA_KEYS:
            if not str(c.get(k, "")).strip():
                errs.append(f"{i}: criteria.{k} が空です")
        if t.get("confirm") and t.get("kind") != "auto":
            errs.append(f"{i}: confirm は auto の Todo だけに付けられます")
        for d in t.get("deps", []):
            if d not in ids:
                errs.append(f"{i}: deps の {d} がありません")
            elif d == i:
                errs.append(f"{i}: 自分自身に依存しています")
    if not errs and has_cycle(todos):
        errs.append("deps に循環があります")
    return errs


def has_cycle(todos):
    deps = {t["id"]: list(t.get("deps", [])) for t in todos}
    done = set()
    while True:
        ready = [i for i, d in deps.items() if i not in done and all(x in done for x in d)]
        if not ready:
            return len(done) != len(deps)
        done.update(ready)


def runnable(plan):
    return plan.get("approved") is True and plan.get("status", "active") == "active"


def sync(plan, tr):
    """前提の結果に応じて deps_done / dep_failed / unblock を、動かなくなるまで適用する。"""
    changes = []
    if not runnable(plan):
        return changes
    tm = todo_map(plan)
    moved = True
    while moved:
        moved = False
        for t in plan["todos"]:
            st = [tm[d]["state"] for d in t.get("deps", [])]
            ok = all(s in SATISFIED for s in st)
            bad = any(s in ("failed", "blocked") for s in st)
            event = None
            if t["state"] == "pending":
                event = "dep_failed" if bad else ("deps_done" if ok else None)
            elif t["state"] == "blocked" and ok:
                event = "unblock"
            if event:
                before = t["state"]
                apply_event(t, event, tr, plan)
                changes.append({"id": t["id"], "event": event, "from": before, "to": t["state"]})
                moved = True
    return changes


def next_view(plan):
    groups = {"ready": "running", "confirm": "awaiting_confirm", "waiting_user": "waiting_user",
              "review": "review", "blocked": "blocked", "failed": "failed"}
    out = {k: [t["id"] for t in plan["todos"] if t["state"] == s] for k, s in groups.items()}
    out["runnable"] = runnable(plan)
    out["status"] = plan.get("status", "active")
    out["approved"] = bool(plan.get("approved"))
    out["finished"] = all(t["state"] in SATISFIED for t in plan["todos"])
    out["accepted"] = bool(plan.get("accepted"))
    # 全 Todo が済んでも、依頼主が受け取るまでは完了ではない（awaiting_accept は依頼主待ち）
    out["awaiting_accept"] = out["finished"] and out["approved"] and out["status"] == "active" and not out["accepted"]
    out["complete"] = out["finished"] and out["accepted"]
    return out


def ingest(plan_path, plan, tr):
    inbox = Path(plan_path).parent / "inbox"
    report = {"applied": [], "rejected": []}
    if not inbox.is_dir():
        return report
    for f in sorted(inbox.glob("*.json")):
        try:
            data = load_json(f)
            apply_input(plan, data, tr)
            write_user_report(Path(plan_path).parent, data)
            dest, key, item = inbox / "done", "applied", f.name
        except (GuildError, KeyError, TypeError, AttributeError) as e:
            dest, key, item = inbox / "rejected", "rejected", {"file": f.name, "reason": str(e)}
        dest.mkdir(exist_ok=True)
        shutil.move(str(f), str(dest / f.name))
        report[key].append(item)
    return report


def write_user_report(qdir, data):
    """依頼主の結果（type が result）を、鑑定士が読める報告 reports/<Todo>-user.md にする。"""
    if data.get("type") != "result":
        return
    rep = Path(qdir) / "reports"
    rep.mkdir(exist_ok=True)
    files = "\n".join(f"- {x}" for x in data.get("files", [])) or "なし"
    result = "できた" if data.get("ok") else "できなかった"
    body = f"## 結果\n{result}\n## メモ\n{data.get('note') or 'なし'}\n## 添付\n{files}\n"
    (rep / f"{data['todo']}-user.md").write_text(body, encoding="utf-8")


def apply_input(plan, data, tr):
    kind = data.get("type")
    tm = todo_map(plan)
    status = plan.get("status", "active")
    # 中止された依頼は、終わったもの。見直し中は、中止以外の入力を受け付けない
    if status == "aborted":
        raise GuildError("中止された依頼には、入力を受け付けません")
    if status == "replan" and not (kind == "decision" and data.get("choice") == "abort"):
        raise GuildError("計画を直し中です。新しい計画ができるまで、入力を受け付けません")
    if kind == "approve":
        if plan.get("approved"):
            raise GuildError("すでに承認されています")
        plan["approved"], plan["status"] = True, "active"
        note(plan, event="approved")
        return
    if kind == "accept":
        if plan.get("accepted"):
            raise GuildError("すでに受け取り済みです")
        if not plan.get("approved") or not all(t["state"] in SATISFIED for t in plan["todos"]):
            raise GuildError("すべての Todo が済むまで、受け取れません")
        plan["accepted"] = True
        note(plan, event="accepted")
        return
    if kind == "decision" and data.get("choice") in ("abort", "replan"):
        plan["status"] = "aborted" if data["choice"] == "abort" else "replan"
        if data["choice"] == "replan":
            plan["approved"] = False
        note(plan, event="decision", choice=data["choice"], comment=data.get("comment", ""))
        return
    t = tm.get(data.get("todo"))
    if t is None:
        raise GuildError(f"todo がありません: {data.get('todo')}")
    if kind == "confirm":
        apply_event(t, "confirmed" if data["ok"] else "declined", tr, plan)
    elif kind == "result":
        apply_event(t, "submitted" if data["ok"] else "reported_failed", tr, plan)
        t["output"] = {"note": data.get("note", ""), "files": data.get("files", [])}
    elif kind == "decision" and data.get("choice") == "skip":
        apply_event(t, "skip", tr, plan)
    elif kind == "decision" and data.get("choice") == "drop":
        # 失敗した Todo と、それに(間接にでも)依存する後続をやめる。後続は実行しない
        apply_event(t, "skip", tr, plan)
        dropped, grew = {t["id"]}, True
        while grew:
            grew = False
            for u in plan["todos"]:
                if u["id"] not in dropped and any(d in dropped for d in u.get("deps", [])):
                    dropped.add(u["id"])
                    grew = True
        for u in plan["todos"]:
            if u["id"] in dropped and u["state"] in ("pending", "blocked"):
                note(plan, id=u["id"], event="dropped", **{"from": u["state"], "to": "skipped"})
                u["state"] = "skipped"
    else:
        raise GuildError(f"入力が不正です: {kind} {data.get('choice', '')}")


def adopt(plan_path, tr):
    """reports/plan-draft.json（地図師の分解結果）を検査し、未承認の plan.json にする。"""
    plan_path = Path(plan_path)
    draft_path = plan_path.parent / "reports" / "plan-draft.json"
    if not draft_path.exists():
        raise GuildError(f"{draft_path} がありません")
    old = None
    if plan_path.exists():
        old = load_json(plan_path)
        if old.get("status") != "replan":
            raise GuildError(f"{plan_path} がすでにあります（上書きしません。やり直すには replan の判断が要ります）")
    draft = load_json(draft_path)
    todos = draft.get("todos")
    if not isinstance(todos, list):
        raise GuildError("plan-draft.json に todos がありません")
    template = draft.get("template")
    if template:
        # テンプレートは guild/templates/ の中のファイルだけ（外を指せない）
        parts = str(template).replace("\\", "/").split("/")
        tpl = plan_path.parent.parent / str(template)
        if len(parts) != 2 or parts[0] != "templates" or parts[1] in ("", ".", "..") or not tpl.is_file():
            raise GuildError(f"template が不正か、見つかりません: {template}")
    plan = {"quest": draft.get("quest"), "title": draft.get("title"), "approved": False,
            "status": "active", "format": draft.get("format", "md"), **({"template": template} if template else {}), "todos": [], "history": [{"t": now(), "event": "adopted"}]}
    for t in todos:
        if not isinstance(t, dict):
            raise GuildError("todos の要素が不正です")
        item = dict(t, deps=list(t.get("deps", [])), state=tr["initial"], retries=0, output=None)
        plan["todos"].append(item)
    errs = validate(plan, tr)
    if errs:
        raise GuildError("plan-draft.json の検査に失敗しました: " + " / ".join(errs))
    carried = []
    if old is not None:
        shutil.copy2(plan_path, plan_path.with_name("plan.prev.json"))
        carried = carry_over(plan, old, plan_path.parent)
    save_plan(plan_path, plan)
    return {"adopted": len(plan["todos"]), "replaced": old is not None, "carried": carried}


def carry_over(plan, old, qdir):
    """計画の作り直し。番号・種別・題名・合格基準が同じで、完了済みの Todo は、状態を引き継ぐ。
    経緯（history）は旧計画のものに追記する。引き継がない Todo の成果物と報告は、prev/ へ退避する。"""
    same = lambda a, b: all(a.get(k) == b.get(k) for k in ("kind", "title", "criteria"))
    new_by = {t["id"]: t for t in plan["todos"]}
    carried = []
    for o in old.get("todos", []):
        n = new_by.get(o["id"])
        if n is not None and o.get("state") == "done" and same(o, n):
            n["state"], n["retries"], n["output"] = "done", o.get("retries", 0), o.get("output")
            carried.append(o["id"])
    plan["history"] = list(old.get("history", [])) + [{"t": now(), "event": "replanned", "carried": carried}]
    arch = Path(qdir) / "prev" / datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    for o in old.get("todos", []):
        if o["id"] in carried:
            continue
        out = Path(qdir) / "output" / o["id"]
        if out.is_dir():
            (arch / "output").mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(arch / "output" / o["id"]))
        for f in sorted((Path(qdir) / "reports").glob(f"{o['id']}-*")):
            (arch / "reports").mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(arch / "reports" / f.name))
    return carried


def init_guild(root):
    """ROOT/guild/ を作り、この Python のパスを config.json に記録する。何度実行しても、既存の依頼は消さない。"""
    gdir = Path(root) / "guild"
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "knowledge").mkdir(exist_ok=True)
    (gdir / "requests").mkdir(exist_ok=True)
    board = HERE / "board.html"
    if board.exists():
        shutil.copy2(board, gdir / "board.html")  # ボードはプラグイン側が正本。init のたびに最新に置き換える
    cfg_path = gdir / "config.json"
    cfg = load_json(cfg_path) if cfg_path.exists() else {}
    cfg["python"] = sys.executable
    cfg["python_version"] = ".".join(map(str, sys.version_info[:3]))
    save_plan(cfg_path, cfg)
    return {"guild": str(gdir), "python": cfg["python"], "python_version": cfg["python_version"],
            "board": str(gdir / "board.html") if board.exists() else None}


REQUEST_ID = re.compile(r"^R[0-9][0-9-]*$")


def list_requests(root):
    """ROOT/guild/requests/ にある、受付待ちの依頼（ボードが保存したもの）を古い順に返す。"""
    rdir = Path(root) / "guild" / "requests"
    out = []
    if rdir.is_dir():
        for f in sorted(rdir.glob("R*.json")):
            try:
                d = load_json(f)
            except GuildError:
                continue
            out.append({"id": f.stem, "text": d.get("text", ""), "due": d.get("due"), "format": d.get("format", "md"), "template": d.get("template"), "files": d.get("files", [])})
    return out


def new_quest(root, request_id=None):
    """ROOT/guild/ に次の依頼のフォルダ（Q001, Q002, …）を作る。request_id があれば、その受付待ちの依頼を取り込む。"""
    gdir = Path(root) / "guild"
    if not (gdir / "config.json").exists():
        raise GuildError(f"{gdir} がありません（/guild:init を先に実行してください）")
    src = None
    if request_id is not None:
        if not REQUEST_ID.match(request_id):
            raise GuildError(f"依頼の ID が不正です: {request_id}")
        src = gdir / "requests" / f"{request_id}.json"
        if not src.exists():
            raise GuildError(f"{src} がありません")
    nums = [int(p.name[1:]) for p in gdir.iterdir() if p.is_dir() and p.name[:1] == "Q" and p.name[1:].isdigit()]
    qdir = gdir / f"Q{max(nums, default=0) + 1:03d}"
    for sub in ("reports", "output", "inbox"):
        (qdir / sub).mkdir(parents=True)
    out = {"quest": qdir.name, "dir": str(qdir), "plan": str(qdir / "plan.json")}
    if src is not None:
        out["request"] = load_json(src)
        shutil.move(str(src), str(qdir / "request.json"))
        files = gdir / "requests" / "files" / request_id
        if files.is_dir():
            shutil.move(str(files), str(qdir / "inputs"))
            out["inputs"] = str(qdir / "inputs")
    return out


def arrivals(root):
    """依頼主がボードから送ったが、まだ取り込んでいないものを返す（inbox の JSON と、受付待ちの依頼）。"""
    gdir = Path(root) / "guild"
    out = []
    if gdir.is_dir():
        for q in sorted(gdir.glob("Q[0-9]*")):
            inbox = q / "inbox"
            if inbox.is_dir():
                for f in sorted(inbox.glob("*.json")):
                    out.append({"kind": "inbox", "quest": q.name, "file": f.name})
        req = gdir / "requests"
        if req.is_dir():
            for f in sorted(req.glob("R*.json")):
                try:
                    load_json(f)
                except GuildError:
                    continue  # 読めない依頼は数えない（list_requests と同じ）
                out.append({"kind": "request", "id": f.stem})
    return out


def wait_for(root, seconds, interval=1.0):
    """依頼主の入力（または新しい依頼）が届くまで待つ。すでに届いていれば、すぐ返す。"""
    start = time.monotonic()
    while True:
        a = arrivals(root)
        waited = round(time.monotonic() - start, 1)
        if a:
            return {"arrived": a, "waited": waited, "timeout": False}
        if waited >= seconds:
            return {"arrived": [], "waited": waited, "timeout": True}
        time.sleep(interval)


def take_answers(qdir):
    """計画がまだない依頼の inbox から、質問への回答（type が answers）を取り出して done/ に移す。"""
    inbox = Path(qdir) / "inbox"
    got = []
    if inbox.is_dir():
        for f in sorted(inbox.glob("*.json")):
            try:
                d = load_json(f)
                ok = isinstance(d, dict) and d.get("type") == "answers"
            except GuildError:
                ok = False  # 壊れたファイル
            # 取り出せなかったものは rejected/ へ。残すと wait が待たずに返り続ける
            dest = inbox / ("done" if ok else "rejected")
            dest.mkdir(exist_ok=True)
            shutil.move(str(f), str(dest / f.name))
            if ok:
                got.append(d)
    return got


def main(argv):
    if len(argv) < 3 or argv[1] not in ("validate", "sync", "next", "ingest", "advance", "adopt", "init", "new", "requests", "wait", "arrivals", "answers"):
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    try:
        if cmd in ("wait", "arrivals", "answers"):
            if cmd == "wait":
                result = wait_for(path, float(argv[3]) if len(argv) > 3 else 540)
            elif cmd == "arrivals":
                result = arrivals(path)
            else:
                result = take_answers(path)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if cmd in ("init", "new", "requests"):
            if cmd == "init":
                result = init_guild(path)
            elif cmd == "requests":
                result = list_requests(path)
            else:
                result = new_quest(path, argv[3] if len(argv) > 3 else None)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if cmd == "adopt":
            print(json.dumps(adopt(path, load_transitions()), ensure_ascii=False))
            return 0
        plan, tr = load_json(path), load_transitions()
        if cmd == "validate":
            errs = validate(plan, tr)
            print(json.dumps({"ok": not errs, "errors": errs}, ensure_ascii=False))
            return 1 if errs else 0
        errs = validate(plan, tr)
        if errs:
            raise GuildError("plan.json の検査に失敗しました: " + " / ".join(errs))
        if cmd == "next":
            print(json.dumps(next_view(plan), ensure_ascii=False))
            return 0
        if cmd == "sync":
            result = sync(plan, tr)
        elif cmd == "advance":
            if len(argv) != 5:
                raise GuildError("advance PLAN ID EVENT の形で指定してください")
            t = todo_map(plan).get(argv[3])
            if t is None:
                raise GuildError(f"todo がありません: {argv[3]}")
            apply_event(t, argv[4], tr, plan)
            result = {"id": t["id"], "state": t["state"]}
        else:
            result = ingest(path, plan, tr)
        save_plan(path, plan)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if cmd == "ingest" and result["rejected"] else 0
    except GuildError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # Windows の既定（cp932）だと呼び出し側が読めない
    sys.exit(main(sys.argv))

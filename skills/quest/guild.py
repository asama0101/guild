#!/usr/bin/env python3
"""guild の実行エンジン（標準ライブラリだけ）。

plan.json を書けるのはこのファイルだけ。遷移は transitions.json で決め、定義にない遷移はエラー。
使い方: guild.py {adopt|validate|sync|next|ingest} PLAN / guild.py advance PLAN ID EVENT
adopt は PLAN と同じフォルダの reports/plan-draft.json から PLAN を作る（承認前の状態で）。
エラーは終了コード 1。
"""
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
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


def apply_event(todo, event, tr):
    for t in effective(tr, todo["kind"]):
        if t["from"] == todo["state"] and t["event"] == event and guard_ok(t.get("guard"), todo, tr):
            if event == "rejected" and t["to"] != "failed":
                todo["retries"] = todo.get("retries", 0) + 1
            todo["state"] = t["to"]
            return t["to"]
    raise GuildError(f"{todo['id']}: 状態 {todo['state']} では {event} できません")


def validate(plan, tr):
    errs = []
    todos = plan.get("todos")
    if not isinstance(todos, list) or not todos:
        return ["todos がありません"]
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
                apply_event(t, event, tr)
                changes.append({"id": t["id"], "event": event, "from": before, "to": t["state"]})
                moved = True
    return changes


def next_view(plan):
    groups = {"ready": "running", "confirm": "awaiting_confirm", "waiting_user": "waiting_user",
              "review": "review", "blocked": "blocked", "failed": "failed"}
    out = {k: [t["id"] for t in plan["todos"] if t["state"] == s] for k, s in groups.items()}
    out["runnable"] = runnable(plan)
    out["finished"] = all(t["state"] in SATISFIED for t in plan["todos"])
    return out


def ingest(plan_path, plan, tr):
    inbox = Path(plan_path).parent / "inbox"
    report = {"applied": [], "rejected": []}
    if not inbox.is_dir():
        return report
    for f in sorted(inbox.glob("*.json")):
        try:
            apply_input(plan, load_json(f), tr)
            dest, key, item = inbox / "done", "applied", f.name
        except (GuildError, KeyError, TypeError, AttributeError) as e:
            dest, key, item = inbox / "rejected", "rejected", {"file": f.name, "reason": str(e)}
        dest.mkdir(exist_ok=True)
        shutil.move(str(f), str(dest / f.name))
        report[key].append(item)
    return report


def apply_input(plan, data, tr):
    kind = data.get("type")
    tm = todo_map(plan)
    if kind == "approve":
        plan["approved"], plan["status"] = True, "active"
        return
    if kind == "decision" and data.get("choice") in ("abort", "replan"):
        plan["status"] = "aborted" if data["choice"] == "abort" else "replan"
        if data["choice"] == "replan":
            plan["approved"] = False
        return
    t = tm.get(data.get("todo"))
    if t is None:
        raise GuildError(f"todo がありません: {data.get('todo')}")
    if kind == "confirm":
        apply_event(t, "confirmed" if data["ok"] else "declined", tr)
    elif kind == "result":
        apply_event(t, "submitted" if data["ok"] else "reported_failed", tr)
        t["output"] = {"note": data.get("note", ""), "files": data.get("files", [])}
    elif kind == "decision" and data.get("choice") == "skip":
        apply_event(t, "skip", tr)
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
    plan = {"quest": draft.get("quest"), "title": draft.get("title"), "approved": False,
            "status": "active", "todos": []}
    for t in todos:
        if not isinstance(t, dict):
            raise GuildError("todos の要素が不正です")
        item = dict(t, deps=list(t.get("deps", [])), state=tr["initial"], retries=0, output=None)
        plan["todos"].append(item)
    errs = validate(plan, tr)
    if errs:
        raise GuildError("plan-draft.json の検査に失敗しました: " + " / ".join(errs))
    if old is not None:
        shutil.copy2(plan_path, plan_path.with_name("plan.prev.json"))
    save_plan(plan_path, plan)
    return {"adopted": len(plan["todos"]), "replaced": old is not None}


def main(argv):
    if len(argv) < 3 or argv[1] not in ("validate", "sync", "next", "ingest", "advance", "adopt"):
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    try:
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
            apply_event(t, argv[4], tr)
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

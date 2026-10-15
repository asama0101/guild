#!/usr/bin/env python3
"""guild の実行エンジン（標準ライブラリだけ）。

plan.json を書けるのはこのファイルだけ。遷移は transitions.json で決め、定義にない遷移はエラー。
使い方: guild.py {adopt|validate|sync|next|ingest} PLAN / guild.py advance PLAN ID EVENT
adopt は PLAN と同じフォルダの reports/plan-draft.json から PLAN を作る（承認前の状態で）。inputs・candidates の名前が guild/inputs/ になければエラー。
guild.py init ROOT: ROOT/guild/ と config.json（この Python のパス）を作る。
guild.py new ROOT [R…]: ROOT/guild/.work/ に次の依頼のフォルダ（Q001…）を作る。R… を渡すと、ボードが保存した受付待ちの依頼を取り込む（選んだインプットが guild/inputs/ になければ、依頼を .work/requests/rejected/ へ移して拒否する）。
guild.py requests ROOT: 受付待ちの依頼を一覧する。
guild.py inputs-list ROOT [--text 依頼文]: guild/inputs/ のファイル（名前・拡張子・大きさ・更新日・文字のファイルの先頭5行）と、依頼文に出てくる書庫の項目からのヒントを一覧する（地図師に渡す）。
guild.py close ROOT: 完了・中止した依頼のインプットのバックアップを消す。
guild.py arrivals ROOT: ボードから届いて、まだ取り込んでいない入力と依頼を一覧する。
guild.py wait ROOT [秒]: 届くまで待つ（既定 540 秒）。届いていれば、すぐ返す。
guild.py answers QDIR: 計画がない依頼の、質問への回答（type が answers）を取り出す。
guild.py publish QDIR: 納品物を guild/deliverables/ へコピーする（全 Todo が済んだとき）。
guild.py archive-propose QDIR: 司書の候補（reports/archive-draft.json）を検査し、心得を登録して、残りを依頼主の確認待ち（archive.json）にする。
guild.py archive-ingest ROOT: .work/archive-inbox/ の入力（entry・promote・deprecate・retype）を書庫に反映する。
guild.py web-ingest ROOT: .work/web/inbox/ の依頼主の答え（WebFetch の許可・不許可、許可リストの追加・削除）を反映する。
guild.py web-pending ROOT: 冒険者が止められて、依頼主の答え待ちのドメインを一覧する。
guild.py web-reset ROOT: 「今回だけ」の許可と、許可しなかった記録を空にする（依頼の完了・中止のとき）。
入力（inbox の JSON）の type の1つに due（依頼の開始日・締切、Todo の予定日・締切の設定。Todo の締切だけ解除できる）がある。
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
sys.path.insert(0, str(HERE))
import webaccess  # noqa: E402

WORK = webaccess.WORK


def work_dir(gdir):
    """機械用・作業用のフォルダ。依頼（Q###）、受付待ちの依頼、外部サイトの許可、書庫の入力、インプットのバックアップを置く。"""
    return Path(gdir) / WORK


def gdir_of(qdir):
    """依頼のフォルダ（guild/.work/Q001）から guild/ を返す。"""
    return Path(qdir).parent.parent

SATISFIED = ("done", "skipped")
PROMPT_SUFFIX = ".prompt.md"  # Markdown 以外（PowerPoint・Excel など）が要るときの、Claude Code に渡すプロンプトのファイル名
CRITERIA_KEYS = ("viewpoint", "pass_line", "check")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_date(v, label):
    """日付は YYYY-MM-DD の実在する日か None。"""
    if v is None:
        return None
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise GuildError(f"{label} は YYYY-MM-DD の日付か null にしてください: {v!r}")
    try:
        datetime.date.fromisoformat(v)
    except ValueError:
        raise GuildError(f"{label} が実在しない日付です: {v}")
    return v


def check_due(v):
    return check_date(v, "due")


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
    for k in ("start", "due"):
        try:
            check_date(plan.get(k), k)
        except GuildError as e:
            errs.append(str(e))
    errs += check_plan_inputs(plan)
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
        for k in ("scheduled", "due"):
            try:
                check_date(t.get(k), k)
            except GuildError as e:
                errs.append(f"{i}: {e}")
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
            if isinstance(data, dict) and data.get("type") == "archive":
                archive_decide(Path(plan_path).parent, data)  # 書庫の確認は、中止された依頼でも受け付ける
            else:
                apply_input(plan, data, tr)
                write_user_report(Path(plan_path).parent, data)
                qdir = Path(plan_path).parent
                if data.get("type") == "accept":
                    publish_deliverables(qdir, plan)  # 受け取ったら、納品物が必ず置かれている（何度でも同じ）
                elif data.get("type") == "decision" and data.get("choice") in ("abort", "replan"):
                    unpublish_deliverables(qdir)  # 中止なら納品物はない。見直しなら古いものは使えない
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
    files = "\n".join(f"- [[{x}]]" for x in data.get("files", [])) or "なし"
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
    if kind == "due":
        apply_dates(plan, data)
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


def apply_dates(plan, data):
    """日付の設定。todo があれば Todo の scheduled / due、なければ依頼の start / due。"""
    keys = [k for k in ("start", "due", "scheduled") if k in data]
    todo = None
    if data.get("todo") is not None:
        todo = todo_map(plan).get(data["todo"])
        if todo is None:
            raise GuildError(f"todo がありません: {data.get('todo')}")
    allowed = ("scheduled", "due") if todo is not None else ("start", "due")
    if not keys or any(k not in allowed for k in keys):
        raise GuildError(f"日付の入力が不正です: {keys or '日付なし'}")
    new = {}
    for k in keys:
        v = check_date(data[k], k)
        if v is None and not (k == "due" and todo is not None):  # 解除できるのは Todo の締切だけ
            raise GuildError(f"{k} は解除できません")
        new[k] = v
    (todo if todo is not None else plan).update(new)
    note(plan, event="due", **({"todo": todo["id"]} if todo is not None else {}), **new)


def quest_dates(qdir, old=None):
    """依頼の開始日・締切。作り直し（replan）のときは旧計画の値、なければ request.json の値、なければ今日。締切が未定なら開始日。"""
    req_path = Path(qdir) / "request.json"
    req = load_json(req_path) if req_path.exists() else {}
    old = old or {}
    start = old.get("start") or req.get("start") or today()
    due = old.get("due") or req.get("due") or start
    return {"start": start, "due": due}


INPUT_SOURCES = ("user", "auto")  # 依頼主の指定 / 地図師の選択


def request_inputs(qdir):
    """request.json の inputs（依頼主の指定。new が検査済み）。なければ []。"""
    req_path = Path(qdir) / "request.json"
    req = load_json(req_path) if req_path.exists() else {}
    names = req.get("inputs", []) if isinstance(req, dict) else []
    return unique_names([n for n in names if isinstance(n, str) and n]) if isinstance(names, list) else []


def user_removed(old):
    """旧計画の履歴（event が inputs）を順にたどり、依頼主が外したまま（後で足し直していない）名前を小文字で返す。"""
    removed = set()
    for h in (old or {}).get("history", []):
        if isinstance(h, dict) and h.get("event") == "inputs":
            removed |= {str(n).lower() for n in h.get("remove", [])}
            removed -= {str(n).lower() for n in h.get("add", [])}
    return removed


def selected_inputs(qdir, draft, old=None):
    """plan.json の inputs と candidates を決める。
    依頼主の指定（request.json の inputs。source=user）が先頭で、地図師の選択（plan-draft.json の inputs。source=auto）を後ろに足す。
    作り直し（replan）では、旧計画の inputs（依頼主の追加・外すを反映済み）を引き継ぎ、依頼主が外したままの名前は足さない。
    地図師が書いた名前は guild/inputs/ にあること（なければエラー。地図師に差し戻す）。"""
    have = existing_inputs(gdir_of(qdir))

    def drafted(key):
        items = draft.get(key, [])
        if not isinstance(items, list):
            raise GuildError(f"plan-draft.json の {key} は配列にしてください")
        out = []
        for x in items:
            if not isinstance(x, dict) or not one_line(x.get("reason")):
                raise GuildError(f"plan-draft.json の {key} の各要素には name と reason（理由）を書いてください: {x!r}")
            check_input_name(x.get("name"), f"plan-draft.json の {key}")
            actual = have.get(x["name"].lower())
            if actual is None:
                raise GuildError(f"plan-draft.json の {key} の {x['name']} が guild/inputs/ にありません")
            out.append({"name": actual, "reason": one_line(x["reason"])})
        return out

    auto, cands = drafted("inputs"), drafted("candidates")
    if old is not None and isinstance(old.get("inputs"), list):
        chosen = [dict(x) for x in old["inputs"]]
    else:
        chosen = [{"name": n, "source": "user", "reason": "依頼主の指定"} for n in request_inputs(qdir)]
    removed = user_removed(old)
    seen = {x["name"].lower() for x in chosen}
    for x in auto:
        if x["name"].lower() not in seen and x["name"].lower() not in removed:
            chosen.append({"name": x["name"], "source": "auto", "reason": x["reason"]})
            seen.add(x["name"].lower())
    candidates = []
    for x in cands:
        if x["name"].lower() not in seen:
            candidates.append(x)
            seen.add(x["name"].lower())
    return chosen, candidates


def check_plan_inputs(plan):
    """plan.json の inputs・candidates の形を検査する（存在は adopt と ingest が見る）。名前は両方をまたいで重ならない。"""
    errs, seen = [], set()
    for key in ("inputs", "candidates"):
        items = plan.get(key, [])
        if not isinstance(items, list):
            errs.append(f"{key} は配列にしてください")
            continue
        for x in items:
            if not isinstance(x, dict):
                errs.append(f"{key} の要素が不正です: {x!r}")
                continue
            try:
                check_input_name(x.get("name"), key)
            except GuildError as e:
                errs.append(str(e))
                continue
            if key == "inputs" and x.get("source") not in INPUT_SOURCES:
                errs.append(f"inputs の {x['name']} の source が不正です: {x.get('source')}")
            if not isinstance(x.get("reason"), str):
                errs.append(f"{key} の {x['name']} に reason がありません")
            if x["name"].lower() in seen:
                errs.append(f"{key} の {x['name']} が重なっています")
            seen.add(x["name"].lower())
    return errs


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
    inputs, candidates = selected_inputs(plan_path.parent, draft, old)  # 何も書く前に検査する（落ちたら地図師に差し戻す）
    plan = {"quest": draft.get("quest"), "title": draft.get("title"), "approved": False, "status": "active",
            **({"archive_used": [str(x) for x in draft["archive_used"]]} if isinstance(draft.get("archive_used"), list) else {}),
            "inputs": inputs, "candidates": candidates,
            "todos": [], "history": [{"t": now(), "event": "adopted"}]}
    plan.update(quest_dates(plan_path.parent, old))
    for t in todos:
        if not isinstance(t, dict):
            raise GuildError("todos の要素が不正です")
        item = dict(t, deps=list(t.get("deps", [])), state=tr["initial"], retries=0, output=None)
        item["scheduled"] = item.get("scheduled") or plan["start"]
        item["due"] = item.get("due") or plan["due"]
        plan["todos"].append(item)
    errs = validate(plan, tr)
    if errs:
        raise GuildError("plan-draft.json の検査に失敗しました: " + " / ".join(errs))
    carried = []
    if old is not None:
        shutil.copy2(plan_path, plan_path.with_name("plan.prev.json"))
        unpublish_deliverables(plan_path.parent)  # 作り直し。置いた納品物は、また全 Todo が済んだ時に置き直す
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
    init_archive(gdir / "archive")
    (work_dir(gdir) / "requests").mkdir(parents=True, exist_ok=True)
    for sub in (INPUTS, DELIV):
        (gdir / sub).mkdir(exist_ok=True)
    board = HERE / "board.html"
    if board.exists():
        shutil.copy2(board, gdir / "board.html")  # ボードはプラグイン側が正本。init のたびに最新に置き換える
    cfg_path = gdir / "config.json"
    cfg = load_json(cfg_path) if cfg_path.exists() else {}
    cfg["python"] = sys.executable
    cfg["python_version"] = ".".join(map(str, sys.version_info[:3]))
    cfg["root"] = str(Path(root).resolve())  # ボードが、パスをフルパスでコピーするために使う
    save_plan(cfg_path, cfg)
    return {"guild": str(gdir), "root": cfg["root"], "python": cfg["python"], "python_version": cfg["python_version"],
            "board": str(gdir / "board.html") if board.exists() else None}


REQUEST_ID = re.compile(r"^R[0-9][0-9-]*$")


def list_requests(root):
    """ROOT/guild/.work/requests/ にある、受付待ちの依頼（ボードが保存したもの）を古い順に返す。"""
    rdir = work_dir(Path(root) / "guild") / "requests"
    out = []
    if rdir.is_dir():
        for f in sorted(rdir.glob("R*.json")):
            try:
                d = load_json(f)
            except GuildError:
                continue
            out.append({"id": f.stem, "text": d.get("text", ""), "start": d.get("start"), "due": d.get("due"),
                        "inputs": d.get("inputs", []), "files": d.get("files", [])})
    return out


INPUTS = "inputs"
INPUT_NAME_BAD = re.compile(r"[\\/:\x00-\x1f\x7f]")  # パス区切り・ドライブの「:」・制御文字


def check_input_name(n, label):
    """インプットの名前（guild/inputs/ の直下のファイル名）の形だけを検査する。存在は見ない。日本語・空白は通す。"""
    if (not isinstance(n, str) or not n.strip() or n != n.strip() or n in (".", "..")
            or INPUT_NAME_BAD.search(n) or len(n) > 255):
        raise GuildError(f"{label} のファイル名が不正です: {n!r}")
    return n


def unique_names(names):
    """名前の重なりを除く（大文字小文字は区別しない。最初のものを残し、順序は保つ）。"""
    out, seen = [], set()
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def existing_inputs(gdir):
    """guild/inputs/ の直下のファイルを {小文字の名前: 実際の名前} で返す（同一判定は大文字小文字を区別しない）。"""
    d = Path(gdir) / INPUTS
    return {p.name.lower(): p.name for p in d.iterdir() if p.is_file()} if d.is_dir() else {}


def picked_inputs(gdir, req, files_dir):
    """依頼主が既存のインプットから選んだ名前（依頼の inputs）を検査し、guild/inputs/ の実際の名前にして返す。
    同じ依頼でアップロードしたファイルの名前なら、まだ guild/inputs/ になくてもよい（取り込みで置かれる）。"""
    if not isinstance(req, dict):
        raise GuildError("依頼の形が不正です")
    picked = req.get("inputs", [])
    if not isinstance(picked, list):
        raise GuildError("依頼の inputs は、ファイル名の配列にしてください")
    have = existing_inputs(gdir)
    fdir = Path(files_dir)
    uploaded = {p.name.lower(): p.name for p in fdir.iterdir() if p.is_file()} if fdir.is_dir() else {}
    out = []
    for n in picked:
        check_input_name(n, "依頼の inputs")
        actual = have.get(n.lower()) or uploaded.get(n.lower())
        if actual is None:
            raise GuildError(f"選んだインプットが guild/inputs/ にありません（削除された可能性があります）: {n}")
        out.append(actual)
    return unique_names(out)


def reject_request(wdir, request_id, reason):
    """受け付けられない依頼を .work/requests/rejected/ へ移し、理由を <ID>.json.reason.txt に残す。添付も rejected/files/<ID>/ へ移す。
    requests/ に残すと、arrivals が「届いた」と返し続けるため。"""
    rdir = Path(wdir) / "requests"
    dest = rdir / "rejected"
    dest.mkdir(parents=True, exist_ok=True)
    os.replace(rdir / f"{request_id}.json", dest / f"{request_id}.json")
    (dest / f"{request_id}.json.reason.txt").write_text(reason, encoding="utf-8")
    files = rdir / "files" / request_id
    if files.is_dir():
        target = dest / "files" / request_id
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(exist_ok=True)
        shutil.move(str(files), str(target))


def import_inputs(gdir, files_dir, quest):
    """依頼の素材を guild/inputs/ に取り込む（共通の置き場に1つだけ）。
    ファイル名（大文字小文字は区別しない）が同じなら同じもの。内容が同じなら何もせず、違えば上書きする。
    上書き前の版は .work/backup/<依頼>/ に残す（その依頼で最初に上書きする版だけ。依頼が閉じたら close で消す）。"""
    inputs = Path(gdir) / INPUTS
    inputs.mkdir(parents=True, exist_ok=True)
    names = []
    for src in sorted(Path(files_dir).iterdir()):
        if not src.is_file():
            continue  # サブフォルダは取り込まない
        existing = {p.name.lower(): p for p in inputs.iterdir() if p.is_file()}
        dest = existing.get(src.name.lower(), inputs / src.name)
        if dest.exists():
            if dest.read_bytes() != src.read_bytes():
                bak = work_dir(gdir) / "backup" / quest
                bak.mkdir(parents=True, exist_ok=True)
                if not (bak / dest.name).exists():
                    shutil.copy2(dest, bak / dest.name)
                shutil.copy2(src, dest)
        else:
            shutil.copy2(src, dest)
        names.append(dest.name)
    return names


def close_quests(root):
    """閉じた依頼（受け取り済み、または中止）のインプットのバックアップを消す。進行中の依頼のものは残す。"""
    wdir = work_dir(Path(root) / "guild")
    removed = []
    for q in sorted(wdir.glob("Q[0-9]*")):
        bak, plan_path = wdir / "backup" / q.name, q / "plan.json"
        if not bak.is_dir() or not plan_path.exists():
            continue
        plan = load_json(plan_path)
        if plan.get("accepted") or plan.get("status") == "aborted":
            shutil.rmtree(bak)
            removed.append(q.name)
    return {"removed": removed}


DELIV = "deliverables"


def deliverable_files(qdir, plan):
    """納品物にするファイルを (Todo の id, パス) で返す。合格（done）した Todo の、
    deliverable の印がある Todo の .md と、どの Todo でも *.prompt.md。印のある Todo が1つもなければ、done の Todo すべての .md。"""
    marked = {t["id"] for t in plan["todos"] if t.get("deliverable")} or {t["id"] for t in plan["todos"]}
    for t in plan["todos"]:
        d = Path(qdir) / "output" / t["id"]
        if t.get("state") != "done" or not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            if f.is_file() and (t["id"] in marked or f.name.lower().endswith(PROMPT_SUFFIX)):
                yield t["id"], f


def unpublish_deliverables(qdir):
    """この依頼の納品物（deliverables/Q###_*）を消す。ほかの依頼のものは消さない。"""
    qdir = Path(qdir)
    d = gdir_of(qdir) / DELIV
    removed = []
    if d.is_dir():
        for f in sorted(d.glob(f"{qdir.name}_*")):
            if f.is_file():
                f.unlink()
                removed.append(f.name)
    return removed


def publish_deliverables(qdir, plan=None):
    """納品物を .work/Q###/output/ から guild/deliverables/ へコピーする（Obsidian でも読めるように）。何度実行しても同じ結果。
    plan を渡すと、ディスクの plan.json の代わりにそれを使う（ingest が保存前の状態で呼ぶため）。"""
    qdir = Path(qdir)
    if plan is None:
        plan = load_json(qdir / "plan.json")
    unpublish_deliverables(qdir)
    dest = gdir_of(qdir) / DELIV
    dest.mkdir(exist_ok=True)
    used, names = set(), []
    for tid, f in deliverable_files(qdir, plan):
        name = f"{qdir.name}_{f.name}"
        if name in used:
            name = f"{qdir.name}_{tid}_{f.name}"
        used.add(name)
        shutil.copy2(f, dest / name)
        names.append(name)
    return {"published": names}


def new_quest(root, request_id=None):
    """ROOT/guild/.work/ に次の依頼のフォルダ（Q001, Q002, …）を作る。request_id があれば、その受付待ちの依頼を取り込む。
    依頼の inputs（依頼主が既存から選んだ名前）が guild/inputs/ になければ、依頼を requests/rejected/ へ移して拒否する（番号は進まない）。
    request.json の inputs は、選んだ名前と、取り込んだアップロードの名前を合わせたもの（重なりを除き、選んだものが先）。"""
    gdir = Path(root) / "guild"
    if not (gdir / "config.json").exists():
        raise GuildError(f"{gdir} がありません（/guild:init を先に実行してください）")
    wdir = work_dir(gdir)
    wdir.mkdir(exist_ok=True)
    src = req = files = None
    picked = []
    if request_id is not None:
        if not REQUEST_ID.match(request_id):
            raise GuildError(f"依頼の ID が不正です: {request_id}")
        src = wdir / "requests" / f"{request_id}.json"
        if not src.exists():
            raise GuildError(f"{src} がありません")
        req = load_json(src)
        files = wdir / "requests" / "files" / request_id
        try:
            picked = picked_inputs(gdir, req, files)
        except GuildError as e:
            reject_request(wdir, request_id, str(e))
            raise
    nums = [int(p.name[1:]) for p in wdir.iterdir() if p.is_dir() and p.name[:1] == "Q" and p.name[1:].isdigit()]
    qdir = wdir / f"Q{max(nums, default=0) + 1:03d}"
    for sub in ("reports", "output", "inbox"):
        (qdir / sub).mkdir(parents=True)
    out = {"quest": qdir.name, "dir": str(qdir), "plan": str(qdir / "plan.json")}
    if src is not None:
        shutil.move(str(src), str(qdir / "request.json"))
        names = []
        if files.is_dir():
            names = import_inputs(gdir, files, qdir.name)
            shutil.rmtree(files)
        req["inputs"] = unique_names(picked + names)
        save_plan(qdir / "request.json", req)  # JSON を原子的に書く関数（plan 専用の名前だが中身は汎用）
        out["request"], out["inputs"], out["inputs_dir"] = req, req["inputs"], str(gdir / INPUTS)
    return out


def arrivals(root):
    """依頼主がボードから送ったが、まだ取り込んでいないものを返す（inbox の JSON と、受付待ちの依頼）。"""
    gdir = Path(root) / "guild"
    wdir = work_dir(gdir)
    out = []
    if wdir.is_dir():
        for q in sorted(wdir.glob("Q[0-9]*")):
            inbox = q / "inbox"
            if inbox.is_dir():
                for f in sorted(inbox.glob("*.json")):
                    out.append({"kind": "inbox", "quest": q.name, "file": f.name})
        req = wdir / "requests"
        if req.is_dir():
            for f in sorted(req.glob("R*.json")):
                try:
                    load_json(f)
                except GuildError:
                    continue  # 読めない依頼は数えない（list_requests と同じ）
                out.append({"kind": "request", "id": f.stem})
        ainbox = wdir / "archive-inbox"
        if ainbox.is_dir():
            for f in sorted(ainbox.glob("*.json")):
                out.append({"kind": "archive", "file": f.name})
        winbox = wdir / "web" / "inbox"
        if winbox.is_dir():
            for f in sorted(winbox.glob("*.json")):
                out.append({"kind": "web", "file": f.name})
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


# ============================================================ 書庫（archive）
ARCHIVE_TYPES = ("term", "flow", "fact", "personal", "lesson")  # 書庫の項目の種類。フォルダは分けず、種類は frontmatter の type で持つ
INDEX_NAME = "index.md"
ARCHIVE_TITLES = {"term": "用語", "flow": "業務フロー", "fact": "業務情報", "personal": "個人"}  # 心得は索引に載せない（役は読まない）
CONFIDENCE = ("guess", "sourced", "confirmed")  # 低い順
ACTIVE_STATUS = ("active", "要確認")
MAX_CANDIDATES = 12
FILE_BAD = re.compile(r'[\\/:*?"<>|\s]+')


def init_archive(adir):
    """archive/ と索引を作る。既存の項目は消さない。"""
    adir = Path(adir)
    adir.mkdir(parents=True, exist_ok=True)
    if not (adir / INDEX_NAME).exists():
        rebuild_index(adir)


def one_line(v):
    return " ".join(str(v or "").split())


def today():
    return datetime.date.today().isoformat()


def read_entry(path):
    """項目のファイルを読む。見出し情報（---で囲んだ key: value）と本文（body）の辞書。読めなければ None。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", text, re.S)
    if not m:
        return None
    e = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep:
            e[k.strip()] = yaml_value(v.strip())
    for k in ("aliases", "inputs"):  # どちらもリストの項目。ない・壊れているときは空
        if not isinstance(e.get(k), list):
            e[k] = []
        e[k] = [str(a).strip() for a in e[k] if str(a).strip()]
    e["body"] = m.group(2)
    e.setdefault("status", "active")
    return e


def yaml_str(v):
    """YAML の二重引用符の文字列にする（JSON の文字列は YAML としても正しい）。コロンや # が入っても崩れない。"""
    return json.dumps(one_line(v), ensure_ascii=False)


def yaml_value(v):
    """見出し情報の値を読む。二重引用符の文字列と [ ] のリストは JSON として、それ以外はそのまま。"""
    if v[:1] in ('"', "["):
        try:
            return json.loads(v)
        except ValueError:
            pass
    return v


def entry_text(e):
    aliases = [one_line(a) for a in e.get("aliases", []) if one_line(a)]
    inputs = [one_line(a) for a in e.get("inputs", []) if one_line(a)]
    head = ["---", f"name: {yaml_str(e['name'])}", f"type: {e['type']}",
            "aliases: " + json.dumps(aliases, ensure_ascii=False),
            "inputs: " + json.dumps(inputs, ensure_ascii=False),
            f"confidence: {e['confidence']}", f"source: {yaml_str(e.get('source'))}", f"confirmed: {e.get('confirmed') or today()}",
            f"status: {yaml_str(e.get('status') or 'active')}", f"summary: {yaml_str(e.get('summary'))}", "---"]
    return "\n".join(head) + "\n" + (e.get("body") or "").strip("\n") + "\n"


def check_entry(e):
    if e.get("type") not in ARCHIVE_TYPES:
        raise GuildError(f"type が不正です: {e.get('type')}（{', '.join(ARCHIVE_TYPES)}）")
    if not one_line(e.get("name")):
        raise GuildError("name がありません")
    if not one_line(e.get("summary")):
        raise GuildError(f"summary がありません: {e.get('name')}")
    if e.get("confidence") not in CONFIDENCE:
        raise GuildError(f"confidence が不正です: {e.get('confidence')}（{', '.join(CONFIDENCE)}）")
    if e["confidence"] != "guess" and not one_line(e.get("source")):
        raise GuildError(f"出典（source）がありません: {e.get('name')}（推測なら confidence を guess にする）")
    inputs = e.get("inputs", [])
    if not isinstance(inputs, list):
        raise GuildError(f"inputs はファイル名の配列にしてください: {e.get('name')}")
    for n in inputs:
        check_input_name(n, f"{one_line(e.get('name'))} の inputs")  # 名前の形だけ。guild/inputs/ にあるかは見ない


def write_entry(adir, e, path=None):
    """項目を書く。path（archive/ からの相対）があれば、そこへ上書き。なければ名前から新しいファイル名を決める。"""
    adir = Path(adir)
    check_entry(e)
    if path is None:
        stem = FILE_BAD.sub("-", one_line(e["name"])).strip("-. ")
        if not stem:
            raise GuildError(f"ファイル名にできない名前です: {e['name']}")
        if stem.lower() == "index":
            stem = "index-項目"  # 索引（index.md）を上書きしない
        n, cand = 1, adir / f"{stem}.md"
        while cand.exists():
            n += 1
            cand = adir / f"{stem}-{n}.md"
        path = cand.name
    target = adir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(entry_text(e), encoding="utf-8")
    return path


def entry_path(adir, rel):
    """archive/ の中の項目（フォルダなしの 名前.md）だけを指せる。索引や、外は指せない。"""
    name = str(rel).replace("\\", "/")
    ok = "/" not in name and ":" not in name and name.endswith(".md") and name.lower() != INDEX_NAME and ".." not in name
    p = Path(adir) / name
    if not ok or not p.is_file():
        raise GuildError(f"項目が見つかりません: {rel}")
    return p


def all_entries(adir):
    for f in sorted(Path(adir).glob("*.md")):
        if f.name == INDEX_NAME:
            continue
        e = read_entry(f)
        if e is not None:
            yield f.name, e


def find_entry(adir, etype, names):
    """同じ種類で、名前か別名が一致する、使われている項目（廃止を除く）を探す。大文字小文字は区別しない。"""
    want = {one_line(n).lower() for n in names if one_line(n)}
    for rel, e in all_entries(adir):
        if e.get("type") != etype or e["status"] not in ACTIVE_STATUS:
            continue
        if want & {one_line(n).lower() for n in [e.get("name"), *e["aliases"]]}:
            return rel
    return None


def rebuild_index(adir):
    """索引（index.md）を作り直す。使われている項目（廃止を除く）だけ。心得は載せない。"""
    adir = Path(adir)
    out = ["# 書庫の索引", "",
           "関係する項目だけ読む。確度は 確認済み／出典あり／推測。推測は断定に使わない。確認日から1年を過ぎた項目は、古い可能性がある。", ""]
    label = {"confirmed": "確認済み", "sourced": "出典あり", "guess": "推測"}
    items = list(all_entries(adir))
    for etype, title in ARCHIVE_TITLES.items():
        rows = [(rel, e) for rel, e in items if e.get("type") == etype and e["status"] in ACTIVE_STATUS]
        out += [f"## {title}", ""]
        if not rows:
            out += ["なし", ""]
            continue
        out += ["| 名前 | 別名 | 確度 | 確認日 | 説明 | インプット | 場所 |", "|---|---|---|---|---|---|---|"]
        for rel, e in rows:
            mark = "（要確認）" if e["status"] == "要確認" else ""
            cells = [e.get("name", ""), "、".join(e["aliases"]), label.get(e.get("confidence"), "") + mark, e.get("confirmed", ""),
                     e.get("summary", ""), "、".join(e["inputs"]), f"[[{rel[:-3]}]]"]
            out.append("| " + " | ".join(c.replace("|", "／") for c in cells) + " |")
        out.append("")
    (adir / "index.md").write_text("\n".join(out), encoding="utf-8")


def apply_candidate(adir, c, quest):
    """候補を書庫に入れる。update_of があれば更新（食い違い＝conflict なら追記して 要確認。確度は下げない）。"""
    rel = c.get("update_of")
    if rel and (Path(adir) / rel).is_file():
        old = read_entry(entry_path(adir, rel))
        e = dict(old, aliases=sorted({*old["aliases"], *c.get("aliases", [])}),
                 inputs=unique_names([*old["inputs"], *c.get("inputs", [])]), confirmed=today())
        if c.get("conflict"):
            e["body"] = old["body"].rstrip("\n") + f"\n\n## 食い違い（{today()}、{quest}）\n{c.get('body', '').strip()}\n出典：{one_line(c.get('source')) or 'なし'}\n"
            e["status"] = "要確認"
        else:
            e.update(summary=c["summary"], body=c.get("body", ""), source=c.get("source", ""), status="active")
            if CONFIDENCE.index(c["confidence"]) > CONFIDENCE.index(old.get("confidence", "guess")):
                e["confidence"] = c["confidence"]
        return write_entry(adir, e, rel)
    return write_entry(adir, dict(c, confirmed=today(), status="active"))


def archive_propose(qdir):
    """司書の候補を検査する。心得はそのまま登録、ほかは依頼主の確認待ち（archive.json）。同名・別名は更新の候補にする。"""
    qdir = Path(qdir)
    adir = gdir_of(qdir) / "archive"
    init_archive(adir)
    draft = qdir / "reports" / "archive-draft.json"
    cands = load_json(draft).get("candidates", []) if draft.exists() else []
    if not isinstance(cands, list) or len(cands) > MAX_CANDIDATES:
        raise GuildError(f"candidates は {MAX_CANDIDATES} 件までの配列にしてください")
    ids = [c.get("id") if isinstance(c, dict) else None for c in cands]
    if None in ids or len(set(ids)) != len(ids):
        raise GuildError("候補の id が欠けているか、重なっています")
    for c in cands:
        check_entry(c)
    registered, pending = [], []
    for c in cands:
        found = find_entry(adir, c["type"], [c["name"], *c.get("aliases", [])])
        if found:
            c["update_of"] = found
        if c["type"] == "lesson":
            registered.append(apply_candidate(adir, c, qdir.name))
        else:
            pending.append(c)
    rebuild_index(adir)
    state = {"status": "proposed" if pending else "done", "candidates": pending, "registered": registered, "decided": {}}
    save_plan(qdir / "archive.json", state)
    return {"status": state["status"], "registered": registered, "pending": [c["id"] for c in pending]}


def archive_decide(qdir, data):
    """依頼主の答え（decisions: {候補の id: register か skip}）を反映する。確認待ちでなければエラー。"""
    qdir = Path(qdir)
    state_path = qdir / "archive.json"
    state = load_json(state_path) if state_path.exists() else {}
    if state.get("status") != "proposed":
        raise GuildError("確認待ちの登録候補がありません")
    decisions = data.get("decisions")
    if not isinstance(decisions, dict):
        raise GuildError("decisions がありません")
    adir = gdir_of(qdir) / "archive"
    for c in state["candidates"]:
        if decisions.get(c["id"]) == "register":
            state["registered"].append(apply_candidate(adir, c, qdir.name))
            state["decided"][c["id"]] = "register"
        else:
            state["decided"][c["id"]] = "skip"
    state["status"] = "done"
    rebuild_index(adir)
    save_plan(state_path, state)


def archive_apply(adir, data):
    kind = data.get("type")
    if kind == "entry":
        e = dict(data["entry"], confidence="confirmed", confirmed=today(), status="active")
        e.setdefault("aliases", [])
        e["source"] = e.get("source") or "依頼主の登録"
        if data.get("update_of") and "inputs" not in e:
            e["inputs"] = read_entry(entry_path(adir, data["update_of"]))["inputs"]  # 編集で inputs を送らなければ、今のものを残す
        e.setdefault("inputs", [])
        check_entry(e)
        if data.get("update_of"):
            entry_path(adir, data["update_of"])
            write_entry(adir, e, data["update_of"])
            return
        dup = find_entry(adir, e["type"], [e["name"], *e["aliases"]])
        if dup:
            raise GuildError(f"同名の項目があります: {dup}（編集してください）")
        write_entry(adir, e)
    elif kind == "promote":
        e = read_entry(entry_path(adir, data["path"]))
        e.update(confidence="confirmed", confirmed=today(), status="active", source=e.get("source") or "依頼主の確認")
        write_entry(adir, e, data["path"])
    elif kind == "retype":
        e = read_entry(entry_path(adir, data["path"]))
        to = data.get("to")
        if to not in ARCHIVE_TYPES or to == "lesson" or e.get("type") == "lesson":
            raise GuildError("心得への付け替え・心得からの付け替えはできません")
        if to == e.get("type"):
            raise GuildError("同じ種類です")
        if e["status"] == "廃止":
            raise GuildError("廃止した項目は付け替えられません")
        dup = find_entry(adir, to, [e.get("name"), *e["aliases"]])
        if dup:
            raise GuildError(f"移動先に同名の項目があります: {dup}")
        e["type"] = to
        write_entry(adir, e, data["path"])  # 同じファイルの type を書き換えるだけ
    elif kind == "deprecate":
        e = read_entry(entry_path(adir, data["path"]))
        e["body"] = e["body"].rstrip("\n") + f"\n\n## 廃止（{today()}）\n{one_line(data.get('reason')) or '理由の記載なし'}\n"
        e["status"] = "廃止"
        write_entry(adir, e, data["path"])
    else:
        raise GuildError(f"入力が不正です: {kind}")


def archive_ingest(root):
    """`.work/archive-inbox/` の入力を反映する。entry（新規・編集）、promote（確認済みにする）、deprecate（廃止にする）、retype（種類の付け替え）。"""
    adir = Path(root) / "guild" / "archive"
    inbox = work_dir(Path(root) / "guild") / "archive-inbox"
    report = {"applied": [], "rejected": []}
    if not inbox.is_dir():
        return report
    for f in sorted(inbox.glob("*.json")):
        try:
            archive_apply(adir, load_json(f))
            dest, key, item = inbox / "done", "applied", f.name
        except (GuildError, KeyError, TypeError, AttributeError) as e:
            dest, key, item = inbox / "rejected", "rejected", {"file": f.name, "reason": str(e)}
        dest.mkdir(exist_ok=True)
        shutil.move(str(f), str(dest / f.name))
        if key == "rejected":  # ボードが理由を見せられるように残す
            (dest / f"{f.name}.reason.txt").write_text(item["reason"], encoding="utf-8")
        report[key].append(item)
    rebuild_index(adir)
    return report


# ============================================================ インプットの一覧（地図師の材料）
TEXT_EXTS = (".md", ".txt", ".csv")  # 先頭の行を読むファイル
HEAD_LINES = 5
HEAD_BYTES = 65536  # 大きなファイルでも、ここまでしか読まない
HEAD_WIDTH = 200  # 1行の長さの上限
HINT_MIN_LEN = 3  # 2文字以下の語は、一致に使わない（偽の一致が多い）
HINT_CONFIDENCE = ("confirmed", "sourced")  # 推測の項目は、ヒントに使わない


def read_head(path):
    """文字のファイルの先頭 HEAD_LINES 行。UTF-8 で読み、読めない文字は置き換える（Shift_JIS などでも止まらない）。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(HEAD_BYTES)
    except OSError:
        return []
    text = raw.decode("utf-8-sig", errors="replace")
    return [line[:HEAD_WIDTH] for line in text.splitlines()[:HEAD_LINES]]


def hint_terms(adir, text):
    """依頼文に名前・別名が出てくる書庫の項目と、その項目の語（3文字以上の名前・別名）の組を返す。
    対象は、確認済みか出典ありで、使われている（active）、心得でない項目だけ。依頼文が空なら何も返さない。"""
    low = (text or "").casefold()
    found = []
    if not low.strip() or not Path(adir).is_dir():
        return found
    for _, e in all_entries(adir):
        if e.get("type") not in ARCHIVE_TITLES or e["status"] != "active" or e.get("confidence") not in HINT_CONFIDENCE:
            continue
        words = [w for w in (one_line(x) for x in [e.get("name"), *e["aliases"]]) if len(w) >= HINT_MIN_LEN]
        if any(w.casefold() in low for w in words):
            found.append((e, words))
    return found


def inputs_list(root, text=""):
    """guild/inputs/ のファイルを一覧する（地図師がインプットを選ぶ材料）。サブフォルダは見ない。
    hints は、依頼文に出てくる書庫の項目から付ける理由。ヒントのあるファイルを先に、それぞれ名前順に並べる。"""
    gdir = Path(root) / "guild"
    if not (gdir / "config.json").exists():
        raise GuildError(f"{gdir} がありません（/guild:init を先に実行してください）")
    d = gdir / INPUTS
    files = sorted((p for p in d.iterdir() if p.is_file()), key=lambda p: p.name.lower()) if d.is_dir() else []
    terms = hint_terms(gdir / "archive", text)
    out = []
    for p in files:
        st = p.stat()
        ext = p.suffix.lower()
        head = read_head(p) if ext in TEXT_EXTS else None
        hints = []
        for e, words in terms:
            label = f"書庫の{ARCHIVE_TITLES[e['type']]}『{one_line(e.get('name'))}』"
            if p.name.lower() in {n.lower() for n in e["inputs"]}:
                hints.append(f"{label}→ このファイル")
            if any(w.casefold() in p.name.casefold() for w in words):
                hints.append(f"ファイル名に{label}")
            elif head and any(w.casefold() in line.casefold() for w in words for line in head):
                hints.append(f"先頭の行に{label}")
        out.append({"name": p.name, "ext": ext, "size": st.st_size,
                    "updated": datetime.date.fromtimestamp(st.st_mtime).isoformat(),
                    "head": head, "hints": list(dict.fromkeys(hints))})
    out.sort(key=lambda x: not x["hints"])  # 安定な並べ替え：ヒントのあるものが先。それぞれの中は名前順のまま
    return out


def main(argv):
    if len(argv) < 3 or argv[1] not in ("validate", "sync", "next", "ingest", "advance", "adopt", "init", "new", "requests", "close", "wait", "arrivals", "answers", "publish", "archive-propose", "archive-ingest", "web-ingest", "web-pending", "web-reset", "inputs-list"):
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    try:
        if cmd == "inputs-list":
            rest = argv[3:]
            if rest and (len(rest) != 2 or rest[0] != "--text"):
                raise GuildError("inputs-list ROOT [--text 依頼文] の形で指定してください")
            print(json.dumps(inputs_list(path, rest[1] if rest else ""), ensure_ascii=False))
            return 0
        if cmd in ("web-ingest", "web-pending", "web-reset"):
            gdir = Path(path) / "guild"
            result = {"web-ingest": webaccess.ingest, "web-pending": webaccess.pending, "web-reset": webaccess.reset}[cmd](gdir)
            print(json.dumps(result, ensure_ascii=False))
            return 1 if cmd == "web-ingest" and result["rejected"] else 0
        if cmd in ("archive-propose", "archive-ingest"):
            print(json.dumps(archive_propose(path) if cmd == "archive-propose" else archive_ingest(path), ensure_ascii=False))
            return 0
        if cmd == "publish":
            print(json.dumps(publish_deliverables(path), ensure_ascii=False))
            return 0
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
        if cmd == "close":
            print(json.dumps(close_quests(path), ensure_ascii=False))
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

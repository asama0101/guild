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
guild.py archive-propose QDIR: 司書の候補（reports/archive-draft.json）を検査し、心得を登録して、残りを依頼主の確認待ち（archive.json）にする。
guild.py archive-ingest ROOT: archive/inbox/ の入力（entry・promote・deprecate・retype）を書庫に反映する。
guild.py web-ingest ROOT: web/inbox/ の依頼主の答え（WebFetch の許可・不許可、許可リストの追加・削除）を反映する。
guild.py web-pending ROOT: 冒険者が止められて、依頼主の答え待ちのドメインを一覧する。
guild.py web-reset ROOT: 「今回だけ」の許可と、許可しなかった記録を空にする（依頼の完了・中止のとき）。
入力（inbox の JSON）の type の1つに due（Todo の期限の設定・解除）がある。
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
# 納品物の形式（拡張子）。作れるようになったものから足す
FORMATS = {"md": ".md"}
# 納品物のテンプレートとして、中身を読んで使える形式（文字のファイル）
TEMPLATE_READABLE = (".md", ".markdown", ".txt", ".csv")
SATISFIED = ("done", "skipped")
CRITERIA_KEYS = ("viewpoint", "pass_line", "check")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_due(v):
    """期限は YYYY-MM-DD の日付（実在する日）か None。"""
    if v is None:
        return None
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise GuildError(f"due は YYYY-MM-DD の日付か null にしてください: {v!r}")
    try:
        datetime.date.fromisoformat(v)
    except ValueError:
        raise GuildError(f"due が実在しない日付です: {v}")
    return v


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
        try:
            check_due(t.get("due"))
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
    t = tm.get(data.get("todo"))
    if t is None:
        raise GuildError(f"todo がありません: {data.get('todo')}")
    if kind == "due":
        t["due"] = check_due(data.get("due"))
        note(plan, event="due", todo=t["id"], due=t["due"])
        return
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
        if not str(template).lower().endswith(TEMPLATE_READABLE):
            raise GuildError(f"template の形式は、今は読めません: {template}（読める形式: {', '.join(TEMPLATE_READABLE)}）")
    plan = {"quest": draft.get("quest"), "title": draft.get("title"), "approved": False,
            "status": "active", "format": draft.get("format", "md"), **({"template": template} if template else {}),
            **({"archive_used": [str(x) for x in draft["archive_used"]]} if isinstance(draft.get("archive_used"), list) else {}), "todos": [], "history": [{"t": now(), "event": "adopted"}]}
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
    init_archive(gdir / "archive")
    (gdir / "requests").mkdir(exist_ok=True)
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
        ainbox = gdir / "archive" / "inbox"
        if ainbox.is_dir():
            for f in sorted(ainbox.glob("*.json")):
                out.append({"kind": "archive", "file": f.name})
        winbox = gdir / "web" / "inbox"
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
ARCHIVE_DIRS = {"term": "terms", "flow": "flows", "fact": "facts", "personal": "personal", "lesson": "lessons"}
ARCHIVE_TITLES = {"term": "用語", "flow": "業務フロー", "fact": "業務情報", "personal": "個人"}  # 心得は索引に載せない（役は読まない）
CONFIDENCE = ("guess", "sourced", "confirmed")  # 低い順
ACTIVE_STATUS = ("active", "要確認")
MAX_CANDIDATES = 12
FILE_BAD = re.compile(r'[\\/:*?"<>|\s]+')


def init_archive(adir):
    """archive/ と種類別のフォルダ、手入力の受け皿（inbox/）、索引を作る。既存の項目は消さない。"""
    adir = Path(adir)
    for sub in (*ARCHIVE_DIRS.values(), "inbox"):
        (adir / sub).mkdir(parents=True, exist_ok=True)
    if not (adir / "index.md").exists():
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
    if not isinstance(e.get("aliases"), list):
        e["aliases"] = []
    e["aliases"] = [str(a).strip() for a in e["aliases"] if str(a).strip()]
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
    head = ["---", f"name: {yaml_str(e['name'])}", f"type: {e['type']}",
            "aliases: " + json.dumps(aliases, ensure_ascii=False),
            f"confidence: {e['confidence']}", f"source: {yaml_str(e.get('source'))}", f"confirmed: {e.get('confirmed') or today()}",
            f"status: {yaml_str(e.get('status') or 'active')}", f"summary: {yaml_str(e.get('summary'))}", "---"]
    return "\n".join(head) + "\n" + (e.get("body") or "").strip("\n") + "\n"


def check_entry(e):
    if e.get("type") not in ARCHIVE_DIRS:
        raise GuildError(f"type が不正です: {e.get('type')}（{', '.join(ARCHIVE_DIRS)}）")
    if not one_line(e.get("name")):
        raise GuildError("name がありません")
    if not one_line(e.get("summary")):
        raise GuildError(f"summary がありません: {e.get('name')}")
    if e.get("confidence") not in CONFIDENCE:
        raise GuildError(f"confidence が不正です: {e.get('confidence')}（{', '.join(CONFIDENCE)}）")
    if e["confidence"] != "guess" and not one_line(e.get("source")):
        raise GuildError(f"出典（source）がありません: {e.get('name')}（推測なら confidence を guess にする）")


def write_entry(adir, e, path=None):
    """項目を書く。path（archive/ からの相対）があれば、そこへ上書き。なければ名前から新しいファイル名を決める。"""
    adir = Path(adir)
    check_entry(e)
    if path is None:
        stem = FILE_BAD.sub("-", one_line(e["name"])).strip("-. ")
        if not stem:
            raise GuildError(f"ファイル名にできない名前です: {e['name']}")
        folder = adir / ARCHIVE_DIRS[e["type"]]
        folder.mkdir(parents=True, exist_ok=True)
        n, cand = 1, folder / f"{stem}.md"
        while cand.exists():
            n += 1
            cand = folder / f"{stem}-{n}.md"
        path = cand.relative_to(adir).as_posix()
    target = adir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(entry_text(e), encoding="utf-8")
    return path


def entry_path(adir, rel):
    """archive/ の中の項目だけを指せる。外や、4つのフォルダ以外は指せない。"""
    parts = str(rel).replace("\\", "/").split("/")
    ok = len(parts) == 2 and parts[0] in ARCHIVE_DIRS.values() and parts[1].endswith(".md") and ".." not in parts[1]
    p = Path(adir) / "/".join(parts)
    if not ok or not p.is_file():
        raise GuildError(f"項目が見つかりません: {rel}")
    return p


def all_entries(adir):
    for folder in ARCHIVE_DIRS.values():
        for f in sorted((Path(adir) / folder).glob("*.md")):
            e = read_entry(f)
            if e is not None:
                yield f"{folder}/{f.name}", e


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
        out += ["| 名前 | 別名 | 確度 | 確認日 | 説明 | 場所 |", "|---|---|---|---|---|---|"]
        for rel, e in rows:
            mark = "（要確認）" if e["status"] == "要確認" else ""
            cells = [e.get("name", ""), "、".join(e["aliases"]), label.get(e.get("confidence"), "") + mark, e.get("confirmed", ""), e.get("summary", ""), f"[[{rel[:-3]}]]"]
            out.append("| " + " | ".join(c.replace("|", "／") for c in cells) + " |")
        out.append("")
    (adir / "index.md").write_text("\n".join(out), encoding="utf-8")


def apply_candidate(adir, c, quest):
    """候補を書庫に入れる。update_of があれば更新（食い違い＝conflict なら追記して 要確認。確度は下げない）。"""
    rel = c.get("update_of")
    if rel and (Path(adir) / rel).is_file():
        old = read_entry(entry_path(adir, rel))
        e = dict(old, aliases=sorted({*old["aliases"], *c.get("aliases", [])}), confirmed=today())
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
    adir = qdir.parent / "archive"
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
    adir = qdir.parent / "archive"
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
        src = entry_path(adir, data["path"])
        e = read_entry(src)
        to = data.get("to")
        if to not in ARCHIVE_DIRS or to == "lesson" or e.get("type") == "lesson":
            raise GuildError("心得への付け替え・心得からの付け替えはできません")
        if to == e.get("type"):
            raise GuildError("同じ種類です")
        if e["status"] == "廃止":
            raise GuildError("廃止した項目は付け替えられません")
        dup = find_entry(adir, to, [e.get("name"), *e["aliases"]])
        if dup:
            raise GuildError(f"移動先に同名の項目があります: {dup}")
        e["type"] = to
        new = adir / write_entry(adir, e)  # 新しい場所へ。ファイル名が重なれば連番になり、上書きしない
        try:
            src.unlink()  # 書けたあとで元を消す（書けなければ元は残る）
        except OSError as err:
            new.unlink()  # 元を消せなかったら、書いたほうを戻す（2つの種類に残さない）
            raise GuildError(f"元の項目を消せませんでした: {err}")
    elif kind == "deprecate":
        e = read_entry(entry_path(adir, data["path"]))
        e["body"] = e["body"].rstrip("\n") + f"\n\n## 廃止（{today()}）\n{one_line(data.get('reason')) or '理由の記載なし'}\n"
        e["status"] = "廃止"
        write_entry(adir, e, data["path"])
    else:
        raise GuildError(f"入力が不正です: {kind}")


def archive_ingest(root):
    """archive/inbox/ の入力を反映する。entry（新規・編集）、promote（確認済みにする）、deprecate（廃止にする）、retype（種類の付け替え）。"""
    adir = Path(root) / "guild" / "archive"
    inbox = adir / "inbox"
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


def main(argv):
    if len(argv) < 3 or argv[1] not in ("validate", "sync", "next", "ingest", "advance", "adopt", "init", "new", "requests", "wait", "arrivals", "answers", "archive-propose", "archive-ingest", "web-ingest", "web-pending", "web-reset"):
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    try:
        if cmd in ("web-ingest", "web-pending", "web-reset"):
            gdir = Path(path) / "guild"
            result = {"web-ingest": webaccess.ingest, "web-pending": webaccess.pending, "web-reset": webaccess.reset}[cmd](gdir)
            print(json.dumps(result, ensure_ascii=False))
            return 1 if cmd == "web-ingest" and result["rejected"] else 0
        if cmd in ("archive-propose", "archive-ingest"):
            print(json.dumps(archive_propose(path) if cmd == "archive-propose" else archive_ingest(path), ensure_ascii=False))
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

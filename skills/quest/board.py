#!/usr/bin/env python3
"""Guild board.json の読み書き（ギルドマスター用。Windows / Mac / Linux 共通）。

<vault>/guild/.system/board.py に置かれて使われる。標準ライブラリのみ。
書き込みは「読む → 変える → 一時ファイルに書く → os.replace」なので、途中で止まっても壊れない。
サブコマンドの一覧は `board.py -h`。値の引数は JSON 文字列。
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

__version__ = "1.7.0"

QUEST_STATES = ["受付済", "冒険中", "鑑定中", "返事待ち", "要手直し", "依頼主がやること", "達成", "中止"]
STUDY_STATES = ["計画中", "承認待ち", "進行中", "達成", "中止"]
DONE = ("達成", "中止")
PRIORITIES = ("優先", "通常", "保留")
ID_PREFIXES = ("Q", "S", "A", "F", "I")
NOTICE_LIMIT = 20
TIME_FMT = "%Y-%m-%d %H:%M"


class BoardError(Exception):
    pass


# ---------- 読み書き ----------

def now_str(now=None):
    return (now or datetime.now()).strftime(TIME_FMT)


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise BoardError(f"board.json を読めない: {e}")
    except ValueError as e:
        raise BoardError(f"board.json が壊れている: {e}")


def save(path, data, now=None):
    """updated を更新し、一時ファイル経由で書く。"""
    data["updated"] = now_str(now)
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".board-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------- 番号 ----------

def _num(s, prefix):
    m = re.fullmatch(prefix + r"(\d+)", str(s or ""))
    return int(m.group(1)) if m else 0


def _all_ids(board):
    """prefix -> 今ある最大の番号（退避前に last_ids へ畳むためにも使う）。"""
    mx = {p: 0 for p in ID_PREFIXES}
    for q in board.get("quests", []):
        mx["Q"] = max(mx["Q"], _num(q.get("id"), "Q"))
        mx["F"] = max(mx["F"], _num((q.get("feedback") or {}).get("id"), "F"))
    for s in board.get("studies", []):
        mx["S"] = max(mx["S"], _num(s.get("id"), "S"))
        mx["F"] = max(mx["F"], _num((s.get("feedback") or {}).get("id"), "F"))
    for a in board.get("questions", []):
        mx["A"] = max(mx["A"], _num(a.get("id"), "A"))
        mx["F"] = max(mx["F"], _num(a.get("feedback_id"), "F"))
        mx["I"] = max(mx["I"], _num(a.get("interview_id"), "I"))
    return mx


def _fold_last_ids(board):
    last = board.setdefault("last_ids", {})
    for p, n in _all_ids(board).items():
        last[p] = max(int(last.get(p, 0) or 0), n)
    return last


def next_id(board, prefix, reserve=False):
    """次の番号。reserve=True なら last_ids に記録して消費する。"""
    if prefix not in ID_PREFIXES:
        raise BoardError(f"知らない番号の種類: {prefix}")
    last = _fold_last_ids(board)
    n = int(last[prefix]) + 1
    if reserve:
        last[prefix] = n
    return f"{prefix}{n}"


# ---------- 検索 ----------

def find_quest(board, qid):
    for q in board.get("quests", []):
        if q.get("id") == qid:
            return q
    return None


def find_study(board, sid):
    for s in board.get("studies", []):
        if s.get("id") == sid:
            return s
    return None


def find_question(board, aid):
    for a in board.get("questions", []):
        if a.get("id") == aid:
            return a
    return None


def _find_target(board, tid):
    t = find_quest(board, tid)
    if t is not None:
        return t, "quest"
    t = find_study(board, tid)
    if t is not None:
        return t, "study"
    raise BoardError(f"{tid} が board.json に無い")


# ---------- 要約 ----------

def summary(board):
    """ギルドマスターが読む要約。result・log・detail・回答済の質問は含めない。"""
    top_keys = ("vault", "inbox", "max_active", "projects_dir", "quests_dir", "glossary_dir",
                "knowledge_dir", "templates_dir", "venv_python",
                "results_backfilled", "pending_term_quests", "updated")
    out = {k: board[k] for k in top_keys if k in board}
    out["studies"] = [{
        "id": s.get("id"), "title": s.get("title"), "status": s.get("status"),
        "priority": s.get("priority", "通常"), "quests": s.get("quests", []),
        "replan": bool(s.get("replan")), "feedback": (s.get("feedback") or {}).get("status"),
        "dir": s.get("dir"),
    } for s in board.get("studies", [])]
    keys = ("id", "study", "priority", "due", "status", "adventurers", "depends_on", "notes",
            "retries", "dir", "output", "report", "terms", "appraise")
    out["quests"] = []
    for q in board.get("quests", []):
        row = {k: q[k] for k in keys if k in q}
        row["title"] = str(q.get("title", ""))[:30]
        fb = (q.get("feedback") or {}).get("status")
        if fb:
            row["feedback"] = fb
        out["quests"].append(row)
    qkeys = ("id", "kind", "quest_id", "study_id", "feedback_id", "interview_id", "grill", "from")
    out["open_questions"] = [{k: a[k] for k in qkeys if a.get(k)}
                             for a in board.get("questions", []) if a.get("status") == "未回答"]
    out["answered_questions"] = sum(1 for a in board.get("questions", []) if a.get("status") == "回答済")
    notices = board.get("notices", [])
    out["notices"] = len(notices)
    out["latest_stops"] = (notices[0].get("stops") or []) if notices else []
    return out


# ---------- 追加 ----------

def add_quest(board, obj, now=None):
    qid = next_id(board, "Q", reserve=True)
    q = {"id": qid, "study": "", "title": "", "detail": "", "priority": 2, "due": "",
         "status": "受付済", "adventurers": [], "depends_on": [], "notes": [], "output": "",
         "dir": "", "files": [], "done_when": [], "retries": 0,
         "terms": {"ask": [], "lookup": []}, "result": "", "links": [], "report": "", "log": []}
    q.update(obj)
    q["id"] = qid
    if q["status"] not in QUEST_STATES:
        raise BoardError(f"クエストの状態が不正: {q['status']}")
    sid = q.get("study")
    if sid:
        s = find_study(board, sid)
        if s is not None and qid not in s.setdefault("quests", []):
            s["quests"].append(qid)
    board.setdefault("quests", []).append(q)
    return qid


def add_study(board, obj, now=None):
    sid = next_id(board, "S", reserve=True)
    s = {"id": sid, "title": "", "goal": "", "due": "", "priority": "通常", "status": "計画中",
         "dir": "", "note": "", "files": [], "quests": [], "next": "", "plan": [], "log": []}
    s.update(obj)
    s["id"] = sid
    if s["status"] not in STUDY_STATES:
        raise BoardError(f"研究の状態が不正: {s['status']}")
    if s["priority"] not in PRIORITIES:
        raise BoardError(f"研究の優先度が不正: {s['priority']}")
    board.setdefault("studies", []).append(s)
    return sid


def add_question(board, obj, now=None):
    aid = next_id(board, "A", reserve=True)
    a = {"id": aid, "kind": "question", "asked": now_str(now), "title": "", "text": "",
         "status": "未回答", "answer": "", "comment": ""}
    a.update(obj)
    a["id"] = aid
    board.setdefault("questions", []).append(a)
    return aid


# ---------- 更新 ----------

def set_status(board, tid, state, text, who="guildmaster", now=None):
    t, kind = _find_target(board, tid)
    states = QUEST_STATES if kind == "quest" else STUDY_STATES
    if state not in states:
        raise BoardError(f"{tid} の状態が不正: {state}")
    entry = {"time": now_str(now), "who": who, "text": text or ""}
    if kind == "quest":
        entry = {"time": entry["time"], "who": who, "edge": f"{t.get('status')}→{state}", "text": entry["text"]}
    t["status"] = state
    t.setdefault("log", []).append(entry)
    return entry


def set_field(board, tid, field, value):
    """value が None なら項目を消す。"""
    t, _ = _find_target(board, tid)
    if value is None:
        t.pop(field, None)
    else:
        if field == "priority" and "title" in t and "goal" in t and value not in PRIORITIES:
            raise BoardError(f"研究の優先度が不正: {value}")
        t[field] = value


def set_top(board, key, value):
    if key in ("studies", "quests", "questions", "notices", "profile"):
        raise BoardError(f"{key} は set-top では書けない")
    if value is None:
        board.pop(key, None)
    else:
        board[key] = value


def add_log(board, tid, text, who="guildmaster", now=None):
    t, _ = _find_target(board, tid)
    t.setdefault("log", []).append({"time": now_str(now), "who": who, "text": text})


def answer_question(board, aid, answer, comment):
    a = find_question(board, aid)
    if a is None:
        raise BoardError(f"質問 {aid} が無い")
    a["status"] = "回答済"
    a["answer"] = answer
    a["comment"] = comment
    return a


def close_questions(board, quest=None, study=None, answer="取り消し"):
    n = 0
    for a in board.get("questions", []):
        if a.get("status") != "未回答":
            continue
        if (quest and a.get("quest_id") == quest) or (study and a.get("study_id") == study):
            a["status"] = "回答済"
            a["answer"] = answer
            n += 1
    return n


def add_notice(board, text, stops=None, by="herald", now=None):
    n = {"time": now_str(now), "by": by, "text": text}
    if stops:
        n["stops"] = list(stops)
    board.setdefault("notices", []).insert(0, n)
    del board["notices"][NOTICE_LIMIT:]
    return n


# ---------- 簡単な依頼の取り込み（M・S ファイル） ----------

def _move_done(f, done_dir):
    done_dir.mkdir(parents=True, exist_ok=True)
    dest = done_dir / f.name
    n = 2
    while dest.exists():
        dest = done_dir / f"{f.stem}-{n}{f.suffix}"
        n += 1
    os.replace(f, dest)


def _read_request(f):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _newest_first(items):
    """(posted, ファイル名) の大きい順。"""
    return sorted(items, key=lambda it: (str(it[1].get("posted", "")), it[0].name), reverse=True)


def apply_simple(board, req_dir, now=None):
    """requests/ 直下の setting・study_priority を取り込み、済/ に移す。
    board は呼び出し側が保存する。取り込んだ内容の文のリストを返す。"""
    req_dir = Path(req_dir)
    if not req_dir.is_dir():
        return []
    settings, prios = [], []
    for f in sorted(req_dir.glob("*.json")):
        d = _read_request(f)
        if d is None:
            continue
        if d.get("kind") == "setting":
            settings.append((f, d))
        elif d.get("kind") == "study_priority":
            prios.append((f, d))
    msgs = []
    done_dir = req_dir / "済"
    by_key = {}
    for f, d in settings:
        by_key.setdefault(d.get("key"), []).append((f, d))
    for key, items in by_key.items():
        items = _newest_first(items)
        f, d = items[0]
        v = d.get("value")
        if key == "max_active" and isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 8:
            board["max_active"] = v
            msgs.append(f"同時数を {v} 件にした")
        else:
            msgs.append(f"設定 {key}={v!r} は受け付けられないので取り込まなかった")
        for f2, _ in items:
            _move_done(f2, done_dir)
    by_study = {}
    for f, d in prios:
        by_study.setdefault(d.get("target"), []).append((f, d))
    for target, items in by_study.items():
        items = _newest_first(items)
        f, d = items[0]
        s = find_study(board, target)
        p = d.get("priority")
        if s is None or s.get("status") in DONE or p not in PRIORITIES:
            msgs.append(f"{target} の優先度の変更は受け付けられないので取り込まなかった（研究が無い・終わっている・値が不正）")
        else:
            s["priority"] = p
            s.setdefault("log", []).append(
                {"time": now_str(now), "who": "guildmaster", "text": f"優先度を {p} にした"})
            msgs.append(f"{target} の優先度を {p} にした")
        for f2, _ in items:
            _move_done(f2, done_dir)
    return msgs


# ---------- 退避 ----------

def _last_time(item):
    times = [e.get("time") for e in item.get("log", []) if e.get("time")]
    return max(times) if times else None


def _is_old(item, cutoff):
    t = _last_time(item)
    return t is not None and t < cutoff.strftime(TIME_FMT)


def archive(board, days=30, now=None):
    """達成・中止から days 日たったものを取り除いて返す。研究のクエストは研究ごと。
    前提（depends_on）に使われている番号は退避しない。last_ids に番号を畳んでから取り除く。"""
    cutoff = (now or datetime.now()) - timedelta(days=days)
    _fold_last_ids(board)
    studies = board.get("studies", [])
    quests = board.get("quests", [])
    old_studies = {s["id"] for s in studies
                   if s.get("status") in DONE and _is_old(s, cutoff)
                   and all((find_quest(board, q) or {}).get("status", "達成") in DONE
                           for q in s.get("quests", []))}
    move_q = {q["id"] for q in quests
              if q.get("status") in DONE
              and ((q.get("study") and q["study"] in old_studies)
                   or (not q.get("study") and _is_old(q, cutoff)))}
    # 退避しないクエストの前提に使われている番号は残す。残すクエストの研究も残す（研究ごと動かすため）
    by_id = {q["id"]: q for q in quests}
    while True:
        needed = {d for q in quests if q["id"] not in move_q for d in q.get("depends_on", [])}
        keep = move_q & needed
        keep_studies = {by_id[i].get("study") for i in keep if by_id[i].get("study")}
        if not keep and not (old_studies & keep_studies):
            break
        old_studies -= keep_studies
        move_q -= keep
        move_q = {i for i in move_q if not by_id[i].get("study") or by_id[i]["study"] in old_studies}
    out = {"quests": [q for q in quests if q["id"] in move_q],
           "studies": [s for s in studies if s["id"] in old_studies],
           "questions": []}
    out["questions"] = [a for a in board.get("questions", [])
                        if a.get("status") == "回答済"
                        and (a.get("quest_id") in move_q or a.get("study_id") in old_studies)]
    board["quests"] = [q for q in quests if q["id"] not in move_q]
    board["studies"] = [s for s in studies if s["id"] not in old_studies]
    gone = {id(a) for a in out["questions"]}
    board["questions"] = [a for a in board.get("questions", []) if id(a) not in gone]
    return out


def append_archive(path, moved):
    path = Path(path)
    data = {"quests": [], "studies": [], "questions": []}
    if path.is_file():
        try:
            data.update(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            raise BoardError(f"{path.name} が壊れている")
    for k in ("quests", "studies", "questions"):
        data.setdefault(k, []).extend(moved[k])
    fd, tmp = tempfile.mkstemp(prefix=".archive-", suffix=".tmp", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------- 用語集の索引 ----------

def parse_term_note(text):
    """用語ノートから (aliases のリスト, 意味の 1 行) を取り出す。"""
    aliases, body = [], text
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?(.*)", text, re.S)
    if m:
        body = m.group(2)
        a = re.search(r"(?m)^aliases:\s*\[(.*?)\]\s*$", m.group(1))
        if a:
            aliases = [x.strip().strip("'\"") for x in a.group(1).split(",") if x.strip()]
    meaning = ""
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        meaning = s
        break
    return aliases, meaning


def build_glossary_index(glossary_dir):
    d = Path(glossary_dir)
    rows = []
    if d.is_dir():
        for f in sorted(d.glob("*.md")):
            if f.name == "用語集.md":
                continue
            aliases, meaning = parse_term_note(f.read_text(encoding="utf-8", errors="replace"))
            cell = lambda s: s.replace("|", "/").replace("\n", " ")
            rows.append(f"| [[{f.stem}]] | {cell(', '.join(aliases))} | {cell(meaning)[:80]} |")
    head = ("---\ntype: glossary-index\n---\n# 用語集\n\n"
            "用語の索引（吟遊詩人が用語ノートを書くたびに直す。照合はこの 1 枚を読む）。\n\n"
            "| 用語 | 別名 | 意味 |\n|---|---|---|\n")
    return head + "\n".join(rows) + ("\n" if rows else "")


def write_glossary_index(glossary_dir):
    d = Path(glossary_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "用語集.md").write_text(build_glossary_index(d), encoding="utf-8")
    return d / "用語集.md"


# ---------- CLI ----------

def _json(s):
    try:
        return json.loads(s)
    except ValueError as e:
        raise BoardError(f"JSON として読めない: {e}")


def _p(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def build_parser():
    ap = argparse.ArgumentParser(description="Guild board.json の読み書き")
    ap.add_argument("--sys-dir", help="guild/.system のパス（既定はこのファイルのあるフォルダ）")
    ap.add_argument("--version", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("get")
    g.add_argument("--summary", action="store_true")
    g.add_argument("--quest")
    g.add_argument("--study")
    g.add_argument("--question")
    for name in ("add-quest", "add-study", "add-question"):
        sub.add_parser(name).add_argument("json")
    sub.add_parser("next-id").add_argument("prefix")
    p = sub.add_parser("set-status")
    p.add_argument("id"); p.add_argument("state")
    p.add_argument("--text", default=""); p.add_argument("--who", default="guildmaster")
    p = sub.add_parser("set")
    p.add_argument("id"); p.add_argument("field"); p.add_argument("json")
    p = sub.add_parser("set-top")
    p.add_argument("key"); p.add_argument("json")
    p = sub.add_parser("log")
    p.add_argument("id"); p.add_argument("--text", required=True); p.add_argument("--who", default="guildmaster")
    p = sub.add_parser("answer")
    p.add_argument("id"); p.add_argument("--answer", default=""); p.add_argument("--comment", default="")
    p = sub.add_parser("close-questions")
    p.add_argument("--quest"); p.add_argument("--study"); p.add_argument("--answer", default="取り消し")
    p = sub.add_parser("add-notice")
    p.add_argument("--text", required=True); p.add_argument("--stop", action="append", default=[])
    p.add_argument("--by", default="herald")
    sub.add_parser("apply-simple")
    p = sub.add_parser("archive")
    p.add_argument("--days", type=int, default=30)
    sub.add_parser("glossary-index").add_argument("glossary_dir")
    return ap


def run(argv, sys_dir=None):
    a = build_parser().parse_args(argv)
    if a.version:
        print(__version__)
        return 0
    if not a.cmd:
        build_parser().print_help()
        return 1
    sysd = Path(a.sys_dir or sys_dir or Path(__file__).resolve().parent)
    bpath = sysd / "board.json"
    if a.cmd == "glossary-index":
        print(write_glossary_index(Path(a.glossary_dir)))
        return 0
    board = load(bpath)
    if a.cmd == "get":
        if a.quest:
            t = find_quest(board, a.quest)
        elif a.study:
            t = find_study(board, a.study)
        elif a.question:
            t = find_question(board, a.question)
        else:
            _p(summary(board))
            return 0
        if t is None:
            raise BoardError("見つからない")
        _p(t)
        return 0
    if a.cmd == "next-id":
        print(next_id(board, a.prefix))
        return 0
    if a.cmd == "add-quest":
        out = add_quest(board, _json(a.json))
    elif a.cmd == "add-study":
        out = add_study(board, _json(a.json))
    elif a.cmd == "add-question":
        out = add_question(board, _json(a.json))
    elif a.cmd == "set-status":
        out = set_status(board, a.id, a.state, a.text, a.who)
    elif a.cmd == "set":
        set_field(board, a.id, a.field, _json(a.json)); out = "ok"
    elif a.cmd == "set-top":
        set_top(board, a.key, _json(a.json)); out = "ok"
    elif a.cmd == "log":
        add_log(board, a.id, a.text, a.who); out = "ok"
    elif a.cmd == "answer":
        answer_question(board, a.id, a.answer, a.comment); out = "ok"
    elif a.cmd == "close-questions":
        out = close_questions(board, a.quest, a.study, a.answer)
    elif a.cmd == "add-notice":
        out = add_notice(board, a.text, a.stop, a.by)
    elif a.cmd == "apply-simple":
        msgs = apply_simple(board, sysd / "requests")
        if msgs:
            add_notice(board, "。".join(msgs) + "。", by="guildmaster")
            save(bpath, board)
        out = {"applied": msgs}
    elif a.cmd == "archive":
        moved = archive(board, a.days)
        if moved["quests"] or moved["studies"] or moved["questions"]:
            append_archive(sysd / "board-archive.json", moved)
        save(bpath, board)
        out = {"archived": {k: [x.get("id") for x in v] for k, v in moved.items()}}
        _p(out)
        return 0
    else:
        return 1
    save(bpath, board)
    if out is not None and out != "ok":
        _p(out) if not isinstance(out, str) else print(out)
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        return run(argv if argv is not None else sys.argv[1:])
    except BoardError as e:
        print(f"board.py: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

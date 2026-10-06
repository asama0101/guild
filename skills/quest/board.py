#!/usr/bin/env python3
"""Guild board.json の読み書き（ギルドマスター用。Windows / Mac / Linux 共通）。

<vault>/guild/.system/board.py に置かれて使われる。標準ライブラリのみ。
書き込みは「読む → 変える → 一時ファイルに書く → os.replace」なので、途中で止まっても壊れない。
サブコマンドの一覧は `board.py -h`。値の引数は JSON 文字列。
"""
import argparse
import hashlib
import json
import os
import re
import stat
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
# 依頼ファイルは小さな JSON という前提の安全上限（巨大・深い入れ子のファイルでメモリや再帰を食わせない）
MAX_REQUEST_BYTES = 1_000_000
MSG_LIMIT = 80  # 拒否メッセージに入れる外部由来の文字列の上限（board.json への巨大文字列の混入を防ぐ）
# 資料庫の後追い抽出（assets-scan）の上限。いずれも暫定。実測して調整する
MAX_SCAN_BYTES = 20 * 1024 * 1024  # 1 ファイルの上限（超過は oversize として手作業に回す）
MAX_SCAN_DEPTH = 20  # input/ からのサブフォルダの深さ
MAX_SCAN_FILES = 1000  # 1 回の走査で調べるファイル数
SCAN_LIMIT = 5  # 1 回に賢者へ渡す件数の既定
SCAN_LIMIT_MAX = 20  # --limit の上限
MAX_BATCH_BYTES = 50 * 1024 * 1024  # 1 回に賢者へ渡す原本サイズの合計


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
    top_keys = ("vault", "inbox", "max_active", "projects_dir", "quests_dir", "glossary_dir", "assets_dir",
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
        if f.stat().st_size > MAX_REQUEST_BYTES:
            return None
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
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

_FM = re.compile(r"---\r?\n(.*?)\r?\n---\r?\n?(.*)", re.S)
# str.splitlines() が行区切りとみなす文字（表のセルに混ぜると行が割れる）
_LINE_BREAKS = re.compile("[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


def _cell(s):
    """表のセル用に、| を / に、改行類を空白に置き換える。"""
    return _LINE_BREAKS.sub(" ", str(s).replace("|", "/"))


def parse_term_note(text):
    """用語ノートから (aliases のリスト, 意味の 1 行) を取り出す。"""
    aliases, body = [], text
    m = _FM.match(text)
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
            rows.append(f"| [[{f.stem}]] | {_cell(', '.join(aliases))} | {_cell(meaning)[:80]} |")
    head = ("---\ntype: glossary-index\n---\n# 用語集\n\n"
            "用語の索引（吟遊詩人が用語ノートを書くたびに直す。照合はこの 1 枚を読む）。\n\n"
            "| 用語 | 別名 | 意味 |\n|---|---|---|\n")
    return head + "\n".join(rows) + ("\n" if rows else "")


def write_glossary_index(glossary_dir):
    d = Path(glossary_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "用語集.md").write_text(build_glossary_index(d), encoding="utf-8")
    return d / "用語集.md"


# ---------- 資料庫（資料から抽出した事実のノート） ----------

ASSET_STATES = ("候補", "確定", "置換済")
ASSET_INDEX = "資料庫.md"
TRASH = "ゴミ箱"
TS_FMT = "%Y%m%d%H%M%S"  # 日時 14 桁（ゴミ箱のファイル名・trashed_at）
_NO_DIR = "資料庫が未設定のため取り込めなかった"


def _atomic_write(path, text):
    """一時ファイル → os.replace。save() は updated を書き換えるので流用しない。"""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".assets-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _short(x):
    """拒否メッセージに入れる外部由来の値を MSG_LIMIT 文字に切る。"""
    return str(x)[:MSG_LIMIT]


def parse_frontmatter(text):
    """1 行 `key: value` だけの frontmatter を (dict, 本文) にする。無ければ ({}, text)。
    行は \\n だけで分ける（U+2028 などで割れて、locator に書き写された `auto: minor` が読まれるのを防ぐ）。"""
    m = _FM.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).split("\n"):
        k, sep, v = line.rstrip("\r").partition(":")
        if sep and k.strip():
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def _set_meta(text, updates):
    """frontmatter の既存キー（複数行あれば全て）を置き換え、無いキーは末尾に足す。本文は触らない。"""
    m = _FM.match(text)
    lines = [x.rstrip("\r") for x in m.group(1).split("\n")]
    for k, v in updates.items():
        hit = [i for i, line in enumerate(lines) if line.partition(":")[0].strip() == k]
        for i in hit:
            lines[i] = f"{k}: {v}"
        if not hit:
            lines.append(f"{k}: {v}")
    return "---\n" + "\n".join(lines) + "\n---\n" + m.group(2)


def _vault_root(sys_dir):
    """vault のルート（sys_dir の 2 つ上）を解決済みの Path で返す。"""
    return Path(sys_dir).parent.parent.resolve()


def resolve_vault_dir(board, sys_dir, key):
    """board.json の key（assets_dir・projects_dir・quests_dir。vault 相対か絶対）を解決した Path にする。
    キー無しは None。解決結果が vault（sys_dir の 2 つ上）の外なら BoardError（../.. や任意の絶対パスを拒否）。"""
    v = board.get(key)
    if not v or not isinstance(v, str):
        return None
    root = _vault_root(sys_dir)
    p = (root / v).resolve()  # 絶対パスはそのまま使われる
    try:
        p.relative_to(root)
    except ValueError:
        raise BoardError(f"{key} が vault の外を指している: {_short(v)}")
    return p


def resolve_assets_dir(board, sys_dir):
    """board.json の assets_dir を解決した Path にする。無ければ None。vault の外は BoardError。"""
    return resolve_vault_dir(board, sys_dir, "assets_dir")


_BAD_ID = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029/\\|\[\]]")


def _load_notes(d):
    """d 直下の type: asset の *.md を {id: {"id","path","text"}} で返す。id はファイル名の stem。
    シンボリックリンクと、表や [[id]] を壊しうる文字を含む id は無視する。"""
    notes = {}
    d = Path(d)
    if not d.is_dir():
        return notes
    for f in sorted(d.glob("*.md")):
        if f.is_symlink() or not f.is_file() or _BAD_ID.search(f.stem) or f.name == ASSET_INDEX:
            continue
        text = f.read_text(encoding="utf-8-sig", errors="replace")
        if parse_frontmatter(text)[0].get("type") == "asset":
            notes[f.stem] = {"id": f.stem, "path": f, "text": text}
    return notes


def _meta(n):
    return parse_frontmatter(n["text"])[0]


def _is_conflict(meta):
    """conflict: yes / true（大小無視）のときだけ競合あり。no・false・空・無しは競合なし。"""
    return str(meta.get("conflict", "")).strip().lower() in ("yes", "true")


def _set_status(n, status):
    n["text"] = _set_meta(n["text"], {"status": status})
    _atomic_write(n["path"], n["text"])


_SHA = re.compile(r"[0-9a-fA-F]{64}")


def _promote(notes):
    """§2: auto: minor・conflict 無し・sha256 が 64 桁 16 進・supersedes 先が確定の候補だけを確定にする。
    連鎖（新 → 中 → 旧）が 1 回で収束するよう、昇格が 0 件になるまで繰り返す。
    同じ旧ノートを置き換える候補が複数あれば、先に昇格した 1 件だけが確定になる。"""
    msgs = []
    while True:
        found = False
        for nid in sorted(notes):
            n, m = notes[nid], _meta(notes[nid])
            old = notes.get(m.get("supersedes"))
            if (m.get("status") == "候補" and m.get("auto") == "minor" and not _is_conflict(m)
                    and _SHA.fullmatch(m.get("sha256", ""))
                    and old is not None and old is not n and _meta(old).get("status") == "確定"):
                _set_status(n, "確定")
                _set_status(old, "置換済")
                msgs.append(f"{nid} を自動確定にした（{old['id']} は置換済）")
                found = True
        if not found:
            return msgs


def _rel(path, root):
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _trash(n, adir, root, now):
    ts = (now or datetime.now()).strftime(TS_FMT)
    tdir = Path(adir) / TRASH
    if tdir.is_symlink():
        raise BoardError("ゴミ箱がシンボリックリンクなので移せない")
    tdir.mkdir(exist_ok=True)
    text = _set_meta(n["text"], {"trashed_from": _rel(n["path"], root), "trashed_at": ts})
    dest = tdir / f"{n['id']}__{ts}.md"
    k = 2
    while dest.exists():  # 同じ秒に同じ id を移しても先のファイルを上書きしない
        dest = tdir / f"{n['id']}__{ts}-{k}.md"
        k += 1
    _atomic_write(dest, text)
    n["path"].unlink()


def trash_notes(adir, ids, now=None, root=None):
    """id を列挙一致で引いてゴミ箱へ移す。1 つでも不明なら何も動かさず BoardError。"""
    ids = list(dict.fromkeys(ids))
    notes = _load_notes(adir)
    bad = [i for i in ids if i not in notes]
    if bad:
        raise BoardError(f"資料庫に無いノート: {bad}")
    for i in ids:
        _trash(notes[i], adir, root or Path(adir).parent, now)
    return ids


def _table(lines):
    """最初の表の事実行を 3 列のリストで返す。
    見出し行・区切り行（先頭の 2 行）を除き、| で始まる連続行だけを読む。"""
    rows, started = [], False
    for line in lines:
        s = line.strip()
        if s.startswith("|"):
            rows.append([c.strip() for c in s.strip("|").split("|")])
            started = True
        elif started:
            break
    return [(r + ["", "", ""])[:3] for r in rows[2:]]


def _facts(body):
    parts = re.split(r"(?m)^## 食い違い.*$", body, maxsplit=1)
    facts = [{"item": a, "value": b, "where": c} for a, b, c in _table(parts[0].splitlines())]
    conf = [{"item": a, "old": b, "new": c} for a, b, c in _table(parts[1].splitlines())] if len(parts) > 1 else []
    return facts, conf


def _note_json(n):
    m, body = parse_frontmatter(n["text"])
    facts, conf = _facts(body)
    out = {"id": n["id"]}
    for k in ("status", "targets", "kind", "source", "version", "date", "sha256", "locator",
              "supersedes", "auto"):
        out[k] = m.get(k, "")
    out["conflict"] = _is_conflict(m)  # 画面は真偽値を見る
    out["facts"], out["conflict_rows"] = facts, conf
    return out


def write_assets_index(adir, sys_dir, now=None):
    """昇格 → 資料庫.md と .system/assets.json を作り直す。(索引パス, counts, 昇格の文) を返す。"""
    adir = Path(adir)
    adir.mkdir(parents=True, exist_ok=True)
    notes = _load_notes(adir)
    promoted = _promote(notes)
    js = [_note_json(notes[i]) for i in sorted(notes)]
    counts = {s: sum(1 for j in js if j["status"] == s) for s in ASSET_STATES}
    cell = lambda s: re.sub(r"\[\[|\]\]", "", _cell(s))  # [[ ]] はリンクを偽造できるので除く
    rows = [f"| [[{j['id']}]] | {cell(j['version'])} | {cell(j['date'])} | {cell(j['targets'])} "
            f"| {cell(j['kind'])} | {len(j['facts'])} |" for j in js if j["status"] == "確定"]
    head = ("---\ntype: assets-index\n---\n# 資料庫\n\n"
            "確定した資料の索引（資料 1 件 1 行）。事実の値はここに無い。該当する資料を見つけたらノートを開いて読む。\n\n"
            "| 資料 | 版 | 日付 | 対象 | 種別 | 事実数 |\n|---|---|---|---|---|---|\n")
    _atomic_write(adir / ASSET_INDEX, head + "\n".join(rows) + ("\n" if rows else ""))
    _atomic_write(Path(sys_dir) / "assets.json", json.dumps(
        {"generated": now_str(now), "counts": counts, "notes": js}, ensure_ascii=False, indent=2) + "\n")
    return adir / ASSET_INDEX, counts, promoted


_OFFICE_EXTS = (".xlsx", ".docx", ".pptx")


def _is_md_copy(f):
    """f が markitdown の写し（同名の Office ファイルがある .md）か。"""
    return f.suffix == ".md" and any(f.with_suffix(e).exists() for e in _OFFICE_EXTS)


def _hashes_in(d):
    """d 直下の資料ノートの sha256 を、小文字にした集合で返す。"""
    return {_meta(n).get("sha256", "").lower() for n in _load_notes(d).values()}


def _known_hashes(adir):
    """資料庫に登録済み（生きているノートとゴミ箱）の sha256 の集合（小文字）。"""
    return _hashes_in(adir) | _hashes_in(Path(adir) / TRASH)


def _sha256(path):
    """通常ファイルだけを MAX_SCAN_BYTES 以下で読んで sha256 を返す。それ以外は OSError。
    先に開いてから fstat で確かめる（確認後の FIFO・リンクへの差し替えで固まらないように）。"""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"通常ファイルではない: {_short(path)}")
        if st.st_size > MAX_SCAN_BYTES:
            raise OSError(f"大きすぎる: {_short(path)}")
    except BaseException:
        os.close(fd)
        raise
    h = hashlib.sha256()
    with os.fdopen(fd, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_assets(files, adir):
    """各ファイルの sha256 と状態（registered > trashed > changed > new）。"""
    live = _load_notes(adir)
    metas = {i: _meta(n) for i, n in live.items()}
    trashed = _hashes_in(Path(adir) / TRASH)
    out = []
    for f in map(Path, files):
        if _is_md_copy(f):
            continue  # markitdown の写し
        row = {"file": str(f), "sha256": None, "state": "unreadable", "note": None}
        try:
            row["sha256"] = sha = _sha256(f)
        except OSError:
            out.append(row)
            continue
        by_sha = [i for i in sorted(live) if metas[i].get("sha256", "").lower() == sha]
        by_src = [i for i in sorted(live) if metas[i].get("source") == f.name]
        if by_sha:
            row["state"], row["note"] = "registered", by_sha[0]
        elif sha in trashed:
            row["state"] = "trashed"
        elif by_src:
            row["state"], row["note"] = "changed", by_src[0]
        else:
            row["state"] = "new"
        out.append(row)
    return out


def _decide(n, action, notes, adir, root, now):
    """遷移表（§4）を 1 件適用する。(適用した文, None) か (None, 拒否した文)。"""
    nid, m = n["id"], _meta(n)
    st, conf = m.get("status"), _is_conflict(m)
    if action == "trash":
        _trash(n, adir, root, now)
        del notes[nid]
        warn = "。注意: 確定ノートを外したので、置換済の旧ノートは自動では戻らない" if st == "確定" else ""
        return f"{nid} をゴミ箱へ移した{warn}", None
    if st == "候補" and action == "approve" and conf:
        return None, f"{nid} は食い違いがあるので、上書き OK/NG で答えてください"
    if st == "候補" and (action == "approve" or (action == "overwrite_ok" and conf)):
        _set_status(n, "確定")
        old = notes.get(m.get("supersedes"))
        if old is not None and old is not n and _meta(old).get("status") == "確定":
            _set_status(old, "置換済")
            return f"{nid} を確定にした（{old['id']} は置換済）", None
        extra = "。注意: 置き換える旧ノートが無い・確定でないので新ノートだけ確定にした" if m.get("supersedes") else ""
        return f"{nid} を確定にした{extra}", None
    if st == "候補" and (action == "reject" or (action == "overwrite_ng" and conf)):
        _trash(n, adir, root, now)
        del notes[nid]
        return f"{nid} をゴミ箱へ移した", None
    return None, f"{_short(nid)}（{st}）に {_short(action)} はできないので取り込まなかった"


def _apply_assets(board, req_dir, sys_dir, now=None):
    """requests/D*.json の asset_decision を適用して 済/ へ移す。(applied, rejected) を返す。
    決定を処理した回・昇格が起きた回の最後に、資料庫.md と assets.json を作り直す。"""
    req_dir = Path(req_dir)
    if not req_dir.is_dir():
        return [], []
    files = sorted(req_dir.glob("D*.json"), key=lambda f: f.stem)  # 無印 < -2 < -3
    try:
        adir = resolve_assets_dir(board, sys_dir)
    except BoardError:  # vault の外などの不正な設定は、未設定と同じに扱う（依頼を溜めない）
        adir = None
    done, applied, rejected = req_dir / "済", [], []
    if adir is None:
        if not files:
            return [], []
        for f in files:
            _move_done(f, done)
        return [], [_NO_DIR]
    root = Path(sys_dir).parent.parent
    notes = _load_notes(adir)
    applied += _promote(notes)
    for f in files:
        d = _read_request(f)
        nid = d.get("note") if d else None
        if not d or d.get("kind") != "asset_decision":
            rejected.append(f"{_short(f.name)} は資料庫の決定として読めないので取り込まなかった")
        elif not isinstance(nid, str) or nid not in notes:  # 列挙した id との一致だけで引く
            rejected.append(f"{_short(f.name)} の note {_short(repr(nid))} は資料庫に無いので取り込まなかった")
        else:
            try:
                ok, ng = _decide(notes[nid], d.get("action"), notes, adir, root, now)
            except BoardError as e:
                ok, ng = None, f"{_short(nid)} は取り込めなかった: {e}"
            (applied if ok else rejected).append(ok or ng)
        _move_done(f, done)
    applied += _promote(notes)
    if files or applied:
        write_assets_index(adir, sys_dir, now)
    return applied, rejected


def apply_assets(board, req_dir, sys_dir, now=None):
    """apply_simple と同じ形。board は読むだけ。適用・拒否した文のリストを返す。"""
    a, r = _apply_assets(board, req_dir, sys_dir, now)
    return a + r


# ---------- 後追い抽出（assets-scan）と一括承認（assets-approve） ----------

# 走査するファイル名・フォルダ名の検査（_BAD_ID に、表示を偽装する双方向制御・ゼロ幅文字と長すぎる名前を足す）
_BAD_SCAN_NAME = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029/\\|\[\]\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]")
MAX_NAME_LEN = 120


def _bad_scan_name(name):
    return len(name) > MAX_NAME_LEN or bool(_BAD_SCAN_NAME.search(name))


def _scan_files(d, st):
    """d の中の通常ファイルを、相対パスの部品のタプルのリストで返す（スタックを使う反復。再帰しない）。
    シンボリックリンク・隠しファイルは辿らない。st（走査全体の集計の dict）の unreadable・files・truncated を更新する。
    scandir の OSError と危険な名前のフォルダ（中に入らない）は unreadable に 1 と数える。
    深さが MAX_SCAN_DEPTH を超えるフォルダと、MAX_SCAN_FILES を超えるファイルは調べず truncated にする。"""
    out, stack = [], [(d, (), 0)]
    while stack:
        path, parts, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            st["unreadable"] += 1
            continue
        for e in entries:
            if e.name.startswith(".") or e.is_symlink():
                continue
            if e.is_dir(follow_symlinks=False):
                if _bad_scan_name(e.name):
                    st["unreadable"] += 1
                elif depth + 1 > MAX_SCAN_DEPTH:
                    st["truncated"] = True
                else:
                    stack.append((e.path, parts + (e.name,), depth + 1))
            elif e.is_file(follow_symlinks=False):  # FIFO などは False
                if st["files"] >= MAX_SCAN_FILES:
                    st["truncated"] = True
                    return out
                st["files"] += 1
                if _bad_scan_name(e.name):  # サイズより先に判定し、名前は返さない
                    st["unreadable"] += 1
                else:
                    out.append(parts + (e.name,))
    return out


def _case_dirs(root):
    """root 直下の案件フォルダ（隠し・シンボリックリンクを除く）。"""
    if root is None or not root.is_dir():
        return []
    try:
        with os.scandir(root) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return []
    return [Path(e.path) for e in entries
            if not e.name.startswith(".") and not e.is_symlink() and e.is_dir(follow_symlinks=False)]


def _scan_case(case, rel_case, known, seen, st):
    """案件フォルダ 1 つの input/ を走査し、未登録の資料を st["found"]（(項目, サイズ) の列）に足す。"""
    if _bad_scan_name(case.name):
        st["unreadable"] += 1
        return
    inp = case / "input"
    if inp.is_symlink() or not inp.is_dir():
        return
    for parts in sorted(_scan_files(inp, st)):
        f = inp.joinpath(*parts)
        if _is_md_copy(f):
            continue  # markitdown の写し
        try:
            size = f.stat().st_size
            if size > MAX_SCAN_BYTES:
                st["oversize"].append(f"{rel_case}/input/{'/'.join(parts)}")
                continue
            sha = _sha256(f)
        except OSError:
            st["unreadable"] += 1
            continue
        if sha in known or sha in seen:
            continue
        seen.add(sha)
        st["found"].append(({"case": rel_case, "file": "input/" + "/".join(parts), "sha256": sha}, size))


def scan_assets(board, sys_dir, limit=SCAN_LIMIT):
    """案件フォルダの input/ から、資料庫に未登録の資料を最大 limit 件返す（既登録・ゴミ箱は除く）。
    limit は 1 以上 SCAN_LIMIT_MAX 以下（範囲外は BoardError）。items の原本サイズの合計が MAX_BATCH_BYTES を
    超える手前で止める（1 件目は超えても返す）。
    remaining は、調べた範囲で未登録なのに items に入らなかった数。truncated が true のときは「少なくとも」の意味
    （深さ MAX_SCAN_DEPTH・ファイル数 MAX_SCAN_FILES の上限で、それ以上は調べていない）。
    unreadable は次の合計: 読めない・通常ファイルでないファイルと危険な名前のファイルの数、
    読めない案件フォルダ・サブフォルダ（scandir の失敗）、危険な名前の案件フォルダ・サブフォルダ（中は数えない）の数。"""
    if not 1 <= limit <= SCAN_LIMIT_MAX:
        raise BoardError(f"--limit は 1 以上 {SCAN_LIMIT_MAX} 以下にする: {limit}")
    adir = resolve_vault_dir(board, sys_dir, "assets_dir")
    dirs = [resolve_vault_dir(board, sys_dir, k) for k in ("projects_dir", "quests_dir")]
    if adir is None or all(x is None for x in dirs):
        raise BoardError("board.json に assets_dir と、projects_dir か quests_dir が要る（/guild:init で足す）")
    root = _vault_root(sys_dir)
    known = _known_hashes(adir)
    cases = sorted((c for r in dirs for c in _case_dirs(r)), key=lambda c: c.relative_to(root).as_posix())
    st = {"unreadable": 0, "files": 0, "truncated": False, "oversize": [], "found": []}
    seen = set()
    for case in cases:
        _scan_case(case, case.relative_to(root).as_posix(), known, seen, st)
    items, total = [], 0
    for item, size in st["found"]:
        if len(items) >= limit or (items and total + size > MAX_BATCH_BYTES):
            break
        items.append(item)
        total += size
    out = {"items": items, "remaining": len(st["found"]) - len(items),
           "unreadable": st["unreadable"], "oversize": st["oversize"]}
    if st["truncated"]:
        out["truncated"] = True
    return out


def _select_candidates(notes, source, target):
    """条件に合う候補を (chosen の id 列, skipped) に分ける。
    食い違い・supersedes を持つもの・同じ資料名の確定ノートがあるものは skipped（理由つき）。"""
    confirmed = {_meta(n).get("source") for n in notes.values() if _meta(n).get("status") == "確定"} - {"", None}
    chosen, skipped = [], []
    for nid in sorted(notes):
        m = _meta(notes[nid])
        if m.get("status") != "候補":
            continue
        if source and m.get("source") != source:
            continue
        if target and target.strip() not in [t.strip() for t in m.get("targets", "").split(",")]:
            continue
        if _is_conflict(m):
            skipped.append({"id": nid, "reason": "食い違いがある（上書き OK/NG で答える）"})
        elif m.get("supersedes"):  # 資料内の指示文で別資料の確定ノートを置換済にされないよう、一括では承認しない
            skipped.append({"id": nid, "reason": "新旧の判断は資料庫タブで"})
        elif m.get("source") in confirmed:
            skipped.append({"id": nid, "reason": "同じ資料名の確定ノートがある（画面で新旧を見て判断する）"})
        else:
            chosen.append(nid)
    return chosen, skipped


def _preview(notes, chosen, root):
    """承認の対象を、事実は先頭 3 件（各値は MSG_LIMIT 文字まで）に絞って見せる。"""
    preview = []
    for nid in chosen:
        j = _note_json(notes[nid])
        twins = [i for i in chosen if i != nid and j["source"] and _meta(notes[i]).get("source") == j["source"]]
        p = {"id": nid, "source": j["source"], "version": j["version"], "date": j["date"],
             "targets": j["targets"], "fact_count": len(j["facts"]), "path": _rel(notes[nid]["path"], root),
             "facts": [{k: _short(v) for k, v in f.items()} for f in j["facts"][:3]]}
        if twins:
            p["warning"] = f"同名の候補あり: {', '.join(twins)}"
        preview.append(p)
    return preview


def approve_assets(board, sys_dir, source=None, target=None, all_=False, yes=False, now=None):
    """条件に合う候補を一括で確定にする。yes なしはプレビューだけ（何も変えない）。
    yes のときは、承認が 0 件でも最後に昇格（_promote）→ 索引の作り直しを行う。"""
    adir = resolve_vault_dir(board, sys_dir, "assets_dir")
    if adir is None:
        raise BoardError("board.json に assets_dir が無い（/guild:init で足す）")
    if not (source or target or all_):
        raise BoardError("--source・--target・--all のどれかが要る（誤って全件を承認しない）")
    root = _vault_root(sys_dir)
    notes = _load_notes(adir)
    chosen, skipped = _select_candidates(notes, source, target)
    if not yes:
        return {"preview": _preview(notes, chosen, root), "skipped": skipped}
    approved = []
    for nid in chosen:
        ok, ng = _decide(notes[nid], "approve", notes, adir, root, now)
        if ok:
            approved.append(nid)
        else:
            skipped.append({"id": nid, "reason": ng})
    promoted = _promote(notes)
    write_assets_index(adir, sys_dir, now)
    return {"approved": approved, "skipped": skipped, "promoted": promoted}


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
    sub.add_parser("assets-index")
    sub.add_parser("assets-apply")
    sub.add_parser("assets-list")
    sub.add_parser("assets-check").add_argument("files", nargs="+")
    sub.add_parser("assets-trash").add_argument("ids", nargs="+")
    sub.add_parser("assets-scan").add_argument("--limit", type=int, default=SCAN_LIMIT)
    p = sub.add_parser("assets-approve")
    p.add_argument("--source"); p.add_argument("--target")
    p.add_argument("--all", action="store_true"); p.add_argument("--yes", action="store_true")
    return ap


def _run_assets(a, board, bpath, sysd, now):
    """assets-* サブコマンド 1 つを実行して終了コードを返す。結果は JSON（assets-list だけ表）で標準出力へ。
    assets-apply は board.json の通知も更新する。それ以外は assets_dir が無ければ BoardError。"""
    if a.cmd == "assets-apply":
        applied, rejected = _apply_assets(board, sysd / "requests", sysd, now)
        if applied or rejected:
            add_notice(board, "。".join(applied + rejected) + "。", by="guildmaster", now=now)
            save(bpath, board, now)
        _p({"applied": applied, "rejected": rejected})
        return 0
    adir = resolve_assets_dir(board, sysd)
    if adir is None:
        raise BoardError("board.json に assets_dir が無い（/guild:init で足す）")
    if a.cmd == "assets-index":
        path, counts, _ = write_assets_index(adir, sysd, now)
        _p({"index": str(path), "counts": counts})
    elif a.cmd == "assets-check":
        _p(check_assets(a.files, adir))
    elif a.cmd == "assets-trash":
        _p(trash_notes(adir, a.ids, now, sysd.parent.parent))
    elif a.cmd == "assets-scan":
        _p(scan_assets(board, sysd, a.limit))
    elif a.cmd == "assets-approve":
        _p(approve_assets(board, sysd, a.source, a.target, a.all, a.yes, now))
    else:  # assets-list
        notes = _load_notes(adir)
        for st in ASSET_STATES:
            for i in sorted(notes):
                m = _meta(notes[i])
                if m.get("status") == st:
                    print(f"{i}  {st}  {m.get('targets', '')}  {m.get('source', '')}  {m.get('version', '')}")
    return 0


def run(argv, sys_dir=None, now=None):
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
    if a.cmd.startswith("assets-"):
        return _run_assets(a, board, bpath, sysd, now)
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

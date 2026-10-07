#!/usr/bin/env python3
"""guild 0.1 の board.py（標準ライブラリだけ）。

board.json（状態の唯一の源）を書けるのはこのファイルだけ。遷移は transitions.json で決め、
辺・役・書込先・述語を検査してから状態を変える。エラーは終了コード 1。
"""
import argparse
import datetime
import html
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

VERSION = "0.1.0"
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 定数
QUEST_STATES = ["受付", "分解中", "承認待ち", "進行中", "最終鑑定", "達成", "失敗", "中止", "保留"]
GOAL_STATES = ["案", "待機", "冒険中", "鑑定中", "要手直し", "確認待ち", "実行承認待ち", "達成", "失敗", "中止"]
QUEST_TERMINAL = ["達成", "失敗", "中止"]
GOAL_TERMINAL = ["達成", "中止"]
QUEST_LABELS = {
    "受付": "聞き取り中", "分解中": "計画を作っている", "承認待ち": "あなたの承認を待っている",
    "進行中": "進めている", "最終鑑定": "全体を確かめている", "達成": "達成",
    "失敗": "達成できなかった", "中止": "中止", "保留": "止めている",
}
GOAL_LABELS = {
    "案": "計画の案", "待機": "順番を待っている", "冒険中": "冒険者が作業している",
    "鑑定中": "鑑定士が確かめている", "要手直し": "直している", "確認待ち": "あなたの確認を待っている",
    "実行承認待ち": "あなたの実行の承認を待っている", "達成": "達成", "失敗": "達成できなかった", "中止": "中止",
}
ACTORS = ["guildmaster", "client", "workshop", "receptionist", "fortune_teller", "adventurer",
          "alchemist", "smith", "appraiser", "wizard", "bard", "tick"]
ROLE_WRITES = {
    "guildmaster": ["board", "quest_md", "adventure_log", "lessons", "rules"],
    "client": ["board", "shared", "inputs", "templates", "profile"],
    "workshop": ["board", "output", "inputs", "reports"],
    "receptionist": ["board", "reports"],
    "fortune_teller": ["board", "reports"],
    "adventurer": ["board", "reports"],
    "alchemist": ["board", "output"],
    "smith": ["board", "output"],
    "appraiser": ["board", "reports"],
    "wizard": ["board", "spellbook"],
    "bard": ["board", "reports"],
    "tick": ["board"],
}
EFFORTS = ["低", "中", "高"]
PRIORITIES = ["優先", "通常"]
FORMS = ["おまかせ", "回答だけ", "ノート", "テキスト", "Word", "Excel", "PowerPoint", "PDF", "その他"]
FIX_KINDS = ["input", "brief", "goal"]
POINT_CODES = ["欠落", "矛盾", "誤り", "形式", "出典なし", "範囲外"]
Q_KINDS = ["choice", "approval", "todo", "confirm", "rule", "term"]
Q_SCOPES = ["route", "output", "execute", "none"]
Q_STATUS = ["未回答", "回答済", "保留"]
NONBLOCKING_KINDS = ["rule", "term"]
REWORK_REASONS = {
    "report_error": "作業中にエラーが出た",
    "precheck_ng": "納品物の形式に問題があった",
    "no_report": "報告書が届かなかった",
    "timeout": "作業に時間がかかりすぎた",
}
DEFAULT_LIMITS = {"max_active": 4, "retries": 3, "rework_total": 6, "replans": 2, "budget": {"max_calls": 20}}
DEFAULT_DUE_DAYS = 3
REMIND_DAYS = 3
HOLD_DAYS = 14
RULE_FILE_MAX_LINES = 20
LESSONS_MAX_LINES = 100
NOTICE_MAX = 20
BUDGET_STOP_NOTICE = "作業が多いため、いったん止めました。次の回で続きから進みます。"
DEPENDENT_OPTIONS = ["この達成条件をやり直す", "この達成条件なしで進める", "後続も中止する"]
FORBIDDEN_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
TEMPLATE_MARK = ("<!-- BEGIN:transitions -->", "<!-- END:transitions -->")


class GuildError(Exception):
    pass


# ---------------------------------------------------------------- 時刻
def now():
    env = os.environ.get("GUILD_NOW")
    if env:
        return datetime.datetime.fromisoformat(env)
    return datetime.datetime.now().replace(microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def parse_dt(s):
    return datetime.datetime.fromisoformat(s)


def jp_date(s):
    if not s:
        return ""
    d = parse_dt(s) if "T" in s else datetime.datetime.fromisoformat(s)
    return f"{d.month}月{d.day}日"


def jp_stamp(s):
    d = parse_dt(s)
    return f"{d.month}月{d.day}日 {d.hour:02d}:{d.minute:02d}"


# ---------------------------------------------------------------- パス
class Paths:
    def __init__(self, root):
        self.root = Path(root)
        self.sys = self.root / ".system"
        self.board = self.sys / "board.json"
        self.archive = self.sys / "board-archive.json"
        self.lock = self.sys / "board.lock"
        self.backup = self.sys / "backup"
        self.answers = self.sys / "answers"
        self.requests = self.sys / "requests"
        self.reports = self.sys / "reports"
        self.briefs = self.sys / "quests"
        self.rules = self.sys / "rules"
        self.lessons = self.sys / "lessons.md"
        self.logs = self.sys / "logs"
        self.profile = self.root / "profile.md"

    def transitions(self):
        p = self.sys / "transitions.json"
        return p if p.exists() else HERE / "transitions.json"


def find_root(arg):
    if arg:
        return Path(arg)
    env = os.environ.get("GUILD_ROOT")
    if env:
        return Path(env)
    if HERE.name == ".system":
        return HERE.parent
    raise GuildError("guild フォルダが分かりません。--root か環境変数 GUILD_ROOT で指定してください")


# ---------------------------------------------------------------- 遷移
_T_CACHE = {}


def load_transitions(paths):
    p = paths.transitions()
    key = str(p)
    mt = p.stat().st_mtime
    if key in _T_CACHE and _T_CACHE[key][0] == mt:
        return _T_CACHE[key][1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise GuildError(f"transitions.json を読めません: {e}")
    _T_CACHE[key] = (mt, data)
    return data


def parse_guard(g):
    m = re.fullmatch(r"(\w+)(?:\((\w+)\))?", g)
    if not m:
        raise GuildError(f"述語の書き方が不正です: {g}")
    return m.group(1), m.group(2)


# ---------------------------------------------------------------- 盤
class Board:
    def __init__(self, paths):
        self.p = paths
        self.d = None
        self.t = load_transitions(paths)

    # 読み書き
    def load(self):
        if not self.p.board.exists():
            raise GuildError(f"board.json がありません: {self.p.board}（/guild:init で作ります）")
        try:
            self.d = json.loads(self.p.board.read_text(encoding="utf-8"))
        except ValueError as e:
            raise GuildError(f"board.json が壊れています（board.py recover で戻せます）: {e}")
        validate(self.d)
        return self

    def save(self):
        self.refresh_blocked()
        self.d["updated"] = iso(now())
        validate(self.d)
        self.p.backup.mkdir(parents=True, exist_ok=True)
        if self.p.board.exists():
            for i in (3, 2):
                src = self.p.backup / f"board.json.{i - 1}"
                if src.exists():
                    shutil.copy2(src, self.p.backup / f"board.json.{i}")
            shutil.copy2(self.p.board, self.p.backup / "board.json.1")
        tmp = self.p.board.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, self.p.board)

    # 採番
    def next_id(self, letter):
        li = self.d["last_ids"]
        li[letter] = li.get(letter, 0) + 1
        return f"{letter}{li[letter]}"

    # 参照
    def quest(self, qid):
        if qid not in self.d["quests"]:
            raise GuildError(f"不明なクエストです: {qid}")
        return self.d["quests"][qid]

    def goal(self, gid):
        if gid not in self.d["goals"]:
            raise GuildError(f"不明な達成条件です: {gid}")
        return self.d["goals"][gid]

    def question(self, aid):
        for q in self.d["questions"]:
            if q["id"] == aid:
                return q
        raise GuildError(f"不明な質問です: {aid}")

    def goals_of(self, qid):
        return [self.d["goals"][g] for g in self.quest(qid)["goals"]]

    def qdir(self, qid):
        return self.p.root / self.quest(qid)["dir"]

    def limit(self, key):
        return self.d["limits"].get(key, DEFAULT_LIMITS[key])

    # 待ちの属性（保存のたびに計算し直す）
    def refresh_blocked(self):
        d = self.d
        open_q = [q for q in d["questions"] if q["status"] == "未回答" and q.get("blocking", True)]
        for g in d["goals"].values():
            if g["status"] in GOAL_TERMINAL:
                g["blocked_on"] = ""
            elif g["status"] in ("確認待ち", "実行承認待ち") or any(q.get("goal") == g["id"] for q in open_q):
                g["blocked_on"] = "client"
            elif g["status"] in ("冒険中", "鑑定中", "要手直し", "待機"):
                g["blocked_on"] = "guild"
            else:
                g["blocked_on"] = ""
        for q in d["quests"].values():
            if q["status"] in QUEST_TERMINAL or q["status"] == "保留":
                q["blocked_on"] = ""
                continue
            gs = [d["goals"][g] for g in q["goals"]]
            if q["status"] == "承認待ち" or any(x["quest"] == q["id"] for x in open_q if not x.get("goal")) \
                    or any(g["blocked_on"] == "client" for g in gs):
                q["blocked_on"] = "client"
            elif q["status"] in ("受付", "分解中", "最終鑑定") or any(g["blocked_on"] == "guild" for g in gs) \
                    or (q["status"] == "進行中" and gs):
                q["blocked_on"] = "guild"
            else:
                q["blocked_on"] = ""


def validate(d):
    def bad(msg):
        raise GuildError(f"board.json の検査に失敗しました: {msg}")
    for k in ("schema_version", "limits", "last_ids", "quests", "goals", "questions", "feedbacks", "interviews", "notices"):
        if k not in d:
            bad(f"{k} がありません")
    lim = d["limits"]
    if not isinstance(lim.get("max_active", 4), int) or not 1 <= lim.get("max_active", 4) <= 8:
        bad("max_active は 1〜8 です")
    for qid, q in d["quests"].items():
        if q.get("id") != qid:
            bad(f"{qid} の id が合いません")
        if q["status"] not in QUEST_STATES:
            bad(f"{qid} の状態が不明です: {q['status']}")
        if q.get("priority", "通常") not in PRIORITIES:
            bad(f"{qid} の優先度が不明です")
        for g in q["goals"]:
            if g not in d["goals"]:
                bad(f"{qid} が不明な達成条件 {g} を持っています")
    for gid, g in d["goals"].items():
        if g.get("id") != gid:
            bad(f"{gid} の id が合いません")
        if g["status"] not in GOAL_STATES:
            bad(f"{gid} の状態が不明です: {g['status']}")
        if g["quest"] not in d["quests"]:
            bad(f"{gid} の quest が不明です")
        if g.get("effort", "中") not in EFFORTS:
            bad(f"{gid} の effort が不明です")
        dw = g.get("done_when", [])
        if not isinstance(dw, list) or len(dw) > 3:
            bad(f"{gid} の done_when は 3 個までのリストです")
        if g.get("form", "おまかせ") not in FORMS:
            bad(f"{gid} の form が不明です")
        for f in g.get("findings", []):
            if f.get("fix_kind") not in FIX_KINDS:
                bad(f"{gid} の fix_kind が不明です")
            if f.get("point_code") and f["point_code"] not in POINT_CODES:
                bad(f"{gid} の point_code が不明です")
    for q in d["questions"]:
        if q["kind"] not in Q_KINDS or q["scope"] not in Q_SCOPES or q["status"] not in Q_STATUS:
            bad(f"質問 {q.get('id')} の kind／scope／status が不明です")


# ---------------------------------------------------------------- 排他ロック
class Lock:
    def __init__(self, paths, timeout=10.0, stale=60.0):
        self.path = paths.lock
        self.timeout = timeout
        self.stale = stale

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        end = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.time() > end:
                    raise GuildError("board.lock が取れません。ほかの board.py が動いています")
                time.sleep(0.05)

    def __exit__(self, *a):
        try:
            self.path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- 道のり
def goal_graph(b, qid):
    gs = {g["id"]: g for g in b.goals_of(qid) if g["status"] != "中止"}
    return gs


def topo_order(gs):
    """依存の順に並べる（同順位は番号順）。閉路・欠けは GuildError。"""
    indeg = {}
    for gid, g in gs.items():
        for dep in g.get("depends_on", []):
            if dep not in gs:
                raise GuildError(f"{gid} の前提 {dep} が、このクエストにありません")
        indeg[gid] = len(g.get("depends_on", []))
    order, ready = [], sorted([g for g, n in indeg.items() if n == 0], key=idnum)
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for gid, g in gs.items():
            if cur in g.get("depends_on", []):
                indeg[gid] -= 1
                if indeg[gid] == 0:
                    ready.append(gid)
                    ready.sort(key=idnum)
    if len(order) != len(gs):
        raise GuildError("道のりに閉路があります: " + ",".join(sorted(set(gs) - set(order), key=idnum)))
    return order


def idnum(s):
    return int(re.sub(r"\D", "", s) or 0)


def route_check(b, qid):
    gs = goal_graph(b, qid)
    result = {"quest": qid, "ok": True, "errors": [], "warnings": [], "route": [], "slack": {}}
    try:
        order = topo_order(gs)
    except GuildError as e:
        result["ok"] = False
        result["errors"].append(str(e))
        return result
    result["route"] = order
    base = now()
    ef, lf = {}, {}
    est = lambda g: int(gs[g].get("estimate_min") or 0)
    for gid in order:
        start = max([ef[d] for d in gs[gid].get("depends_on", [])] or [0])
        ef[gid] = start + est(gid)
    horizon = 10 ** 9
    for gid in reversed(order):
        succ = [s for s in order if gid in gs[s].get("depends_on", [])]
        limit = horizon
        if gs[gid].get("deadline"):
            dl = datetime.datetime.fromisoformat(gs[gid]["deadline"]).replace(hour=23, minute=59)
            limit = min(limit, int((dl - base).total_seconds() // 60))
        for s in succ:
            limit = min(limit, lf[s] - est(s))
        lf[gid] = limit
    for gid in order:
        if lf[gid] >= horizon:
            continue
        slack = lf[gid] - ef[gid]
        result["slack"][gid] = slack
        if slack < 0:
            result["warnings"].append(f"{gid} は締切に間に合わないおそれがあります（ゆとり {slack} 分）")
    return result


# ---------------------------------------------------------------- 回答の記録
def read_records(paths):
    recs = []
    if paths.answers.exists():
        for f in sorted(paths.answers.glob("*.json")):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            r["_file"] = f
            recs.append(r)
    return recs


def find_record(paths, target_id, choices, scope=None):
    for r in read_records(paths):
        if r.get("consumed"):
            continue
        if target_id not in (r.get("covers") or [r.get("goal") or r.get("quest")]):
            continue
        if choices and r.get("choice") not in choices:
            continue
        if scope and r.get("scope") != scope:
            continue
        return r
    return None


def write_record(paths, name, rec):
    paths.answers.mkdir(parents=True, exist_ok=True)
    rec = dict(rec)
    f = paths.answers / f"{name}.json"
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return f


def consume(rec):
    f = rec.pop("_file")
    rec["consumed"] = True
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- pre-check / cross-check
def goal_outputs(b, g):
    qd = b.qdir(g["quest"])
    op = g.get("output_path") or []
    if isinstance(op, str):
        op = [op]
    return [qd / p for p in op]


def report_files(b, gid, role):
    d = b.p.reports
    if not d.exists():
        return []
    return sorted(d.glob(f"{gid}-{role}*.md"))


def md_section(text, name):
    m = re.search(rf"^##\s+{re.escape(name)}\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    n = re.search(r"^##\s+", rest, re.M)
    return rest[: n.start()] if n else rest


def bullets(sec):
    return [ln.strip() for ln in (sec or "").splitlines() if re.match(r"^\s*([-*]|\d+[.)])\s+", ln)]


def pre_check(b, gid):
    g = b.goal(gid)
    issues = []
    outs = goal_outputs(b, g)
    if not outs:
        issues.append("納品物の場所（output_path）が決まっていません")
    for f in outs:
        if not f.exists():
            issues.append(f"納品物がありません: {f.name}")
            continue
        if f.stat().st_size == 0:
            issues.append(f"納品物が空です: {f.name}")
            continue
        suf = f.suffix.lower()
        if suf in (".docx", ".xlsx", ".pptx") and not zipfile.is_zipfile(f):
            issues.append(f"形式が不正です: {f.name}")
        elif suf == ".pdf" and not f.read_bytes()[:5] == b"%PDF-":
            issues.append(f"形式が不正です: {f.name}")
        elif suf == ".md":
            text = f.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"\[[^\]]*\]\(([^)#\s]+)[^)]*\)", text):
                link = m.group(1)
                if re.match(r"^[a-z]+:", link):
                    continue
                if not (f.parent / link).exists():
                    issues.append(f"リンク切れ: {f.name} → {link}")
            for i, ln in enumerate(bullets(md_section(text, "事実")), 1):
                if "[出典:" not in ln and "［出典:" not in ln:
                    issues.append(f"出典のない事実: {f.name} 事実 {i} 行目")
            for i, ln in enumerate(bullets(md_section(text, "推論")), 1):
                if "[前提:" not in ln or "[確度:" not in ln:
                    issues.append(f"前提または確度のない推論: {f.name} 推論 {i} 行目")
    return {"goal": gid, "ok": not issues, "issues": issues}


NUM_PAIR = re.compile(r"([^\s、。：:|=｜\[\]（）()]{2,20})\s*(?:[：:=]|は)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([円%％件個人台日時間分kKmMgG]*)")


def cross_check(b, qid):
    seen = {}
    for g in b.goals_of(qid):
        if g["status"] == "中止":
            continue
        for f in goal_outputs(b, g):
            if f.suffix.lower() != ".md" or not f.exists():
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            sec = (md_section(text, "事実") or "") + (md_section(text, "推論") or "")
            for m in NUM_PAIR.finditer(sec):
                label, val, unit = m.group(1), m.group(2).replace(",", ""), m.group(3)
                seen.setdefault(label, {}).setdefault((val, unit), set()).add(f.name)
    conflicts = []
    for label, vals in seen.items():
        files = set().union(*vals.values())
        if len(vals) > 1 and len(files) > 1:
            conflicts.append({"label": label, "values": sorted(f"{v}{u}" for v, u in vals), "files": sorted(files)})
    return {"quest": qid, "result": "suspect" if conflicts else "clean", "conflicts": conflicts}


# ---------------------------------------------------------------- 述語
class Ctx:
    def __init__(self, kind, obj, frm, to, who, data=None):
        self.kind, self.obj, self.frm, self.to, self.who, self.data = kind, obj, frm, to, who, data or {}


def eval_guard(b, name, arg, c):
    o = c.obj
    d = b.d
    if name == "no_open_questions":
        n = [q for q in d["questions"] if q["quest"] == o["id"] and q["status"] == "未回答" and q["kind"] in ("choice", "todo")]
        return not n, "未回答の問いがあります"
    if name == "has_goals":
        return bool(goal_graph(b, o["id"])), "達成条件がありません"
    if name == "acyclic":
        try:
            topo_order(goal_graph(b, o["id"]))
            return True, ""
        except GuildError as e:
            return False, str(e)
    if name == "all_have_done_when":
        miss = [g["id"] for g in goal_graph(b, o["id"]).values()
                if not (1 <= len([x for x in g.get("done_when", []) if str(x).strip()]) <= 3)]
        return not miss, "done_when のない達成条件があります: " + ",".join(miss)
    if name == "approval_recorded":
        ok = find_record(b.p, o["id"], c.edge.get("choices"), arg) is not None
        return ok, f"回答の記録（scope={arg}）がありません"
    if name == "replans_lt_limit":
        return o.get("replans", 0) < b.limit("replans"), "道のりの差し戻しが上限に達しています"
    if name == "all_goals_done":
        gs = goal_graph(b, o["id"])
        return bool(gs) and all(g["status"] == "達成" for g in gs.values()), "達成していない達成条件があります"
    if name in ("cross_check_clean", "cross_check_suspect"):
        r = cross_check(b, o["id"])["result"]
        return (r == "clean") == (name == "cross_check_clean"), f"cross-check は {r} です"
    if name == "dependents_confirmed":
        if c.kind == "quest":
            return True, ""
        live = [x["id"] for x in d["goals"].values() if o["id"] in x.get("depends_on", []) and x["status"] not in GOAL_TERMINAL + ["失敗"]]
        return (not live) or o.get("dependents_confirmed", False) or bool(c.data.get("force_dependents")), \
            "後続の達成条件があります。依頼主の確認が要ります: " + ",".join(live)
    if name == "fix_kind_goal":
        flagged = [g for g in b.goals_of(o["id"]) if g.get("findings") and g["findings"][-1]["fix_kind"] == "goal"]
        return bool(flagged), "fix_kind が goal の指摘がありません"
    if name == "was_before_hold":
        return o.get("status_before_hold") == c.to, "保留前の状態と合いません"
    if name == "route_approved":
        q = b.quest(o["quest"])
        return bool(q.get("approved_at")) and q["status"] == "進行中", "道のりが承認されていません"
    if name == "quest_replanning":
        return b.quest(o["quest"])["status"] == "分解中", "クエストが分解中ではありません"
    if name == "quest_final_review":
        return b.quest(o["quest"])["status"] == "最終鑑定", "クエストが最終鑑定ではありません"
    if name == "deps_done":
        bad = [x for x in o.get("depends_on", []) if d["goals"].get(x, {}).get("status") != "達成"]
        return not bad, "前提が達成していません: " + ",".join(bad)
    if name == "slot_free":
        n = len([g for g in d["goals"].values() if g["status"] == "冒険中"])
        return n < b.limit("max_active"), f"同時数の上限です（{n}）"
    if name == "no_overlap":
        mine = set(o.get("notes_touched", []))
        for g in d["goals"].values():
            if g["status"] == "冒険中" and g["id"] != o["id"] and mine & set(g.get("notes_touched", [])):
                return False, f"触るノートが {g['id']} と重なっています"
        return True, ""
    if name == "output_present":
        outs = goal_outputs(b, o)
        return bool(outs) and all(f.exists() for f in outs), "納品物がありません"
    if name == "report_present":
        fs = report_files(b, o["id"], "adventurer")
        ok = bool(fs) and md_section(fs[-1].read_text(encoding="utf-8", errors="replace"), "result") is not None
        return ok, "冒険者の報告書（## result）がありません"
    if name == "precheck_ok":
        r = pre_check(b, o["id"])
        return r["ok"], "pre-check が NG です: " + " / ".join(r["issues"][:3])
    if name == "retries_lt_limit":
        q = b.quest(o["quest"])
        ok = o.get("retries", 0) <= b.limit("retries") + o.get("retry_bonus", 0) \
            and q.get("rework_total", 0) <= b.limit("rework_total") + q.get("rework_bonus", 0)
        return ok, "手直しの上限です。依頼主に聞きます"
    if name == "done_when_met":
        return bool(report_files(b, o["id"], "appraiser")), "鑑定士の報告書がありません"
    if name == "needs_execute":
        return bool(o.get("needs_execute")), "元に戻せない操作はありません"
    if name == "not_needs_execute":
        return not o.get("needs_execute"), "元に戻せない操作があります。実行の承認が要ります"
    if name == "finding_recorded":
        return bool(o.get("finding_pending")), "指摘（fix_kind・point_code）が書かれていません"
    raise GuildError(f"未対応の述語です: {name}")


# ---------------------------------------------------------------- 状態遷移
GOAL_LOG_TEXT = {
    ("案", "待機"): "あなたが道のりを承認した。",
    ("待機", "冒険中"): "冒険者が作業を始めた。",
    ("冒険中", "鑑定中"): "冒険者が作業を終えた。鑑定士が確かめている。",
    ("鑑定中", "確認待ち"): "鑑定士が確かめた。問題はなかった。あなたの確認を待っている。",
    ("確認待ち", "達成"): "あなたが確認した。この達成条件は達成した。",
    ("確認待ち", "実行承認待ち"): "あなたの実行の承認を待っている。",
    ("実行承認待ち", "達成"): "あなたが承認した。実行して、達成した。",
    ("実行承認待ち", "失敗"): "あなたが承認しなかった。実行を止めた。",
    ("確認待ち", "実行承認待ち"): "あなたの実行の承認を待っている。",
}


def goal_log_text(g, frm, to, who, text, reason):
    if (frm, to) == ("鑑定中", "要手直し"):
        return f"鑑定士が直す点を見つけた：「{text or (g['findings'][-1]['point'] if g.get('findings') else '')}」。"
    if (frm, to) == ("確認待ち", "要手直し"):
        return f"あなたが直す点を伝えた：「{text or ''}」。"
    if (frm, to) == ("要手直し", "冒険中"):
        return f"冒険者が直して、もう一度作業を始めた（{g.get('retries', 0)} 回目）。"
    if to == "要手直し" and frm in ("冒険中", "実行承認待ち"):
        return f"作業を直す必要が出た：「{REWORK_REASONS.get(reason, text or '')}」。"
    if to == "失敗" and frm not in ("実行承認待ち",):
        return f"この達成条件は達成できなかった。理由：「{text or ''}」。"
    if to == "中止":
        return "あなたが中止した。"
    if who == "workshop" and to in ("冒険中", "確認待ち"):
        return f"あなたと一緒に工房で作業した：「{text or ''}」。"
    if to == "案":
        return "計画を作り直すため、案に戻した。"
    if (frm, to) == ("失敗", "要手直し"):
        return "あなたがやり直しを選んだ。"
    return GOAL_LOG_TEXT.get((frm, to), "")


def resolve_edge(b, kind, obj, to, who, data=None):
    frm = obj["status"]
    edges = [e for e in b.t[kind] if e["from"] == frm and e["to"] == to]
    if not edges:
        raise GuildError(f"{kind} に辺がありません: {frm}→{to}")
    ok = [e for e in edges if who in e["actor"]]
    if not ok:
        allowed = sorted({a for e in edges for a in e["actor"]})
        raise GuildError(f"役 {who} は {frm}→{to} を通せません（通せる役: {', '.join(allowed)}）")
    reasons = []
    for e in ok:
        c = Ctx(kind, obj, frm, to, who, data)
        c.edge = e
        if e.get("reasons") and (data or {}).get("reason") not in e["reasons"]:
            reasons.append(f"理由（reason）が必要です: {', '.join(e['reasons'])}")
            continue
        rec = None
        if "client" in e["actor"] and who == "client":
            scope_g = next((parse_guard(g)[1] for g in e["guards"] if parse_guard(g)[0] == "approval_recorded"), None)
            rec = find_record(b.p, obj["id"], e.get("choices"), scope_g)
            if rec is None:
                reasons.append(f"依頼主の回答の記録がありません（選択: {', '.join(e.get('choices', []))}）")
                continue
        failed = False
        for g in e["guards"]:
            name, arg = parse_guard(g)
            if name == "approval_recorded":
                continue
            ok_g, msg = eval_guard(b, name, arg, c)
            if not ok_g:
                reasons.append(f"{g}: {msg}")
                failed = True
                break
        if failed:
            continue
        return e, rec
    raise GuildError(f"{frm}→{to} を通せません: " + " ／ ".join(reasons))


def check_touch(edge, who, touch):
    for place in touch or []:
        if place not in edge.get("writes", []):
            raise GuildError(f"この辺は {place} に書けません（書けるのは {', '.join(edge.get('writes', []))}）")
        if place not in ROLE_WRITES.get(who, []):
            raise GuildError(f"役 {who} は {place} に書けません")


def set_status(b, oid, to, who="guildmaster", text="", reason=None, touch=None, goals=None, force_dependents=False):
    if who not in ACTORS:
        raise GuildError(f"不明な役です: {who}")
    if re.fullmatch(r"Q\d+", oid):
        kind, obj = "quest", b.quest(oid)
    elif re.fullmatch(r"G\d+", oid):
        kind, obj = "goal", b.goal(oid)
    else:
        raise GuildError(f"状態を変えられる id は Q／G です: {oid}")
    if to not in (QUEST_STATES if kind == "quest" else GOAL_STATES):
        raise GuildError(f"不明な状態です: {to}")
    frm = obj["status"]
    edge, rec = resolve_edge(b, kind, obj, to, who, {"reason": reason, "force_dependents": force_dependents})
    check_touch(edge, who, touch)
    stamp = iso(now())
    if rec is not None:
        if not text:
            text = rec.get("comment", "")
        consume(rec)
        qid_ = rec.get("question")
        if qid_:
            for q in b.d["questions"]:
                if q["id"] == qid_:
                    q["handled"] = True
    obj["status"] = to
    ename = f"{frm}→{to}"
    if kind == "goal":
        post_goal(b, obj, frm, to, who, text, reason, stamp)
        line = goal_log_text(obj, frm, to, who, text, reason)
        if line:
            obj.setdefault("log", []).append({"time": stamp, "who": who, "edge": ename, "text": line})
    else:
        post_quest(b, obj, frm, to, who, text, stamp, goals)
        obj.setdefault("log", []).append({"time": stamp, "who": who, "edge": ename, "text": text or ""})
    return ename


def post_goal(b, g, frm, to, who, text, reason, stamp):
    q = b.quest(g["quest"])
    if to == "冒険中" and frm == "待機":
        g["started_at"] = stamp
    if to == "冒険中" and frm == "要手直し":
        g["retries_applied"] = g.get("retries", 0)
    if to == "要手直し":
        g["retries"] = g.get("retries", 0) + 1
        q["rework_total"] = q.get("rework_total", 0) + 1
        if frm == "確認待ち":
            record_finding(b, g, "brief", "", "output", text or "依頼主が直す点を伝えた", None, None, quiet_rule=True)
        g["finding_pending"] = False
        over = g["retries"] > b.limit("retries") + g.get("retry_bonus", 0) \
            or q["rework_total"] > b.limit("rework_total") + q.get("rework_bonus", 0)
        if over:
            add_question(b, kind="confirm", scope="none", quest=q["id"], goal=g["id"],
                         text=f"「{g['title']}」の手直しが上限に達しました。どうしますか？",
                         options=[{"label": "続ける", "reason": "もう少し直して、もう一度作業する", "recommended": False},
                                  {"label": "工房で直す", "reason": "あなたと一緒に直す", "recommended": False},
                                  {"label": "諦める", "reason": "この達成条件を終える", "recommended": False}],
                         default=None, tag="rework_limit")
    if to == "達成":
        g["closed_at"] = stamp
    if to in ("失敗", "中止"):
        g["closed_at"] = stamp
        propagate_dependents(b, g)
    if to == "確認待ち":
        g["precheck"] = pre_check(b, g["id"])


def propagate_dependents(b, g):
    deps = [x for x in b.d["goals"].values() if g["id"] in x.get("depends_on", []) and x["status"] not in GOAL_TERMINAL]
    if not deps:
        return
    for x in deps:
        if any(q for q in b.d["questions"] if q.get("tag") == "dependent" and q.get("goal") == g["id"]
               and q["status"] == "未回答"):
            break
    else:
        add_question(b, kind="confirm", scope="none", quest=g["quest"], goal=g["id"],
                     text=f"達成条件「{g['title']}」が終わりました。後ろの達成条件をどうしますか？",
                     options=[{"label": lb, "reason": "", "recommended": False} for lb in DEPENDENT_OPTIONS],
                     default=None, tag="dependent", covers=[g["id"]] + [x["id"] for x in deps])


def post_quest(b, q, frm, to, who, text, stamp, goals):
    qid = q["id"]
    if to == "保留":
        q["status_before_hold"] = frm
    if frm == "保留":
        q["status_before_hold"] = None
    if to in QUEST_TERMINAL:
        q["closed_at"] = stamp
    if (frm, to) == ("承認待ち", "進行中"):
        q["approved_at"] = stamp
        for g in b.goals_of(qid):
            if g["status"] == "案":
                set_status(b, g["id"], "待機", "guildmaster")
    if (frm, to) == ("進行中", "分解中"):
        q["replans"] = q.get("replans", 0) + 1
        q["approved_at"] = None
        for g in b.goals_of(qid):
            if g["status"] not in ("達成", "中止", "案"):
                set_status(b, g["id"], "案", "guildmaster")
    if to == "中止":
        for g in b.goals_of(qid):
            if g["status"] != "達成" and g["status"] != "中止":
                g["dependents_confirmed"] = True
                rec = {"covers": [g["id"]], "choice": "中止", "scope": "none", "quest": qid, "goal": g["id"],
                       "time": stamp, "consumed": False, "auto": True}
                write_record(b.p, f"D{g['id']}-{stamp.replace(':', '').replace('-', '')}", rec)
                set_status(b, g["id"], "中止", "client")
        for qq in b.d["questions"]:
            if qq["quest"] == qid and qq["status"] == "未回答":
                qq["status"] = "保留"
    if (frm, to) == ("最終鑑定", "進行中"):
        q["status"] = "最終鑑定"  # 達成→要手直し の述語が、最終鑑定中かを見る
        try:
            for gid in goals or []:
                set_status(b, gid, "要手直し", "appraiser")
        finally:
            q["status"] = "進行中"
    q["blocked_on"] = q.get("blocked_on", "")


# ---------------------------------------------------------------- 質問・回答・指摘
def default_due(days=DEFAULT_DUE_DAYS):
    return iso(now() + datetime.timedelta(days=days))


def add_question(b, kind, scope, quest, text, options=None, default=None, goal=None, diagram=None,
                 due=None, blocking=None, tag=None, covers=None, extra=None):
    if kind not in Q_KINDS:
        raise GuildError(f"kind が不明です: {kind}")
    if scope not in Q_SCOPES:
        raise GuildError(f"scope が不明です: {scope}")
    b.quest(quest)
    if goal:
        b.goal(goal)
    options = options or []
    if not 0 <= len(options) <= 4:
        raise GuildError("選択肢は 4 個までです")
    if default is not None and default not in [o["label"] for o in options]:
        raise GuildError("default は選択肢のどれかにしてください")
    if scope == "route" and not diagram:
        diagram = f"diagrams/route-{quest}.svg"
    qid = b.next_id("A")
    q = {"id": qid, "kind": kind, "scope": scope, "quest": quest, "goal": goal, "text": text, "diagram": diagram,
         "options": options, "default": default, "due": due or default_due(), "status": "未回答",
         "answer": None, "comment": "", "asked": iso(now()),
         "blocking": (kind not in NONBLOCKING_KINDS) if blocking is None else blocking}
    if tag:
        q["tag"] = tag
    if covers:
        q["covers"] = covers
    if extra:
        q.update(extra)
    b.d["questions"].append(q)
    return qid


def answer_question(b, aid, choice, comment="", auto=False, point_code=None):
    q = b.question(aid)
    if q["status"] == "回答済" and not auto:
        raise GuildError(f"{aid} はすでに回答済みです（取り消すには reopen）")
    labels = [o["label"] for o in q["options"]]
    if q["kind"] != "todo" and labels and choice not in labels and not comment:
        raise GuildError(f"選択肢にありません: {choice}（{', '.join(labels)}）")
    if choice == "あとで決める":
        q["status"] = "保留"
        return q
    q["status"] = "回答済"
    q["answer"] = choice
    q["comment"] = comment
    q["handled"] = False
    covers = q.get("covers") or [q.get("goal") or q["quest"]]
    rec = {"question": aid, "quest": q["quest"], "goal": q.get("goal"), "covers": covers, "scope": q["scope"],
           "choice": choice, "comment": comment, "time": iso(now()), "consumed": False, "auto": auto}
    if point_code:
        rec["point_code"] = point_code
    write_record(b.p, aid, rec)
    apply_answer_effects(b, q, choice)
    return q


def apply_answer_effects(b, q, choice):
    if q["kind"] == "rule" and choice == "掟に足す":
        add_rule(b, q)
        q["handled"] = True
    if q.get("tag") == "rework_limit" and choice == "続ける":
        g = b.goal(q["goal"])
        g["retry_bonus"] = g.get("retry_bonus", 0) + b.limit("retries")
        qu = b.quest(g["quest"])
        qu["rework_bonus"] = qu.get("rework_bonus", 0) + b.limit("retries")
    if q.get("tag") == "dependent" and choice == "この達成条件なしで進める":
        for gid in (q.get("covers") or [])[1:]:
            g = b.goal(gid)
            g["depends_on"] = [x for x in g.get("depends_on", []) if x != q["goal"]]
        q["handled"] = True
    if q["kind"] in ("rule", "term", "choice") and choice not in ("掟に足す",):
        if q["kind"] in ("rule", "term"):
            q["handled"] = True


def reopen_question(b, aid):
    q = b.question(aid)
    for r in read_records(b.p):
        if r.get("question") == aid and not r.get("consumed"):
            Path(r["_file"]).unlink()
    q["status"] = "未回答"
    q["answer"] = None
    q["comment"] = ""
    q["handled"] = False
    return q


def record_finding(b, g, fix_kind, point_code, target, point, rule_text, rule_actor, quiet_rule=False):
    if fix_kind not in FIX_KINDS:
        raise GuildError(f"fix_kind は {FIX_KINDS} のどれかです")
    if point_code and point_code not in POINT_CODES:
        raise GuildError(f"point_code は {POINT_CODES} のどれかです")
    g.setdefault("findings", []).append({"fix_kind": fix_kind, "point_code": point_code, "target": target, "point": point})
    g["finding_pending"] = True
    if not point_code:
        return 0
    key = f"{fix_kind}|{point_code}|{target}"
    counts = b.d.setdefault("finding_counts", {})
    counts[key] = counts.get(key, 0) + 1
    rules = b.d.setdefault("rules", {})
    adopted = [r for r in rules.values() if r["key"] == key]
    if adopted:
        adopted[0]["recurrences"] = adopted[0].get("recurrences", 0) + 1
        write_rules(b)
    elif counts[key] == 2 and not quiet_rule:
        add_question(b, kind="rule", scope="none", quest=g["quest"], goal=g["id"],
                     text=f"同じ指摘が 2 回出ました。掟に足しますか？：{rule_text or point}",
                     options=[{"label": "掟に足す", "reason": "次から、同じ指摘を防ぐ", "recommended": True},
                              {"label": "見送る", "reason": "いまは足さない", "recommended": False}],
                     default="掟に足す", extra={"rule_key": key, "rule_text": rule_text or point,
                                              "rule_actor": rule_actor or "_all"})
    return counts[key]


def add_rule(b, q):
    rules = b.d.setdefault("rules", {})
    rid = b.next_id("R")
    actor = q.get("rule_actor") or "_all"
    rules[rid] = {"id": rid, "key": q["rule_key"], "actor": actor, "text": q["rule_text"],
                  "added": iso(now())[:10], "recurrences": 0}
    write_rules(b)


def write_rules(b):
    b.p.rules.mkdir(parents=True, exist_ok=True)
    by_actor = {}
    for r in b.d.get("rules", {}).values():
        by_actor.setdefault(r["actor"], []).append(r)
    for actor, rs in by_actor.items():
        if len(rs) > RULE_FILE_MAX_LINES:
            raise GuildError(f"掟は 1 ファイル {RULE_FILE_MAX_LINES} 行までです（{actor}）。見直してください")
        lines = [f"- {r['id']}｜{r['added']}｜根拠: {r['key'].replace('|', '+')}｜再発 {r.get('recurrences', 0)}｜{r['text']}" for r in rs]
        (b.p.rules / f"{actor}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_notice(b, text, stops=None):
    n = b.d["notices"]
    n.append({"time": iso(now()), "text": text, "stops": stops or []})
    del n[:-NOTICE_MAX]


# ---------------------------------------------------------------- tick / apply-simple / need-claude
def tick(b):
    t = now()
    done = {"defaulted": [], "reminded": [], "held": []}
    for q in b.d["questions"]:
        if q["status"] != "未回答":
            continue
        due = parse_dt(q["due"])
        asked = parse_dt(q.get("asked", q["due"]))
        if q["kind"] == "approval":
            if t >= due:
                last = parse_dt(q["last_reminded"]) if q.get("last_reminded") else None
                if last is None or t - last >= datetime.timedelta(days=REMIND_DAYS):
                    add_notice(b, f"承認待ちです：{q['text']}", stops=[q["id"]])
                    q["last_reminded"] = iso(t)
                    done["reminded"].append(q["id"])
            if q["scope"] == "execute" and t - asked >= datetime.timedelta(days=HOLD_DAYS):
                hold_quest(b, q["quest"], "実行の承認が 14 日たっても届かないため、止めた。", done)
            continue
        if t < due:
            continue
        if q.get("default"):
            answer_question(b, q["id"], q["default"], "期限が来たため、推奨案で進めた。", auto=True)
            done["defaulted"].append(q["id"])
        elif t - asked >= datetime.timedelta(days=HOLD_DAYS):
            hold_quest(b, q["quest"], "返事が 14 日たっても届かないため、止めた。", done)
    return done


def hold_quest(b, qid, text, done):
    q = b.quest(qid)
    if q["status"] in QUEST_TERMINAL or q["status"] == "保留":
        return
    try:
        set_status(b, qid, "保留", "tick", text=text)
        add_notice(b, f"クエスト「{q['title']}」を止めました。{text}")
        done["held"].append(qid)
    except GuildError:
        pass


REQUEST_KINDS = {"setting", "priority", "goal_setting", "cancel", "evaluation", "hold", "final_review"}


def pending_requests(paths):
    out = []
    if paths.requests.exists():
        for f in sorted(paths.requests.glob("*.json")):
            try:
                out.append((f, json.loads(f.read_text(encoding="utf-8"))))
            except ValueError:
                continue
    return out


def move_request(paths, f, sub="済"):
    dest = paths.requests / sub
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(f), str(dest / f.name))


def ingest_answers(b):
    """画面が answers/ に書いた回答を、board.json の質問に取り込む（画面は board.json を書けない）。"""
    done = []
    qs = {q["id"]: q for q in b.d["questions"]}
    for r in read_records(b.p):
        aid = r.get("question")
        if not aid or aid not in qs or r.get("consumed"):
            continue
        q = qs[aid]
        f = Path(r["_file"])
        if r.get("reopen"):
            f.unlink()
            q.update({"status": "未回答", "answer": None, "comment": "", "handled": False})
            done.append(aid)
            continue
        choice = r.get("choice")
        if not choice:
            continue
        if q["status"] == "回答済" and q["answer"] == choice:
            continue
        if q["status"] == "保留" and choice == "あとで決める":
            continue
        q["status"] = "未回答"
        answer_question(b, aid, choice, r.get("comment", ""), auto=bool(r.get("auto")), point_code=r.get("point_code"))
        done.append(aid)
    return done


def apply_simple(b):
    summary = {"ingested": ingest_answers(b), "tick": tick(b), "applied": [], "skipped": []}
    reqs = pending_requests(b.p)
    settings = [(f, r) for f, r in reqs if r.get("kind") == "setting"]
    for f, r in reqs:
        kind = r.get("kind")
        try:
            if kind == "setting":
                if (f, r) != settings[-1]:
                    move_request(b.p, f)
                    continue
                n = int(r["max_active"])
                if not 1 <= n <= 8:
                    raise GuildError("同時数は 1〜8 です")
                b.d["limits"]["max_active"] = n
            elif kind == "priority":
                if r.get("priority") not in PRIORITIES:
                    raise GuildError("優先度が不明です")
                b.quest(r["quest"])["priority"] = r["priority"]
            elif kind == "goal_setting":
                b.goal(r["goal"])["effort"] = "高" if r.get("careful", True) else "中"
            elif kind == "cancel":
                apply_cancel(b, r)
            elif kind == "hold":
                q = b.quest(r["quest"])
                if r.get("action", "hold") == "hold":
                    decide(b, q["id"], "保留")
                    set_status(b, q["id"], "保留", "client")
                else:
                    decide(b, q["id"], "再開")
                    set_status(b, q["id"], q["status_before_hold"] or "", "client")
            elif kind == "final_review":
                decide(b, r["quest"], "最終鑑定を頼む")
                set_status(b, r["quest"], "最終鑑定", "client")
            elif kind == "evaluation":
                fid = b.next_id("F")
                if r.get("score") not in ("good", "bad"):
                    raise GuildError("score は good か bad です")
                b.d["feedbacks"][fid] = {"quest": r["quest"], "goal": r.get("goal"), "score": r["score"],
                                         "reason": r.get("reason", ""), "comment": r.get("comment", "")}
                b.d["feedbacks"][fid]["id"] = fid
            else:
                continue
            move_request(b.p, f)
            summary["applied"].append(f.name)
        except (GuildError, KeyError, ValueError) as e:
            summary["skipped"].append({"file": f.name, "error": str(e)})
            move_request(b.p, f, "保留")
    return summary


def apply_cancel(b, r):
    if r.get("goal"):
        g = b.goal(r["goal"])
        live = [x for x in b.d["goals"].values() if g["id"] in x.get("depends_on", []) and x["status"] not in GOAL_TERMINAL + ["失敗"]]
        if live and not g.get("dependents_confirmed"):
            add_question(b, kind="confirm", scope="none", quest=g["quest"], goal=g["id"],
                         text=f"達成条件「{g['title']}」を取り下げます。後ろの達成条件をどうしますか？",
                         options=[{"label": lb, "reason": "", "recommended": False} for lb in DEPENDENT_OPTIONS],
                         default=None, tag="dependent", covers=[g["id"]] + [x["id"] for x in live])
            return
        decide(b, g["id"], "中止", scope="none")
        set_status(b, g["id"], "中止", "client")
    else:
        decide(b, r["quest"], "中止", scope="none")
        set_status(b, r["quest"], "中止", "client")


def decide(b, oid, choice, scope="none", comment=""):
    stamp = iso(now())
    n = len(list(b.p.answers.glob("D*.json"))) + 1 if b.p.answers.exists() else 1
    rec = {"question": None, "quest": oid if oid.startswith("Q") else b.goal(oid)["quest"],
           "goal": oid if oid.startswith("G") else None, "covers": [oid], "scope": scope, "choice": choice,
           "comment": comment, "time": stamp, "consumed": False, "auto": False}
    write_record(b.p, f"D{n}-{oid}", rec)


def need_claude(b):
    reasons = []
    if any(r.get("kind") in ("quest", "upload") for _, r in pending_requests(b.p)):
        reasons.append("new_request")
    if any(q["status"] == "回答済" and not q.get("handled") and q["kind"] not in NONBLOCKING_KINDS for q in b.d["questions"]):
        reasons.append("answered_question")
    for q in b.d["quests"].values():
        st = q["status"]
        if st == "受付":
            opens = [x for x in b.d["questions"] if x["quest"] == q["id"] and x["status"] == "未回答" and x["kind"] in ("choice", "todo")]
            if not opens:
                reasons.append(f"intake:{q['id']}")
        elif st == "分解中":
            reasons.append(f"decompose:{q['id']}")
        elif st == "最終鑑定":
            reasons.append(f"final_review:{q['id']}")
        elif st == "進行中":
            gs = goal_graph(b, q["id"])
            if gs and all(g["status"] == "達成" for g in gs.values()):
                reasons.append(f"close:{q['id']}")
            for g in gs.values():
                if g["status"] in ("冒険中", "鑑定中"):
                    reasons.append(f"work:{g['id']}")
                elif g["status"] == "要手直し" and not any(x for x in b.d["questions"] if x.get("goal") == g["id"] and x["status"] == "未回答"):
                    reasons.append(f"rework:{g['id']}")
                elif g["status"] == "待機" and ready_goal(b, g):
                    reasons.append(f"depart:{g['id']}")
    return reasons


def ready_goal(b, g):
    c = Ctx("goal", g, "待機", "冒険中", "guildmaster")
    for name in ("deps_done", "slot_free", "no_overlap"):
        if not eval_guard(b, name, None, c)[0]:
            return False
    return True


def ready_list(b):
    rows = []
    for g in b.d["goals"].values():
        q = b.quest(g["quest"])
        if g["status"] == "待機" and q["status"] == "進行中" and ready_goal(b, g):
            slack = route_check(b, q["id"])["slack"].get(g["id"], 10 ** 9)
            rows.append((slack, 0 if q.get("priority") == "優先" else 1, idnum(g["id"]), g["id"]))
    return [r[3] for r in sorted(rows)]


# ---------------------------------------------------------------- アーカイブ
def archive(b, days):
    cutoff = now() - datetime.timedelta(days=days)
    moved = []
    arch = {"quests": {}, "goals": {}}
    if b.p.archive.exists():
        arch = json.loads(b.p.archive.read_text(encoding="utf-8"))
    for qid, q in list(b.d["quests"].items()):
        if q["status"] in ("達成", "中止") and q.get("closed_at") and parse_dt(q["closed_at"]) <= cutoff:
            arch["quests"][qid] = q
            for gid in q["goals"]:
                arch["goals"][gid] = b.d["goals"].pop(gid)
            del b.d["quests"][qid]
            moved.append(qid)
    if moved:
        b.p.archive.write_text(json.dumps(arch, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        b.d["questions"] = [x for x in b.d["questions"] if x["quest"] not in moved]
    return moved


# ---------------------------------------------------------------- 出力：クエスト票・要約・図
def goal_link(b, g):
    op = g.get("output_path") or []
    return [op] if isinstance(op, str) else list(op)


def render_quest_text(b, qid):
    q = b.quest(qid)
    order = []
    try:
        order = topo_order(goal_graph(b, qid))
    except GuildError:
        order = [g["id"] for g in b.goals_of(qid) if g["status"] != "中止"]
    cancelled = [g["id"] for g in b.goals_of(qid) if g["status"] == "中止"]
    lines = [f"# {q['title']}", "", "## 目的", q.get("detail") or q["title"], "", "## 達成条件",
             "| 順 | 達成条件 | 締切 | いまの様子 |", "|---|---|---|---|"]
    for i, gid in enumerate(order + cancelled, 1):
        g = b.goal(gid)
        state = GOAL_LABELS[g["status"]]
        outs = goal_link(b, g)
        if g["status"] == "達成" and outs:
            state += "（" + "、".join(f"[{Path(o).name}]({o.replace(' ', '%20')})" for o in outs) + "）"
        lines.append(f"| {i} | {g['title']} | {jp_date(g.get('deadline'))} | {state} |")
    lines += ["", "## 記録"]
    for i, gid in enumerate(order + cancelled, 1):
        g = b.goal(gid)
        lines.append(f"### {i}. {g['title']}")
        entries = [e for e in g.get("log", []) if e.get("text")]
        if not entries:
            lines.append("（まだ始めていない）")
        for e in entries:
            lines.append(f"- {jp_stamp(e['time'])}　{e['text']}")
        for ref in g.get("refs", []):
            lines.append(f"- 魔導書「{ref}」を参考にした。")
        lines.append("")
    lines.append("## あなたがすること")
    todo = []
    for x in b.d["questions"]:
        if x["quest"] == qid and x["status"] == "未回答":
            todo.append(f"- 質問に答える：「{x['text']}」")
    for gid in order:
        g = b.goal(gid)
        if g["status"] == "確認待ち":
            links = "、".join(f"[{Path(o).name}]({o.replace(' ', '%20')})" for o in goal_link(b, g))
            todo.append(f"- 「{g['title']}」を確認する" + (f"（{links}）" if links else "") + "。")
        elif g["status"] == "実行承認待ち":
            todo.append(f"- 「{g['title']}」の実行を承認する。")
    if q["status"] == "承認待ち":
        todo.insert(0, "- 道のりを確認して、承認する。")
    lines += todo or ["いまはありません。"]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_quest(b, qid):
    qd = b.qdir(qid)
    qd.mkdir(parents=True, exist_ok=True)
    (qd / "quest.md").write_text(render_quest_text(b, qid), encoding="utf-8")
    write_diagram(b, qid)
    return qd / "quest.md"


def write_diagram(b, qid):
    """画面が読む道のり図（SVG）。閉路などで描けないときは作らない。"""
    d = b.p.sys / "diagrams"
    try:
        svg, sentence = render_route_svg(b, qid)
    except GuildError:
        return None
    d.mkdir(parents=True, exist_ok=True)
    (d / f"route-{qid}.svg").write_text(svg + "\n", encoding="utf-8")
    (d / f"route-{qid}.txt").write_text(sentence + "\n", encoding="utf-8")
    return d / f"route-{qid}.svg"


def summary(b):
    lines = []
    live = [q for q in b.d["quests"].values() if q["status"] not in QUEST_TERMINAL]
    for q in sorted(live, key=lambda x: idnum(x["id"])):
        gs = [b.d["goals"][g] for g in q["goals"]]
        wait = {"client": "依頼主待ち", "guild": "ギルド", "": ""}[q.get("blocked_on", "")]
        lines.append(f"{q['id']} {q['title']}｜{q['status']}｜{wait}")
        cnt = {}
        for g in gs:
            cnt[g["status"]] = cnt.get(g["status"], 0) + 1
        lines.append("  " + (" ".join(f"{k}{v}" for k, v in cnt.items()) or "達成条件なし"))
    opens = len([x for x in b.d["questions"] if x["status"] == "未回答"])
    if opens:
        lines.append(f"未回答の質問 {opens} 件")
    if len(lines) > 30:
        lines = lines[:29] + [f"…ほか {len(lines) - 29} 行"]
    return "\n".join(lines) or "進行中のクエストはありません"


def x(s):
    return html.escape(str(s), quote=True)


def render_route_svg(b, qid):
    gs = goal_graph(b, qid)
    order = topo_order(gs)
    depth = {}
    for gid in order:
        depth[gid] = 1 + max([depth[d] for d in gs[gid].get("depends_on", [])] or [-1]) if gs[gid].get("depends_on") else 0
    cols = {}
    for gid in order:
        cols.setdefault(depth[gid], []).append(gid)
    W, H, GX, GY = 220, 64, 60, 24
    pos = {}
    for c, ids in cols.items():
        for r, gid in enumerate(ids):
            pos[gid] = (20 + c * (W + GX), 20 + r * (H + GY))
    width = 40 + (max(cols) + 1) * (W + GX) - GX if cols else 200
    height = 40 + max([len(v) for v in cols.values()] or [1]) * (H + GY) - GY
    q = b.quest(qid)
    desc = "、".join(f"{i}. {gs[g]['title']}" for i, g in enumerate(order, 1))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="t d">',
           f'<title id="t">{x(q["title"])}の道のり</title><desc id="d">{x(desc)}</desc>',
           '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
           '<path d="M0,0 L8,4 L0,8 z" fill="currentColor"/></marker></defs>']
    for gid in order:
        for dep in gs[gid].get("depends_on", []):
            x1, y1 = pos[dep][0] + W, pos[dep][1] + H / 2
            x2, y2 = pos[gid][0], pos[gid][1] + H / 2
            out.append(f'<path d="M{x1},{y1} C{x1 + GX / 2},{y1} {x2 - GX / 2},{y2} {x2},{y2}" fill="none" '
                       f'stroke="currentColor" stroke-width="1.5" marker-end="url(#ar)"><title>{x(gs[dep]["title"])}のあとに{x(gs[gid]["title"])}</title></path>')
    for i, gid in enumerate(order, 1):
        g = gs[gid]
        px, py = pos[gid]
        shape = {"達成": 'rx="28"', "確認待ち": 'rx="4" stroke-dasharray="6 3"'}.get(g["status"], 'rx="8"')
        sw = 3 if g["status"] == "達成" else 1.5
        out.append(f'<g><title>{x(g["title"])}：{x(GOAL_LABELS[g["status"]])}</title>'
                   f'<rect x="{px}" y="{py}" width="{W}" height="{H}" {shape} fill="none" stroke="currentColor" stroke-width="{sw}"/>'
                   f'<text x="{px + 10}" y="{py + 26}" font-size="14" fill="currentColor">{i}. {x(g["title"][:14])}</text>'
                   f'<text x="{px + 10}" y="{py + 48}" font-size="12" fill="currentColor">{x(GOAL_LABELS[g["status"]])}'
                   + (f'　締切 {x(jp_date(g["deadline"]))}' if g.get("deadline") else "") + '</text></g>')
    out.append("</svg>")
    sentence = f"このクエストは、{len(order)} 個の達成条件を、{ '、'.join(gs[g]['title'] for g in order[:5]) }の順で進める。"
    return "\n".join(out), sentence


# ---------------------------------------------------------------- 蓄積：教訓帳・人物伝・依頼書
def lessons_append(b, kind, point_code, text):
    if kind not in ("失敗", "成功"):
        raise GuildError("kind は 失敗／成功 です")
    p = b.p.lessons
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    lines.append(f"- {iso(now())[:10]}｜{point_code or '-'}｜{kind}｜{text}")
    if len(lines) > LESSONS_MAX_LINES:
        old = lines[:-LESSONS_MAX_LINES]
        lines = lines[-LESSONS_MAX_LINES:]
        with open(p.with_name("lessons-old.md"), "a", encoding="utf-8") as f:
            f.write("\n".join(old) + "\n")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def lessons_brief(b, point_code=None, limit=10):
    p = b.p.lessons
    if not p.exists():
        return []
    ls = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if point_code:
        ls = [ln for ln in ls if f"｜{point_code}｜" in ln]
    return ls[-limit:]


def profile_brief(b, limit=10):
    p = b.p.profile
    if not p.exists():
        return []
    ls = [ln.rstrip() for ln in p.read_text(encoding="utf-8").splitlines()
          if ln.strip() and not ln.lstrip().startswith("#") and not ln.startswith("---")]
    return ls[:limit]


def make_brief(b, gid, role):
    if role not in ACTORS:
        raise GuildError(f"不明な役です: {role}")
    g = b.goal(gid)
    q = b.quest(g["quest"])
    n = len(list(b.p.briefs.glob(f"{gid}-{role}*.md"))) if b.p.briefs.exists() else 0
    name = f"{gid}-{role}.md" if n == 0 else f"{gid}-{role}{n + 1}.md"
    L = [f"# 依頼書：{gid} {g['title']}（役：{role}）", "",
         f"- クエスト：{q['id']} {q['title']}", f"- 目的：{q.get('detail') or q['title']}",
         f"- effort：{g.get('effort', '中')}　納品物の形：{g.get('form', 'おまかせ')}",
         "- done_when：", *[f"  - {d}" for d in g.get("done_when", [])],
         f"- 素材の場所：{q['dir']}/input/", f"- 納品物の場所：{q['dir']}/output/",
         f"- 報告書の場所：.system/reports/{gid}-{role}.md"]
    if g.get("findings"):
        L += ["- これまでの指摘：", *[f"  - {f['fix_kind']}／{f['point_code']}／{f['target']}：{f['point']}" for f in g["findings"][-3:]]]
    rules = []
    for rf in (b.p.rules / f"{role}.md", b.p.rules / "_all.md"):
        if rf.exists():
            rules += rf.read_text(encoding="utf-8").splitlines()[:RULE_FILE_MAX_LINES]
    if rules:
        L += ["", "## 掟", *rules]
    if role in ("fortune_teller", "appraiser"):
        ls = lessons_brief(b)
        if ls:
            L += ["", "## 教訓帳（抜粋）", *ls]
    if role in ("receptionist", "fortune_teller", "alchemist", "workshop"):
        pb = profile_brief(b)
        if pb:
            L += ["", "## 人物伝（要約）", *pb]
    b.p.briefs.mkdir(parents=True, exist_ok=True)
    (b.p.briefs / name).write_text("\n".join(L) + "\n", encoding="utf-8")
    return b.p.briefs / name


def model_for(b, gid, role):
    """既定は sonnet。haiku は魔法使い。opus は錬金術師だけ（2.1-1）。"""
    g = b.goal(gid)
    if role == "wizard":
        return "haiku", "機械的な抽出"
    if role == "alchemist":
        if g.get("effort") == "高":
            return "opus", "effort が高"
        if g.get("retries", 0) >= 2 and g.get("findings") and g["findings"][-1].get("point_code") in ("矛盾", "誤り"):
            return "opus", "要手直し 2 回目で、指摘が矛盾か誤り"
    return "sonnet", "既定"


# ---------------------------------------------------------------- 冒険日誌
def log_append(b, gid, text=None, file=None):
    g = b.goal(gid)
    src = text if text is not None else Path(file).read_text(encoding="utf-8")
    sec = md_section(src, "log") if re.search(r"^##\s+log\s*$", src, re.M) else src
    d = b.qdir(g["quest"]) / "adventure log"
    d.mkdir(parents=True, exist_ok=True)
    stamp = now()
    f = d / f"{stamp.strftime('%Y%m%d-%H%M')}-{gid}.md"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(f"## {jp_stamp(iso(stamp))}\n{(sec or src).strip()}\n\n")
    did = md_section_h3(sec or "", "やったこと")
    for ln in bullets(did)[:3]:
        item = re.sub(r"^\s*([-*]|\d+[.)])\s+", "", ln).rstrip("。")
        sentence = item + "。" if item.startswith("冒険者が") else f"冒険者が{item}。"
        g.setdefault("log", []).append({"time": iso(stamp), "who": "adventurer", "edge": "log", "text": sentence})
    return f


def md_section_h3(text, name):
    m = re.search(rf"^###\s+{re.escape(name)}\s*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    n = re.search(r"^#{2,3}\s+", rest, re.M)
    return rest[: n.start()] if n else rest


# ---------------------------------------------------------------- gen-transitions
def transitions_md(t):
    out = []
    for kind, title in (("quest", "クエスト"), ("goal", "達成条件")):
        out += [f"### {title}の遷移", "", "| 辺 | 役 | 述語 | 説明 |", "|---|---|---|---|"]
        for e in t[kind]:
            out.append(f"| {e['from']}→{e['to']} | {'／'.join(e['actor'])} | {', '.join(e['guards']) or '—'} | {e['note']} |")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def transitions_svg(t):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 {H}" role="img" aria-labelledby="t d">',
             '<title id="t">状態遷移図</title><desc id="d">{D}</desc>',
             '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor"/></marker></defs>']
    y0 = 20
    desc = []
    for kind, states, title in (("quest", QUEST_STATES, "クエスト"), ("goal", GOAL_STATES, "達成条件")):
        pos = {}
        for i, s in enumerate(states):
            pos[s] = (20 + (i % 5) * 175, y0 + 30 + (i // 5) * 90)
        parts.append(f'<text x="20" y="{y0 + 14}" font-size="14" fill="currentColor">{x(title)}</text>')
        for e in t[kind]:
            a, c = pos[e["from"]], pos[e["to"]]
            parts.append(f'<line x1="{a[0] + 70}" y1="{a[1] + 16}" x2="{c[0] + 70}" y2="{c[1] + 16}" stroke="currentColor" stroke-width="0.8" '
                         f'opacity="0.55" marker-end="url(#ar)"><title>{x(e["from"])}→{x(e["to"])}（{x("／".join(e["actor"]))}）</title></line>')
            desc.append(f'{e["from"]}→{e["to"]}')
        for s, (px, py) in pos.items():
            parts.append(f'<rect x="{px}" y="{py}" width="140" height="32" rx="6" fill="Canvas" stroke="currentColor"/>'
                         f'<text x="{px + 70}" y="{py + 21}" text-anchor="middle" font-size="13" fill="currentColor">{x(s)}</text>')
        y0 += 30 + ((len(states) + 4) // 5) * 90 + 20
    parts.append("</svg>")
    return "\n".join(parts).replace("{H}", str(y0)).replace("{D}", x("、".join(desc[:20]) + " ほか"))


def gen_transitions(paths, skill=None, svg=None, check=False):
    t = load_transitions(paths)
    md = transitions_md(t)
    changed = []
    if skill:
        sp = Path(skill)
        text = sp.read_text(encoding="utf-8")
        a, z = TEMPLATE_MARK
        if a not in text or z not in text:
            raise GuildError(f"SKILL.md に {a} と {z} がありません")
        new = text[: text.index(a) + len(a)] + "\n" + md + text[text.index(z):]
        if new != text:
            changed.append(str(sp))
            if not check:
                sp.write_text(new, encoding="utf-8")
    if svg:
        sv = Path(svg)
        new = transitions_svg(t) + "\n"
        if not sv.exists() or sv.read_text(encoding="utf-8") != new:
            changed.append(str(sv))
            if not check:
                sv.parent.mkdir(parents=True, exist_ok=True)
                sv.write_text(new, encoding="utf-8")
    return changed


# ---------------------------------------------------------------- 予算・利用記録
def budget(b, use=0, quest=None, reset=False):
    run = b.d.setdefault("run", {"calls": 0})
    if reset:
        run["calls"] = 0
    mx = b.limit("budget")["max_calls"]
    if use:
        if run["calls"] + use > mx:
            if quest:
                q = b.quest(quest)
                q["budget_stops"] = q.get("budget_stops", 0) + 1
                add_notice(b, BUDGET_STOP_NOTICE)
                if q["budget_stops"] >= 3 and not any(k for k in b.d["questions"] if k.get("tag") == "budget" and k["status"] == "未回答"):
                    add_question(b, kind="confirm", scope="none", quest=quest,
                                 text="予算で 3 回続けて止まりました。どうしますか？",
                                 options=[{"label": "続ける", "reason": "もう一度、続きから進める", "recommended": False},
                                          {"label": "中止する", "reason": "このクエストを取り下げる", "recommended": False}],
                                 tag="budget")
            return False, mx - run["calls"]
        run["calls"] += use
    return True, mx - run["calls"]


def usage_log(b, role, model, tokens, quest=None, goal=None):
    b.p.logs.mkdir(parents=True, exist_ok=True)
    row = {"time": iso(now()), "role": role, "model": model, "tokens": int(tokens), "quest": quest, "goal": goal}
    with open(b.p.logs / "usage.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 復旧・初期化
def recover(paths):
    for i in (1, 2, 3):
        f = paths.backup / f"board.json.{i}"
        if not f.exists():
            continue
        try:
            validate(json.loads(f.read_text(encoding="utf-8")))
        except (ValueError, GuildError):
            continue
        if paths.board.exists():
            shutil.copy2(paths.board, paths.board.with_name("board.json.broken"))
        shutil.copy2(f, paths.board)
        return f"board.json.{i}"
    raise GuildError("戻せる世代がありません")


def new_board(vault_path="", python=""):
    return {"schema_version": 1, "python": python, "vault_path": vault_path, "updated": iso(now()),
            "limits": json.loads(json.dumps(DEFAULT_LIMITS)), "last_ids": {"Q": 0, "G": 0, "A": 0, "F": 0, "I": 0},
            "quests": {}, "goals": {}, "questions": [], "feedbacks": {}, "interviews": {},
            "profile_pending": 0, "notices": []}


def init_board(paths, vault_path="", python=""):
    for d in (paths.sys, paths.backup, paths.answers, paths.requests / "files", paths.requests / "済",
              paths.requests / "保留", paths.reports / "済", paths.briefs, paths.rules, paths.logs, paths.sys / "auto",
              paths.root / "quests", paths.root / "shared", paths.root / "templates"):
        d.mkdir(parents=True, exist_ok=True)
    if paths.board.exists():
        return False
    bd = Board.__new__(Board)
    bd.p, bd.t = paths, None
    bd.d = new_board(vault_path, python)
    bd.d["updated"] = iso(now())
    paths.board.write_text(json.dumps(bd.d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


# ---------------------------------------------------------------- クエスト・達成条件の追加
def safe_name(s):
    s = FORBIDDEN_NAME_CHARS.sub("", s).strip(" .")
    return s[:40] or "無題"


def add_quest(b, title, detail="", due=None, priority="通常"):
    if priority not in PRIORITIES:
        raise GuildError("優先度は 優先／通常 です")
    qid = b.next_id("Q")
    rel = f"quests/{qid} {safe_name(title)}"
    b.d["quests"][qid] = {"id": qid, "title": title, "detail": detail, "status": "受付", "status_before_hold": None,
                          "blocked_on": "", "priority": priority, "due": due, "goals": [], "route": [], "dir": rel,
                          "requested_at": iso(now()), "approved_at": None, "rework_total": 0, "replans": 0,
                          "budget_stops": 0, "log": []}
    for sub in ("input", "output", "adventure log"):
        (b.p.root / rel / sub).mkdir(parents=True, exist_ok=True)
    return qid


def add_goal(b, quest, title, done_when, effort="中", deadline=None, estimate_min=0, depends_on=None, form="おまかせ",
             template=None, output_path=None, needs_execute=False, notes_touched=None):
    q = b.quest(quest)
    if q["status"] not in ("受付", "分解中"):
        raise GuildError(f"達成条件を足せるのは、受付か分解中のクエストだけです（いま：{q['status']}）")
    if not 1 <= len(done_when) <= 3:
        raise GuildError("done_when は 1〜3 個です")
    if effort not in EFFORTS or form not in FORMS:
        raise GuildError("effort または form が不正です")
    if deadline:
        datetime.datetime.fromisoformat(deadline)
    gid = b.next_id("G")
    b.d["goals"][gid] = {"id": gid, "quest": quest, "title": title, "effort": effort, "done_when": done_when,
                         "deadline": deadline, "estimate_min": int(estimate_min), "actual_min": 0,
                         "depends_on": depends_on or [], "status": "案", "blocked_on": "", "form": form,
                         "template": template, "output_path": output_path or [], "needs_execute": needs_execute,
                         "notes_touched": notes_touched or [], "retries": 0, "findings": [], "refs": [], "log": []}
    q["goals"].append(gid)
    return gid


PROTECTED = {"id", "status", "quest", "goals", "closed_at"}


def set_field(b, oid, field, value, who="guildmaster"):
    if who not in ("guildmaster", "workshop", "tick", "client"):
        raise GuildError(f"役 {who} は board.json に書けません")
    if field in PROTECTED:
        raise GuildError(f"{field} は set では変えられません（set-status を使います）")
    if re.fullmatch(r"Q\d+", oid):
        b.quest(oid)[field] = value
    elif re.fullmatch(r"G\d+", oid):
        g = b.goal(oid)
        if field == "depends_on" and not isinstance(value, list):
            raise GuildError("depends_on はリストです")
        g[field] = value
    elif re.fullmatch(r"A\d+", oid):
        b.question(oid)[field] = value
    else:
        raise GuildError(f"set できる id は Q／G／A です: {oid}")


def set_top(b, key, value):
    if key == "limits":
        if not isinstance(value, dict):
            raise GuildError("limits は辞書です")
        for k, v in value.items():
            if k == "budget" and isinstance(v, dict):
                b.d["limits"]["budget"].update(v)
            else:
                b.d["limits"][k] = v
    elif key in ("profile_pending", "python", "vault_path"):
        b.d[key] = value
    else:
        raise GuildError(f"set-top できるキーは limits／profile_pending／python／vault_path です: {key}")


# ---------------------------------------------------------------- CLI
def out(obj):
    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=1))


def build_parser():
    ap = argparse.ArgumentParser(prog="board.py", description="guild 0.1 の board.py")
    ap.add_argument("--root", help="guild フォルダ（既定：このファイルの親の親、または GUILD_ROOT）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, *args, **kw):
        sp = sub.add_parser(name)
        for a in args:
            flags = a[0] if isinstance(a, tuple) else a
            opts = a[1] if isinstance(a, tuple) and len(a) > 1 else {}
            sp.add_argument(*([flags] if isinstance(flags, str) else flags), **opts)
        return sp

    add("version")
    add("init-board", ("--vault-path", {"default": ""}), ("--python", {"default": ""}))
    add("get", ("--summary", {"action": "store_true"}), ("--quest",), ("--goal",), ("--question",))
    add("add-quest", ("--title", {"required": True}), ("--detail", {"default": ""}), ("--due",), ("--priority", {"default": "通常"}))
    add("add-goal", ("--quest", {"required": True}), ("--title", {"required": True}),
        ("--done-when", {"action": "append", "required": True}), ("--effort", {"default": "中"}), ("--deadline",),
        ("--estimate-min", {"type": int, "default": 0}), ("--depends-on", {"default": ""}), ("--form", {"default": "おまかせ"}),
        ("--template",), ("--output-path", {"action": "append"}), ("--needs-execute", {"action": "store_true"}),
        ("--notes-touched", {"default": ""}))
    add("add-question", ("--quest", {"required": True}), ("--goal",), ("--kind", {"default": "choice"}),
        ("--scope", {"default": "none"}), ("--text", {"required": True}), ("--options", {"default": "[]"}),
        ("--default",), ("--due",), ("--diagram",), ("--no-block", {"action": "store_true"}))
    add("set-status", "id", "to", ("--who", {"default": "guildmaster"}), ("--text", {"default": ""}),
        ("--reason",), ("--touch", {"default": ""}), ("--goals", {"default": ""}), ("--force-dependents", {"action": "store_true"}))
    add("set", "id", "field", "value", ("--who", {"default": "guildmaster"}))
    add("set-top", "key", "value")
    add("route-check", "quest", ("--write", {"action": "store_true"}))
    add("ready")
    add("add-finding", "goal", ("--fix-kind", {"required": True}), ("--point-code", {"required": True}),
        ("--target", {"required": True}), ("--point", {"required": True}), ("--rule-text",), ("--rule-actor",))
    add("log-append", "goal", ("--file",), ("--text",))
    add("answer", "id", ("--choice", {"required": True}), ("--comment", {"default": ""}), ("--point-code",))
    add("reopen", "id")
    add("decide", "id", ("--choice", {"required": True}), ("--scope", {"default": "none"}), ("--comment", {"default": ""}))
    add("close-questions", ("--quest",), ("--ids", {"default": ""}))
    add("add-notice", ("--text", {"required": True}), ("--stops", {"default": ""}))
    add("apply-simple")
    add("tick")
    add("need-claude")
    add("archive", ("--days", {"type": int, "default": 30}))
    add("render-quest", "quest")
    add("render-route", "quest", ("--out",), ("--summary", {"action": "store_true"}))
    add("pre-check", "goal")
    add("cross-check", "quest")
    add("lessons-append", ("--kind", {"default": "失敗"}), ("--point-code", {"default": ""}), ("--text", {"required": True}))
    add("lessons-brief", ("--point-code",))
    add("profile-brief")
    add("make-brief", "goal", "role")
    add("model-for", "goal", "role")
    add("budget", ("--use", {"type": int, "default": 0}), ("--quest",), ("--reset", {"action": "store_true"}))
    add("usage-log", ("--role", {"required": True}), ("--model", {"required": True}), ("--tokens", {"default": 0}),
        ("--quest",), ("--goal",))
    add("recover")
    add("check-write", "role", "place")
    add("gen-transitions", ("--skill",), ("--svg",), ("--check", {"action": "store_true"}))
    return ap


READONLY = {"version", "get", "route-check-ro", "ready", "pre-check", "cross-check", "lessons-brief", "profile-brief",
            "model-for", "render-route", "check-write", "gen-transitions", "need-claude", "recover", "init-board"}


def split(s):
    return [p for p in (s or "").split(",") if p]


def run(args):
    c = args.cmd
    if c == "version":
        out(VERSION)
        return
    root = find_root(args.root)
    paths = Paths(root)
    if c == "recover":
        out(f"戻しました: {recover(paths)}")
        return
    if c == "init-board":
        out("作りました" if init_board(paths, args.vault_path, args.python) else "すでにあります")
        return
    if c == "check-write":
        if args.place not in ROLE_WRITES.get(args.role, []):
            raise GuildError(f"役 {args.role} は {args.place} に書けません")
        out("OK")
        return
    if c == "gen-transitions":
        changed = gen_transitions(paths, args.skill, args.svg, args.check)
        if args.check and changed:
            raise GuildError("生成物が transitions.json と合っていません: " + ", ".join(changed))
        out("更新: " + ", ".join(changed) if changed else "変更なし")
        return
    mutating = c not in READONLY and not (c == "route-check" and not args.write)
    if mutating:
        with Lock(paths):
            b = Board(paths).load()
            result = dispatch(b, args, paths)
            b.save()
    else:
        b = Board(paths).load()
        result = dispatch(b, args, paths)
    if result is not None:
        out(result)


def dispatch(b, a, paths):
    c = a.cmd
    if c == "get":
        if a.summary:
            return summary(b)
        if a.quest:
            q = b.quest(a.quest)
            return {"quest": q, "goals": b.goals_of(a.quest),
                    "questions": [x for x in b.d["questions"] if x["quest"] == a.quest]}
        if a.goal:
            return b.goal(a.goal)
        if a.question:
            return b.question(a.question)
        raise GuildError("--summary／--quest／--goal／--question のどれかを指定してください")
    if c == "add-quest":
        qid = add_quest(b, a.title, a.detail, a.due, a.priority)
        render_quest(b, qid)
        return qid
    if c == "add-goal":
        gid = add_goal(b, a.quest, a.title, a.done_when, a.effort, a.deadline, a.estimate_min, split(a.depends_on),
                       a.form, a.template, a.output_path, a.needs_execute, split(a.notes_touched))
        render_quest(b, a.quest)
        return gid
    if c == "add-question":
        return add_question(b, a.kind, a.scope, a.quest, a.text, json.loads(a.options), a.default, a.goal, a.diagram,
                            a.due, False if a.no_block else None)
    if c == "set-status":
        e = set_status(b, a.id, a.to, a.who, a.text, a.reason, split(a.touch), split(a.goals), a.force_dependents)
        qid = a.id if a.id.startswith("Q") else b.goal(a.id)["quest"]
        render_quest(b, qid)
        return f"OK {a.id} {e}"
    if c == "set":
        set_field(b, a.id, a.field, json.loads(a.value), a.who)
        return "OK"
    if c == "set-top":
        set_top(b, a.key, json.loads(a.value))
        return "OK"
    if c == "route-check":
        r = route_check(b, a.quest)
        if a.write and r["ok"]:
            b.quest(a.quest)["route"] = r["route"]
        if not r["ok"]:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            raise GuildError("道のりに問題があります")
        return r
    if c == "ready":
        return ready_list(b)
    if c == "add-finding":
        g = b.goal(a.goal)
        n = record_finding(b, g, a.fix_kind, a.point_code, a.target, a.point, a.rule_text, a.rule_actor)
        return f"OK 同じ指摘は {n} 回目"
    if c == "log-append":
        if not (a.file or a.text):
            raise GuildError("--file か --text が要ります")
        f = log_append(b, a.goal, a.text, a.file)
        render_quest(b, b.goal(a.goal)["quest"])
        return str(f)
    if c == "answer":
        q = answer_question(b, a.id, a.choice, a.comment, point_code=a.point_code)
        return f"OK {a.id} {q['status']}"
    if c == "reopen":
        reopen_question(b, a.id)
        return "OK"
    if c == "decide":
        decide(b, a.id, a.choice, a.scope, a.comment)
        return "OK"
    if c == "close-questions":
        ids = split(a.ids)
        n = 0
        for q in b.d["questions"]:
            if (a.quest and q["quest"] == a.quest) or q["id"] in ids:
                if q["status"] == "回答済":
                    q["handled"] = True
                    n += 1
        return f"OK {n} 件"
    if c == "add-notice":
        add_notice(b, a.text, split(a.stops))
        return "OK"
    if c == "apply-simple":
        r = apply_simple(b)
        for q in b.d["quests"]:
            render_quest(b, q)
        return r
    if c == "tick":
        return tick(b)
    if c == "need-claude":
        r = need_claude(b)
        return ("yes: " + ", ".join(r)) if r else "no"
    if c == "archive":
        return {"moved": archive(b, a.days)}
    if c == "render-quest":
        return str(render_quest(b, a.quest))
    if c == "render-route":
        svg, sentence = render_route_svg(b, a.quest)
        if a.out:
            Path(a.out).write_text(svg + "\n", encoding="utf-8")
        if a.summary:
            return sentence
        return None if a.out else svg
    if c == "pre-check":
        r = pre_check(b, a.goal)
        if not r["ok"]:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            raise GuildError("pre-check が NG です")
        return r
    if c == "cross-check":
        return cross_check(b, a.quest)
    if c == "lessons-append":
        lessons_append(b, a.kind, a.point_code, a.text)
        return "OK"
    if c == "lessons-brief":
        return "\n".join(lessons_brief(b, a.point_code))
    if c == "profile-brief":
        return "\n".join(profile_brief(b))
    if c == "make-brief":
        return str(make_brief(b, a.goal, a.role))
    if c == "model-for":
        m, why = model_for(b, a.goal, a.role)
        return f"{m}（{why}）"
    if c == "budget":
        ok, left = budget(b, a.use, a.quest, a.reset)
        return f"ok 残り {left}" if ok else f"stop 残り {left}"
    if c == "usage-log":
        usage_log(b, a.role, a.model, a.tokens, a.quest, a.goal)
        return "OK"
    raise GuildError(f"未対応のコマンドです: {c}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        run(build_parser().parse_args(argv))
    except GuildError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

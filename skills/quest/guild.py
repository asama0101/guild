#!/usr/bin/env python3
"""guild の実行エンジン（標準ライブラリだけ）。

plan.json を書けるのはこのファイルだけ。遷移は transitions.json で決め、定義にない遷移はエラー。
使い方: guild.py {adopt|validate|sync|next|ingest} PLAN / guild.py advance PLAN ID EVENT
adopt は PLAN と同じフォルダの reports/plan-draft.json から PLAN を作る（承認前の状態で）。inputs・candidates の名前が guild/inputs/ になければエラー。
guild.py init ROOT: ROOT/guild/ と guild/.work/config.json（この Python のパス）、掟（guild/.work/codex/）を作る。
guild.py new ROOT [R…]: ROOT/guild/.work/ に次の依頼のフォルダ（Q001…）を作る。R… を渡すと、ボードが保存した受付待ちの依頼を取り込む（選んだインプットが guild/inputs/ になければ、依頼を .work/requests/rejected/ へ移して拒否する）。
guild.py requests ROOT: 受付待ちの依頼を一覧する。
guild.py inputs-list ROOT [--text 依頼文 | --text-file パス]（同時指定は不可。長い依頼文や記号を含む依頼文はファイルで渡す）:guild/inputs/ のファイル（名前・拡張子・大きさ・更新日・文字のファイルの先頭5行）と、依頼文に出てくる書庫の項目からのヒントを一覧する（受付係に渡す）。
guild.py close ROOT: 完了・中止した依頼のインプットのバックアップを消す。
guild.py arrivals ROOT: ボードから届いて、まだ取り込んでいない入力と依頼を一覧する。
guild.py pause ROOT: 「ギルドを閉める」。.work/pause.json を書く。ギルドマスターは、新しい役を呼ばず、実行中の役が終わるのを待って止まる（依頼は中止にならない）。
guild.py pause-status ROOT: pause.json があるかを返す（paused）。壊れていても「あり」とする。
guild.py pause-clear ROOT: pause.json を消す（ギルドマスターが起動したとき）。
guild.py wait ROOT [秒]: 届くまで待つ（既定 540 秒）。届いていれば、すぐ返す。
guild.py answers QDIR: 計画がない依頼の、質問への回答（type が answers）を取り出す。
guild.py publish QDIR: 納品物を guild/deliverables/ へコピーする（全目標が済んだとき）。
guild.py archive-propose QDIR: 司書の候補（reports/archive-draft.json）を検査し、心得を登録して、残りを依頼主の確認待ち（archive.json）にする。
guild.py archive-ingest ROOT: .work/archive-inbox/ の入力（entry・promote・deprecate・retype）を書庫に反映する。
guild.py web-ingest ROOT: .work/web/inbox/ の依頼主の答え（WebFetch の許可・不許可、許可リストの追加・削除）を反映する。
guild.py web-describe ROOT FILE: FILE（{"descriptions": {ドメイン: 一言の説明}}）の説明を、許可待ちのドメインに付ける（ボードの手紙に「AI の推測」として出る）。
guild.py web-pending ROOT: 魔法使いが止められて、依頼主の答え待ちのドメインを一覧する。
guild.py web-reset ROOT: 「今回だけ」の許可と、許可しなかった記録を空にする（依頼の完了・中止のとき）。
入力（inbox の JSON）の type には、due（依頼の開始日・締切、目標の予定日・締切の設定。目標の締切だけ解除できる）と、inputs（このクエストのインプットの追加・外す。足す名前は guild/inputs/ にあること）がある。
エラーは終了コード 1。
"""
import contextlib
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
PAUSE = "pause.json"  # guild/.work/pause.json：「ギルドを閉める」の印


def work_dir(gdir):
    """機械用・作業用のフォルダ。依頼（Q###）、受付待ちの依頼、外部サイトの許可、書庫の入力、インプットのバックアップを置く。"""
    return Path(gdir) / WORK


def gdir_of(qdir):
    """依頼のフォルダ（guild/.work/Q001）から guild/ を返す。"""
    return Path(qdir).parent.parent

SATISFIED = ("done", "skipped")
MAX_RETRIES_LIMIT = 5  # 目標ごとの max_retries の上限
PROMPT_SUFFIX = ".prompt.md"  # Markdown 以外（PowerPoint・Excel など）が要るときの、Claude Code に渡すプロンプトのファイル名
CRITERIA_KEYS = ("viewpoint", "pass_line", "check")
CLASSES = ("wizard", "alchemist", "adventurer")  # 目標（auto）を実行する役（職業）
FORMATS = {"md": ".md", "html": ".html"}  # 納品物の形式（文字の形式だけ。ほかはプロンプト *.prompt.md）
REQUEST_FORMATS = {**FORMATS, "prompt": PROMPT_SUFFIX}  # 依頼で選べる形式。prompt は、納品物が Claude Code に貼るプロンプト（*.prompt.md）だけ
PROMPT_TARGETS = {"pptx": "PowerPoint", "xlsx": "Excel", "docx": "Word", "pdf": "PDF", "image": "画像"}  # prompt のとき、作るファイルの種類（request.json の targets）
DEFAULT_FORMAT = "md"
TITLE_HINT = 24  # 依頼のタイトルの目安（超えると警告）
META_MAX = 80  # タイトル・series の上限（超えるとエラー）
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GOAL_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,20}")


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


LEGACY_MSG = "旧形式の計画です（todos）。この版は「目標（goals）」を使うので、読めません。この依頼は中止して、もう一度出し直してください"


def is_legacy_plan(path):
    """旧形式（todos）の plan.json か。読めない・ないものは False。"""
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(plan, dict) and "todos" in plan and "goals" not in plan


def load_plan(path):
    """plan.json を読む。旧形式（todos）は、分かるエラーで止める（自動の移行はしない）。"""
    plan = load_json(path)
    if isinstance(plan, dict) and "todos" in plan and "goals" not in plan:
        raise GuildError(f"{path}: {LEGACY_MSG}")
    return plan


REPLACE_TRIES = webaccess.REPLACE_TRIES
write_text_atomic = webaccess.write_text_atomic  # フック（別プロセス）も使うので、webaccess.py に置く


def save_plan(path, plan):
    """JSON を原子的に書く。tmp 名にプロセス番号を付け、並列で書いても tmp が衝突しない。"""
    write_text_atomic(path, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")


LOCK_TIMEOUT = 15  # ロックを待つ秒数。超えたらエラー（他人のロックは壊さない）
LOCK_STALE = 60  # この秒数より古いロックは、落ちたプロセスの残りとみなして取り上げる


def _unlink_quietly(path):
    """OneDrive・ウイルス対策が掴んでいると PermissionError になる。数回やり直し、だめでも握りつぶす（ロックは古くなれば取り上げられる）。"""
    for n in range(REPLACE_TRIES):
        try:
            Path(path).unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(0.05 * (n + 1))


def _steal_stale(lock):
    """古いロックの取り上げ。取り上げ役を <lock>.steal の O_EXCL で 1 人に絞り、その中で古さを確かめ直してから消す
    （他の人が取り上げて作り直した新しいロックを消さない）。"""
    guard = Path(str(lock) + ".steal")
    try:
        os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        try:
            if time.time() - guard.stat().st_mtime > LOCK_STALE:
                _unlink_quietly(guard)  # 取り上げ役が落ちた残り
        except OSError:
            pass
        return
    except OSError:
        return
    try:
        if time.time() - lock.stat().st_mtime > LOCK_STALE:
            lock.unlink()
    except OSError:
        pass
    finally:
        _unlink_quietly(guard)


@contextlib.contextmanager
def plan_lock(path):
    """plan.json の読み→書きを 1 つずつにする排他ロック（<path>.lock を O_EXCL で作る）。load から save までを包む。"""
    lock = Path(str(path) + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > LOCK_STALE
            except OSError:
                continue  # 確かめている間に消えた。作り直しを試す
            if stale:
                _steal_stale(lock)
                continue
            if time.monotonic() > deadline:
                raise GuildError(f"{lock.name} を他のプロセスが使っています。しばらくしてからもう一度実行してください")
            time.sleep(0.05)
            continue
        except PermissionError:
            if time.monotonic() > deadline:
                raise GuildError(f"{lock.name} を作れません（権限）")
            time.sleep(0.05)
            continue
        try:
            os.write(fd, str(os.getpid()).encode())
        except OSError:
            os.close(fd)
            _unlink_quietly(lock)
            raise
        os.close(fd)
        break
    try:
        yield
    finally:
        _unlink_quietly(lock)


def load_transitions(path=None):
    return load_json(path or HERE / "transitions.json")


def goal_map(plan):
    return {t["id"]: t for t in plan.get("goals", [])}


def effective(tr, kind):
    """種別ごとの遷移表。差分は (from, event) が同じ共通の遷移をすべて置き換える。"""
    over = tr["kinds"].get(kind, {}).get("override", [])
    keys = {(o["from"], o["event"]) for o in over}
    return [t for t in tr["transitions"] if (t["from"], t["event"]) not in keys] + over


def guard_ok(name, goal, tr):
    if name is None:
        return True
    left = goal.get("retries", 0) < goal.get("max_retries", tr.get("max_retries", 0))  # 目標ごとの max_retries が先
    return {"confirm": bool(goal.get("confirm")), "no_confirm": not goal.get("confirm"),
            "retries_left": left, "no_retries_left": not left}[name]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def note(plan, **kw):
    """状態の移り変わりの記録（ボードのタイムラインが読む）。plan.json の history に追記する。"""
    if plan is not None:
        plan.setdefault("history", []).append({"t": now(), **kw})


def apply_event(goal, event, tr, plan=None):
    for t in effective(tr, goal["kind"]):
        if t["from"] == goal["state"] and t["event"] == event and guard_ok(t.get("guard"), goal, tr):
            if event == "rejected" and t["to"] != "failed":
                goal["retries"] = goal.get("retries", 0) + 1
            before = goal["state"]
            goal["state"] = t["to"]
            note(plan, id=goal["id"], event=event, **{"from": before, "to": t["to"]})
            return t["to"]
    raise GuildError(f"{goal['id']}: 状態 {goal['state']} では {event} できません")


def validate(plan, tr):
    errs = []
    goals = plan.get("goals")
    if not isinstance(goals, list) or not goals:
        return ["goals がありません"]
    for k in ("start", "due"):
        try:
            check_date(plan.get(k), k)
        except GuildError as e:
            errs.append(str(e))
    errs += check_plan_inputs(plan)
    ids = [t.get("id") for t in goals]
    if len(set(ids)) != len(ids) or None in ids:
        errs.append("id が重複しているか、欠けています")
    for t in goals:
        i = t.get("id")
        if not isinstance(i, str) or not GOAL_ID_RE.fullmatch(i):  # id はファイルのパスに使う（output/<id>・reports/<id>-…）。外へ出る形は通さない
            errs.append(f"目標の id は、英数字・_・- の 20 字までにしてください: {i!r}")
        if t.get("kind") not in tr["kinds"]:
            errs.append(f"{i}: kind が不明です: {t.get('kind')}")
        if t.get("state") not in tr["states"]:
            errs.append(f"{i}: state が不明です: {t.get('state')}")
        if "format" in t and not (isinstance(t["format"], str) and t["format"] in REQUEST_FORMATS):
            errs.append(f"{i}: format は {'・'.join(REQUEST_FORMATS)} のどれかにしてください: {t['format']!r}")
        if t.get("kind") == "auto":
            if t.get("class") not in CLASSES:
                errs.append(f"{i}: class は {'・'.join(CLASSES)} のどれかにしてください: {t.get('class')!r}")
        elif "class" in t:
            errs.append(f"{i}: class は auto の目標だけに付けられます")
        c = t.get("criteria") or {}
        if not isinstance(c, dict):
            errs.append(f"{i}: criteria はオブジェクト（viewpoint・pass_line・check）にしてください")
            continue
        for k in CRITERIA_KEYS:
            if not str(c.get(k, "")).strip():
                errs.append(f"{i}: criteria.{k} が空です")
        if "max_retries" in t:
            m = t["max_retries"]
            if not isinstance(m, int) or isinstance(m, bool) or not 0 <= m <= MAX_RETRIES_LIMIT:
                errs.append(f"{i}: max_retries は 0〜{MAX_RETRIES_LIMIT} の整数にしてください: {m!r}")
        if t.get("confirm") and t.get("kind") != "auto":
            errs.append(f"{i}: confirm は auto の目標だけに付けられます")
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
    if not errs and has_cycle(goals):
        errs.append("deps に循環があります")
    return errs


def has_cycle(goals):
    deps = {t["id"]: list(t.get("deps", [])) for t in goals}
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
    tm = goal_map(plan)
    moved = True
    while moved:
        moved = False
        for t in plan["goals"]:
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


REOPEN_MAX = 1000


def retire_draft(qdir):
    """計画の見直しに入るとき、古い受付係の下書きを plan-draft.prev.json に退避する。残すと、受付係が書き直さなくても、古い下書きがそのまま採用される。"""
    f = Path(qdir) / "reports" / "plan-draft.json"
    if f.exists():
        os.replace(f, f.with_name("plan-draft.prev.json"))


def reset_archive_state(qdir):
    """再実行のとき、書庫の登録候補の確認の状態（archive.json）を、archive.prev.json に退避する。もう一度完了したときに、新しく確認するため。"""
    f = Path(qdir) / "archive.json"
    if f.exists():
        os.replace(f, Path(qdir) / "archive.prev.json")


def archive_state(qdir):
    """書庫の登録候補の確認の状態。none（archive.json がない）/ proposed（依頼主の答え待ち）/ done。壊れていれば proposed（終わらない側）。"""
    f = Path(qdir) / "archive.json"
    if not f.exists():
        return "none"
    try:
        return "done" if load_json(f).get("status") == "done" else "proposed"
    except (GuildError, AttributeError):  # 壊れている・dict でない archive.json は、確認待ちとして扱う
        return "proposed"


OVERALL_REPORT = "overall-receptionist.md"  # 総合確認の報告（受付係が、依頼文と納品物だけを読んで書く）


def overall_skip(qdir):
    """総合確認が得られないときの、最後の手段。「不足あり（総合確認ができなかった）」の報告を書き、依頼主が自分で確かめて受け取れるようにする。
    受付係の判定を作り上げるのではなく、できなかったことを、そのまま依頼主に知らせる。"""
    qdir = Path(qdir)
    if overall_state(qdir) is not None:
        raise GuildError("総合確認は済んでいます")
    (qdir / "reports").mkdir(exist_ok=True)
    write_text_atomic(qdir / "reports" / OVERALL_REPORT, "## 判定\n不足あり\n## 要件ごとの確認\n（総合確認ができませんでした）\n## 不足\n"
                      "総合確認ができませんでした（受付係の報告が得られなかったため）。納品物を、依頼文と見比べて、ご自身で確かめてください。\n")
    return {"written": str(qdir / "reports" / OVERALL_REPORT)}


def overall_state(qdir):
    """総合確認の報告（reports/overall-receptionist.md）の状態。ok（満たしている）／gaps（不足あり）／None（ない・空・判定がない）。"""
    try:
        body = section_of((Path(qdir) / "reports" / OVERALL_REPORT).read_text(encoding="utf-8-sig"), "判定")
    except OSError:
        return None
    first = re.sub(r"^[\s>*`_-]+", "", one_line(body.split("\n")[0])) if body else ""  # **不足あり**・- 満たしている のような飾りは取る
    if first.startswith("満たしている"):
        return "ok"
    if first.startswith("不足あり"):
        return "gaps"
    return None


def next_view(plan, qdir=None):
    groups = {"ready": "running", "confirm": "awaiting_confirm", "waiting_user": "waiting_user",
              "review": "review", "blocked": "blocked", "failed": "failed"}
    out = {k: [t["id"] for t in plan["goals"] if t["state"] == s] for k, s in groups.items()}
    out["ready_by_class"] = {c: [t["id"] for t in plan["goals"] if t["state"] == "running" and t.get("kind") == "auto" and t.get("class") == c]
                             for c in CLASSES}  # 実行できる目標を、呼ぶ役（職業）ごとに分けたもの
    out["runnable"] = runnable(plan)
    out["status"] = plan.get("status", "active")
    out["approved"] = bool(plan.get("approved"))
    out["finished"] = all(t["state"] in SATISFIED for t in plan["goals"])
    out["accepted"] = bool(plan.get("accepted"))
    # 全目標が済んだら、受付係が総合確認（依頼文と納品物の照合）をする。済んでから受け取りの確認。受け取るまでは完了ではない（awaiting_accept は依頼主待ち）
    ov = overall_state(qdir) if qdir is not None else "ok"  # qdir がなければ、総合確認は問わない
    waiting = out["finished"] and out["approved"] and out["status"] == "active" and not out["accepted"]
    out["overall"] = ov or "none"
    out["awaiting_overall"] = waiting and ov is None
    out["awaiting_accept"] = waiting and ov is not None
    out["complete"] = out["finished"] and out["accepted"]
    # 完了・中止した依頼の、書庫の記録（司書→依頼主の確認）がどこまで進んだか。closed になった依頼は、もう何もしない
    ended = out["complete"] or out["status"] == "aborted"
    out["archive"] = archive_state(qdir) if qdir is not None else "none"
    out["needs_archive"] = ended and out["archive"] == "none"
    out["closed"] = ended and out["archive"] == "done"
    return out


def check_evidence(plan, goal_id, qdir):
    """passed の証拠ゲート：鑑定士の報告 reports/<id>-appraiser.md があり、空でなく、目標が鑑定待ちになったあとに書かれていること。
    報告を読まずに、または古い報告のまま合格にすることを防ぐ（rejected には要らない）。"""
    f = Path(qdir) / "reports" / f"{goal_id}-appraiser.md"
    if not f.is_file() or f.stat().st_size == 0:
        raise GuildError(f"{goal_id}: 鑑定士の報告 reports/{goal_id}-appraiser.md がないか空です。鑑定士が報告を書いてから passed を送ってください")
    verdict = re.search(r"##\s*判定\s*" + chr(10) + r"\s*(\S+)", f.read_text(encoding="utf-8", errors="replace"))
    if not verdict or not verdict.group(1).lower().startswith("passed"):
        raise GuildError(f"{goal_id}: 鑑定士の報告の「## 判定」が passed ではありません（{verdict.group(1) if verdict else '見つかりません'}）")
    sent = [h for h in plan.get("history", []) if h.get("id") == goal_id and h.get("to") == "review"]
    if sent:
        try:
            ts = datetime.datetime.fromisoformat(sent[-1]["t"]).timestamp()
        except (KeyError, ValueError, TypeError):
            return
        if f.stat().st_mtime < ts - 2:
            raise GuildError(f"{goal_id}: 鑑定士の報告が、鑑定待ちになる前の古いものです。鑑定士にもう一度判定させてください")


def ingest(plan_path, plan, tr, commit=None):
    inbox = Path(plan_path).parent / "inbox"
    report = {"applied": [], "rejected": [], "warnings": []}
    if not inbox.is_dir():
        return report
    after = []  # 計画の保存のあとにする、ファイルの退避（retry の古い成果物）
    moves = []  # 入力ファイルの移動は、計画の保存（commit）のあとに行う。保存前に落ちても、入力は inbox に残る
    for f in sorted(inbox.glob("*.json")):
        try:
            data = load_json(f)
            if isinstance(data, dict) and data.get("type") == "answers" and plan.get("status") == "replan":
                continue  # 計画を直し中の質問への答えは、ここでは取り込まない（`answers` で取り出して、受付係を呼び直す）
            if isinstance(data, dict) and data.get("type") == "archive":
                archive_decide(Path(plan_path).parent, data)  # 書庫の確認は、中止された依頼でも受け付ける
            else:
                apply_input(plan, data, tr, Path(plan_path).parent, after)
                write_user_report(Path(plan_path).parent, data)
                qdir = Path(plan_path).parent
                try:
                    if data.get("type") == "accept" or (data.get("type") == "meta" and plan.get("accepted")):
                        publish_deliverables(qdir, plan)  # 受け取ったら、納品物が必ず置かれている（何度でも同じ）
                    elif data.get("type") == "decision" and data.get("choice") in ("abort", "replan"):
                        unpublish_deliverables(qdir)  # 中止なら納品物はない。見直しなら古いものは使えない
                    elif data.get("type") == "reopen":
                        unpublish_deliverables(qdir)  # 再実行：受け取り済みの納品物（deliver_to のコピーも）を取り下げる
                        reset_archive_state(qdir)  # 書庫の確認は、再び完了したときにもう一度行う
                except (OSError, GuildError) as e:
                    # 入力は適用済み。ここで落とすと同じバッチの適用済みの入力が計画に保存されず失われるので、警告にして続ける
                    report["warnings"].append(f"納品物の置き直しに失敗しました（{f.name}：{e}）。`publish` を再実行してください")
            dest, key, item = inbox / "done", "applied", f.name
        except (GuildError, KeyError, TypeError, AttributeError) as e:
            dest, key, item = inbox / "rejected", "rejected", {"file": f.name, "reason": str(e)}
        moves.append((f, dest))
        report[key].append(item)
    if commit is not None:
        commit()
    for job in after:
        try:
            job()
        except OSError as e:
            report["warnings"].append(f"古い成果物の退避に失敗しました（{e}）。output/ と reports/ に残った古いファイルを、手で prev/ へ移してください")
    for f, dest in moves:
        try:
            dest.mkdir(exist_ok=True)
            shutil.move(str(f), str(dest / f.name))
        except OSError as e:
            # 計画は保存済み。ここで落とすと報告が失われ、残った入力が次回また適用される。警告にして続ける
            report["warnings"].append(f"入力の移動に失敗しました（{f.name}：{e}）。inbox から手で done/ へ移してください")
    return report


def write_user_report(qdir, data):
    """依頼主の結果（type が result）を、鑑定士が読める報告 reports/<目標>-user.md にする。"""
    if data.get("type") != "result":
        return
    rep = Path(qdir) / "reports"
    rep.mkdir(exist_ok=True)
    files = "\n".join(f"- [[{x}]]" for x in data.get("files", [])) or "なし"
    result = "できた" if data.get("ok") else "できなかった"
    body = f"## 結果\n{result}\n## メモ\n{data.get('note') or 'なし'}\n## 添付\n{files}\n"
    (rep / f"{data['goal']}-user.md").write_text(body, encoding="utf-8")


def retire_after(qdir, after):
    """下書きの退避は、計画の保存のあとにする（after があれば、そこへ積む）。"""
    if qdir is not None:
        job = lambda: retire_draft(qdir)
        after.append(job) if after is not None else job()


def apply_input(plan, data, tr, qdir=None, after=None):
    kind = data.get("type")
    tm = goal_map(plan)
    status = plan.get("status", "active")
    # 中止された依頼は、終わったもの。見直し中は、中止以外の入力を受け付けない
    if status == "aborted" and kind != "reopen":
        raise GuildError("中止された依頼には、入力を受け付けません（修正して再実行するには reopen を送ります）")
    if status == "replan" and not (kind == "decision" and data.get("choice") == "abort"):
        raise GuildError("計画を直し中です。新しい計画ができるまで、入力を受け付けません")
    if kind == "reopen":
        # 完了（受け取り済み）か中止の依頼を、修正して再実行する。計画の見直し（replan）と同じ流れ：合格済みで変わらない目標は引き継ぐ
        if not (plan.get("accepted") or status == "aborted"):
            raise GuildError("完了か中止の依頼だけ、修正して再実行できます")
        comment = str(data.get("comment") or "").strip()
        if not comment or len(comment) > REOPEN_MAX:
            raise GuildError(f"comment（直したい内容）を 1〜{REOPEN_MAX} 字で書いてください")
        plan["status"], plan["approved"] = "replan", False
        plan.pop("accepted", None)
        note(plan, event="reopen", comment=comment)
        retire_after(qdir, after)
        return
    if kind == "approve":
        if plan.get("approved"):
            raise GuildError("すでに承認されています")
        plan["approved"], plan["status"] = True, "active"
        note(plan, event="approved")
        return
    if kind == "meta":
        changes = {}
        for k in ("title", "series"):
            if k in data:
                v = one_line(data[k]) if isinstance(data[k], str) else ""
                if not v or len(v) > META_MAX:
                    raise GuildError(f"{k} は 1〜{META_MAX} 字の文字列にしてください")
                changes[k] = v
        if not changes:
            raise GuildError("title か series が必要です")
        plan.update(changes)
        plan["meta_locked"] = sorted(set(plan.get("meta_locked", [])) | set(changes))  # 依頼主が直したものは、受付係が上書きしない
        note(plan, event="meta", **changes)
        return
    if kind == "accept":
        if qdir is not None and not plan.get("accepted") and overall_state(qdir) is None:
            raise GuildError("総合確認がまだです（受付係の報告 reports/overall-receptionist.md ができてから、受け取れます）")
        if plan.get("accepted"):
            raise GuildError("すでに受け取り済みです")
        if not plan.get("approved") or not all(t["state"] in SATISFIED for t in plan["goals"]):
            raise GuildError("すべての目標が済むまで、受け取れません")
        plan["accepted"] = True
        note(plan, event="accepted")
        return
    if kind == "decision" and data.get("choice") in ("abort", "replan"):
        plan["status"] = "aborted" if data["choice"] == "abort" else "replan"
        if data["choice"] == "replan":
            plan["approved"] = False
        note(plan, event="decision", choice=data["choice"], comment=data.get("comment", ""))
        if data["choice"] == "replan":
            retire_after(qdir, after)
        return
    if kind == "due":
        apply_dates(plan, data)
        return
    if kind == "inputs":
        if plan.get("accepted"):
            raise GuildError("受け取り済みの依頼のインプットは変えられません")
        apply_inputs(plan, data, gdir_of(qdir) if qdir is not None else None)
        return
    t = tm.get(data.get("goal"))
    if t is None:
        raise GuildError(f"goal がありません: {data.get('goal')}")
    if kind == "confirm":
        apply_event(t, "confirmed" if data["ok"] else "declined", tr, plan)
    elif kind == "result":
        apply_event(t, "submitted" if data["ok"] else "reported_failed", tr, plan)
        t["output"] = {"note": data.get("note", ""), "files": data.get("files", [])}
    elif kind == "decision" and data.get("choice") == "skip":
        apply_event(t, "skip", tr, plan)
    elif kind == "decision" and data.get("choice") == "retry":
        # 失敗した目標をもう一度やる。やり直しの回数は数え直し、古い成果物と報告は prev/ へ退避する（保存のあと）
        apply_event(t, "retry", tr, plan)
        t["retries"], t["output"] = 0, None
        if qdir is not None:
            job = lambda: archive_outputs({"goals": [t]}, [], qdir)
            after.append(job) if after is not None else job()
    elif kind == "decision" and data.get("choice") == "drop":
        # 失敗した目標と、それに(間接にでも)依存する後続をやめる。後続は実行しない
        apply_event(t, "skip", tr, plan)
        dropped, grew = {t["id"]}, True
        while grew:
            grew = False
            for u in plan["goals"]:
                if u["id"] not in dropped and any(d in dropped for d in u.get("deps", [])):
                    dropped.add(u["id"])
                    grew = True
        for u in plan["goals"]:
            if u["id"] in dropped and u["state"] in ("pending", "blocked"):
                note(plan, id=u["id"], event="dropped", **{"from": u["state"], "to": "skipped"})
                u["state"] = "skipped"
    else:
        raise GuildError(f"入力が不正です: {kind} {data.get('choice', '')}")


def apply_dates(plan, data):
    """日付の設定。goal があれば目標の scheduled / due、なければ依頼の start / due。"""
    keys = [k for k in ("start", "due", "scheduled") if k in data]
    goal = None
    if data.get("goal") is not None:
        goal = goal_map(plan).get(data["goal"])
        if goal is None:
            raise GuildError(f"goal がありません: {data.get('goal')}")
    allowed = ("scheduled", "due") if goal is not None else ("start", "due")
    if not keys or any(k not in allowed for k in keys):
        raise GuildError(f"日付の入力が不正です: {keys or '日付なし'}")
    new = {}
    for k in keys:
        v = check_date(data[k], k)
        if v is None and not (k == "due" and goal is not None):  # 解除できるのは目標の締切だけ
            raise GuildError(f"{k} は解除できません")
        new[k] = v
    (goal if goal is not None else plan).update(new)
    note(plan, event="due", **({"goal": goal["id"]} if goal is not None else {}), **new)


def apply_inputs(plan, data, gdir):
    """このクエストのインプットの追加・外す（依頼主の入力）。足す名前は guild/inputs/ にあること、外す名前は計画の inputs にあること。
    足したものは source=user・reason「依頼主が追加」で後ろに付け、候補（candidates）から除く。全部を検査してから変える。"""
    add, remove = data.get("add", []), data.get("remove", [])
    if not isinstance(add, list) or not isinstance(remove, list):
        raise GuildError("inputs の add・remove は、ファイル名の配列にしてください")
    cur = plan.get("inputs", [])
    have = {x["name"].lower(): x["name"] for x in cur}
    rm = []
    for n in remove:
        check_input_name(n, "inputs の remove")
        if n.lower() not in have:
            raise GuildError(f"外すインプットが計画にありません: {n}")
        rm.append(have[n.lower()])
    gone = {r.lower() for r in rm}
    on_disk = existing_inputs(gdir) if gdir is not None else {}
    ad = []
    for n in add:
        check_input_name(n, "inputs の add")
        if n.lower() in gone:
            raise GuildError(f"同じ名前を足して外すことはできません: {n}")
        actual = on_disk.get(n.lower())
        if actual is None:
            raise GuildError(f"足すインプットが guild/inputs/ にありません: {n}")
        if actual.lower() not in have:
            ad.append(actual)  # すでに入っている名前は足さない
    rm, ad = unique_names(rm), unique_names(ad)
    if not rm and not ad:
        raise GuildError("インプットの変更がありません")
    added = {a.lower() for a in ad}
    plan["inputs"] = [x for x in cur if x["name"].lower() not in gone] + [{"name": a, "source": "user", "reason": "依頼主が追加"} for a in ad]
    plan["candidates"] = [x for x in plan.get("candidates", []) if x["name"].lower() not in added]
    note(plan, event="inputs", add=ad, remove=rm)


def quest_dates(qdir, old=None):
    """依頼の開始日・締切。作り直し（replan）のときは旧計画の値、なければ request.json の値、なければ今日。締切が未定なら開始日。"""
    req_path = Path(qdir) / "request.json"
    req = load_json(req_path) if req_path.exists() else {}
    old = old or {}
    start = old.get("start") or req.get("start") or today()
    due = old.get("due") or req.get("due") or start
    return {"start": start, "due": due}


INPUT_SOURCES = ("user", "auto")  # 依頼主の指定 / 受付係の選択


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
    依頼主の指定（request.json の inputs。source=user）が先頭で、受付係の選択（plan-draft.json の inputs。source=auto）を後ろに足す。
    作り直し（replan）では、旧計画の inputs（依頼主の追加・外すを反映済み）を引き継ぎ、依頼主が外したままの名前は足さない。
    受付係が書いた名前は guild/inputs/ にあること（なければエラー。受付係に差し戻す）。"""
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


AMBIGUOUS = ("適切", "十分", "適宜", "なるべく", "できるだけ", "速やか", "高品質", "わかりやすく", "分かりやすく", "きちんと", "しっかり", "必要に応じて")
# 「不適切」「二十分」のような別の意味の語に当たらないよう、前に付く字で除く
_AMBIGUOUS_RE = {w: re.compile(("(?<!不)" if w == "適切" else "(?<![二三四五六七八九〇0-9０-９])" if w == "十分" else "") + re.escape(w)) for w in AMBIGUOUS}
MAX_GOALS = 12  # これを超えたら、粒度が細かすぎないかの警告
MIN_CRITERIA_LEN = 6  # これより短い合格基準は、測れる書き方になっていない可能性の警告
EFFECTS = ("none", "external", "irreversible")  # 目標（auto）の影響：なし（読む・書くだけ）／外部への送信・公開／元に戻せない変更
DANGER_WORDS = ("送信", "送る", "公開する", "公開し", "削除", "消去", "投稿", "共有する", "共有し", "アップロード", "メールを", "上書き", "発注", "支払", "申請する", "申請し",
                "配信", "掲載する", "掲載し", "通知", "書き込", "デプロイ", "リリース", "ツイート", "push", "send", "post ", "upload", "delete", "publish")  # 名詞の「公開情報」などは拾わない


def _str_list(v):
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def normalize_brief(brief, ids):
    """受付係の自己点検（目的・非目標・前提・リスク・要件と目標の対応）を整える。返り値は (brief か None, エラー, 警告)。"""
    if not isinstance(brief, dict):
        return None, [], ["受付係の自己点検（brief）がありません。要件が目標で網羅されているかは、確かめられていません"]
    errs, warns = [], []
    out = {"intent": str(brief.get("intent") or "").strip(), "non_goals": _str_list(brief.get("non_goals")),
           "assumptions": _str_list(brief.get("assumptions")), "risks": _str_list(brief.get("risks")), "coverage": []}
    if not out["intent"]:
        warns.append("自己点検に、目的の言い換え（intent）がありません")
    cov = brief.get("coverage")
    for c in cov if isinstance(cov, list) else []:
        if not isinstance(c, dict) or not str(c.get("requirement") or "").strip():
            continue
        req, goals = str(c["requirement"]).strip(), _str_list(c.get("goals"))
        for i in goals:
            if i not in ids:
                errs.append(f"自己点検の「{req}」が、ない目標 {i} を指しています")
        if not goals:
            warns.append(f"要件「{req}」に対応する目標がありません（網羅漏れの可能性）")
        out["coverage"].append({"requirement": req, "goals": goals})
    if not out["coverage"]:
        warns.append("自己点検に、要件と目標の対応（coverage）がありません")
    return out, errs, warns


def plan_quality(plan, brief):
    """計画の質の検査（adopt のときだけ）。エラーは受付係に差し戻し、警告は承認の手紙に出す（承認は止めない）。
    返り値は (エラー, 警告, 整えた brief)。"""
    goals = plan["goals"]
    errs, warns = [], []
    n = sum(1 for t in goals if t.get("deliverable") is True)
    if n != 1:
        errs.append(f"deliverable: true の目標は、最後のまとめ 1 つだけにしてください（いま {n} 件）")
    for t in goals:
        i = t.get("id")
        if t.get("kind") == "auto":
            e = t.get("effects")
            if not (isinstance(e, str) and e in EFFECTS):
                errs.append(f"{i}: effects は {'・'.join(EFFECTS)} のどれかにしてください: {e!r}")
            elif e != "none" and not t.get("confirm"):
                errs.append(f"{i}: effects が {e} の目標には、confirm: true が要ります（実行前に、依頼主の確認を取るため）")
            elif e == "none":
                text = " ".join([str(t.get("title") or ""), *[str(v) for v in (t.get("criteria") or {}).values()]])
                hits = [w for w in DANGER_WORDS if w in text.lower()]
                if hits:
                    warns.append(f"{i}: effects が none ですが、「{'・'.join(hits)}」とあります。外部への送信・公開・元に戻せない変更を含むなら、effects と confirm を直してください")
        if t.get("deliverable") is True:
            spec = t.get("deliverable_spec")
            if spec is None:
                warns.append(f"{i}: 納品する目標に deliverable_spec（見出しの並びと読み手）がありません。納品物の構成が決まらないまま作ることになります")
            elif not (isinstance(spec, dict) and isinstance(spec.get("headings"), list) and spec["headings"]
                      and all(isinstance(x, str) and x.strip() for x in spec["headings"])
                      and isinstance(spec.get("reader"), str) and spec["reader"].strip()):
                errs.append(f"{i}: deliverable_spec は {{\"headings\": [見出し…], \"reader\": 読み手}} の形にしてください")
        if t.get("kind") == "human" and not (isinstance(t.get("instruction"), str) and t["instruction"].strip()):
            errs.append(f"{i}: human の目標には instruction（依頼主への頼み方）が要ります")
        for k in CRITERIA_KEYS:
            v = str((t.get("criteria") or {}).get(k, "")).strip()
            hit = [w for w in AMBIGUOUS if _AMBIGUOUS_RE[w].search(v)]
            if hit:
                warns.append(f"{i}: criteria.{k} に測れない言葉があります（{'・'.join(hit)}）。数や有無で言える書き方にしてください")
            elif v and len(v) < MIN_CRITERIA_LEN:
                warns.append(f"{i}: criteria.{k} が短すぎます（{len(v)} 文字）。何をどう確かめるかを具体的に書いてください")
    if len(goals) > MAX_GOALS:
        warns.append(f"目標が {len(goals)} 件あります（{MAX_GOALS} 件超）。粒度が細かすぎないか確かめてください")
    ids = {t.get("id") for t in goals}
    out, b_errs, b_warns = normalize_brief(brief, ids)
    return errs + b_errs, warns + b_warns, out


def workload(plan):
    """依頼主（あなた）の作業量：human の目標の件数・予定日ごとの件数・一覧。依頼の締切を超える予定の目標も返す。"""
    items = [{"id": t["id"], "title": t.get("title"), "scheduled": t.get("scheduled"), "due": t.get("due")}
             for t in plan["goals"] if t.get("kind") == "human"]
    days = {}
    for i in items:
        if i["scheduled"]:
            days[i["scheduled"]] = days.get(i["scheduled"], 0) + 1
    end = plan.get("due")
    over = [i["id"] for i in items if end and i["due"] and i["due"] > end]
    return {"human": len(items), "days": dict(sorted(days.items())), "items": items, "over_deadline": over}


def plan_diff(old, plan, carried):
    """再計画の差分：足された目標・なくなった目標・変わった目標（番号は同じで、種別・題名・合格基準・依存のどれかが違う）・引き継がれた目標。"""
    brief = lambda t: {"id": t["id"], "title": t.get("title")}
    old_by = {t["id"]: t for t in old.get("goals", [])}
    new_by = {t["id"]: t for t in plan["goals"]}
    keys = ("kind", "title", "criteria", "deps")
    return {"added": [brief(t) for t in plan["goals"] if t["id"] not in old_by],
            "removed": [brief(t) for t in old.get("goals", []) if t["id"] not in new_by],
            "changed": [brief(t) for t in plan["goals"] if t["id"] in old_by and t["id"] not in carried
                        and any(old_by[t["id"]].get(k) != t.get(k) for k in keys)],
            "carried": list(carried)}


def check_meta(draft):
    """受付係が決めた、依頼のタイトルと series（関連の名前）の検査。返り値は (エラー, 警告, タイトル, series)。
    タイトルは依頼ごとに固有、series は同じ種類の依頼を関連づけるだけ（定期でも突発でも付ける）。"""
    title, series = one_line(draft.get("title")), one_line(draft.get("series"))
    errs, warns = [], []
    for name, v, what in (("title", title, "依頼のタイトル"), ("series", series, "関連の名前")):
        if not v:
            errs.append(f"{name}（{what}）がありません")
        elif len(v) > META_MAX:
            errs.append(f"{name} は {META_MAX} 字までにしてください（{len(v)} 字）")
        elif len(v) > TITLE_HINT:
            warns.append(f"{name}（{what}）が {TITLE_HINT} 字を超えています。検索しやすい短さにしてください（{len(v)} 字）")
    return errs, warns, title, series


def check_targets(req):
    """format が prompt の依頼の targets（作るファイルの種類）を検査する。問題があれば文を、なければ None を返す。prompt 以外では targets を消す。"""
    if req.get("format") != "prompt":
        req.pop("targets", None)
        return None
    t = req.get("targets")
    if not isinstance(t, list) or not t or not all(isinstance(x, str) and x in PROMPT_TARGETS for x in t) or len(set(t)) != len(t):
        return f"format が prompt のときは、targets に、作るファイルの種類（{'・'.join(PROMPT_TARGETS)}）を 1 つ以上、重ならないように入れてください: {t!r}"
    return None


def request_format(qdir):
    """依頼（request.json）の納品形式。ない・不明なら md。"""
    try:
        f = load_json(Path(qdir) / "request.json").get("format") if (Path(qdir) / "request.json").exists() else None
    except (GuildError, AttributeError):
        f = None
    return f if isinstance(f, str) and f in REQUEST_FORMATS else DEFAULT_FORMAT


RESERVED_NAME = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)


def check_deliver_to(qdir, value):
    """deliver_to（納品物をコピーする、プロジェクト内の場所）の検査。プロジェクト外・絶対パス・.. ・guild/・.git/ は不可。正規化した相対パス（/ 区切り）を返す。"""
    if not isinstance(value, str) or not value.strip():
        raise GuildError("deliver_to は、プロジェクト内の相対パス（文字列）にしてください")
    v = value.strip().replace("\\", "/")
    if v.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", v):
        raise GuildError(f"deliver_to は、プロジェクト内の相対パスだけです（絶対パスは使えません）: {value}")
    parts = [p for p in v.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise GuildError(f"deliver_to に、空のパスと .. は使えません: {value}")
    if parts[0].lower() in ("guild", ".git"):
        raise GuildError("deliver_to に、guild/ と .git/ は指定できません")
    for p in parts:  # Windows が名前を変えてしまうもの（末尾のドット・空白、予約名、8.3 短縮名）
        if p != p.rstrip(" .") or RESERVED_NAME.match(p) or re.search(r"~\d", p):
            raise GuildError(f"deliver_to に、使えない名前があります（末尾のドット・空白、CON などの予約名、~1 のような短縮名）: {p}")
    if any(c in p for p in parts for c in '<>:"|?*\x00'):
        raise GuildError(f"deliver_to に、使えない文字があります: {value}")
    root = gdir_of(qdir).parent.resolve()
    target = root.joinpath(*parts).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise GuildError(f"deliver_to が、プロジェクトの外を指しています: {value}")
    for protected in ((root / "guild").resolve(), (root / ".git").resolve()):  # シンボリックリンク・ジャンクションを含め、解決後が guild/・.git/ の中なら不可
        try:
            target.relative_to(protected)
        except ValueError:
            continue
        raise GuildError(f"deliver_to が、guild/ か .git/ の中を指しています: {value}")
    if target.exists() and not target.is_dir():
        raise GuildError(f"deliver_to は、フォルダにしてください（ファイルがあります）: {value}")
    return "/".join(parts)


def apply_format(plan, fmt):
    """納品する目標（deliverable）の format を、依頼の形式にそろえる。なければ入れる。食い違いはエラー。"""
    errs = []
    for t in plan["goals"]:
        if t.get("deliverable") is True:
            if t.get("format") is not None and t.get("format") != fmt:
                errs.append(f"{t['id']}: 納品する目標の format は、依頼の形式（{fmt}）と同じにしてください: {t['format']!r}")
            t["format"] = fmt
    return errs


def adopt(plan_path, tr):
    """reports/plan-draft.json（受付係の分解結果）を検査し、未承認の plan.json にする。"""
    plan_path = Path(plan_path)
    draft_path = plan_path.parent / "reports" / "plan-draft.json"
    if not draft_path.exists():
        raise GuildError(f"{draft_path} がありません")
    old = None
    if plan_path.exists():
        old = load_plan(plan_path)
        if old.get("status") != "replan":
            raise GuildError(f"{plan_path} がすでにあります（上書きしません。やり直すには replan の判断が要ります）")
    draft = load_json(draft_path)
    goals = draft.get("goals")
    if not isinstance(goals, list):
        raise GuildError("plan-draft.json に goals がありません")
    inputs, candidates = selected_inputs(plan_path.parent, draft, old)  # 何も書く前に検査する（落ちたら受付係に差し戻す）
    m_errs, m_warns, title, series = check_meta(draft)
    if m_errs:
        raise GuildError("plan-draft.json のタイトルの検査に失敗しました: " + " / ".join(m_errs))
    deliver_to = check_deliver_to(plan_path.parent, draft["deliver_to"]) if draft.get("deliver_to") is not None else None
    plan = {"quest": draft.get("quest"), "title": title, "series": series, "approved": False, "status": "active",
            **({"deliver_to": deliver_to} if deliver_to else {}),
            **({"archive_used": [str(x) for x in draft["archive_used"]]} if isinstance(draft.get("archive_used"), list) else {}),
            "inputs": inputs, "candidates": candidates,
            "goals": [], "history": [{"t": now(), "event": "adopted"}]}
    plan.update(quest_dates(plan_path.parent, old))
    for t in goals:
        if not isinstance(t, dict):
            raise GuildError("goals の要素が不正です")
        item = dict(t, deps=list(t.get("deps", [])), state=tr["initial"], retries=0, output=None)
        item["scheduled"] = item.get("scheduled") or plan["start"]
        item["due"] = item.get("due") or plan["due"]
        plan["goals"].append(item)
    errs = validate(plan, tr)
    if errs:
        raise GuildError("plan-draft.json の検査に失敗しました: " + " / ".join(errs))
    q_errs, q_warns, brief = plan_quality(plan, draft.get("brief"))
    if q_errs:
        raise GuildError("plan-draft.json の計画検査に失敗しました: " + " / ".join(q_errs))
    f_errs = apply_format(plan, request_format(plan_path.parent))
    if f_errs:
        raise GuildError("plan-draft.json の形式の検査に失敗しました: " + " / ".join(f_errs))
    plan["brief"], plan["check"], plan["workload"] = brief, {"warnings": m_warns + q_warns}, workload(plan)
    carried, warnings = [], []
    if old is not None:
        for k in old.get("meta_locked", []):  # 依頼主がボードで直したタイトル・series は、作り直しでも保つ
            if k in ("title", "series") and old.get(k):
                plan[k] = old[k]
        if old.get("meta_locked"):
            plan["meta_locked"] = list(old["meta_locked"])
        carried = carry_over(plan, old)
        plan["replan_diff"] = plan_diff(old, plan, carried)
    save_plan(plan_path, plan)  # 保存してから成果物を動かす。保存に失敗しても、成果物は元の場所に残る
    if old is not None:
        unpublish_deliverables(plan_path.parent)  # 作り直し。置いた納品物は、また全目標が済んだ時に置き直す
        try:
            archive_outputs(old, carried, plan_path.parent)
        except OSError as e:  # 計画は保存済み。やり直すと adopt が拒否するので、警告にして続ける
            warnings.append(f"古い成果物の退避に失敗しました（{e}）。output/ と reports/ に残った古いファイルを、手で prev/ へ移してください")
    return {"adopted": len(plan["goals"]), "replaced": old is not None, "carried": carried, **({"warnings": warnings} if warnings else {})}


def carry_over(plan, old):
    """計画の作り直し。完了済みで、番号・種別・職業・題名・合格基準・依存が同じで、依存先もすべて引き継がれる目標は、状態を引き継ぐ。
    上流が変わった（引き継がれなかった）目標の下流は、古い成果物が前提にずれるので引き継がない。
    経緯（history）は旧計画のものに追記する。引き継いだ id の一覧を返す（成果物の退避は archive_outputs）。"""
    same = lambda a, b: all(a.get(k) == b.get(k) for k in ("kind", "class", "title", "criteria", "effects", "confirm", "deliverable_spec", "format"))         and list(a.get("deps", [])) == list(b.get("deps", []))
    new_by = {t["id"]: t for t in plan["goals"]}
    old_by = {t["id"]: t for t in old.get("goals", [])}
    carried = []
    undecided = {o["id"] for o in old.get("goals", [])}  # 依存の順に辿る。上流が先に決まるまで待つ
    progressed = True
    while progressed:
        progressed = False
        for i in list(undecided):
            o, n = old_by[i], new_by.get(i)
            deps = o.get("deps", [])
            if any(d in undecided for d in deps):
                continue
            undecided.discard(i)
            progressed = True
            if n is not None and o.get("state") == "done" and same(o, n) and all(d in carried for d in deps):
                n["state"], n["retries"], n["output"] = "done", o.get("retries", 0), o.get("output")
                carried.append(i)
    carried = [o["id"] for o in old.get("goals", []) if o["id"] in carried]
    plan["history"] = list(old.get("history", [])) + [{"t": now(), "event": "replanned", "carried": carried}]
    return carried


def archive_outputs(old, carried, qdir, reports=True):
    """引き継がなかった目標の成果物と報告を、prev/<日時>/ へ退避する（計画を保存したあとに呼ぶ）。"""
    arch = Path(qdir) / "prev" / datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    for o in old.get("goals", []):
        if o["id"] in carried:
            continue
        out = Path(qdir) / "output" / o["id"]
        if out.is_dir():
            (arch / "output").mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(arch / "output" / o["id"]))
        for f in (sorted((Path(qdir) / "reports").glob(f"{o['id']}-*")) if reports else []):
            (arch / "reports").mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(arch / "reports" / f.name))
    if not reports:
        return  # 目標のやり直し：報告（鑑定士の指摘）と総合確認は、そのまま残す
    ov = Path(qdir) / "reports" / OVERALL_REPORT  # 古い計画の総合確認は、作り直したあとには当てはまらない
    if ov.is_file():
        try:
            (arch / "reports").mkdir(parents=True, exist_ok=True)
            shutil.move(str(ov), str(arch / "reports" / ov.name))
        except OSError:
            ov.unlink()  # 退避できなくても、古い報告を残さない（残ると、新しい計画の受け取りが、古い判定で進む）


def init_guild(root):
    """ROOT/guild/ を作り、この Python のパスを config.json に記録する。何度実行しても、既存の依頼は消さない。"""
    gdir = Path(root) / "guild"
    gdir.mkdir(parents=True, exist_ok=True)
    init_archive(gdir / "archive")
    (work_dir(gdir) / "requests").mkdir(parents=True, exist_ok=True)
    legacy = gdir / CONFIG
    if legacy.exists() and not config_path(gdir).exists():
        shutil.move(str(legacy), str(config_path(gdir)))  # 旧版の guild/config.json を .work/ へ移す
    for c in CLASSES:
        (experience_dir(gdir) / c / "notes").mkdir(parents=True, exist_ok=True)
    cdir = work_dir(gdir) / CODEX
    cdir.mkdir(exist_ok=True)
    codex = HERE / "codex.md"
    if codex.exists():
        shutil.copy2(codex, cdir / "default.md")  # 既定の掟はプラグイン側が正本。init のたびに最新に置き換える
    if not (cdir / "project.md").exists():
        (cdir / "project.md").write_text("# プロジェクトの掟（追記）\n\n（まだありません）\n", encoding="utf-8")
    for sub in (INPUTS, DELIV):
        (gdir / sub).mkdir(exist_ok=True)
    board = HERE / "board.html"
    if board.exists():
        shutil.copy2(board, gdir / "board.html")  # ボードはプラグイン側が正本。init のたびに最新に置き換える
    cfg_path = config_path(gdir)
    cfg = load_json(cfg_path) if cfg_path.exists() else {}
    cfg["python"] = sys.executable
    cfg["python_version"] = ".".join(map(str, sys.version_info[:3]))
    cfg["root"] = str(Path(root).resolve())  # ボードが、パスをフルパスでコピーするために使う
    save_plan(cfg_path, cfg)
    return {"guild": str(gdir), "root": cfg["root"], "python": cfg["python"], "python_version": cfg["python_version"],
            "board": str(gdir / "board.html") if board.exists() else None, "codex": str(cdir / "default.md")}


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


CONFIG = "config.json"  # guild/.work/config.json（旧版は guild/config.json。init が移す）
CODEX = "codex"  # guild/.work/codex/：default.md（既定の掟のコピー。init が毎回更新）と project.md（プロジェクトの追記）


EXPERIENCE = "experience"  # guild/.work/experience/<class>/：summary.md（司書がまとめる）と notes/<依頼>-<目標>.md（各役が書く）
EXPERIENCE_MAX = 2000  # 職業ごとの経験の要約の長さの上限（文字）。役が作業の前に読むので、短く保つ
AUTO_CONFIDENCE = ("sourced",)  # 書庫に自動で登録してよい確度（推測は依頼主が選ぶ。確認済みは依頼主だけが付ける）


def experience_dir(gdir):
    return work_dir(gdir) / EXPERIENCE


def config_path(gdir):
    return work_dir(gdir) / CONFIG


def has_config(gdir):
    """/guild:init の済んだ guild/ か。旧版の配置（guild/config.json）も、init を再実行するまでは認める。"""
    return config_path(gdir).exists() or (Path(gdir) / CONFIG).exists()


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
        bak, prev, plan_path = wdir / "backup" / q.name, q / "prev", q / "plan.json"
        if not (bak.is_dir() or prev.is_dir()) or not plan_path.exists():
            continue
        plan = load_plan(plan_path)
        if plan.get("accepted") or plan.get("status") == "aborted":
            for d in (bak, prev):  # 閉じた依頼の、インプットのバックアップと、退避した古い成果物
                if d.is_dir():
                    shutil.rmtree(d)
            removed.append(q.name)
    return {"removed": removed}


DELIV = "deliverables"


def deliverable_files(qdir, plan):
    """納品物にするファイルを (目標の id, パス) で返す。合格（done）した目標の、
    deliverable の印がある目標の .md と、どの目標でも *.prompt.md。印のある目標が1つもなければ、done の目標すべての .md。"""
    marked = {t["id"] for t in plan["goals"] if t.get("deliverable")} or {t["id"] for t in plan["goals"]}
    for t in plan["goals"]:
        d = Path(qdir) / "output" / t["id"]
        if t.get("state") != "done" or not d.is_dir():
            continue
        f = t.get("format")
        exts = {REQUEST_FORMATS[f] if isinstance(f, str) and f in REQUEST_FORMATS else ".md"}  # 納品する目標は、指定の形式のファイルだけを納品物にする
        for f in sorted(d.rglob("*")):
            if not f.is_file():
                continue
            if f.name.lower().endswith(PROMPT_SUFFIX):
                yield t["id"], f
            elif t["id"] in marked and f.suffix.lower() in exts:
                yield t["id"], f


def unpublish_delivered(qdir):
    """deliver_to にコピーした納品物を消す。delivered.json に残した、この依頼の名前（Q###_ で始まるもの）だけを、その場所から消す。"""
    qdir = Path(qdir)
    rec = qdir / "delivered.json"
    if not rec.exists():
        return
    try:
        info = load_json(rec)
        rel = check_deliver_to(qdir, info.get("dir"))
        target = gdir_of(qdir).parent / Path(*rel.split("/"))
        for n in info.get("files", []):
            if isinstance(n, str) and n.startswith(qdir.name + "_") and "/" not in n and "\\" not in n and (target / n).is_file():
                (target / n).unlink()
    except (GuildError, AttributeError, TypeError, OSError):
        pass  # 記録が壊れていても、納品物の取り下げは止めない
    rec.unlink(missing_ok=True)


def unpublish_deliverables(qdir):
    """この依頼の納品物（deliverables/Q###_*）を消す。ほかの依頼のものは消さない。deliver_to にコピーしたものも消す。"""
    qdir = Path(qdir)
    unpublish_delivered(qdir)
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
        plan = load_plan(qdir / "plan.json")
    unpublish_deliverables(qdir)
    dest = gdir_of(qdir) / DELIV
    dest.mkdir(exist_ok=True)
    used, names = set(), []
    files = list(deliverable_files(qdir, plan))
    mains = [x for x in files if not x[1].name.lower().endswith(PROMPT_SUFFIX)]
    safe = " ".join(re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", one_line(plan.get("title"))).split()).strip(" .")
    for tid, f in files:
        name = f"{qdir.name}_{f.name}"
        if safe and len(mains) == 1 and (tid, f) == mains[0]:
            name = f"{qdir.name}_{safe}{f.suffix}"  # 納品物が 1 つなら、依頼のタイトルをファイル名にする（探しやすいように）
        if name in used:
            name = f"{qdir.name}_{tid}_{f.name}"
        used.add(name)
        shutil.copy2(f, dest / name)
        names.append(name)
    out = {"published": names}
    if plan.get("deliver_to") and plan.get("accepted"):  # 依頼主が受け取ったら、受付係が決めた置き場（プロジェクト内）にも、同じ名前でコピーする
        rel = check_deliver_to(qdir, plan["deliver_to"])
        target = gdir_of(qdir).parent / Path(*rel.split("/"))
        target.mkdir(parents=True, exist_ok=True)
        save_plan(qdir / "delivered.json", {"dir": rel, "files": names})  # コピーの前に、置く予定の一覧を残す（途中で失敗しても、取り下げで消せる）
        for n in names:
            shutil.copy2(dest / n, target / n)
        out["delivered_to"] = rel
    return out


def new_quest(root, request_id=None):
    """ROOT/guild/.work/ に次の依頼のフォルダ（Q001, Q002, …）を作る。request_id があれば、その受付待ちの依頼を取り込む。
    依頼の inputs（依頼主が既存から選んだ名前）が guild/inputs/ になければ、依頼を requests/rejected/ へ移して拒否する（番号は進まない）。
    request.json の inputs は、選んだ名前と、取り込んだアップロードの名前を合わせたもの（重なりを除き、選んだものが先）。"""
    gdir = Path(root) / "guild"
    if not has_config(gdir):
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
        if req.get("format") is not None and not (isinstance(req["format"], str) and req["format"] in REQUEST_FORMATS):
            msg = f"format は {'・'.join(REQUEST_FORMATS)} のどれかにしてください: {req['format']!r}"
            reject_request(wdir, request_id, msg)
            raise GuildError(msg)
        t_errs = check_targets(req)
        if t_errs:
            reject_request(wdir, request_id, t_errs)
            raise GuildError(t_errs)
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
            files = sorted(inbox.glob("*.json")) if inbox.is_dir() else []
            if not files or is_legacy_plan(q / "plan.json"):
                continue  # 旧形式の依頼は、取り込めない（待機が空回りしないよう、届いたものに数えない）。届いていない依頼の plan.json は、毎秒は読まない
            out.extend({"kind": "inbox", "quest": q.name, "file": f.name} for f in files)
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
        if (wdir / PAUSE).exists():
            out.append({"kind": "pause"})  # 「ギルドを閉める」。待機を終わらせる
    return out


def pause_guild(root):
    """「ギルドを閉める」の印（.work/pause.json）を書く。すでにあれば、そのまま。"""
    gdir = Path(root) / "guild"
    if not gdir.is_dir():
        raise GuildError("guild/ がありません。先に /guild:init を実行してください")
    f = work_dir(gdir) / PAUSE
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"type": "pause", "created": datetime.datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"paused": True}


def pause_status(root):
    """印があれば paused。中身は見ない（壊れていても、止まる側に倒す）。"""
    return {"paused": (work_dir(Path(root) / "guild") / PAUSE).exists()}


def pause_clear(root):
    """印を消す。なければ何もしない。"""
    f = work_dir(Path(root) / "guild") / PAUSE
    cleared = f.exists()
    if cleared:
        f.unlink()
    return {"paused": False, "cleared": cleared}


HEARTBEAT = "heartbeat.json"  # guild/.work/heartbeat.json：ギルドマスターが動いているしるし（ボードが「待機中／作業中／停止中」を出す）
BEAT_EVERY = 10  # wait 中に印を書き直す間隔（秒）


def beat(root, state):
    """稼働の印を書く。state は waiting（依頼主の答え待ち）か working（進めている）。書けなくても、コマンドは止めない。"""
    try:
        gdir = Path(root) / "guild"
        if gdir.is_dir():
            save_plan(work_dir(gdir) / HEARTBEAT, {"state": state, "t": now(), "pid": os.getpid()})
    except OSError:
        pass


def wait_for(root, seconds, interval=1.0):
    """依頼主の入力（または新しい依頼）が届くまで待つ。すでに届いていれば、すぐ返す。待っている間は、稼働の印を書く。"""
    start = time.monotonic()
    last = None
    while True:
        a = arrivals(root)
        waited = round(time.monotonic() - start, 1)
        if a:
            beat(root, "working")
            return {"arrived": a, "waited": waited, "timeout": False}
        if last is None or time.monotonic() - last >= BEAT_EVERY:
            beat(root, "waiting")
            last = time.monotonic()
        if waited >= seconds:
            return {"arrived": [], "waited": waited, "timeout": True}
        time.sleep(interval)


CLOG = "clog.json"  # guild/.work/clog.json：クエストログ（待機の直前と完了時に、guild.py digest が作る。LLM は使わない）
ADVICE_ACTIONS = (("もう一度", "retry"), ("計画を直す", "replan"), ("やめる", "drop"))
MAX_FOLLOWUPS = 3
FOLLOWUP_MAX = 80


def section_of(text, title):
    """Markdown の「## <title>」の節の本文（次の「## 」まで）を返す。なければ空。"""
    lines, out, on = str(text).replace("\r\n", "\n").split("\n"), [], False
    for l in lines:
        if l.startswith("## "):
            if on:
                break
            on = l[3:].strip() == title
        elif on:
            out.append(l)
    return "\n".join(out).strip()


def advice_of(qdir, goal_id):
    """鑑定士の報告（reports/<id>-appraiser.md）の「勧める対応」。1 行目が もう一度／計画を直す／やめる で始まるものだけ返す。
    返り値は {"action": retry|replan|drop, "text": 1 行} か None。"""
    f = Path(qdir) / "reports" / f"{goal_id}-appraiser.md"
    try:
        body = section_of(f.read_text(encoding="utf-8"), "勧める対応")
    except OSError:
        return None
    first = one_line(body.split("\n")[0]) if body else ""
    for head, action in ADVICE_ACTIONS:
        if first.startswith(head):
            return {"action": action, "text": first}
    return None


def quest_digest(qdir):
    """依頼 1 件の、クエストログの記録。plan.json などの状態だけから、決まった形で作る。"""
    qdir = Path(qdir)
    qid = qdir.name
    plan_path = qdir / "plan.json"
    req = {}
    try:
        req = load_json(qdir / "request.json") if (qdir / "request.json").exists() else {}
    except GuildError:
        pass
    title = str((req.get("text") or "")).strip().split("\n")[0][:24] or qid
    if is_legacy_plan(plan_path):
        return {"id": qid, "title": title, "series": None, "label": "旧形式", "legacy": True, "goals": {}, "active": [], "needs": [], "blockers": [], "followups": []}
    if not plan_path.exists():
        qs = []
        try:
            d = qdir / "reports" / "plan-draft.json"
            qs = load_json(d).get("questions") if d.exists() else []
        except (GuildError, AttributeError):
            qs = []
        needs = [{"kind": "questions", "text": "質問への回答"}] if qs and not any((qdir / "inbox").glob("*answers*")) else []
        return {"id": qid, "title": title, "series": None, "label": "質問あり" if needs else "分解中", "goals": {}, "active": [],
                "needs": needs, "blockers": [], "followups": []}
    plan = load_plan(plan_path)
    goals = plan.get("goals", [])
    by = {g["id"]: g for g in goals}
    counts = {"total": len(goals), "done": sum(g["state"] == "done" for g in goals), "failed": sum(g["state"] == "failed" for g in goals),
              "skipped": sum(g["state"] == "skipped" for g in goals)}
    status = plan.get("status", "active")
    active = [{"id": g["id"], "title": g.get("title"), "class": g.get("class"), "state": g["state"]} for g in goals if g["state"] in ("running", "review")]
    needs, blockers = [], []
    if not plan.get("approved") and status == "active":
        needs.append({"kind": "approve", "text": "計画の承認"})
    for g in goals:
        if g["state"] == "awaiting_confirm":
            needs.append({"kind": "confirm", "goal": g["id"], "text": f"{g['id']} の実行前の確認"})
        elif g["state"] == "waiting_user":
            needs.append({"kind": "result", "goal": g["id"], "text": f"{g['id']}（あなたの実行）"})
        elif g["state"] == "failed":
            n = {"kind": "decision", "goal": g["id"], "text": f"{g['id']} の失敗の判断"}
            adv = advice_of(qdir, g["id"])
            if adv:
                n["advice"] = adv
            needs.append(n)
        elif g["state"] == "blocked":
            roots = sorted({d for d in g.get("deps", []) if by.get(d, {}).get("state") == "failed"})
            blockers.append({"goal": g["id"], "because": roots})
    view = next_view(plan, qdir)
    if view["awaiting_accept"]:
        needs.append({"kind": "accept", "text": "受け取りの確認"})
    follow = []
    try:
        arch = load_json(qdir / "archive.json") if (qdir / "archive.json").exists() else {}
    except GuildError:
        arch = {}
    if not isinstance(arch, dict):
        arch = {}
    if arch.get("status") == "proposed":
        needs.append({"kind": "archive", "text": "書庫の登録候補の確認"})
    if isinstance(arch.get("followups"), list):
        follow = [str(x) for x in arch["followups"]]
    if status == "aborted":
        label = "中止"
    elif view["complete"]:
        label = "完了"
    elif needs:
        label = "あなたの番"
    elif view["awaiting_overall"]:
        label = "総合確認中"
    elif plan.get("status") == "replan":
        label = "計画を直し中"
    else:
        label = "進行中"
    return {"id": qid, "title": str(plan.get("title") or title), "series": plan.get("series"), "label": label, "goals": counts,
            "active": active, "needs": needs, "blockers": blockers, "followups": follow}


def digest(root):
    """クエストログ（guild/.work/clog.json）を作る。依頼ごとの進み・あなたの番・担当の職業・止まっている理由・次の提案と、効果の集計。"""
    wd = work_dir(Path(root) / "guild")
    quests = []
    if wd.is_dir():
        for q in sorted(wd.glob("Q[0-9]*")):
            if q.is_dir():
                try:
                    quests.append(quest_digest(q))
                except (GuildError, KeyError, TypeError, AttributeError):
                    continue  # 壊れた依頼は、ログから外す（ほかの依頼は出す）
    out = {"t": now(), "quests": quests, "needs_total": sum(len(q["needs"]) for q in quests), "stats": stats(root)["total"]}
    if wd.is_dir():
        save_plan(wd / CLOG, out)
    return out


def past_quests(root, limit=50):
    """過去の依頼のタイトルと series の一覧（新しい順に limit 件）。受付係が、同じ種類の依頼に同じ series を使うための材料。"""
    wd = work_dir(Path(root) / "guild")
    out = []
    for q in sorted(wd.glob("Q[0-9]*"), reverse=True) if wd.is_dir() else []:
        if len(out) >= limit:
            break
        try:
            if (q / "plan.json").exists() and not is_legacy_plan(q / "plan.json"):
                p = load_json(q / "plan.json")
                out.append({"id": q.name, "title": p.get("title"), "series": p.get("series")})
        except (GuildError, AttributeError):
            continue
    return out


def stats(root):
    """効果の測定：依頼ごとの目標数・完了・失敗・やめた数・不合格（rejected）の回数・もう一度やる（retry）の回数・計画の直し（replan）の回数を、
    plan.json の history から数える。壊れた計画は読み飛ばす。"""
    quests = []
    tot = {"quests": 0, "goals": 0, "done": 0, "failed": 0, "skipped": 0, "rejected": 0, "retries": 0, "replans": 0, "aborted": 0}
    wd = work_dir(Path(root) / "guild")
    for f in sorted(wd.glob("Q*/plan.json")) if wd.is_dir() else []:
        try:
            p = load_plan(f)
            goals, hist = p.get("goals", []), p.get("history", [])
            q = {"id": f.parent.name, "status": p.get("status", "active"), "goals": len(goals),
                 "done": sum(t.get("state") == "done" for t in goals), "failed": sum(t.get("state") == "failed" for t in goals),
                 "skipped": sum(t.get("state") == "skipped" for t in goals),
                 "rejected": sum(h.get("event") == "rejected" for h in hist), "retries": sum(h.get("event") == "retry" for h in hist),
                 "replans": sum(h.get("event") == "replanned" for h in hist)}
        except (GuildError, AttributeError, TypeError):
            continue
        quests.append(q)
        tot["quests"] += 1
        tot["aborted"] += q["status"] == "aborted"
        for k in ("goals", "done", "failed", "skipped", "rejected", "retries", "replans"):
            tot[k] += q[k]
    tot["rejected_per_goal"] = round(tot["rejected"] / tot["goals"], 2) if tot["goals"] else 0
    return {"quests": quests, "total": tot}


def take_answers(qdir):
    """計画がまだない依頼（と、計画を直し中の依頼）の inbox から、質問への回答（type が answers）を取り出して done/ に移す。
    計画がある依頼では、answers 以外の入力は、そのまま残す（ingest が取り込む）。"""
    inbox = Path(qdir) / "inbox"
    got = []
    has_plan = (Path(qdir) / "plan.json").exists()
    if inbox.is_dir():
        for f in sorted(inbox.glob("*.json")):
            try:
                d = load_json(f)
                ok = isinstance(d, dict) and d.get("type") == "answers"
            except GuildError:
                ok = False  # 壊れたファイル
            if has_plan and not ok:
                continue  # 計画がある依頼の、ほかの入力は、取り出さない
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
    write_text_atomic(target, entry_text(e))  # 途中で切れても、半分の項目を残さない
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
    write_text_atomic(adir / "index.md", "\n".join(out))


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


def apply_experience(qdir):
    """司書の経験の要約（reports/experience-draft.json：{"summaries": {職業: 本文}}）を、職業ごとの summary.md に書く。
    承認は要らない。職業の名前の誤り・空・長すぎるものは、書かずに rejected で返す（ほかは書く）。"""
    qdir = Path(qdir)
    draft = qdir / "reports" / "experience-draft.json"
    out = {"written": [], "rejected": []}
    if not draft.exists():
        return out
    try:
        sums = load_json(draft).get("summaries")
    except (GuildError, AttributeError):
        sums = None
    if not isinstance(sums, dict):
        out["rejected"].append({"class": None, "reason": "summaries がオブジェクトではありません"})
        return out
    gdir = gdir_of(qdir)
    for c, text in sums.items():
        if c not in CLASSES:
            out["rejected"].append({"class": c, "reason": f"職業は {'・'.join(CLASSES)} のどれかです"})
        elif not isinstance(text, str) or not text.strip():
            out["rejected"].append({"class": c, "reason": "本文が空です"})
        elif len(text.strip()) > EXPERIENCE_MAX:
            out["rejected"].append({"class": c, "reason": f"{EXPERIENCE_MAX} 字を超えています（{len(text.strip())} 字）"})
        else:
            d = experience_dir(gdir) / c
            d.mkdir(parents=True, exist_ok=True)
            write_text_atomic(d / "summary.md", text.strip() + "\n")
            out["written"].append(c)
    return out


def auto_registrable(adir, c):
    """書庫に自動で登録してよい候補か。心得、または確度が出典あり（sourced）で、既存との食い違いがなく、
    依頼主が確認した項目（confirmed）や、要確認の項目を、書き換えるものではないもの。
    推測・食い違い・確認済み／要確認の項目の更新は、依頼主が選ぶ。"""
    if c["type"] == "lesson":
        return True
    if c.get("conflict") or c.get("confidence") not in AUTO_CONFIDENCE:
        return False
    rel = c.get("update_of")
    if rel and (Path(adir) / rel).is_file():
        old = read_entry(entry_path(adir, rel))
        if old.get("confidence") == "confirmed" or old.get("status") == "要確認":
            return False
    return True


def codex_line(text):
    """1 行にする。改行・\r・U+2028 など、すべての空白を 1 つの空白にし、行頭の見出し・箇条書きの記号を落とす。"""
    t = " ".join(str(text or "").split())
    while t[:1] in ("#", "-", "*", ">", "+"):
        t = t[1:].lstrip()
    return t


def codex_proposals(cands, quest):
    """同じ心得が 2 回目に出た（既存の心得の更新になる）とき、掟に足す提案にする。決めるのは依頼主。
    候補に codex（掟に書く 1 行）があればそれを、なければ要約を使う。"""
    out = []
    for c in cands:
        if c["type"] == "lesson" and c.get("update_of"):
            text = codex_line(c.get("codex") or c.get("summary"))
            if text:
                out.append({"id": f"K{len(out) + 1}", "name": codex_line(c["name"]), "text": text, "quest": quest})
    return out


def clean_followups(raw):
    """司書の「次の提案」（関連してやるとよいこと）。文字列の配列で、3 件まで、1 件 80 字まで。形の誤りは捨てる（依頼にはしない）。"""
    if not isinstance(raw, list):
        return []
    out = []
    for x in raw:
        t = codex_line(x) if isinstance(x, str) else ""
        if t:
            out.append(t[:FOLLOWUP_MAX])
    return out[:MAX_FOLLOWUPS]


def archive_propose(qdir):
    """司書の候補を検査する。心得と、確度が出典あり（sourced）で食い違いのないものは、そのまま書庫に登録する。
    推測・既存との食い違い・確度を下げる更新は、依頼主の確認待ち（archive.json）。同名・別名は更新の候補にする。
    同じ心得の 2 回目は、掟への提案にする。職業ごとの経験の要約（experience-draft.json）も、ここで書く。"""
    qdir = Path(qdir)
    adir = gdir_of(qdir) / "archive"
    init_archive(adir)
    draft = qdir / "reports" / "archive-draft.json"
    cands = load_json(draft).get("candidates", []) if draft.exists() else []
    followups = clean_followups(load_json(draft).get("followups") if draft.exists() else None)
    if not isinstance(cands, list) or len(cands) > MAX_CANDIDATES:
        raise GuildError(f"candidates は {MAX_CANDIDATES} 件までの配列にしてください")
    ids = [c.get("id") if isinstance(c, dict) else None for c in cands]
    if None in ids or len(set(ids)) != len(ids):
        raise GuildError("候補の id が欠けているか、重なっています")
    for c in cands:
        check_entry(c)
    registered, pending = [], []
    for c in cands:
        c.pop("update_of", None)  # 更新先は、司書の指定ではなく、書庫の検索の結果だけを使う
        found = find_entry(adir, c["type"], [c["name"], *c.get("aliases", [])])
        if found:
            c["update_of"] = found
        if auto_registrable(adir, c):
            registered.append(apply_candidate(adir, c, qdir.name))
        else:
            pending.append(c)
    rebuild_index(adir)
    proposals = codex_proposals(cands, qdir.name)
    state = {"status": "proposed" if pending or proposals else "done", "candidates": pending, "registered": registered,
             "codex_proposals": proposals, "followups": followups, "decided": {}}
    save_plan(qdir / "archive.json", state)
    return {"status": state["status"], "registered": registered, "pending": [c["id"] for c in pending],
            "codex_proposals": [k["id"] for k in proposals], "followups": followups, "experience": apply_experience(qdir)}


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
    codex = data.get("codex", {})
    if not isinstance(codex, dict):
        raise GuildError("codex は {提案の id: adopt か skip} にしてください")
    adir = gdir_of(qdir) / "archive"
    for c in state["candidates"]:
        if c["id"] in state["decided"]:
            continue  # 前回、途中で落ちたときに、済んだ候補。もう一度書かない（同じ項目が -2 で増えるため）
        if decisions.get(c["id"]) == "register":
            state["registered"].append(apply_candidate(adir, c, qdir.name))
            state["decided"][c["id"]] = "register"
        else:
            state["decided"][c["id"]] = "skip"
        save_plan(state_path, state)  # 1 件ごとに残す
    for k in state.get("codex_proposals", []):  # 掟への追記は、依頼主が採用したものだけ（既定は採用しない）
        if codex.get(k["id"]) == "adopt":
            append_codex(gdir_of(qdir), k)
            state["decided"][k["id"]] = "adopt"
        else:
            state["decided"][k["id"]] = "skip"
    state["status"] = "done"
    rebuild_index(adir)
    save_plan(state_path, state)


def append_codex(gdir, proposal):
    """依頼主が採用した提案を、プロジェクトの掟（guild/.work/codex/project.md）に 1 行で追記する。同じ文は、二度書かない。
    既定の掟（default.md）には触れない。"""
    path = work_dir(gdir) / CODEX / "project.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else "# プロジェクトの掟（追記）\n\n"
    ptext, pname = codex_line(proposal["text"]), codex_line(proposal["name"])
    line = f"- {ptext}（心得「{pname}」、{codex_line(proposal.get('quest'))}、{today()}）"
    if f"- {ptext}（" in text:
        return
    if "（まだありません）" in text:
        text = text.replace("（まだありません）\n", "")
    write_text_atomic(path, text.rstrip("\n") + "\n" + line + "\n")


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


# ============================================================ インプットの一覧（受付係の材料）
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
    """guild/inputs/ のファイルを一覧する（受付係がインプットを選ぶ材料）。サブフォルダは見ない。
    hints は、依頼文に出てくる書庫の項目から付ける理由。ヒントのあるファイルを先に、それぞれ名前順に並べる。"""
    gdir = Path(root) / "guild"
    if not has_config(gdir):
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


def mutate_plan(cmd, path, argv):
    """sync / advance / ingest：plan.json を読み、変え、保存する（呼び出し側が plan_lock で包む）。"""
    plan, tr = load_plan(path), load_transitions()
    errs = validate(plan, tr)
    if errs:
        raise GuildError("plan.json の検査に失敗しました: " + " / ".join(errs))
    commit = lambda: save_plan(path, plan)
    redo_goal = None
    if cmd == "sync":
        result = sync(plan, tr)
    elif cmd == "advance":
        if len(argv) != 5:
            raise GuildError("advance PLAN ID EVENT の形で指定してください")
        t = goal_map(plan).get(argv[3])
        if t is None:
            raise GuildError(f"goal がありません: {argv[3]}")
        if argv[4] == "passed" and t["state"] == "review":  # 状態が違うときは、apply_event が状態のエラーを返す
            check_evidence(plan, t["id"], Path(path).parent)
        was = t["state"]
        apply_event(t, argv[4], tr, plan)
        result = {"id": t["id"], "state": t["state"]}
        if argv[4] == "rejected" and was == "review" and t["state"] != "failed":
            redo_goal = t  # 不合格でやり直す目標：古い版の成果物は、保存のあとに prev/ へ退避する（報告は残す。鑑定士の指摘を読むため）
    else:
        result = ingest(path, plan, tr, commit=commit)  # 保存してから入力を done へ移す
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["rejected"] else 0
    commit()
    if redo_goal is not None:
        try:
            archive_outputs({"goals": [redo_goal]}, [], Path(path).parent, reports=False)
        except OSError as e:
            result["warning"] = f"古い成果物の退避に失敗しました（{e}）。output/{redo_goal['id']}/ の古いファイルを、手で prev/ へ移してください"
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) < 3 or argv[1] not in ("validate", "sync", "next", "ingest", "advance", "adopt", "init", "new", "requests", "close", "wait", "arrivals", "answers", "publish", "archive-propose", "archive-ingest", "web-ingest", "web-pending", "web-reset", "web-describe", "inputs-list", "pause", "pause-status", "pause-clear", "stats", "digest", "past-quests", "overall-skip"):
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    try:
        if cmd == "inputs-list":
            rest = argv[3:]
            if rest and (len(rest) != 2 or rest[0] not in ("--text", "--text-file")):
                raise GuildError("inputs-list ROOT [--text 依頼文 | --text-file パス] の形で指定してください（同時指定は不可）")
            text = rest[1] if rest else ""
            if rest and rest[0] == "--text-file":
                try:
                    text = Path(rest[1]).read_text(encoding="utf-8-sig")
                except (OSError, UnicodeDecodeError) as e:
                    raise GuildError(f"--text-file を読めません：{rest[1]}（{e}）")
            print(json.dumps(inputs_list(path, text), ensure_ascii=False))
            return 0
        if cmd in ("pause", "pause-status", "pause-clear"):
            print(json.dumps({"pause": pause_guild, "pause-status": pause_status, "pause-clear": pause_clear}[cmd](path), ensure_ascii=False))
            return 0
        if cmd == "web-describe":
            if len(argv) != 4:
                raise GuildError("web-describe ROOT FILE の形で指定してください")
            try:
                body = load_json(Path(argv[3]))
                result = webaccess.describe(Path(path) / "guild", body.get("descriptions") if isinstance(body, dict) else None)
            except webaccess.WebError as e:
                raise GuildError(str(e))
            print(json.dumps(result, ensure_ascii=False))
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
        if cmd == "stats":
            print(json.dumps(stats(path), ensure_ascii=False))
            return 0
        if cmd == "overall-skip":
            print(json.dumps(overall_skip(path), ensure_ascii=False))
            return 0
        if cmd == "past-quests":
            print(json.dumps(past_quests(path), ensure_ascii=False))
            return 0
        if cmd == "digest":
            print(json.dumps(digest(path), ensure_ascii=False))
            return 0
        if cmd in ("wait", "arrivals", "answers"):
            if cmd == "arrivals":
                beat(path, "working")
            if cmd == "wait":
                try:
                    digest(path)  # 待機に入る直前に、クエストログを更新する（失敗しても、待機は止めない）
                except (GuildError, OSError):
                    pass
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
            with plan_lock(path):
                print(json.dumps(adopt(path, load_transitions()), ensure_ascii=False))
            return 0
        if cmd in ("sync", "advance", "ingest"):
            with plan_lock(path):  # load から save までを 1 つずつにする（並列の advance で更新が消えない）
                return mutate_plan(cmd, path, argv)
        plan, tr = load_plan(path), load_transitions()
        if cmd == "validate":
            errs = validate(plan, tr)
            print(json.dumps({"ok": not errs, "errors": errs}, ensure_ascii=False))
            return 1 if errs else 0
        errs = validate(plan, tr)
        if errs:
            raise GuildError("plan.json の検査に失敗しました: " + " / ".join(errs))
        print(json.dumps(next_view(plan, Path(path).parent), ensure_ascii=False))
        return 0
    except GuildError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # Windows の既定（cp932）だと呼び出し側が読めない
    sys.exit(main(sys.argv))

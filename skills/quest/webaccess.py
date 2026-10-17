"""魔法使いの WebFetch の許可（標準ライブラリだけ）。

許可の状態は guild/.work/web/access.json に置く。フック（hooks/web_gate.py）と guild.py の両方が、このファイルを使う。
  allow    許可リストのドメイン（サブドメインも通す）
  once     「今回だけ」許可したドメイン。依頼の完了・中止で guild.py web-reset が空にする
  denied   依頼主が許可しなかったドメイン。同じく web-reset で空にする
  pending  魔法使いが開こうとして止められ、依頼主の答えを待っているもの（domain・urls・purposes〈WebFetch の prompt＝取りたい内容。事実〉・at）
  notes    ドメインごとの一言の説明（{ドメイン: 文}）。ギルドマスターが web-describe で書く。AI の推測で、事実ではない
依頼主の答えは guild/.work/web/inbox/ に JSON で届き、guild.py web-ingest が反映する。
"""
import contextlib
import datetime
import json
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit

WORK = ".work"  # 機械用・作業用のフォルダ（guild/ の中。Obsidian に出ない）
DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
DECISIONS = ("allow", "once", "deny")
MAX_PENDING = 50
PURPOSE_MAX, PURPOSES_MAX, NOTE_MAX = 200, 3, 80


class WebError(Exception):
    pass


def access_path(gdir):
    return Path(gdir) / WORK / "web" / "access.json"


def _blank():
    return {"allow": [], "once": [], "denied": [], "pending": [], "notes": {}}


def load(gdir):
    p = access_path(gdir)
    data = _blank()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            for k in ("allow", "once", "denied", "pending"):
                if isinstance(raw.get(k), list):
                    data[k] = raw[k]
            if isinstance(raw.get("notes"), dict):
                data["notes"] = {str(k): str(v) for k, v in raw["notes"].items() if isinstance(v, str)}
    return data


REPLACE_TRIES = 6  # Windows・OneDrive 配下で、置き換え先を他のプロセスが開いていると PermissionError になる。短い間隔で数回やり直す


LOCK_TIMEOUT = 15  # ロックを待つ秒数。超えたらエラー（他人のロックは壊さない）
LOCK_STALE = 60  # この秒数より古いロックは、落ちたプロセスの残りとみなして取り上げる


def unlink_quietly(path):
    """OneDrive・ウイルス対策が掴んでいると PermissionError になる。数回やり直し、だめでも握りつぶす（ロックは古くなれば取り上げられる）。"""
    for n in range(REPLACE_TRIES):
        try:
            Path(path).unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(0.05 * (n + 1))


def steal_stale(lock, stale=LOCK_STALE):
    """古いロックの取り上げ。取り上げ役を <lock>.steal の O_EXCL で 1 人に絞り、その中で古さを確かめ直してから消す
    （他の人が取り上げて作り直した新しいロックを消さない）。"""
    guard = Path(str(lock) + ".steal")
    try:
        os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        try:
            if time.time() - guard.stat().st_mtime > stale:
                unlink_quietly(guard)  # 取り上げ役が落ちた残り
        except OSError:
            pass
        return
    except OSError:
        return
    try:
        if time.time() - lock.stat().st_mtime > stale:
            lock.unlink()
    except OSError:
        pass
    finally:
        unlink_quietly(guard)


@contextlib.contextmanager
def file_lock(path, error=None, timeout=None, stale=None):
    """<path>.lock を O_EXCL で作る排他ロック。読み→書きを 1 つずつにする（plan.json も access.json も、これを使う）。
    取れなければ error（なければ WebError）を投げる。"""
    error = error or WebError
    timeout = LOCK_TIMEOUT if timeout is None else timeout
    stale = LOCK_STALE if stale is None else stale
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                old = time.time() - lock.stat().st_mtime > stale
            except OSError:
                continue  # 確かめている間に消えた。作り直しを試す
            if old:
                steal_stale(lock, stale)
                continue
            if time.monotonic() > deadline:
                raise error(f"{lock.name} を他のプロセスが使っています。しばらくしてからもう一度実行してください")
            time.sleep(0.05)
            continue
        except PermissionError:
            if time.monotonic() > deadline:
                raise error(f"{lock.name} を作れません（権限）")
            time.sleep(0.05)
            continue
        try:
            os.write(fd, str(os.getpid()).encode())
        except OSError:
            os.close(fd)
            unlink_quietly(lock)
            raise
        os.close(fd)
        break
    try:
        yield
    finally:
        unlink_quietly(lock)


def write_text_atomic(path, text):
    """テキストを原子的に書く。tmp 名にプロセス番号を付け、並列で書いても tmp が衝突しない（フックと guild.py は別プロセス）。"""
    tmp = Path(f"{path}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        for n in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if n == REPLACE_TRIES - 1:
                    raise
                time.sleep(0.05 * (n + 1))
    finally:
        tmp.unlink(missing_ok=True)


def save(gdir, data):
    p = access_path(gdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(p, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def domain_of(url):
    """http(s) の URL からホスト名（小文字）を返す。それ以外は None。"""
    try:
        parts = urlsplit(str(url).strip())
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    return host.lower().rstrip(".")


def check_domain(v):
    d = str(v or "").strip().lower().rstrip(".")
    if not DOMAIN_RE.match(d):
        raise WebError(f"ドメインの形が不正です: {v!r}")
    return d


def covered(domain, entries):
    """domain が entries のどれかに一致するか。登録が go.jp なら www.go.jp も通す。"""
    return any(domain == e or domain.endswith("." + e) for e in entries if isinstance(e, str))


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def one_line(text, limit):
    return " ".join(str(text or "").split())[:limit]


def gate(gdir, url, prompt="", lock_timeout=5):
    """URL を開いてよいか。(allow か deny, 魔法使いに返す理由) を返す。許可がなければ pending に積む。"""
    text = str(url).strip()
    if re.search(r"[\\\s\x00-\x1f\x7f]", text) or "@" in urlsplit(text).netloc:  # バックスラッシュ・空白・制御文字・ホスト部の @（ユーザー情報）：パーサによって、ホストの読みが変わる。開かない（パスの @ は、そのまま通す）
        return "deny", f"URL に、読み方が分かれる文字（バックスラッシュ、空白、制御文字、ホスト部の @）があるため開けません: {url!r}。URL を直して、もう一度試してください。"
    domain = domain_of(url)
    if domain is None:
        return "deny", f"http(s) の URL ではないため開けません: {url}"
    try:
        domain = domain.encode("idna").decode("ascii")  # 日本語ドメインは punycode にそろえる（許可の答えは、この形でしか受け付けない）
    except UnicodeError:
        return "deny", f"ホスト名を読めないため開けません: {url}"
    if not DOMAIN_RE.match(domain):  # IP・localhost・イントラの短い名前は、許可の答えを受け付けられない。手紙に積まず、開かない
        return "deny", f"{domain} は、ドメイン名ではない（IP アドレス・localhost など）ため開けません。今は開かずに進め、報告の「未確認」に「許可なし：{url}」と書いてください。"
    data = load(gdir)
    if covered(domain, data["allow"]) or covered(domain, data["once"]):
        return "allow", ""
    if covered(domain, data["denied"]):
        return "deny", f"依頼主が {domain} の取得を許可しませんでした。このドメインは開かずに進めてください。報告の「未確認」に「許可なし：{url}」と書いてください。"
    purpose = one_line(prompt, PURPOSE_MAX)
    with file_lock(access_path(gdir), timeout=lock_timeout):  # 並列の魔法使いが、同時に許可待ちを書いても、片方が消えない
        data = load(gdir)  # ロックの中で読み直す
        if covered(domain, data["allow"]) or covered(domain, data["once"]):
            return "allow", ""
        seen = [p for p in data["pending"] if isinstance(p, dict) and p.get("domain") == domain]
        if seen:
            changed = False
            if url not in seen[0].setdefault("urls", []) and len(seen[0]["urls"]) < 5:
                seen[0]["urls"].append(url)
                changed = True
            ps = seen[0].setdefault("purposes", [])
            if purpose and purpose not in ps and len(ps) < PURPOSES_MAX:
                ps.append(purpose)
                changed = True
            if changed:
                save(gdir, data)
        elif len(data["pending"]) < MAX_PENDING:
            data["pending"].append({"domain": domain, "urls": [url], "purposes": [purpose] if purpose else [], "at": now()})
            save(gdir, data)
        else:
            return "deny", (f"{domain} は、依頼主の許可がないため開けません。許可待ちの手紙がいっぱい（{MAX_PENDING} 件）で、この確認は積めませんでした。"
                        f"今は開かずに進め、報告の「未確認」に「許可なし：{url}」と書いてください。")
    return "deny", (f"{domain} は、依頼主の許可がないため開けません。依頼主へは、ボードの手紙で確認を出します。"
                    f"今は開かずに、ほかの出典で進められる範囲で進めてください。報告の「未確認」に「許可待ち：{url}」と書いてください。")


def apply(data, msg):
    """依頼主の答え1通を data に反映する。"""
    if not isinstance(msg, dict) or msg.get("type") != "web":
        raise WebError("type が web ではありません")
    decisions = msg.get("decisions") or {}
    add, remove = msg.get("add") or [], msg.get("remove") or []
    if not isinstance(decisions, dict) or not isinstance(add, list) or not isinstance(remove, list):
        raise WebError("decisions は辞書、add と remove は配列にしてください")
    for raw, how in decisions.items():
        d = check_domain(raw)
        if how not in DECISIONS:
            raise WebError(f"decisions の値は {'・'.join(DECISIONS)} のどれかにしてください: {how!r}")
        data["pending"] = [p for p in data["pending"] if not (isinstance(p, dict) and isinstance(p.get("domain"), str) and (p["domain"] == d or p["domain"].endswith("." + d)))]  # 親ドメインへの答えは、その下の許可待ちもまとめて片付ける
        for key in ("allow", "once", "denied"):
            data[key] = [x for x in data[key] if x != d]
        data[{"allow": "allow", "once": "once", "deny": "denied"}[how]].append(d)
    for raw in add:
        d = check_domain(raw)
        if d not in data["allow"]:
            data["allow"].append(d)
        data["denied"] = [x for x in data["denied"] if x != d]
    for raw in remove:
        d = check_domain(raw)
        data["allow"] = [x for x in data["allow"] if x != d]


def ingest(gdir):
    """guild/.work/web/inbox/ の答えを反映する。反映できなかったものは rejected/ に理由つきで移す。"""
    with file_lock(access_path(gdir)):
        return _ingest(gdir)


def _ingest(gdir):
    inbox = Path(gdir) / WORK / "web" / "inbox"
    report = {"applied": [], "rejected": []}
    if not inbox.is_dir():
        return report
    data = load(gdir)
    moves = []  # 答えのファイルの移動は、許可リストの保存のあとに行う。保存前に落ちても、答えは inbox に残る
    for f in sorted(inbox.glob("*.json")):
        try:
            try:
                msg = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise WebError(f"{f.name} を読めません: {e}")
            trial = json.loads(json.dumps(data))
            apply(trial, msg)
            data = trial
            dest, key, item, reason = inbox / "done", "applied", f.name, None
        except WebError as e:
            dest, key, item, reason = inbox / "rejected", "rejected", {"file": f.name, "reason": str(e)}, str(e)
        moves.append((f, dest, reason))
        report[key].append(item)
    save(gdir, data)
    for f, dest, reason in moves:
        dest.mkdir(exist_ok=True)
        shutil.move(str(f), str(dest / f.name))
        if reason:
            (dest / f"{f.name}.reason.txt").write_text(reason, encoding="utf-8")
    return report


def describe(gdir, mapping):
    """許可待ち・許可リスト・今回だけ許可のドメインに、一言の説明（AI の推測）を付ける。ほかのドメインは受け付けない。書いた数と、飛ばした理由を返す。"""
    if not isinstance(mapping, dict):
        raise WebError("descriptions は {ドメイン: 説明} の辞書にしてください")
    with file_lock(access_path(gdir)):
        return _describe(gdir, mapping)


def _describe(gdir, mapping):
    data = load(gdir)
    waiting = {p.get("domain") for p in data["pending"] if isinstance(p, dict)} | set(data["allow"]) | set(data["once"])  # 許可待ち・許可リスト・今回だけ許可のドメイン
    written, skipped = [], []
    for raw, text in mapping.items():
        d = check_domain(raw)
        t = one_line(text, NOTE_MAX)
        if d not in waiting:
            skipped.append({"domain": d, "reason": "許可待ち・許可リスト・今回だけ許可のどれにもありません"})
        elif not t:
            skipped.append({"domain": d, "reason": "説明が空です"})
        else:
            data["notes"][d] = t
            written.append(d)
    save(gdir, data)
    return {"written": written, "skipped": skipped}


def reset(gdir):
    """依頼の完了・中止で、「今回だけ」の許可と、許可しなかった記録を空にする。"""
    with file_lock(access_path(gdir)):
        return _reset(gdir)


def _reset(gdir):
    data = load(gdir)
    cleared = {"once": data["once"], "denied": data["denied"]}
    data["once"], data["denied"] = [], []
    keep = set(data["allow"]) | {p.get("domain") for p in data["pending"] if isinstance(p, dict)}
    data["notes"] = {k: v for k, v in data["notes"].items() if k in keep}  # 許可リストと許可待ちのドメインの説明だけ残す
    save(gdir, data)
    return {"cleared": cleared, "allow": data["allow"]}  # cleared は消したもの。残るのは allow（許可リスト）だけ


def pending(gdir):
    return [p for p in load(gdir)["pending"] if isinstance(p, dict)]

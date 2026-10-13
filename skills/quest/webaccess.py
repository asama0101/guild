"""冒険者の WebFetch の許可（標準ライブラリだけ）。

許可の状態は guild/web/access.json に置く。フック（hooks/web_gate.py）と guild.py の両方が、このファイルを使う。
  allow    許可リストのドメイン（サブドメインも通す）
  once     「今回だけ」許可したドメイン。依頼の完了・中止で guild.py web-reset が空にする
  denied   依頼主が許可しなかったドメイン。同じく web-reset で空にする
  pending  冒険者が開こうとして止められ、依頼主の答えを待っているもの
依頼主の答えは guild/web/inbox/ に JSON で届き、guild.py web-ingest が反映する。
"""
import datetime
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
DECISIONS = ("allow", "once", "deny")
MAX_PENDING = 50


class WebError(Exception):
    pass


def access_path(gdir):
    return Path(gdir) / "web" / "access.json"


def _blank():
    return {"allow": [], "once": [], "denied": [], "pending": []}


def load(gdir):
    p = access_path(gdir)
    data = _blank()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            for k in data:
                if isinstance(raw.get(k), list):
                    data[k] = raw[k]
    return data


def save(gdir, data):
    p = access_path(gdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


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


def gate(gdir, url):
    """URL を開いてよいか。(allow か deny, 冒険者に返す理由) を返す。許可がなければ pending に積む。"""
    domain = domain_of(url)
    if domain is None:
        return "deny", f"http(s) の URL ではないため開けません: {url}"
    data = load(gdir)
    if covered(domain, data["allow"]) or covered(domain, data["once"]):
        return "allow", ""
    if covered(domain, data["denied"]):
        return "deny", f"依頼主が {domain} の取得を許可しませんでした。このドメインは開かずに進めてください。報告の「未確認」に「許可なし：{url}」と書いてください。"
    seen = [p for p in data["pending"] if isinstance(p, dict) and p.get("domain") == domain]
    if seen:
        if url not in seen[0].setdefault("urls", []) and len(seen[0]["urls"]) < 5:
            seen[0]["urls"].append(url)
            save(gdir, data)
    elif len(data["pending"]) < MAX_PENDING:
        data["pending"].append({"domain": domain, "urls": [url], "at": now()})
        save(gdir, data)
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
        data["pending"] = [p for p in data["pending"] if not (isinstance(p, dict) and p.get("domain") == d)]
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
    """guild/web/inbox/ の答えを反映する。反映できなかったものは rejected/ に理由つきで移す。"""
    inbox = Path(gdir) / "web" / "inbox"
    report = {"applied": [], "rejected": []}
    if not inbox.is_dir():
        return report
    data = load(gdir)
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
        dest.mkdir(exist_ok=True)
        shutil.move(str(f), str(dest / f.name))
        if reason:
            (dest / f"{f.name}.reason.txt").write_text(reason, encoding="utf-8")
        report[key].append(item)
    save(gdir, data)
    return report


def reset(gdir):
    """依頼の完了・中止で、「今回だけ」の許可と、許可しなかった記録を空にする。"""
    data = load(gdir)
    cleared = {"once": data["once"], "denied": data["denied"]}
    data["once"], data["denied"] = [], []
    save(gdir, data)
    return {"cleared": cleared, "allow": data["allow"]}  # cleared は消したもの。残るのは allow（許可リスト）だけ


def pending(gdir):
    return [p for p in load(gdir)["pending"] if isinstance(p, dict)]

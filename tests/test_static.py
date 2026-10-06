"""画面（board.html）と文書の静的検査。ブラウザは使わず、文字列と正規表現で確かめる。"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "skills" / "init" / "board.html").read_text(encoding="utf-8")


def _func(src, name):
    """`function name(` から、波括弧の対応が閉じるまでの本文を返す。"""
    i = src.index(f"function {name}(")
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(name)


# ---------- 資料庫の節：innerHTML に入る式が esc を通っているかの機械判定 ----------
# JS を完全に解釈はしない。「テンプレートリテラルの ${...} と draw() の引数」が、次の限られた形だけかを見る。
#  - esc(...) 1 回の呼び出し全体 / 数値リテラル / 文字列リテラル / `識別子.length`
#  - 固定ラベル AS_LABEL[識別子]（ラベル表が文字列だけのリテラルのとき）
#  - 三項（条件は見ず、両枝を見る）・`||`・`+` は、各項を見る
#  - X.map(関数).join(...)（関数は式本体 or return を持つブロック、または検査対象の関数名）
#  - 同じ関数内の `名前 = 右辺` で定義された名前（右辺を同じ規則で見る）
# これ以外（生のプロパティ・添字参照・`AS_LABEL[x]||x` のような生へのフォールバック）は違反。

ASSET_FUNCS = ("assetNote", "assetActions", "renderAssets", "renderAssetsBody")


def _skip_lit(s, i):
    """s[i] が引用符またはバッククォートのとき、そのリテラルの直後の位置を返す。"""
    q = s[i]
    i += 1
    while i < len(s):
        if s[i] == "\\":
            i += 2
        elif s[i] == q:
            return i + 1
        elif q == "`" and s.startswith("${", i):
            i = _close(s, i + 1) + 1
        else:
            i += 1
    raise ValueError("リテラルが閉じない")


def _close(s, i):
    """s[i] の開き括弧に対応する閉じ括弧の位置。"""
    d = 0
    while i < len(s):
        c = s[i]
        if c in "\"'`":
            i = _skip_lit(s, i)
            continue
        if s.startswith("//", i):
            i = s.find("\n", i)
            if i < 0:
                break
            continue
        d += (c in "([{") - (c in ")]}")
        if d == 0:
            return i
        i += 1
    raise ValueError("括弧が閉じない")


def _top(s):
    """括弧・文字列・コメントの外にある文字を (位置, 文字) で返す。"""
    i = d = 0
    while i < len(s):
        c = s[i]
        if c in "\"'`":
            i = _skip_lit(s, i)
            continue
        if s.startswith("//", i):
            i = s.find("\n", i)
            if i < 0:
                return
            continue
        if c in ")]}":
            d -= 1
        if d == 0:
            yield i, c
        if c in "([{":
            d += 1
        i += 1


def _split(e, op):
    """括弧の外にある演算子 op で分ける。"""
    cuts = [i for i, _ in _top(e) if e.startswith(op, i)]
    out, prev = [], 0
    for i in cuts:
        out.append(e[prev:i])
        prev = i + len(op)
    return out + [e[prev:]]


def _is_q(e, i):
    """e[i] が三項演算子の ?（`??` と `?.` は除く）。"""
    return e[i] == "?" and e[i + 1:i + 2] not in ("?", ".") and e[i - 1:i] != "?"


def _ternary(e):
    """`cond ? a : b` なら (a, b)。条件 cond は返さない（真偽値なので出力に入らない）。"""
    q = next((i for i, _ in _top(e) if _is_q(e, i)), None)
    if q is None:
        return None
    depth = 0
    for i, c in _top(e):
        if i > q and _is_q(e, i):
            depth += 1
        elif i > q and c == ":":
            if depth == 0:
                return e[q + 1:i], e[i + 1:]
            depth -= 1
    raise ValueError("三項の : が無い")


def _calls(e):
    """括弧の外の `.名前(引数)` を [(名前, 引数文字列)] で返す。"""
    out = []
    for i, c in _top(e):
        m = re.match(r"\.(\w+)\(", e[i:]) if c == "." else None
        if m:
            out.append((m.group(1), e[i + m.end():_close(e, i + m.end() - 1)]))
    return out


def _returns(blk):
    """ブロック本体（波括弧の中身）の直下にある return の式。"""
    out = []
    for i, _ in _top(blk):
        if blk.startswith("return", i) and not re.match(r"\w", blk[i - 1:i] or " ") and blk[i + 6:i + 7] in (" ", "("):
            rest = blk[i + 6:]
            out.append(rest[:next((k for k, ch in _top(rest) if ch == ";"), len(rest))])
    return out


def _labels_literal(html):
    """AS_LABEL が「識別子: "文字列"」だけのリテラルで、文字列に HTML の特殊文字・${・\\ が無い。"""
    m = re.search(r"const AS_LABEL = \{(.*?)\};", html)
    items = [x for x in m.group(1).split(",") if x.strip()] if m else []
    return bool(items) and all(re.fullmatch(r'\s*\w+\s*:\s*"[^"<>&\'`$\\]*"\s*', x) for x in items)


def _bad_exprs(e, fsrc, labels_ok, funcs, seen=()):
    """式 e のうち、esc を通した値と同じ安全さを示せないものを返す。fsrc は e がある関数の本文。"""
    e = e.strip()

    def rec(x):
        return _bad_exprs(x, fsrc, labels_ok, funcs, seen)

    if not e or re.fullmatch(r"\d+|[A-Za-z_]\w*\.length", e):
        return []
    if e[0] == "(" and _close(e, 0) == len(e) - 1:
        return rec(e[1:-1])
    if e.startswith("esc(") and _close(e, 3) == len(e) - 1:
        return []
    if e[0] in "\"'" and _skip_lit(e, 0) == len(e):
        return []
    t = _ternary(e)
    if t:
        return rec(t[0]) + rec(t[1])
    for op in ("||", "+"):
        parts = _split(e, op)
        if len(parts) > 1:
            return [b for x in parts for b in rec(x)]
    if e[0] == "`" and _skip_lit(e, 0) == len(e):
        out, i = [], 1
        while i < len(e) - 1:
            if e[i] == "\\":
                i += 2
            elif e.startswith("${", i):
                j = _close(e, i + 1)
                out += rec(e[i + 2:j])
                i = j + 1
            else:
                i += 1
        return out
    if labels_ok and re.fullmatch(r"AS_LABEL\[\w+\]", e):
        return []
    calls = _calls(e)
    if len(calls) >= 2 and calls[-1][0] == "join" and calls[-2][0] == "map":
        fn = calls[-2][1].strip()
        if fn in funcs:
            return []
        m = re.fullmatch(r"\w+\s*=>\s*(.*)", fn, re.S)
        if m and m.group(1).strip().startswith("{"):
            return [b for r in _returns(m.group(1).strip()[1:-1]) for b in rec(r)]
        return rec(m.group(1)) if m else [e]
    if re.fullmatch(r"[A-Za-z_]\w*", e) and e not in seen:
        m = re.search(r"(?<![\w.])" + e + r"\s*=(?![=>])\s*", fsrc)
        if m:
            rest = fsrc[m.end():]
            rhs = rest[:next((k for k, c in _top(rest) if c in ",;"), len(rest))]
            return _bad_exprs(rhs, fsrc, labels_ok, funcs, seen + (e,))
    return [e]


def asset_violations(html):
    """資料庫の節の関数で、innerHTML に入る式のうち安全と示せないものを返す。"""
    labels_ok = _labels_literal(html)
    out = [] if labels_ok else ["AS_LABEL が文字列だけのリテラルでない"]
    for fn in ASSET_FUNCS:
        src = _func(html, fn)
        args = []
        for m in re.finditer(r"\bdraw\(", src):  # draw(id, html, ...) の html
            args.append(_split(src[m.end():_close(src, m.end() - 1)], ",")[1])
        i = 0
        while i < len(src):  # 関数内の最も外側のテンプレートリテラルを全て検査
            if src[i] == "`":
                j = _skip_lit(src, i)
                args.append(src[i:j])
                i = j
            elif src[i] in "\"'":
                i = _skip_lit(src, i)
            elif src.startswith("//", i):
                i = src.find("\n", i) if "\n" in src[i:] else len(src)
            else:
                i += 1
        for a in args:
            out += [f"{fn}: {b}" for b in _bad_exprs(a, src, labels_ok, ASSET_FUNCS)]
    return out


class TestBoardHtml(unittest.TestCase):
    def test_tabs_nav_and_views_match(self):
        tabs = re.search(r"const TABS = \[(.*?)\];", HTML).group(1)
        tabs = re.findall(r'"(\w+)"', tabs)
        nav = re.findall(r'<a href="#\w+" data-tab="(\w+)"', HTML)
        views = re.findall(r'<main id="v-(\w+)"', HTML)
        self.assertEqual(tabs, nav)
        self.assertEqual(tabs, views)
        self.assertIn("assets", tabs)
        self.assertIn('id="nbAssets"', HTML)
        self.assertIn('renderAssets(force)', HTML)

    def test_assets_values_are_escaped(self):
        # 許可リストではなく、${...} の中身が esc か限られた安全な形だけかを機械判定する
        self.assertEqual(asset_violations(HTML), [])

    def test_escape_checker_catches_unescaped_values(self):
        """検査器自身の確認: esc を外した（または生へフォールバックさせた）HTML は違反になる。"""
        mutations = [
            ("${esc(m[0])}：${esc(m[1])}", "${m[0]}：${esc(m[1])}"),                       # 添字参照
            ("${esc(m[0])}：${esc(m[1])}", "${esc(m[0])}：${m[1]}"),
            ("${esc(c[k] ?? 0)}", "${c[k] ?? 0}"),                                       # 添字参照
            ('data-note="${esc(id)}"', 'data-note="${id}"'),                             # 変数そのまま
            ("<b>${esc(id)}</b>", "<b>${id}</b>"),
            ('data-dk="${esc(id)}"', 'data-dk="${id}"'),
            ('<h3 class="sh">${esc(k)}</h3>${ns.map', '<h3 class="sh">${k}</h3>${ns.map'),
            ('data-asset="${esc(a)}"', 'data-asset="${a}"'),
            ("s-${esc(n.status)}", "s-${n.status}"),                                     # 属性値の途中
            ("${esc(AS_LABEL[sent.action]||sent.action)}", "${AS_LABEL[sent.action]||sent.action}"),  # 生へのフォールバック
            ("${esc(e.message)}", "${e.message}"),                                       # renderAssets の例外表示
            ("${esc(n.supersedes)}", "${n.supersedes}"),                                 # 三項の中
            ("${esc(f.item)}", "${f.item}"),                                             # map の中
            ("${esc(r.old)}", "${r.old}"),
            ("<b>${other.length}</b>", "<b>${other[0].id}</b>"),                         # .length 以外
            (".join(\" ／ \");", ".join(\" ／ \") + n.source;"),                      # 変数の右辺に生の値
            ('const AS_LABEL = {approve:"承認",', 'const AS_LABEL = {approve:n.source,'),   # ラベル表がリテラルでない
            ("head + (body ||", "head + n.source + (body ||"),                           # draw の引数
        ]
        for old, new in mutations:
            self.assertIn(old, HTML, old)
            self.assertNotEqual(asset_violations(HTML.replace(old, new, 1)), [], f"検出できない変異: {old} -> {new}")

    def test_label_table_is_literal(self):
        self.assertTrue(_labels_literal(HTML))

    def test_asset_decision_post(self):
        self.assertRegex(HTML, r'postRequest\("D",\s*\{kind:"asset_decision"')
        self.assertIn("overwrite_ok", HTML)
        # 遷移表に合わないボタンを出さない: 却下は conflict なしの候補だけ
        self.assertRegex(_func(HTML, "assetActions"), r'conflict===true \? \["overwrite_ok","overwrite_ng","trash"\]')

    def test_conflict_is_boolean(self):
        self.assertNotIn('conflict==="yes"', HTML)
        self.assertIn("n.conflict===true", _func(HTML, "assetNote"))

    def test_assets_normalized_and_isolated(self):
        norm = _func(HTML, "normAssets")
        for key in ("notes", "facts", "conflict_rows"):
            self.assertIn(key, norm)
        self.assertIn("Array.isArray", norm)
        # 無ければ null、壊れた JSON なら前の内容
        self.assertRegex(HTML, r'atxt==null\) assets = null')
        self.assertRegex(HTML, r"try\{ assets = normAssets\(JSON\.parse\(atxt\)\); \}catch")
        # 描画の例外が他のタブへ及ばない
        self.assertRegex(_func(HTML, "renderAssets"), r"try\{ renderAssetsBody")
        self.assertRegex(_func(HTML, "renderBand"), r"try\{ nAs =")

    def test_details_key_uses_id_and_unknown_status_shown(self):
        self.assertIn('data-dk="${esc(id)}"', _func(HTML, "assetNote"))
        self.assertIn("d.dataset.dk", HTML)
        self.assertIn("その他", _func(HTML, "renderAssetsBody"))
        self.assertIn('m[1]!=null && m[1]!==""', _func(HTML, "assetNote"))

    def test_send_asset_guards(self):
        src = _func(HTML, "sendAsset")
        self.assertIn('["trash","reject","overwrite_ng"].includes(action)', src)
        self.assertIn("手動", src)
        self.assertIn("btn.disabled = true", src)
        self.assertIn("finally", src)

    def test_done_column_show_more(self):
        self.assertNotIn("slice(0,8)", HTML.replace(" ", ""))
        self.assertRegex(HTML, r"const DONE_STEP = 8;\s*let doneShown = DONE_STEP;")
        self.assertRegex(HTML, r"xs\.slice\(0, doneShown\)")
        self.assertIn("`達成・中止 ${total} 件`", HTML)
        self.assertIn("`達成 ${total} 件中 ${shown} 件を表示`", HTML)
        self.assertIn("もっと見る", HTML)
        # 委譲ハンドラ（document の click）で受け、ON のときはボタンを出さない
        self.assertRegex(HTML, r'if\(c\("#doneMore"\)\)\{[^}]*?doneShown \+= DONE_STEP; renderQuests\(true\);')
        self.assertRegex(HTML, r"if\(!all && shown<total\) h \+= `<button[^`]*doneMore")

    def test_done_column_behavior(self):
        """renderQuests を最小の DOM スタブで実行し、表示件数・見出し・ボタン有無を値で確かめる。"""
        import json, shutil, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node が無い")
        head = re.search(r"const COLS = .*?\n  const DONE_STEP = 8;\n.*?\n  const qnum = [^\n]*\n", HTML, re.S).group(0)
        js = head + _func(HTML, "allQuests") + _func(HTML, "renderQuests") + r"""
const els = {}; const $ = id => els[id] || (els[id] = {textContent:"", innerHTML:"", checked:false});
const STATUSES = ["受付待ち","受付済","冒険中","鑑定中","要手直し","返事待ち","依頼主がやること","達成","中止"];
const pendingReq = [], lastHtml = {}; let dirty = false;
const board = {quests: [], questions: []};
for(let i=1;i<=20;i++) board.quests.push({id:"Q"+i, status:"達成"});
board.quests.push({id:"Q21", status:"中止"});
const isExpAsk = () => false, notSent = () => true, busy = () => false;
const keepState = (root, fn) => fn();
const card = q => `<div class="card">${q.id}</div>`;
const out = [];
const snap = () => ({title: $("doneTitle").textContent, cards: ($("k3").innerHTML.match(/class="card"/g)||[]).length,
  more: $("k3").innerHTML.includes("doneMore"), first: ($("k3").innerHTML.match(/>(Q\d+)</)||[])[1], shown: doneShown});
renderQuests(true); out.push(snap());
doneShown += DONE_STEP; renderQuests(true); out.push(snap());
doneShown += DONE_STEP; renderQuests(true); out.push(snap());
$("showAll").checked = true; renderQuests(true); out.push(snap());
console.log(JSON.stringify(out));
"""
        r = subprocess.run([node, "-e", js], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        a, b, c, d = json.loads(r.stdout)
        self.assertEqual((a["cards"], a["more"], a["title"], a["first"]), (8, True, "達成 20 件中 8 件を表示", "Q20"))
        self.assertEqual((b["cards"], b["more"], b["title"]), (16, True, "達成 20 件中 16 件を表示"))
        self.assertEqual((c["cards"], c["more"], c["title"]), (20, False, "達成 20 件中 20 件を表示"))
        self.assertEqual((d["cards"], d["more"], d["title"]), (21, False, "達成・中止 21 件"))

    def test_script_syntax(self):
        import shutil, subprocess, tempfile
        node = shutil.which("node")
        if not node:
            self.skipTest("node が無い")
        js = re.findall(r"<script>(.*?)</script>", HTML, re.S)[-1]
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestDocs(unittest.TestCase):
    FILES = ["skills/init/board.html", "skills/init/SKILL.md", "skills/help/SKILL.md", "README.md"]
    # 「5 つのタブ」「5 枚のタブ」「5のタブ」の形（「タブ」を含む語に限る。「4 つの列」などには当たらない）
    TAB_COUNT = re.compile(r"(\d+)\s*[つ枚]?の?タブ")

    def _counts(self):
        out = {}
        for f in self.FILES:
            text = (ROOT / f).read_text(encoding="utf-8")
            out[f] = self.TAB_COUNT.findall(text)
        return out

    def test_tab_count_pattern_ignores_columns(self):
        self.assertEqual(self.TAB_COUNT.findall("4 つの列と 5 つのタブ、3枚のタブ、2のタブ"), ["5", "3", "2"])
        self.assertEqual(self.TAB_COUNT.findall("4 つの列"), [])

    def test_board_html_tab_count(self):
        c = self._counts()["skills/init/board.html"]
        self.assertTrue(c)
        self.assertEqual(set(c), {"5"}, c)

    def test_tab_count_docs_consistent(self):
        """board.html 以外の文書で見つかった「N つのタブ」が全て 5 で、1 件以上あること。"""
        c = self._counts()
        found = [n for f in self.FILES[1:] for n in c[f]]
        self.assertTrue(found, c)
        self.assertEqual(set(found), {"5"}, c)


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class TestAssetDocs(unittest.TestCase):
    """R9: 資料庫の手順が文書に書かれている（キーワードの存在だけを見る。言い回しの揺れには依らない）。"""

    def _has_all(self, rel, keywords):
        text = _read(rel)
        for k in keywords:
            self.assertIn(k, text, f"{rel} に {k!r} が無い")

    def test_quest_skill(self):
        self._has_all("skills/quest/SKILL.md",
                      ["asset_decision", "assets-apply", "assets-index", "資料庫.md", "assets_dir"])
        # kind の一覧（apply-simple の取り込みの行）に asset_decision がある
        self.assertRegex(_read("skills/quest/SKILL.md"), r"kind[^\n]*asset_decision|asset_decision[^\n]*assets-apply")

    def test_assets_check_is_documented_for_quest(self):
        # assets-check は SKILL.md 本体ではなく references/assets.md に書かれている（SKILL.md の分量制限のため）
        self.assertIn("assets-check", _read("skills/quest/SKILL.md") + _read("skills/quest/references/assets.md"))

    def test_sage_rules(self):
        self._has_all("agents/sage.md", ["assets_dir", "認証情報"])
        self.assertRegex(_read("agents/sage.md"), r"確定[`」]?\s*は書かない")

    def test_readers_use_index_and_skip_candidates(self):
        for name in ("receptionist", "herald", "bard"):
            rel = f"agents/{name}.md"
            self._has_all(rel, ["資料庫.md"])
            self.assertRegex(_read(rel), r"候補[`」]?\s*は引かない", rel)

    def test_assets_reference(self):
        self._has_all("skills/quest/references/assets.md",
                      ["type: asset", "auto: minor", "supersedes", "conflict", "registered", "changed",
                       "trashed", "add-notice"])

    # ---------- 後追い（T9） ----------
    @staticmethod
    def _backfill(text):
        """assets.md の「## 後追い」節（次の ## 見出しまで）を返す。"""
        m = re.search(r"^## 後追い.*?(?=^## |\Z)", text, re.S | re.M)
        return m.group(0) if m else ""

    def test_assets_backfill_section(self):
        sec = self._backfill(_read("skills/quest/references/assets.md"))
        self.assertTrue(sec, "assets.md に「## 後追い」節が無い")
        for k in ("assets-scan", "assets-approve", "--yes", "資料庫の後追いを続けて", "oversize"):
            self.assertIn(k, sec, f"後追い節に {k!r} が無い")

    def test_assets_guildmaster_never_runs_yes(self):
        self.assertRegex(_read("skills/quest/references/assets.md"),
                         r"ギルドマスターは\s*`--yes`\s*を付けて実行しない")

    def test_assets_backfill_zero_fact_note(self):
        sec = self._backfill(_read("skills/quest/references/assets.md"))
        for k in ("抽出できなかった", "supersedes", "auto"):
            self.assertIn(k, sec, f"後追い節に {k!r} が無い")

    def test_quest_skill_backfill_line(self):
        text = _read("skills/quest/SKILL.md")
        self.assertIn("資料庫の後追い", text)
        self.assertRegex(text, r"資料庫の後追い[^\n]*references/assets\.md")
        self.assertRegex(text, r"--yes[^\n]*依頼主が実行[^\n]*付けて実行しない")

    def test_sage_backfill_rules(self):
        text = _read("agents/sage.md")
        self.assertRegex(text, r"後追い[^\n]*必ずノート[^\n]*supersedes[^\n]*auto")
        self.assertRegex(text, r"supersedes[^\n]*auto[^\n]*付けない")


if __name__ == "__main__":
    unittest.main()

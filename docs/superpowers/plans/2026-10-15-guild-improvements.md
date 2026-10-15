# guild 改善要望 4件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MCP を同梱せず環境の Playwright MCP を使い、Todo の日付とガント（新タブ「クエスト進捗」）を足し、出力を Markdown に限り、`guild/` を `.work/` で隠す浅い構成に改める。

**Architecture:** 実行エンジン `skills/quest/guild.py` / `webaccess.py` が `guild/.work/` 配下（依頼 `Q###`、受付待ち、外部サイトの許可、書庫の入力、インプットのバックアップ）を扱い、閲覧用（`archive/` `deliverables/` `inputs/` `templates/`）は `guild/` 直下に置く。ボード（`board.html`、1ファイル）は、論理パス（今の `Q001/…` `requests/…` `web/…` `archive/inbox/…`）を物理パスに写す薄い `PathMap` を通してファイルを読み書きするので、画面側のパス文字列はほとんど変えない。日付は `plan.json` の項目と既存の `due` 入力の拡張で持つ。

**Tech Stack:** Python 3 標準ライブラリ（`unittest`）、素の HTML/CSS/JS（外部ライブラリなし）、Playwright MCP（画面の確認用）。

**Spec:** `docs/specs/2026-10-15_2216_guild-improvements.md`（承認済み）

> コミットは、実行セッションで依頼主が許可したときに行う（手順にはコミットの区切りだけ書く）。テストは、リポジトリのルートで `python -m unittest tests.test_guild` を実行する（以降 `TEST`）。

## Global Constraints

- 外部ライブラリを使わない（ガントは HTML/SVG）。ボードは1ファイルの HTML で、外部通信はしない。
- 「計画の承認は1回だけ」を維持する。冒険者が `*.prompt.md` を足しても承認を取らない。
- `plan.json` を書けるのは `guild.py` だけ。進め方はデータ（`plan.json`、`transitions.json`）で持ち、役に判断させない。
- 互換性は不要（既存の `guild/` の移行はしない）。ロジックはシンプルに保つ（日付の矛盾は警告表示だけ、連動なし）。
- MCP の確認は `/guild:init` のときだけ。代替手段へのフォールバックはしない。
- 納品物は `deliverables/Q###_<元のファイル名>`（衝突時だけ `Q###_<Todo>_<元のファイル名>`）。インプットの同一判定はファイル名（大文字小文字を区別しない）、サブフォルダなし。
- コメントとコミットメッセージは日本語（既存の慣習）。パスは Windows でも動くよう `pathlib` を使う。

## Review Focus

- **同名の書庫項目が `index` のとき**：`archive/index.md`（索引）を上書きしない。→ Task 3 のテスト
- **インプットのファイル名にパス区切りや `..` が入る**：`inputs/` の外へ書かない。→ Task 4 のテスト
- **同じ依頼が同名のインプットを2回上書きする**：最初の（依頼前の）版を失わない。→ Task 4 のテスト
- **依頼の締切が未定・開始日だけ指定**：Todo の日付が登録日で埋まり、`validate` を通る。→ Task 5 のテスト
- **`replan` で作り直す**：置いた納品物が消え、日付と依頼の開始日・締切が引き継がれる。→ Task 5・7 のテスト
- **完了・中止後の `close`**：進行中の依頼のバックアップは消えない。→ Task 4 のテスト

## ファイル構成（責務）

| ファイル | 責務 | 変更 |
|---|---|---|
| `.mcp.json` | （削除） | Task 1 |
| `agents/scout.md` | 斥候。`tools` を Playwright MCP に | Task 1 |
| `skills/init/SKILL.md` | MCP の確認を最初の手順に | Task 1 |
| `skills/quest/webaccess.py` | `WORK` 定数、許可・入力のパスを `.work/web/` に | Task 2 |
| `skills/quest/guild.py` | パス、書庫（フラット）、インプット、日付、Markdown 限定、納品物の公開 | Task 2〜7 |
| `skills/quest/board.html` | `PathMap`、フラット書庫、日付 UI、新タブ、プロンプト表示、案内文 | Task 8〜11 |
| `skills/quest/SKILL.md`、`agents/*.md` | 指示書の更新（`close`/`publish`、`*.prompt.md`、日付、書庫のパス） | Task 12 |
| `README.md`、`docs/*.md` | 構成・必要なものの更新 | Task 12 |
| `tests/test_guild.py` | 各 Task の自動テスト | Task 1〜8 |

---

### Task 1: 要望1 — MCP を同梱しない

**Files:**
- Delete: `.mcp.json`
- Modify: `agents/scout.md:4`（`tools` 行）
- Modify: `skills/init/SKILL.md`（手順の先頭に MCP の確認を足す）
- Modify: `README.md`（「必要なもの」）
- Test: `tests/test_guild.py`（末尾に `McpContractTest`）

**Interfaces:**
- Produces: なし（後続の Task は MCP に依存しない）

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_guild.py` の末尾に追加）

```python
class McpContractTest(unittest.TestCase):
    """MCP は同梱しない。斥候は環境の Playwright MCP（サーバー名 playwright）を使い、init が先に確認する。"""

    def test_no_bundled_mcp(self):
        self.assertFalse((ROOT / ".mcp.json").exists())

    def test_scout_uses_environment_playwright(self):
        head = (ROOT / "agents" / "scout.md").read_text(encoding="utf-8").split("---")[1]
        tools = re.search(r"^tools:(.*)$", head, re.M).group(1)
        for name in ("navigate", "snapshot", "wait_for", "press_key", "take_screenshot", "tabs", "close"):
            self.assertIn(f"mcp__playwright__browser_{name}", tools)
        self.assertNotIn("plugin_guild_browser", tools)

    def test_init_skill_checks_the_mcp_first(self):
        s = (ROOT / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("mcp__playwright__browser_navigate", s)
        self.assertLess(s.index("mcp__playwright__browser_navigate"), s.index("使える Python を探す"))
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.McpContractTest -v`
Expected: 3件とも FAIL

- [ ] **Step 3: 実装する**

`.mcp.json` を削除する（`git rm .mcp.json`）。`agents/scout.md` の4行目を次に置き換える。

```
tools: Read, Glob, Grep, Write, mcp__playwright__browser_navigate, mcp__playwright__browser_snapshot, mcp__playwright__browser_wait_for, mcp__playwright__browser_press_key, mcp__playwright__browser_take_screenshot, mcp__playwright__browser_tabs, mcp__playwright__browser_close
```

`skills/init/SKILL.md` の「## 手順」の直後（`1. **使える Python を探す。**` の前）に、次の手順を挿入し、以降の番号を1つずつ繰り下げる。

```markdown
1. **Playwright MCP を確認する。** 斥候（動的ページを読む役）が使うので、このセッションで使えるか確かめる。ツール一覧に `mcp__playwright__browser_navigate` があればよい（後から読み込む形式のツールなら、`ToolSearch` で `select:mcp__playwright__browser_navigate` を引く）。**なければ、次の警告を伝えて、ここで止める**（`guild/` は作らない。代わりの手段は使わない）。

   > Playwright MCP が見つかりません。guild の斥候が使います。`playwright` という名前で導入・接続してから、`/guild:init` をもう一度実行してください。
   > 導入の例：`claude mcp add playwright -- npx -y @playwright/mcp@0.0.83 --headless --isolated`
```

`description` の行の末尾に「Playwright MCP が使えないときは警告して止まる。」を足す。`README.md` の「必要なもの」の Node.js の行を次に置き換える。

```markdown
- Playwright MCP（斥候が動的ページを読むときに使う。`playwright` という名前で導入・接続しておく。未接続だと `/guild:init` が警告して止まる）
```

- [ ] **Step 4: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.McpContractTest -v` → PASS。続けて `TEST` が全部通ること。

- [ ] **Step 5: コミット**

```bash
git add -A .mcp.json agents/scout.md skills/init/SKILL.md README.md tests/test_guild.py
git commit -m "MCP を同梱しない：斥候は環境の Playwright MCP を使い、init が未接続なら止める"
```

---

### Task 2: 作業用フォルダ `.work/` へ移す（Python 側）

**Files:**
- Modify: `skills/quest/webaccess.py:28,136`（と先頭の docstring）
- Modify: `skills/quest/guild.py`（定数・`init_guild`・`list_requests`・`new_quest`・`arrivals`・`adopt`・`archive_propose`・`archive_decide`・`archive_ingest`、先頭の docstring）
- Test: `tests/test_guild.py`（既存テストのパス更新と `WorkDirTest`）

**Interfaces:**
- Produces（以降の Task が使う）：
  - `guild.WORK == ".work"`（`webaccess.WORK` と同じ値）
  - `guild.work_dir(gdir) -> Path`：`gdir/.work`
  - `guild.gdir_of(qdir) -> Path`：`guild/.work/Q001` から `guild/` を返す
  - 配置：依頼 `guild/.work/Q###/`、受付待ち `guild/.work/requests/`（添付は `requests/files/<ID>/`）、外部サイト `guild/.work/web/{access.json,inbox/}`、書庫の入力 `guild/.work/archive-inbox/`

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_guild.py` に追加）

```python
class WorkDirTest(unittest.TestCase):
    """機械用のファイルは guild/.work/ に置く（Obsidian に出さない）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.g = self.root / "guild"

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_and_new_use_work(self):
        self.assertTrue((self.g / ".work" / "requests").is_dir())
        self.assertFalse((self.g / "requests").exists())
        q = guild.new_quest(self.root)
        self.assertEqual(Path(q["dir"]), self.g / ".work" / "Q001")
        self.assertEqual(guild.gdir_of(q["dir"]), self.g)
        self.assertFalse((self.g / "Q001").exists())

    def test_arrivals_read_work(self):
        q = Path(guild.new_quest(self.root)["dir"])
        (q / "inbox" / "a.json").write_text("{}", encoding="utf-8")
        (self.g / ".work" / "requests" / "R20261010-1.json").write_text("{}", encoding="utf-8")
        (self.g / ".work" / "archive-inbox").mkdir()
        (self.g / ".work" / "archive-inbox" / "b.json").write_text("{}", encoding="utf-8")
        (self.g / ".work" / "web" / "inbox").mkdir(parents=True)
        (self.g / ".work" / "web" / "inbox" / "c.json").write_text("{}", encoding="utf-8")
        kinds = sorted((a["kind"], a.get("file") or a.get("id")) for a in guild.arrivals(self.root))
        self.assertEqual(kinds, [("archive", "b.json"), ("inbox", "a.json"), ("request", "R20261010-1"), ("web", "c.json")])

    def test_web_access_lives_in_work(self):
        webaccess.save(self.g, dict(webaccess.load(self.g), allow=["example.jp"]))
        self.assertTrue((self.g / ".work" / "web" / "access.json").is_file())
        self.assertFalse((self.g / "web").exists())
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.WorkDirTest -v` → FAIL（`gdir_of` がない、など）

- [ ] **Step 3: `webaccess.py` を直す**

`import` の後（`DOMAIN_RE` の前）に次を足す。

```python
WORK = ".work"  # 機械用・作業用のフォルダ（guild/ の中。Obsidian に出ない）
```

`access_path` と `ingest` の `"web"` を `WORK` 経由にする。

```python
def access_path(gdir):
    return Path(gdir) / WORK / "web" / "access.json"
```

```python
    inbox = Path(gdir) / WORK / "web" / "inbox"
```

先頭の docstring の `guild/web/access.json` → `guild/.work/web/access.json`、`guild/web/inbox/` → `guild/.work/web/inbox/`。

- [ ] **Step 4: `guild.py` を直す**

`import webaccess` の下に定数と補助関数を足す。

```python
WORK = webaccess.WORK


def work_dir(gdir):
    """機械用・作業用のフォルダ。依頼（Q###）、受付待ちの依頼、外部サイトの許可、書庫の入力、インプットのバックアップを置く。"""
    return Path(gdir) / WORK


def gdir_of(qdir):
    """依頼のフォルダ（guild/.work/Q001）から guild/ を返す。"""
    return Path(qdir).parent.parent
```

各関数を次のとおりに直す。

`init_guild`：

```python
    (work_dir(gdir) / "requests").mkdir(parents=True, exist_ok=True)
```
（`(gdir / "requests").mkdir(exist_ok=True)` を置き換える）

`list_requests`：`rdir = work_dir(Path(root) / "guild") / "requests"`

`new_quest`：

```python
    wdir = work_dir(gdir)
    wdir.mkdir(exist_ok=True)
    src = None
    if request_id is not None:
        if not REQUEST_ID.match(request_id):
            raise GuildError(f"依頼の ID が不正です: {request_id}")
        src = wdir / "requests" / f"{request_id}.json"
        if not src.exists():
            raise GuildError(f"{src} がありません")
    nums = [int(p.name[1:]) for p in wdir.iterdir() if p.is_dir() and p.name[:1] == "Q" and p.name[1:].isdigit()]
    qdir = wdir / f"Q{max(nums, default=0) + 1:03d}"
```
と、後段の `files = wdir / "requests" / "files" / request_id`。

`arrivals`：

```python
    gdir = Path(root) / "guild"
    wdir = work_dir(gdir)
    out = []
    if wdir.is_dir():
        for q in sorted(wdir.glob("Q[0-9]*")):
            ...                                   # inbox の走査は今のまま
        req = wdir / "requests"                   # 以下、requests / archive-inbox / web/inbox
        ...
        ainbox = wdir / "archive-inbox"
        ...
        winbox = wdir / "web" / "inbox"
```
（`if gdir.is_dir():` を `if wdir.is_dir():` に変える。ほかの本体は今のまま。）

`adopt`：`tpl = gdir_of(plan_path.parent) / str(template)`

`archive_propose` / `archive_decide`：`adir = gdir_of(qdir) / "archive"`

`archive_ingest`：

```python
    adir = Path(root) / "guild" / "archive"
    inbox = work_dir(Path(root) / "guild") / "archive-inbox"
```

先頭の docstring：`archive/inbox/` → `.work/archive-inbox/`、`web/inbox/` → `.work/web/inbox/`、`ROOT/guild/ に次の依頼のフォルダ（Q001…）` → `ROOT/guild/.work/ に…`。

- [ ] **Step 5: 既存テストのパスを更新する**

Run: `TEST` で落ちたものを、次の規則で直す。

| 古い | 新しい |
|---|---|
| `self.root / "guild" / "requests"`（370, 379, 387, 405, 436, 480 行付近） | `self.root / "guild" / ".work" / "requests"` |
| `Path(d) / "guild" / "Q001"`（`TemplateTest.make`、654 行付近） | `Path(d) / "guild" / ".work" / "Q001"` |
| `self.gdir / "web"`（`WebAccessTest`、1177〜1241 行付近） | `self.gdir / ".work" / "web"` |
| `ArchiveTest.put_inbox` の `self.adir / "inbox"`（875 行付近） | `self.root / "guild" / ".work" / "archive-inbox"` |
| `test_init_makes_archive_and_keeps_items` の `"inbox"`（897 行付近） | 外す（書庫の中に `inbox/` は作らない） |

`Path(d) / "Q001"` だけの直接の依頼フォルダを使うテスト（`AdoptTest`、`DueTest` など）は、`adopt` が `gdir_of` を使うのはテンプレートがあるときだけなので、そのままでよい。

- [ ] **Step 6: 通ることを確かめる**

Run: `TEST` → すべて PASS。

- [ ] **Step 7: コミット**

```bash
git add skills/quest/guild.py skills/quest/webaccess.py tests/test_guild.py
git commit -m "作業用のファイル（依頼・受付待ち・外部サイト・書庫の入力）を guild/.work/ に移す"
```

---

### Task 3: 書庫をフラットにする

**Files:**
- Modify: `skills/quest/guild.py`（`ARCHIVE_DIRS` と、それを使う `init_archive`・`write_entry`・`entry_path`・`all_entries`・`check_entry`・`archive_apply` の `retype`）
- Test: `tests/test_guild.py`（`ArchiveTest` の更新）

**Interfaces:**
- Consumes: Task 2 の配置
- Produces：書庫の項目の相対パスは `名前.md`（フォルダなし）。`guild.ARCHIVE_TYPES == ("term","flow","fact","personal","lesson")`。種類は frontmatter の `type`。`write_entry(adir, e, path=None) -> str`（`path` は `名前.md`）。`all_entries(adir)` は `(名前.md, entry)` を返す。

- [ ] **Step 1: 失敗するテストを書く**（`ArchiveTest` に追加。既存の `test_init_makes_archive_and_keeps_items` は次のとおりに差し替える）

```python
    def test_init_makes_flat_archive_and_keeps_items(self):
        self.assertTrue((self.adir / "index.md").is_file())
        self.assertEqual([p.name for p in self.adir.iterdir() if p.is_dir()], [])  # 種類別フォルダはない
        rel = guild.write_entry(self.adir, self.entry(type="fact", name="料金", summary="s"))
        self.assertEqual(rel, "料金.md")
        guild.init_guild(self.root)  # 再実行しても消えない
        self.assertTrue((self.adir / "料金.md").is_file())

    def test_an_entry_named_index_does_not_overwrite_the_index(self):
        rel = guild.write_entry(self.adir, self.entry(name="index", summary="s"))
        self.assertNotEqual(rel, "index.md")
        guild.rebuild_index(self.adir)
        self.assertIn("書庫の索引", (self.adir / "index.md").read_text(encoding="utf-8"))

    def test_entry_path_accepts_only_flat_md_names(self):
        guild.write_entry(self.adir, self.entry(name="KPI", summary="s"))
        self.assertEqual(guild.entry_path(self.adir, "KPI.md"), self.adir / "KPI.md")
        for bad in ("terms/KPI.md", "../x.md", "index.md", "KPI.txt", "ない.md"):
            with self.assertRaises(guild.GuildError):
                guild.entry_path(self.adir, bad)

    def test_retype_only_rewrites_type_in_place(self):
        rel = guild.write_entry(self.adir, self.entry(name="料金", type="term", summary="s", confidence="confirmed", source="x"))
        self.put_inbox("1.json", {"type": "retype", "path": rel, "to": "fact"})
        r = guild.archive_ingest(self.root)
        self.assertEqual(r["rejected"], [])
        self.assertEqual(guild.read_entry(self.adir / rel)["type"], "fact")
        self.assertEqual([p.name for p in self.adir.glob("*.md")].count(rel), 1)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.ArchiveTest -v` → 上の4件が FAIL

- [ ] **Step 3: 実装する**

`ARCHIVE_DIRS = {...}` の行を次に置き換える。

```python
ARCHIVE_TYPES = ("term", "flow", "fact", "personal", "lesson")  # 書庫の項目の種類。フォルダは分けず、種類は frontmatter の type で持つ
INDEX_NAME = "index.md"
```

`init_archive`：

```python
def init_archive(adir):
    """archive/ と索引を作る。既存の項目は消さない。"""
    adir = Path(adir)
    adir.mkdir(parents=True, exist_ok=True)
    if not (adir / INDEX_NAME).exists():
        rebuild_index(adir)
```

`check_entry` の最初の判定：`if e.get("type") not in ARCHIVE_TYPES:` と、メッセージ `{', '.join(ARCHIVE_TYPES)}`。

`write_entry` の `path is None` の枝を次にする。

```python
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
```

`entry_path`：

```python
def entry_path(adir, rel):
    """archive/ の中の項目（フォルダなしの 名前.md）だけを指せる。索引や、外は指せない。"""
    name = str(rel).replace("\\", "/")
    ok = "/" not in name and name.endswith(".md") and name != INDEX_NAME and ".." not in name
    p = Path(adir) / name
    if not ok or not p.is_file():
        raise GuildError(f"項目が見つかりません: {rel}")
    return p
```

`all_entries`：

```python
def all_entries(adir):
    for f in sorted(Path(adir).glob("*.md")):
        if f.name == INDEX_NAME:
            continue
        e = read_entry(f)
        if e is not None:
            yield f.name, e
```

`archive_apply` の `retype` の枝を次にする（`src.unlink()` 以降の移動処理が要らなくなる）。

```python
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
```

`rebuild_index` の場所の列 `f"[[{rel[:-3]}]]"` はそのまま（`[[名前]]` になる）。

- [ ] **Step 4: 既存の `ArchiveTest` を新しい形に直す**

Run: `python -m unittest tests.test_guild.ArchiveTest` で落ちたものを、次の規則で直す。

| 古い | 新しい |
|---|---|
| `self.adir / "terms" / "X.md"`（903, 968, 1002, 1042, 1069 行付近）、`"flows"`、`"facts"` | `self.adir / "X.md"` |
| パス文字列 `"terms/KPI.md"`、`"flows/経費精算.md"`、`"terms/ない.md"`（1053, 1067, 1107, 1139, 1148, 1152〜1154 行付近） | `"KPI.md"`、`"経費精算.md"`、`"ない.md"`（`"terms/none.md"` は不正な例のまま、`"../x.md"` も残す） |
| `"[[personal/文体]]"`、`"[[terms/生きている]]"`、`"[[facts/料金]]"`（911, 949, 1086 行付近） | `"[[文体]]"`、`"[[生きている]]"`、`"[[料金]]"`。`assertNotIn("[[terms/料金]]")` は `assertNotIn` を種類別の一覧の確認に置き換える（`type: term` の行が索引にないこと） |
| `rel.startswith("facts/")`（923〜924 行付近） | `self.assertNotIn("/", rel)` |
| `len(list((self.adir / "terms").glob("*.md"))) == 1`（1014 行付近） | `len([p for p in self.adir.glob("*.md") if p.name != "index.md"]) == 1` |
| 「ファイル名だけ同じ」の `write_entry(..., "facts/料金.md")`、`self.adir / "facts" / "料金-2.md"`（1097〜1101 行付近） | `"料金.md"`、`self.adir / "料金-2.md"` |
| `retype` のテスト（1105〜1125 行付近）の「移動して元が消える」確認 | Step 1 の `test_retype_only_rewrites_type_in_place` に置き換え、`self_.parent.name == "terms"` のパッチは削除 |

- [ ] **Step 5: 通ることを確かめる**

Run: `TEST` → PASS

- [ ] **Step 6: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "書庫をフラットにする（種類は frontmatter の type で持ち、retype はその場で書き換える）"
```

---

### Task 4: 共通インプット `inputs/` とバックアップ・`close`

**Files:**
- Modify: `skills/quest/guild.py`（`import_inputs`、`new_quest`、`close_quests`、`main`、docstring）
- Test: `tests/test_guild.py`（`InitAndNewTest` の更新と `InputsTest`）

**Interfaces:**
- Consumes: Task 2 の `work_dir`、`gdir_of`
- Produces：
  - `guild.import_inputs(gdir, files_dir, quest) -> list[str]`：取り込んだ名前（`inputs/` の中の実際の名前）。同名（大文字小文字を区別しない）で内容が同じなら何もしない。違えば上書きし、古い版を `guild/.work/backup/<quest>/<名前>` に（その依頼で最初に上書きする版だけ）残す。
  - `new_quest` の戻り値に `inputs`（名前のリスト）と `inputs_dir`。`request.json` に `"inputs": [...]` が入る。
  - `guild.close_quests(root) -> {"removed": ["Q003", ...]}`、CLI `guild.py close ROOT`：完了（`accepted`）または中止（`status == "aborted"`）の依頼のバックアップを消す。

- [ ] **Step 1: 失敗するテストを書く**

```python
class InputsTest(unittest.TestCase):
    """素材は guild/inputs/ に1つだけ置く。上書き前の版はバックアップし、上書きした依頼が閉じたら消す。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.g = self.root / "guild"

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, rid, **files):
        w = self.g / ".work"
        (w / "requests").mkdir(parents=True, exist_ok=True)
        (w / "requests" / f"{rid}.json").write_text(json.dumps({"type": "request", "text": "t", "files": list(files)}), encoding="utf-8")
        fdir = w / "requests" / "files" / rid
        fdir.mkdir(parents=True)
        for name, body in files.items():
            (fdir / name).write_text(body, encoding="utf-8")

    def test_new_quest_puts_inputs_in_the_shared_folder(self):
        self.request("R20261010-1", **{"メモ.txt": "v1"})
        q = guild.new_quest(self.root, "R20261010-1")
        self.assertEqual((self.g / "inputs" / "メモ.txt").read_text(encoding="utf-8"), "v1")
        self.assertEqual(q["inputs"], ["メモ.txt"])
        self.assertEqual(guild.load_json(Path(q["dir"]) / "request.json")["inputs"], ["メモ.txt"])
        self.assertFalse((Path(q["dir"]) / "inputs").exists())
        self.assertFalse((self.g / ".work" / "requests" / "files" / "R20261010-1").exists())

    def test_same_content_does_nothing_and_different_content_overwrites_with_backup(self):
        self.request("R20261010-1", **{"メモ.txt": "v1"})
        guild.new_quest(self.root, "R20261010-1")
        self.request("R20261010-2", **{"メモ.txt": "v1"})
        guild.new_quest(self.root, "R20261010-2")
        self.assertFalse((self.g / ".work" / "backup").exists())  # 同じ内容なら何も起きない
        self.request("R20261010-3", **{"メモ.TXT": "v2"})  # 大文字小文字だけ違う名前も同じもの
        guild.new_quest(self.root, "R20261010-3")
        self.assertEqual([p.name for p in (self.g / "inputs").iterdir()], ["メモ.txt"])
        self.assertEqual((self.g / "inputs" / "メモ.txt").read_text(encoding="utf-8"), "v2")
        self.assertEqual((self.g / ".work" / "backup" / "Q003" / "メモ.txt").read_text(encoding="utf-8"), "v1")

    def test_a_quest_overwriting_twice_keeps_the_first_backup(self):
        self.request("R20261010-1", **{"a.txt": "v1"})
        guild.new_quest(self.root, "R20261010-1")
        self.request("R20261010-2", **{"a.txt": "v2"})
        guild.new_quest(self.root, "R20261010-2")
        bak = self.g / ".work" / "backup" / "Q002" / "a.txt"
        guild.import_inputs(self.g, self._files(a="v3"), "Q002")  # 同じ依頼が、もう一度上書きする
        self.assertEqual(bak.read_text(encoding="utf-8"), "v1")  # 依頼前の版を失わない
        self.assertEqual((self.g / "inputs" / "a.txt").read_text(encoding="utf-8"), "v3")

    def _files(self, **kw):
        d = Path(tempfile.mkdtemp(dir=self.tmp.name))
        for n, b in kw.items():
            (d / n).write_text(b, encoding="utf-8")
        return d

    def test_close_removes_only_backups_of_closed_quests(self):
        self.request("R20261010-1", **{"a.txt": "v1"})
        guild.new_quest(self.root, "R20261010-1")
        for rid, body in (("R20261010-2", "v2"), ("R20261010-3", "v3")):
            self.request(rid, **{"a.txt": body})
            guild.new_quest(self.root, rid)
        for q, extra in (("Q002", {"accepted": True}), ("Q003", {})):
            guild.save_plan(self.g / ".work" / q / "plan.json", dict(plan(todo("T1")), **extra))
        self.assertEqual(guild.close_quests(self.root), {"removed": ["Q002"]})
        self.assertFalse((self.g / ".work" / "backup" / "Q002").exists())
        self.assertTrue((self.g / ".work" / "backup" / "Q003").is_dir())  # 進行中の依頼のバックアップは残る
        guild.save_plan(self.g / ".work" / "Q003" / "plan.json", dict(plan(todo("T1")), status="aborted"))
        self.assertEqual(guild.close_quests(self.root), {"removed": ["Q003"]})

    def test_unsafe_names_are_skipped(self):
        d = self._files(**{"ok.txt": "x"})
        (d / "sub").mkdir()
        (d / "sub" / "inner.txt").write_text("y", encoding="utf-8")
        self.assertEqual(guild.import_inputs(self.g, d, "Q001"), ["ok.txt"])  # サブフォルダは取り込まない
        self.assertEqual([p.name for p in (self.g / "inputs").iterdir()], ["ok.txt"])
```

また `InitAndNewTest.test_new_takes_request_and_files` の `inputs` の確認行を次に差し替える（Task 2 で `.work/requests` に移した後）。

```python
        self.assertEqual((self.root / "guild" / "inputs" / "memo.txt").read_text(encoding="utf-8"), "素材")
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.InputsTest tests.test_guild.InitAndNewTest -v` → FAIL

- [ ] **Step 3: 実装する**（`new_quest` の直前に追加）

```python
INPUTS = "inputs"


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
```

`new_quest` の `if src is not None:` の枝を次に置き換える。

```python
    if src is not None:
        out["request"] = load_json(src)
        shutil.move(str(src), str(qdir / "request.json"))
        files = wdir / "requests" / "files" / request_id
        names = []
        if files.is_dir():
            names = import_inputs(gdir, files, qdir.name)
            shutil.rmtree(files)
        req = load_json(qdir / "request.json")
        req["inputs"] = names
        save_plan(qdir / "request.json", req)  # JSON を原子的に書く関数（plan 専用の名前だが中身は汎用）
        out["inputs"], out["inputs_dir"] = names, str(gdir / INPUTS)
```

`main` の許可リストに `"close"` を足し、`("init", "new", "requests")` の群に次を足す。

```python
        if cmd == "close":
            print(json.dumps(close_quests(path), ensure_ascii=False))
            return 0
```

先頭の docstring に `guild.py close ROOT: 完了・中止した依頼のインプットのバックアップを消す。` を足す。

- [ ] **Step 4: 通ることを確かめる**

Run: `TEST` → PASS

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "共通インプット guild/inputs/：同名は上書きして古い版をバックアップし、依頼が閉じたら消す"
```

---

### Task 5: 日付（依頼の開始日・締切、Todo の予定日・締切）

**Files:**
- Modify: `skills/quest/guild.py`（`check_date`、`validate`、`adopt`、`apply_input`、docstring）
- Test: `tests/test_guild.py`（`DueTest` に追加、`BoardContractTest.CASES` に追加）

**Interfaces:**
- Produces：
  - `plan.json` の最上位に `start`・`due`（`YYYY-MM-DD`）。各 Todo に `scheduled`・`due`。
  - `guild.check_date(v, label) -> str | None`（`check_due(v)` は `check_date(v, "due")` の別名のまま）。
  - 入力 `{"type":"due","todo":"T1","scheduled":"2026-10-20","due":"2026-10-22"}`（どちらか片方でもよい。`due` は `null` で解除できる。`scheduled` は解除できない）。
  - 入力 `{"type":"due","start":"2026-10-15","due":"2026-10-30"}`（`todo` なし = 依頼の日付。どちらも解除できない）。
  - `adopt` は、依頼の `start`・`due`（`request.json`。replan のときは旧計画の値を優先）を取り、未指定は `start = 今日`、`due = start`。Todo の `scheduled` 未指定は `start`、`due` 未指定は依頼の `due` で埋める。

- [ ] **Step 1: 失敗するテストを書く**（`DueTest` に追加）

```python
    def test_set_todo_scheduled_and_due_together(self):
        p = plan(todo("T1", state="running"))
        r = self.ingest(p, {"type": "due", "todo": "T1", "scheduled": "2026-10-20", "due": "2026-10-22"})
        self.assertEqual(r["rejected"], [])
        self.assertEqual((p["todos"][0]["scheduled"], p["todos"][0]["due"]), ("2026-10-20", "2026-10-22"))
        self.assertEqual(p["history"][-1]["scheduled"], "2026-10-20")
        self.assertNotIn("id", p["history"][-1])

    def test_scheduled_cannot_be_cleared_or_malformed(self):
        for bad in (None, "", "2026-02-30", 20261020):
            with self.subTest(bad=bad):
                p = plan(todo("T1", scheduled="2026-10-20"))
                self.assertEqual(len(self.ingest(p, {"type": "due", "todo": "T1", "scheduled": bad})["rejected"]), 1)
                self.assertEqual(p["todos"][0]["scheduled"], "2026-10-20")

    def test_set_quest_start_and_due(self):
        p = plan(todo("T1"))
        p["start"], p["due"] = "2026-10-15", "2026-10-15"
        r = self.ingest(p, {"type": "due", "start": "2026-10-16", "due": "2026-10-30"})
        self.assertEqual(r["rejected"], [])
        self.assertEqual((p["start"], p["due"]), ("2026-10-16", "2026-10-30"))
        self.assertNotIn("todo", p["history"][-1])
        for bad in ({"type": "due", "due": None}, {"type": "due", "start": None}, {"type": "due", "scheduled": "2026-10-20"}, {"type": "due"}):
            with self.subTest(bad=bad):
                self.assertEqual(len(self.ingest(p, bad)["rejected"]), 1)
        self.assertEqual((p["start"], p["due"]), ("2026-10-16", "2026-10-30"))

    def test_order_mismatch_is_not_an_error(self):
        p = plan(todo("T1", scheduled="2026-11-01", due="2026-10-01"))
        p["start"], p["due"] = "2026-10-15", "2026-10-20"
        self.assertEqual(guild.validate(p, TR), [])  # 矛盾はボードの警告表示だけ

    def test_validate_checks_new_date_fields(self):
        p = plan(todo("T1", scheduled="10/20"))
        self.assertTrue(any("T1" in e and "scheduled" in e for e in guild.validate(p, TR)))
        p = plan(todo("T1"))
        p["start"] = "2026-13-01"
        self.assertTrue(any("start" in e for e in guild.validate(p, TR)))


class AdoptDatesTest(unittest.TestCase):
    def adopt(self, request=None, todos=None, old=None):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "guild" / ".work" / "Q001"
            (q / "reports").mkdir(parents=True)
            if request is not None:
                (q / "request.json").write_text(json.dumps(request), encoding="utf-8")
            if old is not None:
                (q / "plan.json").write_text(json.dumps(old), encoding="utf-8")
            draft = {"quest": "Q001", "title": "t", "todos": todos or [
                {"id": "T1", "title": "a", "kind": "auto", "deps": [], "criteria": CRIT}]}
            (q / "reports" / "plan-draft.json").write_text(json.dumps(draft), encoding="utf-8")
            guild.adopt(q / "plan.json", TR)
            return json.loads((q / "plan.json").read_text(encoding="utf-8"))

    def test_unspecified_dates_become_today_everywhere(self):
        today = guild.today()
        p = self.adopt()
        self.assertEqual((p["start"], p["due"]), (today, today))
        self.assertEqual((p["todos"][0]["scheduled"], p["todos"][0]["due"]), (today, today))

    def test_request_dates_are_taken_and_draft_todo_dates_are_kept(self):
        p = self.adopt(request={"start": "2026-10-15", "due": "2026-10-30"}, todos=[
            {"id": "T1", "title": "a", "kind": "auto", "deps": [], "criteria": CRIT, "scheduled": "2026-10-16", "due": "2026-10-18"},
            {"id": "T2", "title": "b", "kind": "human", "deps": ["T1"], "criteria": CRIT, "instruction": "x"}])
        self.assertEqual((p["start"], p["due"]), ("2026-10-15", "2026-10-30"))
        self.assertEqual((p["todos"][0]["scheduled"], p["todos"][0]["due"]), ("2026-10-16", "2026-10-18"))
        self.assertEqual((p["todos"][1]["scheduled"], p["todos"][1]["due"]), ("2026-10-15", "2026-10-30"))

    def test_start_only_request_gets_due_equal_to_start(self):
        p = self.adopt(request={"start": "2026-10-15", "due": None})
        self.assertEqual((p["start"], p["due"]), ("2026-10-15", "2026-10-15"))

    def test_replan_keeps_the_old_plan_dates(self):
        old = {"quest": "Q001", "title": "t", "approved": True, "status": "replan", "start": "2026-10-16", "due": "2026-11-05",
               "todos": [dict(todo("T1"), state="done")], "history": []}
        p = self.adopt(request={"start": "2026-10-15", "due": "2026-10-30"}, old=old)
        self.assertEqual((p["start"], p["due"]), ("2026-10-16", "2026-11-05"))
```

`BoardContractTest.CASES` の末尾に次の2件を足す。

```python
        ({"type": "due", "todo": "T1", "scheduled": "2026-10-20", "due": "2026-10-22"}, lambda: plan(todo("T1", state="running")), {"T1": "running"}),
        ({"type": "due", "start": "2026-10-16", "due": "2026-10-30"}, lambda: plan(todo("T1")), {"T1": "pending"}),
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.DueTest tests.test_guild.AdoptDatesTest tests.test_guild.BoardContractTest -v` → FAIL

- [ ] **Step 3: 実装する**

`check_due` を次の2つに置き換える。

```python
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
```

`validate` の `try: check_due(t.get("due"))` を次に置き換える。`todos` の検査の前（`ids = ...` の前）に、依頼の日付の検査も足す。

```python
    for k in ("start", "due"):
        try:
            check_date(plan.get(k), k)
        except GuildError as e:
            errs.append(str(e))
```

```python
        for k in ("scheduled", "due"):
            try:
                check_date(t.get(k), k)
            except GuildError as e:
                errs.append(f"{i}: {e}")
```

`adopt`：`plan = {...}` を作った後、`for t in todos:` の前に、日付の決定を足す。

```python
    plan.update(quest_dates(plan_path.parent, old))
```
そして Todo を足す `item = dict(t, ...)` の後（`plan["todos"].append(item)` の前）に、次の2行。

```python
        item["scheduled"] = item.get("scheduled") or plan["start"]
        item["due"] = item.get("due") or plan["due"]
```

`adopt` の直前に、`quest_dates` を足す。

```python
def quest_dates(qdir, old=None):
    """依頼の開始日・締切。作り直し（replan）のときは旧計画の値、なければ request.json の値、なければ今日。締切が未定なら開始日。"""
    req_path = Path(qdir) / "request.json"
    req = load_json(req_path) if req_path.exists() else {}
    old = old or {}
    start = old.get("start") or req.get("start") or today()
    due = old.get("due") or req.get("due") or start
    return {"start": start, "due": due}
```

`apply_input` の `t = tm.get(data.get("todo"))` の前に、次を足し、後ろの古い `if kind == "due":` の枝を削除する。

```python
    if kind == "due":
        apply_dates(plan, data)
        return
```

```python
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
```

先頭の docstring の `due（Todo の期限の設定・解除）` を `due（依頼の開始日・締切、Todo の予定日・締切の設定。Todo の締切だけ解除できる）` に直す。

- [ ] **Step 4: 通ることを確かめる**

Run: `TEST` → PASS（既存の `DueTest` は、履歴の形 `{event, todo, due}` が同じなので通る）

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "日付を足す：依頼の開始日・締切、Todo の予定日・締切（形式の検査と、ボードからの変更）"
```

---

### Task 6: Markdown だけ（`format` の削除、テンプレートは `.md`）

**Files:**
- Modify: `skills/quest/guild.py`（`FORMATS`、`TEMPLATE_READABLE`、`validate`、`adopt`、`list_requests`）
- Test: `tests/test_guild.py`（`FormatTest` を差し替え、`TemplateTest` の更新）

**Interfaces:**
- Produces：`plan.json` に `format` がない。`template` は `templates/*.md` だけ。`guild.PROMPT_SUFFIX == ".prompt.md"`（Task 7 が使う）。

- [ ] **Step 1: テストを書き換える**

`FormatTest` クラス全体を次に差し替える。

```python
class MarkdownOnlyTest(unittest.TestCase):
    """納品物は Markdown だけ。format の項目はなく、テンプレートも .md だけ。"""

    def test_no_format_machinery(self):
        self.assertFalse(hasattr(guild, "FORMATS"))
        self.assertEqual(guild.validate(plan(todo("T1")), TR), [])

    def test_adopt_does_not_carry_format(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "Q001"
            (q / "reports").mkdir(parents=True)
            draft = {"quest": "Q001", "title": "t", "format": "pptx", "todos": [
                {"id": "T1", "title": "x", "kind": "auto", "deps": [], "deliverable": True, "criteria": CRIT}]}
            (q / "reports" / "plan-draft.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            guild.adopt(q / "plan.json", TR)
            saved = json.loads((q / "plan.json").read_text(encoding="utf-8"))
        self.assertNotIn("format", saved)
        self.assertTrue(saved["todos"][0]["deliverable"])
```

`TemplateTest` に追加（`test_adopt_rejects_unreadable_template_format` は `.docx` のまま通る。名前を `test_adopt_rejects_non_markdown_template` に変え、`.txt` も確かめる）。

```python
    def test_adopt_rejects_non_markdown_template(self):
        for ext in ("docx", "txt", "csv"):
            with self.subTest(ext=ext), tempfile.TemporaryDirectory() as d:
                q = self.make(d, f"templates/週次.{ext}")
                (Path(d) / "guild" / "templates" / f"週次.{ext}").write_bytes(b"x")
                with self.assertRaises(guild.GuildError):
                    guild.adopt(q / "plan.json", TR)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.MarkdownOnlyTest tests.test_guild.TemplateTest -v` → FAIL

- [ ] **Step 3: 実装する**

削除：`FORMATS = {"md": ".md"}`、`TEMPLATE_READABLE = (...)`、`validate` の `format` の検査（`if plan.get("format", "md") not in FORMATS:` の3行）。`adopt` の `plan = {...}` から `"format": draft.get("format", "md"),` を外す。`list_requests` の `"format": d.get("format", "md"),` を外す。`adopt` のテンプレートの形式の検査を次にする。

```python
        if not str(template).lower().endswith(".md"):
            raise GuildError(f"template は Markdown（.md）だけです: {template}")
```

定数を足す（`SATISFIED` の近く）。

```python
PROMPT_SUFFIX = ".prompt.md"  # Markdown 以外（PowerPoint・Excel など）が要るときの、Claude Code に渡すプロンプトのファイル名
```

- [ ] **Step 4: 通ることを確かめる**

Run: `TEST` → PASS

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "出力は Markdown だけ：format を廃止し、テンプレートは .md だけにする"
```

---

### Task 7: 納品物を `deliverables/` に置く（`publish`）

**Files:**
- Modify: `skills/quest/guild.py`（`DELIV`、`deliverable_files`、`publish_deliverables`、`unpublish_deliverables`、`adopt`、`main`、docstring）
- Test: `tests/test_guild.py`（`DeliverablesTest`）

**Interfaces:**
- Consumes: Task 2 `gdir_of`、Task 6 `PROMPT_SUFFIX`
- Produces：
  - `guild.publish_deliverables(qdir) -> {"published": [名前...]}`：`guild/deliverables/Q###_<元のファイル名>` へコピー（名前が衝突したら `Q###_<Todo>_<元のファイル名>`）。対象は `done` の Todo のうち、`deliverable: true` の Todo の `.md` と、どの Todo でも `*.prompt.md`。`deliverable` の印がある Todo が1つもなければ、`done` のすべての Todo の `.md`。何度実行しても同じ結果（先に自分の依頼のものを消す）。
  - `guild.unpublish_deliverables(qdir) -> [消した名前...]`。`adopt` が `replan` で作り直すときに呼ぶ。
  - CLI `guild.py publish QDIR`。

- [ ] **Step 1: 失敗するテストを書く**

```python
class DeliverablesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.g = self.root / "guild"
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def out(self, tid, name, body="x"):
        d = self.q / "output" / tid
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body, encoding="utf-8")

    def save(self, *todos):
        guild.save_plan(self.q / "plan.json", plan(*todos))

    def names(self):
        d = self.g / "deliverables"
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def test_publishes_deliverable_todo_and_any_prompt(self):
        self.out("T1", "材料.md")
        self.out("T1", "スライド.prompt.md")
        self.out("T2", "調査報告.md")
        self.out("T2", "メモ.txt")
        self.save(todo("T1", state="done"), todo("T2", state="done", deliverable=True, deps=["T1"]))
        self.assertEqual(guild.publish_deliverables(self.q)["published"], ["Q001_スライド.prompt.md", "Q001_調査報告.md"])
        self.assertEqual(self.names(), ["Q001_スライド.prompt.md", "Q001_調査報告.md"])
        self.assertEqual((self.g / "deliverables" / "Q001_調査報告.md").read_text(encoding="utf-8"), "x")

    def test_without_a_deliverable_mark_all_done_markdown_is_published(self):
        self.out("T1", "a.md")
        self.out("T2", "b.md")
        self.save(todo("T1", state="done"), todo("T2", state="skipped"))
        self.assertEqual(guild.publish_deliverables(self.q)["published"], ["Q001_a.md"])  # やめた Todo は含めない

    def test_same_file_name_in_two_todos_gets_the_todo_id(self):
        self.out("T1", "報告.md")
        self.out("T2", "報告.md")
        self.save(todo("T1", state="done"), todo("T2", state="done"))
        self.assertEqual(guild.publish_deliverables(self.q)["published"], ["Q001_報告.md", "Q001_T2_報告.md"])

    def test_publish_is_idempotent_and_does_not_touch_other_quests(self):
        (self.g / "deliverables").mkdir()
        (self.g / "deliverables" / "Q002_他の依頼.md").write_text("keep", encoding="utf-8")
        self.out("T1", "a.md")
        self.save(todo("T1", state="done"))
        guild.publish_deliverables(self.q)
        guild.publish_deliverables(self.q)
        self.assertEqual(self.names(), ["Q001_a.md", "Q002_他の依頼.md"])

    def test_unpublish_removes_only_this_quest(self):
        (self.g / "deliverables").mkdir()
        (self.g / "deliverables" / "Q0010_別.md").write_text("keep", encoding="utf-8")
        self.out("T1", "a.md")
        self.save(todo("T1", state="done"))
        guild.publish_deliverables(self.q)
        self.assertEqual(guild.unpublish_deliverables(self.q), ["Q001_a.md"])
        self.assertEqual(self.names(), ["Q0010_別.md"])

    def test_replan_adopt_unpublishes(self):
        self.out("T1", "a.md")
        old = dict(plan(todo("T1", state="done")), status="replan")
        guild.save_plan(self.q / "plan.json", old)
        guild.publish_deliverables(self.q)
        (self.q / "reports" / "plan-draft.json").write_text(json.dumps({"quest": "Q001", "title": "t", "todos": [
            {"id": "T1", "title": "x", "kind": "auto", "deps": [], "criteria": CRIT}]}), encoding="utf-8")
        guild.adopt(self.q / "plan.json", TR)
        self.assertEqual(self.names(), [])

    def test_cli_publish(self):
        self.out("T1", "a.md")
        self.save(todo("T1", state="done"))
        r = subprocess.run([sys.executable, str(ROOT / "skills" / "quest" / "guild.py"), "publish", str(self.q)],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["published"], ["Q001_a.md"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.DeliverablesTest -v` → FAIL

- [ ] **Step 3: 実装する**（`close_quests` の後に追加）

```python
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


def publish_deliverables(qdir):
    """納品物を .work/Q###/output/ から guild/deliverables/ へコピーする（Obsidian でも読めるように）。何度実行しても同じ結果。"""
    qdir = Path(qdir)
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
```

`adopt` で、`old is not None`（replan）のとき、`carried = carry_over(...)` の直前に次を足す。

```python
        unpublish_deliverables(plan_path.parent)  # 作り直し。置いた納品物は、また全 Todo が済んだ時に置き直す
```

`main` の許可リストに `"publish"` を足し、`("answers")` の群の近くに次を足す。

```python
        if cmd == "publish":
            print(json.dumps(publish_deliverables(path), ensure_ascii=False))
            return 0
```

docstring に `guild.py publish QDIR: 納品物を guild/deliverables/ へコピーする（全 Todo が済んだとき）。` を足す。

- [ ] **Step 4: 通ることを確かめる**

Run: `TEST` → PASS

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "納品物を deliverables/Q###_… に置く publish と、replan のときの取り下げ"
```

---

### Task 8: ボード — `PathMap`・フラット書庫・納品物・テンプレート・インプット（画面のパス）

**Files:**
- Modify: `skills/quest/board.html`（定数、FS 層、`loadAll`、`deliverables`/`deliverableBlock`/`partialOutputs`、`delivTab`、書庫のタブ、新しい依頼の送信、デモ）
- Test: `tests/test_guild.py`（`BoardPathsTest`：ソースの文字列確認）と、Playwright での画面確認

**Interfaces:**
- Consumes: Task 2〜7 の配置
- Produces（Task 9〜11 が使う）：
  - `physical(path)`：論理パス → 物理パス。`PathMap`（`list`/`readText`/`writeText`/`writeBlob`/`remove` を `physical()` 経由で包む）。`useHandle` と `?demo=` の両方で使う。
  - モデル：各 `quest` に `published: string[]`（`deliverables/` にある `Q###_` で始まるファイル名）。`loadAll()` の戻り値に `inputs: string[]`（`inputs/` のファイル名）。
  - 書庫の項目の `path` は `名前.md`（フォルダなし）。`ARCH_TYPES` は `[type, 見出し]` の対。

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_guild.py`）

```python
class BoardPathsTest(unittest.TestCase):
    """ボードは、論理パスを .work/ の物理パスに写して読み書きする（画面の中のパス文字列は変えない）。"""

    def setUp(self):
        self.board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")

    def test_path_map_is_defined_and_used(self):
        self.assertIn("function physical(", self.board)
        self.assertIn("class PathMap", self.board)
        self.assertIn("new PathMap(new RealFS(", self.board)
        self.assertIn("new PathMap(new MemFS(", self.board)
        for needle in (".work/archive-inbox", "'.work/$1'"):
            self.assertIn(needle, self.board)

    def test_no_format_or_unreadable_template_machinery(self):
        for gone in ("const FORMATS", "TEMPLATE_READABLE", "tplReadable", "new:format", "納品物の形式"):
            self.assertNotIn(gone, self.board)

    def test_flat_archive_and_deliverables_are_read(self):
        self.assertNotIn("archive/${dir}", self.board)
        self.assertIn("S.fs.list('deliverables')", self.board)
        self.assertIn("S.fs.list('inputs')", self.board)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest -v` → FAIL

- [ ] **Step 3: 定数と FS 層**

`const FORMATS = [...]` ブロックと、その上のコメント、`TEMPLATE_READABLE` と `tplReadable` の3〜4行を削除する。`ARCH_TYPES` を置き換える。

```js
// 書庫の種類。[type, 見出し]（フォルダは分けない。種類は項目の type で持つ）
const ARCH_TYPES = [['term', '用語'], ['flow', '業務フロー'], ['fact', '業務情報'], ['personal', '個人'], ['lesson', '心得']];
```
`ARCH_TYPES` を使う箇所（`grep -n ARCH_TYPES`）を、順に直す：`typeName` は `(…)[2]` → `[1]`、`([t, , l])` → `([t, l])`、`([type, , title])` → `([type, title])`、`ARCH_TYPES.find((x) => x[0] === e.type) || [0, 0, e.type])[2]` → `|| [0, e.type])[1]`。

`MemFS` クラスの後ろ（`const DB = {` の前）に、`PathMap` を足す。

```js
// 論理パス（画面の中で使う Q001/… requests/… web/… archive/inbox/…）を、guild/ の中の物理パスに写す。
// 機械用のファイルは guild/.work/ にある（Obsidian に出ない）。archive/ の項目、deliverables/、inputs/、templates/ はそのまま。
const PHYS = [[/^archive\/inbox(?=\/|$)/, '.work/archive-inbox'], [/^(Q\d+|requests|web)(?=\/|$)/, '.work/$1']];
function physical(p) { for (const [re, to] of PHYS) if (re.test(p)) return p.replace(re, to); return p; }
class PathMap {
  constructor(fs) { this.fs = fs; }
  list(p) { return this.fs.list(physical(p)); }
  readText(p) { return this.fs.readText(physical(p)); }
  writeText(p, t) { return this.fs.writeText(physical(p), t); }
  writeBlob(p, b) { return this.fs.writeBlob(physical(p), b); }
  remove(p, r) { return this.fs.remove(physical(p), r); }
}
```

`useHandle` の `S.fs = new RealFS(dir);` → `S.fs = new PathMap(new RealFS(dir));`。`start()` のデモ：`S.fs = new MemFS(demoTree(...))` → `S.fs = new PathMap(new MemFS(toPhysicalTree(demoTree(params.get('demo') || 'human'))));`。`window.__guildBoard.useFS` はテスト用に生の FS を受けるので、そのままにする（呼ぶ側が `PathMap` で包む）。`toPhysicalTree` を `demoTree` の後ろに足す。

```js
// 見本の木（論理パスの形）を、物理パスの形（.work/ の下）に並べ替える
function toPhysicalTree(t) {
  const out = { ...t }, w = {};
  for (const k of Object.keys(t)) if (/^(Q\d+|requests|web)$/.test(k)) { w[k] = t[k]; delete out[k]; }
  if (t.archive && t.archive.inbox) { w['archive-inbox'] = t.archive.inbox; out.archive = { ...t.archive }; delete out.archive.inbox; }
  out['.work'] = w;
  return out;
}
```

`fullPath(rel)` の `[root..., 'guild', ...rel.split('/')]` の `rel` を `physical(rel)` にする：`...physical(rel).split('/')`、`text: 'guild/' + physical(rel)`。

- [ ] **Step 4: `loadAll`**

`const top = await S.fs.list('');` と依頼の走査の先頭を、`.work` の一覧に変える。

```js
  const top = await S.fs.list('.work');
```
（`PathMap` は `.work/…` をそのまま通す。依頼のファイルの読み書きは、論理パス `${q}/…` のままでよい。）

依頼の中で、納品物の一覧を足す。`quests.push(...)` の前で一度だけ `deliv` を読む（ループの外、`quests` の宣言の直後）。

```js
  const delivFiles = (await S.fs.list('deliverables')).filter((x) => x.kind === 'file' && x.name.endsWith('.md')).map((x) => x.name).sort();
```
`quests.push({ id: q, plan, request, draft, reports, output, inbox, archive });` → `... archive, published: delivFiles.filter((n) => n.startsWith(q + '_')) });`。

書庫の読み込み（`for (const [, dir] of ARCH_TYPES) ...` の4行）を次に置き換える。

```js
  const archive = [];
  for (const f of await S.fs.list('archive')) {
    if (f.kind !== 'file' || !f.name.endsWith('.md') || f.name === 'index.md') continue;
    const e = parseEntry(f.name, await S.fs.readText(`archive/${f.name}`));
    if (e) archive.push(e);
  }
```
`requests.push({...})` から `format: r.format || 'md',` を外す。`templates` の行の下に `inputs` を足し、戻り値に入れる。

```js
  const inputs = (await S.fs.list('inputs')).filter((e) => e.kind === 'file').map((e) => e.name).sort();
  return { requests, quests, archive, archiveWait, archiveRejected, web, templates: templates.filter((n) => n.toLowerCase().endsWith('.md')), inputs, root: (cfg && cfg.root) || '' };
```
（`refresh` が戻り値のキーを列挙している箇所 — `return { root: raw.root, requests: raw.requests, ... templates: raw.templates, quests, ...}`（509 行付近）— にも `inputs: raw.inputs` を足す。）

- [ ] **Step 5: 納品物の表示**

`deliverables(qd)` を次に置き換える（納品物 = 公開済み、材料 = `output/` のもの）。

```js
// 納品物は、全 Todo が済んだ時に guild.py が guild/deliverables/ に置いたもの（Q###_…）。output/ の中のファイルは材料
function deliverables(qd) {
  const main = (qd.q.published || []).map((n) => 'deliverables/' + n);
  return { main, rest: qd.q.output };
}
```
`partialOutputs` はそのまま。`fileRow` のラベルの置換（`replace(/^Q\d+\/output\//, '')`）を `replace(/^(Q\d+\/output\/|deliverables\/)/, '')` に。`deliverableBlock` から `fmt` の行（`形式：…`）を削除し、`fmt` の変数も削除する。「納品物のファイルはありません（報告だけです）。」の文は、公開前に `finished` でない依頼向けに `『準備中です。』` を足す。

```js
    d.main.length ? h('ul', { class: 'flist' }, d.main.map((f) => fileRow(f))) : h('p', null, qd.allDone ? '納品物は準備中です（数秒で出ます）。' : '納品物のファイルはありません（報告だけです）。'),
```

`delivTab` のテンプレートの節（`h3 'テンプレート'` の行）の `tplReadable(n)` を外す：`n + (tplReadable(n) ? '' : '（今は使えません）')` → `n`。説明文の「追加は…」の末尾にある「Word・Excel…」に触れる部分があれば「Markdown（.md）だけ追加できます」に直す。

- [ ] **Step 6: 新しい依頼の送信とフォーム**

`composer`（`納品物の形式` の `select`、880〜893 行付近）：`fmt` の `select` とその `fld('納品物の形式', fmt)` を削除する。`tplSel` の `option` から `tplReadable`/`disabled` を外す。

```js
  const tplSel = h('select', { 'aria-label': '納品物のテンプレート' }, h('option', { value: '' }, 'なし'), ((S.model && S.model.templates) || []).map((n) => h('option', { value: 'templates/' + n }, n)));
```
追加の注意文（「今は読めない形式です…」の `h('span', { class: 'fine' }, ...)`）を `Markdown（.md）のテンプレートだけ追加できます。` に置き換える。ファイル選択（`fileField('newtpl', …)`）の後の検証を `sendRequest` に足す（下）。

`sendRequest` を次のとおりに直す。

```js
  const files = S.files.new || [], names = [];
  const tfile = (S.files.newtpl || [])[0];
  let template = S.form['new:template'] || null;
  const start = S.form['new:start'] || localToday();
  try {
    if (tfile) {
      if (!tfile.name.toLowerCase().endsWith('.md')) { S.newError = 'テンプレートは Markdown（.md）だけ追加できます。'; render(); return; }
      const have = (S.model && S.model.templates) || [];
      let tn = tfile.name; if (have.includes(tn)) tn = tn.replace(/(\.[^.]*)?$/, `-${stamp14(new Date())}$1`);
      await S.fs.writeBlob(`templates/${tn}`, tfile); template = `templates/${tn}`;
    }
    for (const f of files) { await S.fs.writeBlob(`requests/files/${id}/${f.name}`, f); names.push(f.name); }
    await S.fs.writeText(`requests/${id}.json`, JSON.stringify({ type: 'request', text, start, due: S.form['new:due'] || null, template, files: names, created: new Date().toISOString() }, null, 2));
  } catch (e) { ... 今のまま ... }
  S.form['new:text'] = ''; S.form['new:due'] = ''; S.form['new:start'] = ''; S.form['new:template'] = ''; S.files.new = []; S.files.newtpl = []; S.newSaved = id;
```
（`fmtKey` の行と `format: fmtKey` を削除。`if (k === 'new:format' || …` の `new:format` も削除。）`localToday` を足す。

```js
// ローカルの今日（YYYY-MM-DD）。依頼の開始日の既定
function localToday() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
```
開始日の入力欄を `composer` の期限の欄（`fld('期限', due)`）の隣に足す。

```js
  const start = h('input', { type: 'date', 'aria-label': '開始日' }); start.value = S.form['new:start'] || ''; bindKey(start, 'new:start');
  // …… fld('開始日（未指定なら登録日）', start), fld('締切（未定なら登録日）', due)
```
（`due` の入力の作り方を真似る。ラベルの「期限」→「締切（未定なら登録日）」。）

- [ ] **Step 7: デモの木を直す**

`demoTree` の戻り値で、`archive: { terms: { 'KPI.md': T(...) }, flows: {}, facts: {}, personal: { '文体.md': T(...) }, lessons: {}, inbox: {} }` を、フラットな `archive: { 'KPI.md': T(...), '文体.md': T(...), 'index.md': T('# 書庫の索引'), inbox: {} }` に直す（`inbox` は `toPhysicalTree` が `.work/archive-inbox` へ移す）。`Q001` の `output` の下の納品物の見本（`publish/digest.md` など）に合わせて、`deliverables: { 'Q002_comparison.md': T('見本') }` を足す。`p1`/`p2` の `format` があれば外す。

- [ ] **Step 8: 通ることを確かめる**

Run: `TEST` → PASS。続けて画面を確かめる（Playwright MCP）：

1. `mcp__playwright__browser_navigate` で `file:///<プロジェクトのフォルダ>/skills/quest/board.html?demo=accept` を開く。
2. `mcp__playwright__browser_evaluate`：`() => ({ a: physical('Q001/plan.json'), b: physical('archive/inbox/x.json'), c: physical('archive/KPI.md'), d: physical('requests/files/R1/a.txt'), e: physical('web/access.json'), f: physical('deliverables/Q001_a.md') })`
   Expected: `.work/Q001/plan.json`、`.work/archive-inbox/x.json`、`archive/KPI.md`、`.work/requests/files/R1/a.txt`、`.work/web/access.json`、`deliverables/Q001_a.md`（`physical` が見えないときは、`window.__guildBoard` に `physical` を足してから確かめる）
3. `browser_snapshot` で、掲示板に依頼が出ていること、「書庫」タブに `KPI`・`文体` が出ること、コンソールにエラーがないこと（`browser_console_messages`）を確かめる。

- [ ] **Step 9: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：論理パスを .work/ に写す PathMap、フラットな書庫、deliverables/ と inputs/ の読み込み、format の廃止"
```

---

### Task 9: ボード — 日付の表示と変更（依頼・Todo）

**Files:**
- Modify: `skills/quest/board.html`（`dueRow` の置き換え、`questDatesRow` の追加、`questDetail`、`todoTags`、`derive`、デモの日付）
- Test: `tests/test_guild.py`（`BoardPathsTest` に文字列の確認）と Playwright

**Interfaces:**
- Consumes: Task 5 の入力の形（`{type:'due', todo, scheduled, due}` と `{type:'due', start, due}`）
- Produces：`dateIssues(plan, t)`（Todo の日付の矛盾を文字列の配列で返す）。Task 10 は使わない（独立）。

- [ ] **Step 1: テストを足す**

```python
    def test_board_sends_the_date_inputs(self):
        for needle in ("type: 'due', todo: t.id, scheduled:", "type: 'due', start:", "function questDatesRow(", "function dateIssues("):
            self.assertIn(needle, self.board)
```

Run → FAIL

- [ ] **Step 2: 矛盾の判定を足す**（`overdue` の下）

```js
// 日付の矛盾は警告にとどめる（遷移には使わない）。YYYY-MM-DD は文字列のまま比べられる
function dateIssues(plan, t) {
  const out = [], s = t.scheduled, d = t.due;
  if (s && plan.start && s < plan.start) out.push(`予定日が依頼の開始日（${plan.start}）より前です。`);
  if (s && d && s > d) out.push('予定日が締切より後です。');
  if (d && plan.due && d > plan.due) out.push(`締切が依頼の締切（${plan.due}）より後です。`);
  for (const id of t.deps || []) { const u = plan.todos.find((x) => x.id === id); if (u && u.scheduled && s && u.scheduled > s) out.push(`前提 ${id} の予定日（${u.scheduled}）より前です。`); }
  return out;
}
```

- [ ] **Step 3: `dueRow` を置き換える**（Todo の予定日と締切を、まとめて設定する）

```js
function dueRow(qd, t) {
  const p = qd.q.plan, key = `due:${qd.id}:${t.id}`, over = overdue(t, Date.now());
  const editable = p.status === 'active' || p.status === undefined;
  const cur = (f) => (S.form[`${key}:${f}`] !== undefined ? S.form[`${key}:${f}`] : (t[f] || ''));
  const mk = (f, label) => { const i = h('input', { type: 'date', 'aria-label': `${t.id} の${label}` }); i.value = cur(f); bindKey(i, `${key}:${f}`); return i; };
  const sch = mk('scheduled', '予定日'), due = mk('due', '締切');
  const warn = h('p', { class: 'dwarn' });
  const btn = h('button', { type: 'button', class: 'btn ghost sm', onclick: async () => {
    const body = { type: 'due', todo: t.id, scheduled: sch.value || t.scheduled, due: due.value || null };
    await send(qd.id, body, key); delete S.form[`${key}:scheduled`]; delete S.form[`${key}:due`]; render(); } });
  // 入力中に描き直すと、日付の欄の入力位置が先頭に戻る。ボタンと注意文だけをその場で直す
  const sync = () => {
    const probe = { ...t, scheduled: sch.value || t.scheduled, due: due.value || null };
    btn.disabled = S.conn !== 'ok' || (probe.scheduled === t.scheduled && probe.due === (t.due || null));
    btn.textContent = '日付を設定';
    warn.textContent = dateIssues(p, probe).join(' '); warn.hidden = !warn.textContent;
  };
  for (const i of [sch, due]) i.addEventListener('change', () => { S.form[`${key}:${i === sch ? 'scheduled' : 'due'}`] = i.value; sync(); });
  sync();
  const pend = qd.q.inbox.filter((x) => x.type === 'due' && x.todo === t.id).slice(-1)[0];
  return h('div', { class: 'duerow' },
    h('span', { class: 'dl' }, '予定日'), h('span', null, t.scheduled || 'なし'), h('span', { class: 'dl' }, '締切'), h('span', null, t.due || 'なし'),
    over ? stampEl('期限切れ', 'sd-ng') : null, pend ? stampEl('反映待ち', 'sd-turn') : null,
    editable ? [sch, due, btn] : null, editable ? warn : null);
}
```
`derive` の `waitDue`/`dueWait` の2行（`const waitDue = …` と `dueWait: …`）は使わなくなるので、`todos` の `map` から外す。`loadAll` の `inbox.push({... due: j.due === undefined ? undefined : j.due })` はそのままでよい。

- [ ] **Step 4: 依頼の日付の行を足す**（`dueRow` の後ろ）

```js
function questDatesRow(qd) {
  const p = qd.q.plan, key = `qdates:${qd.id}`;
  const editable = p.status === 'active' || p.status === undefined;
  const cur = (f) => (S.form[`${key}:${f}`] !== undefined ? S.form[`${key}:${f}`] : (p[f] || ''));
  const mk = (f, label) => { const i = h('input', { type: 'date', 'aria-label': `依頼の${label}` }); i.value = cur(f); bindKey(i, `${key}:${f}`); return i; };
  const st = mk('start', '開始日'), du = mk('due', '締切');
  const btn = h('button', { type: 'button', class: 'btn ghost sm', onclick: async () => {
    await send(qd.id, { type: 'due', start: st.value || p.start, due: du.value || p.due }, key); delete S.form[`${key}:start`]; delete S.form[`${key}:due`]; render(); } });
  const sync = () => { btn.disabled = S.conn !== 'ok' || ((st.value || p.start) === p.start && (du.value || p.due) === p.due); btn.textContent = '依頼の日付を設定'; };
  for (const i of [st, du]) i.addEventListener('change', () => { S.form[`${key}:${i === st ? 'start' : 'due'}`] = i.value; sync(); });
  sync();
  return h('div', { class: 'duerow' }, h('span', { class: 'dl' }, '依頼の開始日'), h('span', null, p.start || 'なし'), h('span', { class: 'dl' }, '締切'), h('span', null, p.due || 'なし'),
    editable ? [st, du, btn] : null);
}
```
`questDetail` の `h3 '道のり'` の直後に `questDatesRow(qd),` を足す（`qd.todos.length ? [h('h3', …'道のり'), questDatesRow(qd), h('div', { class: 'way', … })…`）。

承認の手紙（`a.kind === 'approve'`）の本文に日付の案内を足す：`'下の「道のり」を確かめて、承認してください。'` の直後に `' 日付（予定日・締切）も、下で確かめて直せます。'` を足す。

- [ ] **Step 5: デモの日付**

`demoTree` の `p1`/`p2` の後ろ（`p1.todos[0].due = …` の行）に日付を足す。

```js
  const d0 = (n) => new Date(now + n * 86400000).toISOString().slice(0, 10);
  p1.start = d0(-2); p1.due = d0(5); p1.todos.forEach((t, i) => { t.scheduled = d0(i); t.due = t.due || d0(i + 1); });
  p2.start = d0(-10); p2.due = d0(-3); p2.todos.forEach((t, i) => { t.scheduled = d0(-9 + i * 2); t.due = d0(-8 + i * 2); });
```
（`p1.todos[0].due = '2026-10-01'; p1.todos[1].due = '2026-12-31'` の既存の行はこの行より前に置く。）`p1.todos[1].kind` は `human`。

- [ ] **Step 6: 通ることを確かめる**

Run: `TEST` → PASS。Playwright：`?demo=human` を開き、`browser_snapshot` で次を確かめる。
- Q001 を開くと「依頼の開始日」「締切」と各 Todo の「予定日」「締切」が出て、日付の入力欄がある。
- 予定日を依頼の開始日より前にすると、赤い注意文が出る（`browser_evaluate` で `document.querySelector('.dwarn')` が `hidden` でないこと）。
- 「日付を設定」を押すと、`Q001/inbox/…-due-T1.json` に `{"type":"due","todo":"T1","scheduled":…}` が書かれる（デモの FS は `window.__guildBoard.S.fs.fs.list('.work/Q001/inbox')` で確かめる）。

- [ ] **Step 7: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：依頼の開始日・締切と Todo の予定日・締切を表示・変更でき、矛盾は警告にする"
```

---

### Task 10: ボード — 新タブ「クエスト進捗」（ガント＋`human` の日別件数）

**Files:**
- Modify: `skills/quest/board.html`（CSS、`scheduleModel`・`progressTab`・`ganttSvg`・`humanBars` の追加、`render` のタブ）
- Test: `tests/test_guild.py`（文字列の確認）と Playwright（計算の確認）

**Interfaces:**
- Consumes: Task 5 の日付、Task 8 のモデル（`S.model.quests[].q.plan`）、`closed(state)`、`TSTATE`
- Produces：`scheduleModel(quests, includeClosed) -> { rows, min, max, humanDays }`（`rows[i] = { id, title, start, due, state: 'active'|'done'|'aborted', done, total, todos:[{id,title,kind,state,scheduled,due}] }`、`min`/`max` は日番号、`humanDays` は `[{ day, open, done }]`）。

- [ ] **Step 1: テストを足す**

```python
    def test_progress_tab_exists(self):
        for needle in ("['prog', 'クエスト進捗']", "function scheduleModel(", "function progressTab(", "function ganttSvg(", "function humanBars("):
            self.assertIn(needle, self.board)
        self.assertNotIn("<script src", self.board)  # 外部ライブラリを使わない
```

Run → FAIL

- [ ] **Step 2: モデルを書く**（`derive` の後ろ、`// ====== 描画（画面）` の前）

```js
// ============================================================ クエスト進捗（ガント）
const DAY_MS = 86400000;
const dayNum = (s) => Math.floor(Date.parse(s + 'T00:00:00Z') / DAY_MS);
const dayStr = (n) => new Date(n * DAY_MS).toISOString().slice(0, 10);

// 予定のモデル。計画のない依頼は載せない。includeClosed が false なら、完了・中止の依頼を除く
function scheduleModel(quests, includeClosed) {
  const rows = [];
  for (const q of quests) {
    const p = q.q.plan; if (!p || !p.start) continue;
    const state = p.status === 'aborted' ? 'aborted' : (p.accepted ? 'done' : 'active');
    if (!includeClosed && state !== 'active') continue;
    const todos = p.todos.map((t) => ({ id: t.id, title: t.title, kind: t.kind, state: t.state, scheduled: t.scheduled || p.start, due: t.due || null }));
    rows.push({ id: q.id, title: q.title, start: p.start, due: p.due || p.start, state, done: todos.filter((t) => closed(t.state)).length, total: todos.length, todos });
  }
  rows.sort((a, b) => a.id.localeCompare(b.id));
  const days = rows.flatMap((r) => [r.start, r.due, ...r.todos.map((t) => t.scheduled)]).map(dayNum);
  const today = Math.floor(Date.now() / DAY_MS);
  let min = days.length ? Math.min(...days, today) : today, max = days.length ? Math.max(...days, today) : today;
  min -= 1; max += 1; if (max - min < 7) max = min + 7;
  const byDay = new Map();
  for (const r of rows) for (const t of r.todos) if (t.kind === 'human') {
    const k = dayNum(t.scheduled), e = byDay.get(k) || { day: k, open: 0, done: 0 };
    if (closed(t.state)) e.done++; else e.open++;
    byDay.set(k, e);
  }
  return { rows, min, max, humanDays: [...byDay.values()].sort((a, b) => a.day - b.day) };
}
```

- [ ] **Step 3: 描画を書く**

色は既存の CSS 変数（`--ok --ng --warn --mute --stop --sub --brass`）を使う。進捗は、Todo の印の色、依頼バーの塗り（完了した Todo の割合）で表す。

```js
const SVGNS = 'http://www.w3.org/2000/svg';
const sv = (tag, attrs, ...kids) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v); for (const c of kids.flat()) if (c != null) e.append(c.nodeType ? c : document.createTextNode(c)); return e; };
// Todo の状態の色（印と同じ系統）
const STATE_FILL = { pending: 'var(--mute)', blocked: 'var(--stop)', awaiting_confirm: 'var(--warn)', running: 'var(--brass)', waiting_user: 'var(--warn)', review: 'var(--brass)', done: 'var(--ok)', failed: 'var(--ng)', skipped: 'var(--stop)' };

function ganttSvg(m) {
  const LABEL = 210, PAD = 16, ROW = 26, HEAD = 34, W = 1000, n = m.max - m.min + 1, DW = (W - LABEL - PAD) / n;
  const x = (day) => LABEL + (day - m.min) * DW + DW / 2;
  const rows = m.rows.flatMap((r) => [{ q: r }, ...r.todos.map((t) => ({ q: r, t }))]);
  const H = HEAD + rows.length * ROW + 10, today = Math.floor(Date.now() / DAY_MS);
  const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', role: 'img', 'aria-label': '依頼と Todo の予定', class: 'gantt' });
  for (let d = m.min; d <= m.max; d++) {
    const major = n <= 31 || new Date(d * DAY_MS).getUTCDate() === 1 || (d - m.min) % 7 === 0;
    svg.append(sv('line', { x1: x(d), x2: x(d), y1: HEAD - 6, y2: H, stroke: 'var(--line)', 'stroke-width': major ? 1 : 0.4, opacity: major ? 0.7 : 0.4 }));
    if (major && (n <= 31 || (d - m.min) % 7 === 0)) svg.append(sv('text', { x: x(d), y: 16, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--sub)' }, dayStr(d).slice(5)));
  }
  if (today >= m.min && today <= m.max) svg.append(sv('line', { x1: x(today), x2: x(today), y1: HEAD - 6, y2: H, stroke: 'var(--ng)', 'stroke-width': 1.5, 'stroke-dasharray': '4 3' }), sv('text', { x: x(today), y: 30, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--ng)' }, '今日'));
  rows.forEach((row, i) => {
    const y = HEAD + i * ROW, cy = y + ROW / 2, r = row.q;
    if (!row.t) {
      const x1 = x(dayNum(r.start)) - DW / 2, x2 = x(dayNum(r.due)) + DW / 2, w = Math.max(x2 - x1, 6), pct = r.total ? r.done / r.total : 0;
      svg.append(sv('text', { x: 4, y: cy + 4, 'font-size': 12, 'font-weight': 700, fill: 'var(--ink)' }, `${r.id} ${r.title.length > 14 ? r.title.slice(0, 14) + '…' : r.title}`),
        sv('rect', { x: x1, y: cy - 7, width: w, height: 14, rx: 3, fill: 'var(--surface2)', stroke: r.state === 'aborted' ? 'var(--stop)' : 'var(--brass)' }),
        sv('rect', { x: x1, y: cy - 7, width: w * pct, height: 14, rx: 3, fill: r.state === 'aborted' ? 'var(--stop)' : 'var(--ok)', opacity: 0.8 }),
        sv('text', { x: x1 + w + 6, y: cy + 4, 'font-size': 11, fill: 'var(--sub)' }, `${r.done}/${r.total}${r.state === 'aborted' ? '（中止）' : r.state === 'done' ? '（完了）' : ''}`));
    } else {
      const t = row.t, cx = x(dayNum(t.scheduled)), s = 7, fill = STATE_FILL[t.state] || 'var(--mute)', late = t.due && t.state !== 'done' && t.state !== 'skipped' && t.due < dayStr(today);
      svg.append(sv('text', { x: 18, y: cy + 4, 'font-size': 11, fill: 'var(--sub)' }, `${t.id} ${t.kind === 'human' ? '👤 ' : ''}${t.title.length > 12 ? t.title.slice(0, 12) + '…' : t.title}`),
        sv('path', { d: `M${cx} ${cy - s} L${cx + s} ${cy} L${cx} ${cy + s} L${cx - s} ${cy} Z`, fill, stroke: late ? 'var(--ng)' : 'var(--ink)', 'stroke-width': late ? 2 : 0.6 },
          sv('title', null, `${t.id} ${t.title}\n予定日 ${t.scheduled}${t.due ? '　締切 ' + t.due : ''}\n${(TSTATE[t.state] || [t.state])[0]}`)));
    }
  });
  return svg;
}

function humanBars(m) {
  if (!m.humanDays.length) return h('p', { class: 'sub' }, 'あなたの実行（human）の Todo はありません。');
  const peak = Math.max(...m.humanDays.map((d) => d.open + d.done)), BW = 46, BH = 120, W = Math.max(m.humanDays.length * BW + 40, 300);
  const svg = sv('svg', { viewBox: `0 0 ${W} ${BH + 44}`, width: Math.min(W, 1000), role: 'img', 'aria-label': '予定日ごとのあなたの実行の件数', class: 'gantt' });
  m.humanDays.forEach((d, i) => {
    const x0 = 20 + i * BW, ho = (d.open / peak) * BH, hd = (d.done / peak) * BH;
    svg.append(sv('rect', { x: x0, y: 8 + BH - ho - hd, width: BW - 14, height: hd, fill: 'var(--ok)', opacity: 0.55 }),
      sv('rect', { x: x0, y: 8 + BH - ho, width: BW - 14, height: ho, fill: 'var(--warn)' }),
      sv('text', { x: x0 + (BW - 14) / 2, y: 8 + BH - ho - hd - 3, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--ink)' }, d.open + d.done),
      sv('text', { x: x0 + (BW - 14) / 2, y: BH + 24, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--sub)' }, dayStr(d.day).slice(5)));
  });
  return svg;
}

function progressTab() {
  const m0 = S.model; if (!m0) return h('p', { class: 'sub' }, '保存先につなぐと、ここに表示されます。');
  const inc = !!S.form['prog:closed'];
  const m = scheduleModel(m0.quests, inc);
  const chk = h('input', { type: 'checkbox', id: 'prog:closed' }); chk.checked = inc; chk.addEventListener('change', () => { S.form['prog:closed'] = chk.checked; render(); });
  const legend = h('div', { class: 'legend', style: 'margin:6px 0 12px' }, ['pending', 'running', 'waiting_user', 'review', 'done', 'failed', 'skipped'].map((s) => h('span', { class: 'lg' }, h('i', { style: `display:inline-block;width:10px;height:10px;transform:rotate(45deg);margin:0 6px 0 4px;background:${STATE_FILL[s]}` }), TSTATE[s][0])));
  return [h('h2', { class: 'h2' }, 'クエスト進捗'),
    h('p', { class: 'sub', style: 'margin:0 0 8px' }, '依頼は開始日から締切までの帯です（緑の塗りが、合格した Todo の割合）。◆ は Todo の予定日で、色が状態です。赤い点線は今日です。'),
    h('label', { class: 'fine', for: 'prog:closed' }, chk, ' 完了・中止した依頼も含める'), legend,
    m.rows.length ? h('div', { class: 'ganttbox' }, ganttSvg(m)) : h('p', { class: 'sub' }, '進行中の依頼はありません。'),
    h('h3', { class: 'sec' }, 'あなたの実行（human）の予定日ごとの件数'),
    h('p', { class: 'fine', style: 'margin:0 0 6px' }, 'オレンジが未了、緑が済んだ件数です。'), humanBars(m)];
}
```
CSS を `<style>` の末尾に足す。

```css
.ganttbox{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--paper2);padding:6px}
svg.gantt{display:block;min-width:720px}
.legend .lg{margin-right:12px;font-size:13px;white-space:nowrap}
```

- [ ] **Step 4: タブに足す**（`render` の `tabs` と `body`）

```js
  const tabs = [['board', '掲示板'], ['prog', 'クエスト進捗'], ['deliv', '納品物'], ['know', '書庫'], ['talk', '冒険の書'], ['web', …], ['obs', 'Obsidian'], ['help', 'ヘルプ']];
  const body = { board: boardTab, prog: progressTab, deliv: delivTab, know: knowTab, talk: talkTab, web: webTab, obs: obsidianTab, help: helpTab }[S.tab]();
```
（`['web', …]` は今の式のまま。）`window.__guildBoard` に `scheduleModel` を足す（確認用）。ヘルプ・README のタブ数（7→8）は Task 12 で直す。

- [ ] **Step 5: 通ることを確かめる**

Run: `TEST` → PASS。Playwright：
1. `?demo=human` を開く。`browser_evaluate`：
   `() => { const m = window.__guildBoard.scheduleModel(window.__guildBoard.S.model.quests, false); return { rows: m.rows.map(r => [r.id, r.state, r.done + '/' + r.total, r.todos.length]), human: m.humanDays }; }`
   Expected: Q001 のみ（Q002 は完了なので除外）、`human` に Q001 の T2 の予定日が1件（`open: 1`）。`scheduleModel(…, true)` では Q002 も入る。
2. 「クエスト進捗」タブを押し、`browser_take_screenshot` で、依頼のバー、◆（状態の色）、今日の赤い点線、`human` の棒が出ることを目で確かめる。「完了・中止した依頼も含める」にチェックすると Q002 が増える。
3. `?demo=failed` と `?demo=plan` でもエラーなく描かれる（`browser_console_messages` にエラーなし）。

- [ ] **Step 6: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：新タブ「クエスト進捗」（HTML/SVG のガントと、human の予定日ごとの件数）"
```

---

### Task 11: ボード — プロンプトの表示、`publish` 後の納品物、案内文

**Files:**
- Modify: `skills/quest/board.html`（`deliverableBlock`、受け取りの手紙、`openFile` のコピー、Obsidian の案内、ヘルプ、書庫のタブの注記）
- Test: `tests/test_guild.py`（文字列の確認）と Playwright

**Interfaces:**
- Consumes: Task 8 の `published`、Task 6 の `*.prompt.md` の規約
- Produces：`isPrompt(name)`、`promptRow(path)`（開く／パスをコピー／**プロンプトをコピー**）

- [ ] **Step 1: テストを足す**

```python
    def test_prompt_files_are_shown_with_a_copy_button(self):
        for needle in ("function isPrompt(", "function promptRow(", "プロンプトをコピー", ".prompt.md"):
            self.assertIn(needle, self.board)
```

Run → FAIL

- [ ] **Step 2: 実装する**

`deliverableBlock` の前に足す。

```js
// Markdown 以外（PowerPoint・Excel など）が要るときの、Claude Code に渡すプロンプト。ファイル名が *.prompt.md
const isPrompt = (name) => /\.prompt\.md$/i.test(String(name));
function promptRow(f) {
  return h('li', null, h('a', { href: '#', onclick: (e) => { e.preventDefault(); openFile(f); } }, f.replace(/^deliverables\//, '')),
    h('span', { class: 'acts' },
      h('button', { type: 'button', class: 'btn ghost sm', onclick: () => openFile(f) }, '開く'),
      h('button', { type: 'button', class: 'btn ghost sm', onclick: async () => { const t = await S.fs.readText(f); if (t == null) { S.toast = '読めませんでした'; render(); return; } copyText(t.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, ''), 'プロンプト'); } }, 'プロンプトをコピー'),
      h('button', { type: 'button', class: 'btn ghost sm', onclick: () => copyPath(f) }, 'パスをコピー')));
}
```
（`copyText(text, label)` は既存。第2引数は `copyPath` が渡している説明文なので、そのまま使える。）

`deliverableBlock` を、納品物とプロンプトに分けて出す形にする。

```js
function deliverableBlock(qd) {
  const d = deliverables(qd), docs = d.main.filter((f) => !isPrompt(f)), prompts = d.main.filter(isPrompt);
  return [
    docs.length ? h('ul', { class: 'flist' }, docs.map((f) => fileRow(f))) : (prompts.length ? null : h('p', null, qd.allDone ? '納品物は準備中です（数秒で出ます）。' : '納品物のファイルはありません（報告だけです）。')),
    prompts.length ? [h('p', { class: 'fine', style: 'margin:8px 0 4px' }, 'PowerPoint・Excel など Markdown 以外が要る部分は、Claude Code に渡すプロンプトにしてあります。「プロンプトをコピー」で貼り付けて、Claude Code に作らせてください。'),
      h('ul', { class: 'flist' }, prompts.map(promptRow))] : null,
    h('p', { class: 'fine', style: 'margin:0 0 8px' }, '納品物は ', code('guild/deliverables/'), ' にもあります（Obsidian で読めます）。「パスをコピー」は、フルパスでコピーします。'),
    d.rest.length ? keepOpen('rest:' + qd.id, h('summary', null, `途中の資料（材料）を見る（${d.rest.length}件）`), h('ul', { class: 'flist' }, d.rest.map((f) => fileRow(f)))) : null];
}
```

Obsidian の案内（`obsidianTab`）：
- 「ディレクトリ構成」の `pre([...])` を新しい構成に差し替える。

```js
pre(['guild/', '  board.html  config.json', '  archive/            書庫（用語名.md。種類は項目の type）', '    index.md          索引（役が最初に読む）',
  '  deliverables/       納品物と、Claude Code に渡すプロンプト（Q001_… .md / .prompt.md）', '  inputs/             共通のインプット（1つだけ。各依頼はファイル名で参照）', '  templates/          納品物のテンプレート（.md）',
  '  .work/              作業用（Obsidian に出ない）：依頼ごとの Q001/（plan.json・報告・途中の資料）、受付待ち、外部サイトの許可、バックアップ'].join('\n'))
```
- 「納品物を見る」の `dl` の「場所」の説明（`code('Q###/output/<Todo>/')`…）を `code('deliverables/Q###_…')` に直し、「全 Todo が済んで受け取りの確認の手紙が出た時に置かれます」を足す。
- 「除外ファイル」の案内（`inbox/ reports/ requests/` を除外に足す手順の `li`）は、`.work/` が Obsidian に出ないので、行ごと削除する。
- 「書庫だけ読みたいときは、`guild/archive/` を保管庫にします。」はそのまま。

書庫のタブの注記と、ヘルプ（`helpTab`）：
- ヘルプの「処理フロー」や「納品物」の説明にある `Q###/output/` を `deliverables/` に（受け取りの手紙）、「7つのタブ」の言い回しがあれば「8つ」に、「クエスト進捗」の説明を1項目足す（`faq('予定や進み具合を見たい', '「クエスト進捗」のタブに、依頼ごとの帯と Todo の予定日（◆）、あなたの実行の日ごとの件数が出ます。日付は掲示板の依頼の「道のり」で直せます。')`）。
- `faq('依頼を取り消したい', …, code('guild/requests'), …)`（1341 行付近）を `code('guild/.work/requests')` に。

- [ ] **Step 3: 通ることを確かめる**

Run: `TEST` → PASS。Playwright：
1. `demoTree` の `deliverables` に `'Q001_report.md': T('見本'), 'Q001_スライド.prompt.md': T('---\ntype: prompt\n---\n# PowerPoint 5枚を作って…')` を足し、`Q001` の `published` に出るようにする（`?demo=accept`）。
2. 「受け取りの確認」の手紙に、納品物（`report.md`）と「プロンプトをコピー」つきのプロンプトの行が分かれて出る。「プロンプトをコピー」を押してトーストが出る（`browser_snapshot`）。
3. 「Obsidian」タブに新しい構成が出る。

- [ ] **Step 4: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：納品物とプロンプト（*.prompt.md）を分けて表示し、コピーできる。案内文を新しい構成に直す"
```

---

### Task 12: 指示書・ドキュメントの更新と、通しの確認

**Files:**
- Modify: `skills/quest/SKILL.md`、`agents/cartographer.md`、`agents/adventurer.md`、`agents/appraiser.md`、`agents/librarian.md`、`agents/scout.md`（パスの記述）、`README.md`、`docs/graph-format.md`、`docs/spec.md`、`docs/board-design.md`、`docs/archive-spec.md`、`docs/roles-spec.md`
- Test: `tests/test_guild.py`（`DocsContractTest`）

**Interfaces:** なし（文書）

- [ ] **Step 1: 文書の契約テストを書く**

```python
class DocsContractTest(unittest.TestCase):
    def read(self, *p):
        return (ROOT.joinpath(*p)).read_text(encoding="utf-8")

    def test_quest_skill_runs_close_and_publish(self):
        s = self.read("skills", "quest", "SKILL.md")
        for needle in ("guild.py\" publish", "close <root>", ".prompt.md", ".work/"):
            self.assertIn(needle, s)

    def test_cartographer_decides_dates_and_prompts(self):
        s = self.read("agents", "cartographer.md")
        for needle in ("scheduled", "\"due\"", ".prompt.md"):
            self.assertIn(needle, s)
        self.assertNotIn("\"format\"", s)

    def test_adventurer_may_add_prompts_without_approval(self):
        s = self.read("agents", "adventurer.md")
        self.assertIn(".prompt.md", s)
        self.assertIn("承認", s)

    def test_graph_format_documents_dates(self):
        s = self.read("docs", "graph-format.md")
        for needle in ("scheduled", "\"start\"", "publish", "close"):
            self.assertIn(needle, s)

    def test_readme_matches_the_new_layout(self):
        s = self.read("README.md")
        for needle in ("deliverables/", "inputs/", ".work/", "クエスト進捗", "Playwright MCP"):
            self.assertIn(needle, s)
        self.assertNotIn(".mcp.json", s)
```

Run: `python -m unittest tests.test_guild.DocsContractTest -v` → FAIL

- [ ] **Step 2: `skills/quest/SKILL.md` を直す**

- 手順1（受付）：「素材は `files`（取り込むと `<dir>/inputs/` に移る）」→「素材は `files`。取り込むと共通の `guild/inputs/` に1つだけ置かれ（同名で内容が違えば上書き）、依頼の `request.json` の `inputs` にファイル名が入る。地図師・冒険者には `guild/inputs/<ファイル名>` で渡す」。依頼の日付：「開始日は `start`、締切は `due`（未指定は、開始日が登録日、締切が開始日）」。
- 手順2（分解）の地図師へのメッセージに「依頼の開始日・締切（`request.json` の `start`・`due`）」を足す。
- 手順4 の `awaiting_accept` の行（表の `confirm / waiting_user / …` の行の説明）の後に、次の段落を足す。

```markdown
   **納品物を置く**：`next` の出力で `awaiting_accept` が `true` になった依頼は、`guild.py publish <dir>` を実行する（何度実行しても同じ。納品物と `*.prompt.md` が `guild/deliverables/Q###_…` に置かれ、ボードの「受け取りの確認」の手紙と Obsidian の両方で読める）。「直してほしい」（`replan`）になると、`adopt` が置いたものを取り下げるので、また全 Todo が済んだ時に実行する。
```
- 手順4 の「何も進められないとき」の `web-reset` の行を、`guild.py web-reset <root>` と `guild.py close <root>`（インプットのバックアップを消す）の両方を実行する形に直す。
- 手順5（納品）：「成果物の置き場は、実行中はいつも `output/<id>/`」の後に「受け取りの確認の手紙が出るとき、納品物は `guild/deliverables/` にも置かれる（手順4）。依頼にファイルの置き場の指定があれば、そこへコピーする」。
- すべての `guild/Q###/` の記述はそのままでよい（実体は `guild/.work/Q###/` だが、`guild.py` が返す `dir` を使う）。冒頭の「依頼のフォルダ」の説明に「依頼のフォルダは `guild/.work/Q###/`（`guild.py new` の `dir`）」を1行足す。
- 「守ること」に「出力は Markdown だけ。PowerPoint・Excel などが要るときは、Claude Code に渡すプロンプトを `*.prompt.md` で出す（冒険者が実行中に足してもよい。Todo は増やさず、承認は取らない）」を足す。

- [ ] **Step 3: 役の指示書を直す**

`agents/cartographer.md`：
- 「納品物のテンプレート」の説明から「ボードは、今読める形式（`.md` `.markdown` `.txt` `.csv`）のものだけを渡す」を「テンプレートは Markdown（`.md`）だけ」に。「納品物の形式（依頼の `format`…）」の項目を削除し、「出力は Markdown だけ。依頼文に PowerPoint・Excel などの指定があれば、その形式のファイルを作る Todo は置かず、**Claude Code に渡すプロンプトを `*.prompt.md` で書く Todo** を計画に入れる（`criteria` に「依頼主がそのまま Claude Code に貼れる」を入れる）」と書く。
- 依頼の入力に「依頼の開始日・締切（`start`・`due`）」を足し、`plan-draft.json` の説明に次を足す。

```markdown
- 各 Todo に `scheduled`（実行予定日 `YYYY-MM-DD`）と `due`（締切）を書く。依存関係から決める：前提の Todo の予定日以降にする。`human` の Todo は依頼主の作業量が偏らないよう、日をならす。依頼の締切が開始日と同じ（未定）なら、すべて同じ日でよい。依頼の `start`・`due` は書かない（依頼主が決める）。
```
- JSON の例から `"format": "md",` を削除し、各 Todo の例に `"scheduled": "2026-10-16", "due": "2026-10-18"` を足す。
- 書庫のパスの説明 `"archive_used": ["terms/WVS2.md"]` → `["WVS2.md"]`。「`index.md` を見て…のファイルだけ読む。`lessons/` は読まない」→「…のファイルだけ読む。`type: lesson`（心得）の項目は読まない」。

`agents/adventurer.md`：成果物は Markdown だけ。「PowerPoint・Excel などが要ると実行中に気づいたら、自分の Todo の成果物として `*.prompt.md`（Claude Code に渡すプロンプト）を `output/<id>/` に足してよい。Todo は増やさない。計画の承認は取らない。報告の『結果』に、足した理由を書く」。書庫の説明も、種類別フォルダ → `type` に直す。

`agents/appraiser.md`・`agents/librarian.md`・`agents/scout.md`：書庫のパス（`terms/WVS2` → `WVS2`、`lessons/` → `type: lesson`）の記述を、`grep -n "terms/\|lessons/\|facts/\|flows/\|personal/" agents/*.md` で洗い出して直す。`appraiser.md` には「報告の『結果』に `*.prompt.md` を足した理由があるか」を確認項目に足す。

- [ ] **Step 4: `README.md` と `docs/` を直す**

`README.md`：
- 特長に1行：`- **見える化**: ボードの「クエスト進捗」に、依頼の開始日〜締切の帯と、Todo の予定日（◆）、あなたの実行（human）の日ごとの件数が出ます。`
- 必要なもの（Task 1 で直した）はそのまま。
- 使い方の1：「`guild/`、`guild/archive/`、`guild/requests/`、…ができます」→「`guild/`（`archive/`、`inputs/`、`deliverables/`、`.work/`、`config.json`、`board.html`）ができます」。4：「納品物（Markdown）が `guild/Q###/output/` に残ります」→「納品物（Markdown）が `guild/deliverables/Q###_….md` に残ります。PowerPoint・Excel などが要るときは、Claude Code に渡すプロンプト（`*.prompt.md`）が一緒に出ます」。
- ボードのタブ：「7つ」→「8つ」、「掲示板／クエスト進捗／納品物／書庫／冒険の書／外部サイト／Obsidian／ヘルプ」、「クエスト進捗」の説明の行を足す。
- 「データの置き場」のツリーを次に差し替える。

```
guild/
  config.json     Python のパスなどの設定
  board.html      ボード
  archive/        書庫（用語名.md と index.md。種類は項目の type）
  deliverables/   納品物と、Claude Code に渡すプロンプト（Q001_….md / .prompt.md）
  inputs/         共通のインプット（1つだけ。各依頼はファイル名で参照）
  templates/      納品物のテンプレート（.md）
  .work/          作業用（Obsidian に出ない）
    Q001/         依頼ごとのフォルダ（plan.json、reports/、output/、inbox/）
    requests/ web/ archive-inbox/ backup/
```
- 「書庫と納品物は Obsidian の記法で…」の文：`guild/` を Vault にすると書庫・納品物・インプットが読める、`.work/` は出ない、と直す。
- 「承認は計画の1回だけ」の項に「Markdown 以外が要るときのプロンプトの追加は、計画を変えないので承認を取りません」を足す。

`docs/graph-format.md`：`plan.json` の例に `"start"`・`"due"`（最上位）と各 Todo の `"scheduled"`・`"due"` を足し、`format` の記述（`format` は納品物の形式…）を削除する。`due` の項を「Todo の締切（任意）」として残し、`scheduled`（実行予定日）、依頼の `start`・`due`、`adopt` の既定（未指定の `start` は今日、`due` は `start`、Todo の `scheduled` は `start`、Todo の `due` は依頼の `due`）、矛盾は警告のみ、を書く。入力ファイルの種類の `due` の説明を Task 5 の形（Todo の `scheduled`/`due`、依頼の `start`/`due`）に書き換える。`guild.py` のコマンドの表に `publish` と `close` を足し、`init`/`new` の説明のパス（`guild/.work/`）を直す。

`docs/spec.md`・`docs/board-design.md`・`docs/archive-spec.md`・`docs/roles-spec.md`：`grep -n "Q###/\|guild/requests\|guild/web\|archive/terms\|terms/\|\.mcp\.json\|plugin_guild_browser\|7つ\|format" docs/*.md` で洗い出し、パス・タブ数・MCP の記述を新しい構成に直す（過去の決定ログ `docs/2026-*` の中は歴史なので直さない）。`docs/archive-spec.md` の「構成」は、フラット（種類は `type`）に直し、「種類の付け替え」は「`type` を書き換える」に直す。

- [ ] **Step 5: 通しで確認する**

1. Run: `TEST` → すべて PASS（`DocsContractTest` を含む）。
2. 実際のフォルダでの通し（一時フォルダ。リポジトリの外）：

```bash
python skills/quest/guild.py init "$TMPDIR/p"   # guild/.work/requests、archive/index.md ができる
ls -A "$TMPDIR/p/guild"
```
   Expected: `.work archive board.html config.json`（`requests`・`web`・`Q001` が `guild/` 直下にないこと）。
3. 実ブラウザでの確認（Playwright MCP では `showDirectoryPicker` が使えないため、**ユーザーが手元で実施する**）：Chrome で上の `guild/board.html` を開き、「フォルダを選ぶ」で `$TMPDIR/p` を選ぶ。依頼を出し（開始日・締切つき）、`.work/requests/` に `R….json` が書かれること、`.work` を含むフォルダをボードが読めることを確かめる。**ここで `.work`（先頭が `.` の名前）をボードが読めない場合は、フォルダ名を `_work` に変えて Task 2〜8 の `WORK` と `PHYS` の2か所だけを直す**（Obsidian に出る代わりに、動く）。
4. 一時フォルダを消す前に、中身を確認してから削除する。

- [ ] **Step 6: コミット**

```bash
git add skills agents README.md docs tests
git commit -m "指示書とドキュメントを新しい構成に合わせる（close/publish、日付、プロンプト、フラットな書庫）"
```

---

## Self-Review

**1. Spec coverage**

| SPEC | Task |
|---|---|
| 要望1：`.mcp.json` 削除、`playwright` 前提の `tools`、init だけで確認・止める、README | 1 |
| 要望1：導入後の切れは失敗の経路（新ロジックなし） | 1（何も足さない。SPEC の方針どおり） |
| 要望2：日付の項目、地図師が決める、承認画面で確認、ボードで変更、連動なし | 5（データ）、9（画面）、12（`cartographer.md`） |
| 要望2：形式だけエラー、矛盾は警告 | 5・9（`dateIssues`） |
| 要望2：新タブ（ガント、human の件数、進捗の色と塗り、既定は進行中のみ） | 10 |
| 要望2：`graph-format.md` の更新 | 12 |
| 要望3：`format` 削除、テンプレート `.md` だけ | 6、8 |
| 要望3：`*.prompt.md`、3つの判断、承認なし、手紙に表示 | 6（規約）、11（表示）、12（指示書） |
| 要望4：構成（`.work/`、`archive/` フラット、`deliverables/`、`inputs/`、`templates/`） | 2、3、4、7、8 |
| 要望4：納品物を全 Todo 済みで置く、`replan` で取り下げ | 7、12（ギルドマスターが `publish`） |
| 要望4：インプット（同名・内容同一・上書き・バックアップ・閉じたら削除） | 4 |
| 受入条件8（テスト・README・docs・指示書・フック） | 12（フックは `web_gate.py` が `webaccess.access_path` 経由で `.work/web/` を読むため、コード変更なし。`WebGateHookTest` で確認される） |

**2. Placeholder scan**：手順は具体のコード・コマンド・期待値で書いた。「行番号付近」とした箇所は、既存コードを読んで確かめた位置の目安で、置換前後の文字列を明示している。Task 8・11 の画面の細部（文言の差し替え）は、置換前後の文字列を示した上で、Playwright の確認を付けた。

**3. 型・名前の整合**：`work_dir`/`gdir_of`/`WORK`（Task 2）→ Task 4・7 が使用。`ARCHIVE_TYPES`/`INDEX_NAME`（Task 3）。`import_inputs`/`close_quests`（Task 4）。`check_date`/`quest_dates`/`apply_dates`（Task 5）。`PROMPT_SUFFIX`（Task 6）→ Task 7。`publish_deliverables`/`unpublish_deliverables`（Task 7）→ Task 12 の `SKILL.md`。ボード側 `physical`/`PathMap`/`published`/`dateIssues`/`scheduleModel`/`isPrompt` はそれぞれ定義した Task で使う。

**4. Review Focus**：冒頭の6行は、それぞれ Task 3（`index`）、4（不正なファイル名・2回の上書き・`close`）、5（日付の既定・`replan`）、7（`replan` の取り下げ）のテストが持つ。

**5. リスク（SPEC より）と対処**：`.work` をボードが読めるか → Task 12 Step 5-3 で実ブラウザ確認、だめなら `WORK`/`PHYS` の2か所を `_work` に。`init` の MCP 判定 → Task 1 は `ToolSearch` でツールの有無を見る方式（`claude mcp list` は使わない）。書庫のフラット化の波及 → Task 3 の規則表で既存テストを機械的に直す。

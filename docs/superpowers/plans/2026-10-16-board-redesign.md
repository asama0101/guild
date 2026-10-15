# ボード作り直し Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 掲示板を「クエスト掲示板」（左に一覧・右に詳細パネル）に作り直し、クエスト進捗をクエストで絞れるようにし、冒険の書と納品物のテンプレートを廃止し、インプットを「既存から選ぶ」「地図師の自動選択（書庫のヒントつき）」「あとから追加・外す」で扱えるようにする。

**Architecture:** 実行エンジン `skills/quest/guild.py` が、インプットの一覧とヒント（`inputs-list`）、依頼の `inputs` の検査（`new`）、計画の `inputs`・`candidates`（`adopt`）、新しい入力 `inputs`（`ingest`）、書庫の項目の `inputs`（見出し情報）を受け持つ（Task 1〜5）。地図師はヒントつきの一覧と依頼文から理由つきで選び、`adopt` が `guild/inputs/` にあるかを検査する。ボード（`board.html`、1ファイル）は、これらの JSON の形を読んで書くだけで、`plan.json` は書かない（Task 6〜12）。最後に README・docs を合わせて全体を確かめる（Task 13）。

**Tech Stack:** Python 3 標準ライブラリ（`unittest`）、素の HTML/CSS/JS（外部ライブラリなし）、Playwright MCP（画面の確認用）。

**Spec:** `docs/specs/2026-10-16_board-redesign.md`（承認済み）

> コミットは、実行セッションで依頼主が許可したときに行う（手順にはコミットの区切りだけ書く）。コミットメッセージの末尾には、次の2行を付ける。
>
> ```
> Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
> Claude-Session: https://claude.ai/code/session_01WyZGUQMHwygvLeFk1pobRt
> ```
>
> テストは、リポジトリのルートで `python -m unittest tests.test_guild` を実行する（以降 `TEST`）。新しいテストのクラスは、`tests/test_guild.py` の末尾の `if __name__ == "__main__":` の**上**に足す。ファイルの変更は Edit ツールで行う（`sed` は使わない）。コメントとコミットメッセージは日本語。

## Global Constraints

- 外部通信・外部ライブラリを使わない。ボードは1ファイルの HTML。
- `plan.json` を書けるのは `guild.py` だけ。`plan.json` と `inbox/` の入力の形は、`template` の削除と `inputs`・`candidates`・入力 `inputs` の追加だけにする。
- インプットの同一判定はファイル名（大文字小文字を区別しない）。`guild/inputs/` の直下だけ（サブフォルダは見ない）。名前の形の検査は、パス区切り（`/` `\`）・ドライブの `:`・制御文字・空・`.`・`..` を拒否する。日本語・空白を含む名前は通す。
- `guild/inputs/` に 200 件あっても、`inputs-list` が全件を返し、ボードが操作できる（先頭の行は1ファイル 64KB まで読む）。
- ヒントの偽の一致を防ぐ：一致に使うのは、確認済み（`confirmed`）か出典あり（`sourced`）で、状態が `active` の項目の、3文字以上の名前・別名だけ。依頼文が空なら、ヒントは付けない。
- `inputs-list` の先頭の行は、地図師へのメッセージにだけ入れる（ファイルに保存しない。チャットと画面に出さない）。
- 互換性は不要（既存の `guild/` の移行はしない）。ただし、`inputs` を持たない古い書庫の項目・計画は、そのまま読める（空として扱う）。

## Review Focus

- **`guild/inputs/` に 200 件**：`inputs-list` が全件を名前順で返し、文字のファイルは先頭 5 行だけ読む。→ Task 3 のテスト
- **日本語・空白を含むファイル名**：`inputs-list`・`new`・`adopt`・入力 `inputs`・書庫の `inputs` のどれでも、そのまま通り、CLI の JSON で崩れない。→ Task 2・3・4・5 のテスト
- **短い語によるヒントの偽の一致**：2文字以下の語、推測（`guess`）の項目、廃止・要確認の項目、心得は、ヒントに使わない。→ Task 3 のテスト
- **依頼主がインプットを直したあとの `replan`**：依頼主が足したもの・外したものが、作り直した計画で元に戻らない（外した名前を地図師が選び直しても足さない）。→ Task 4 のテスト
- **ボードの表示から `new` までの間に、選んだインプットが消された**：依頼を拒否し、`requests/rejected/` へ理由つきで移す（`arrivals` が届いたと返し続けない）。依頼の番号は進まない。→ Task 4 のテスト

## ファイル構成（責務）

| ファイル | 責務 | 変更 |
|---|---|---|
| `skills/quest/guild.py` | テンプレートの削除、書庫の `inputs`、`inputs-list` とヒント、`new` の `inputs` 検査、`adopt` の `inputs`・`candidates`、入力 `inputs` | Task 1〜5 |
| `tests/test_guild.py` | エンジンのテスト（`NoTemplateTest`、`ArchiveInputsTest`、`InputsListTest`、`InputsSelectTest`、`InputsInputTest`、契約テスト） | Task 1〜5 |
| `tests/test_guild.py` | ボードの文字列の契約テスト（冒険の書・テンプレートがない、新しいタブ・関数・入力の形） | Task 6〜12 |
| `agents/cartographer.md` | インプットの選び方（`inputs`・`candidates`）。テンプレートの記述を消す | Task 5 |
| `agents/librarian.md` | 候補に任意で `inputs` を書ける | Task 5 |
| `agents/adventurer.md`、`agents/appraiser.md`、`agents/scout.md` | `plan.json` の `inputs` のファイルを読む。テンプレートの記述を消す | Task 5 |
| `skills/quest/SKILL.md` | `inputs-list` を地図師に渡す、`inputs` を各役に渡す、拒否された依頼。テンプレートの記述を消す | Task 5 |
| `docs/graph-format.md`、`docs/archive-spec.md`、`docs/spec.md` | `plan.json` の `inputs`・`candidates`、入力 `inputs`、`inputs-list`、書庫の `inputs`。テンプレートの記述を消す | Task 5 |
| `README.md` | データの置き場から `templates/` を消す | Task 1 |
| `skills/quest/board.html` | クエスト掲示板（一覧＋詳細パネル、道のり／日付／インプット）、手紙の置き場所の移動、「＋ 新規」（既存から選ぶ）、書庫の `inputs` 欄、クエスト進捗のフィルタ、冒険の書・テンプレートの削除、デモ | Task 6〜12 |
| `README.md`、`docs/board-design.md` | タブ構成（7つ）、冒険の書・テンプレートの記述を消す。全体の確認（`TEST` とデモの目視） | Task 13 |

---

### Task 1: 納品物のテンプレートを消す（Python 側）

**Files:**
- Modify: `skills/quest/guild.py`（`adopt` のテンプレートの検査と `plan` の `template`、`init_guild` の `templates/`、`list_requests` の `template`）
- Modify: `README.md`（「データの置き場」の `templates/` の行）
- Test: `tests/test_guild.py`（`TemplateTest` を削除、`InitAndNewTest.test_init_creates_inputs_deliverables_templates` を差し替え、`MarkdownOnlyTest` の docstring、`NoTemplateTest` を追加）

**Interfaces:**
- Consumes: なし
- Produces（以降の Task が使う）：
  - `plan.json` に `template` がない。`plan-draft.json` に `template` があっても、`adopt` は検査も引き継ぎもしない（無視する）。
  - `guild.init_guild(root)` は `guild/templates/` を作らない（`inputs/`・`deliverables/`・`archive/`・`.work/requests/` だけ）。
  - `guild.list_requests(root)` の要素は `{"id", "text", "due", "files"}`（`template` なし。Task 4 で `start`・`inputs` を足す）。
- ボード側に残るもの（Task 6〜12 で消す。この Task では触らない）：`board.html` の `S.fs.list('templates')`、`loadAll` の `templates`、モデルの `templates: raw.templates`、「＋ 新規」の `tplSel`・`new:template`・`newtpl`・「素材ファイル・テンプレートをつける（任意）」、`submitNew` の `template`（`writeBlob('templates/…')` と request の `template`）、納品物タブの「テンプレート」節、ヘルプのディレクトリ構成の `templates/` の行、`PathMap` のコメントの `templates/`、デモの `templates: {…}`。ボードの契約テスト（`BoardPathsTest.test_no_format_or_unreadable_template_machinery`）は、この Task では変わらず通る。

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_guild.py` の `if __name__ == "__main__":` の上に追加）

```python
class NoTemplateTest(unittest.TestCase):
    """納品物のテンプレートは廃止した。guild.py は templates/ を作らず、plan.json に template を持たない。"""

    def test_init_does_not_create_templates(self):
        with tempfile.TemporaryDirectory() as d:
            guild.init_guild(Path(d))
            self.assertFalse((Path(d) / "guild" / "templates").exists())

    def test_adopt_ignores_a_template_in_the_draft(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "guild" / ".work" / "Q001"
            (q / "reports").mkdir(parents=True)
            draft = {"quest": "Q001", "title": "t", "template": "templates/ない.md", "todos": [
                {"id": "T1", "title": "x", "kind": "auto", "deps": [], "deliverable": True, "criteria": CRIT}]}
            (q / "reports" / "plan-draft.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            guild.adopt(q / "plan.json", TR)  # テンプレートの検査はしない（ないファイルを書いてきても落ちない）
            self.assertNotIn("template", guild.load_json(q / "plan.json"))

    def test_requests_do_not_list_a_template(self):
        with tempfile.TemporaryDirectory() as d:
            guild.init_guild(Path(d))
            rdir = Path(d) / "guild" / ".work" / "requests"
            (rdir / "R20261016-1.json").write_text(json.dumps({"type": "request", "text": "t", "template": "templates/x.md", "files": []}), encoding="utf-8")
            self.assertNotIn("template", guild.list_requests(Path(d))[0])

    def test_engine_has_no_template_machinery(self):
        s = (ROOT / "skills" / "quest" / "guild.py").read_text(encoding="utf-8")
        for gone in ("template", "テンプレート"):
            self.assertNotIn(gone, s)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.NoTemplateTest -v`
Expected: 4件とも FAIL か ERROR（`templates/` が作られる、`adopt` が「template が不正か、見つかりません」で落ちる、`list_requests` に `template` がある、`guild.py` に `template` がある）

- [ ] **Step 3: 古いテストを直す**

`TemplateTest` クラス全体（`class TemplateTest(unittest.TestCase):` から `test_adopt_rejects_missing_or_outside_template` の終わりまで）を削除する。

`InitAndNewTest` の次のテストを、

```python
    def test_init_creates_inputs_deliverables_templates(self):
        guild.init_guild(self.root)
        guild.init_guild(self.root)
        for d in ("inputs", "deliverables", "templates"):
            self.assertTrue((self.root / "guild" / d).is_dir(), d)
```

次に置き換える。

```python
    def test_init_creates_inputs_and_deliverables(self):
        guild.init_guild(self.root)
        guild.init_guild(self.root)
        for d in ("inputs", "deliverables"):
            self.assertTrue((self.root / "guild" / d).is_dir(), d)
```

`MarkdownOnlyTest` の docstring を次に置き換える。

```python
    """納品物は Markdown だけ。format の項目はない。"""
```

- [ ] **Step 4: 実装する**

`skills/quest/guild.py` の `adopt` で、次の部分を、

```python
    template = draft.get("template")
    if template:
        # テンプレートは guild/templates/ の中のファイルだけ（外を指せない）
        parts = str(template).replace("\\", "/").split("/")
        tpl = gdir_of(plan_path.parent) / str(template)
        if len(parts) != 2 or parts[0] != "templates" or parts[1] in ("", ".", "..") or not tpl.is_file():
            raise GuildError(f"template が不正か、見つかりません: {template}")
        if not str(template).lower().endswith(".md"):
            raise GuildError(f"template は Markdown（.md）だけです: {template}")
    plan = {"quest": draft.get("quest"), "title": draft.get("title"), "approved": False,
            "status": "active", **({"template": template} if template else {}),
            **({"archive_used": [str(x) for x in draft["archive_used"]]} if isinstance(draft.get("archive_used"), list) else {}), "todos": [], "history": [{"t": now(), "event": "adopted"}]}
```

次に置き換える。

```python
    plan = {"quest": draft.get("quest"), "title": draft.get("title"), "approved": False, "status": "active",
            **({"archive_used": [str(x) for x in draft["archive_used"]]} if isinstance(draft.get("archive_used"), list) else {}),
            "todos": [], "history": [{"t": now(), "event": "adopted"}]}
```

`init_guild` の

```python
    for sub in ("inputs", DELIV, "templates"):
```

を次に置き換える。

```python
    for sub in (INPUTS, DELIV):
```

（`INPUTS` と `DELIV` はモジュールの定数で、`init_guild` が呼ばれる時点では定義済み。）

`list_requests` の

```python
            out.append({"id": f.stem, "text": d.get("text", ""), "due": d.get("due"), "template": d.get("template"), "files": d.get("files", [])})
```

を次に置き換える。

```python
            out.append({"id": f.stem, "text": d.get("text", ""), "due": d.get("due"), "files": d.get("files", [])})
```

`README.md` の「データの置き場」から、次の1行を削除する。

```
  templates/      納品物のテンプレート（.md）
```

- [ ] **Step 5: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.NoTemplateTest tests.test_guild.InitAndNewTest tests.test_guild.MarkdownOnlyTest -v` → PASS。続けて `TEST` が全部通ること（`BoardPathsTest`・`DocsContractTest` は、この Task では変わらない）。

- [ ] **Step 6: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py README.md
git commit -m "納品物のテンプレートを廃止する（guild.py の検査・templates/ の作成・依頼一覧の template を削除）"
```

---

### Task 2: 書庫の項目の `inputs`（見出し情報）

**Files:**
- Modify: `skills/quest/guild.py`（`check_input_name`・`unique_names` を追加、`read_entry`、`entry_text`、`check_entry`、`rebuild_index`、`apply_candidate`、`archive_apply`）
- Test: `tests/test_guild.py`（`ArchiveInputsTest` を追加）

**Interfaces:**
- Consumes: Task 1 の `guild.py`
- Produces（以降の Task が使う）：
  - `guild.check_input_name(n, label) -> str`：インプットの名前の形だけを検査する（`str`・空でない・前後に空白がない・`.` `..` でない・`/` `\` `:` と制御文字を含まない・255 文字以下）。不正なら `GuildError`。存在は見ない。
  - `guild.unique_names(names) -> list`：大文字小文字を区別せずに重なりを除く（最初のものを残し、順序は保つ）。
  - 書庫の項目の見出し情報に `inputs: ["売上 2026年度.xlsx", "KGI定義.md"]`（JSON の配列。`aliases` の次の行）。`read_entry` は、ない・配列でないときは `[]` を返す。`entry_text` はいつも `inputs:` の行を書く。
  - `check_entry` は `inputs` が配列で、各要素が `check_input_name` を通ることを検査する（`guild/inputs/` にあるかは見ない。上書き・削除で外れても項目は壊れない）。
  - 索引（`index.md`）の表は `| 名前 | 別名 | 確度 | 確認日 | 説明 | インプット | 場所 |`。
  - 司書の候補（`archive-draft.json`）に任意で `"inputs": [...]`。新規の登録ではそのまま入り、更新の候補では既存の `inputs` に足す（重なりは除く）。
  - 入力 `{"type": "entry", "entry": {..., "inputs": [...]}}`（新規・編集）。編集（`update_of`）で `entry` に `inputs` の鍵がなければ、今の `inputs` を残す。`[]` を送れば空にする。`promote`・`retype`・`deprecate` は `inputs` を変えない。
  - ボードの書庫の読み取り（フロントマターの解析）は、`inputs` を `aliases` と同じ形（JSON の配列）で読む（Task 6〜12）。

- [ ] **Step 1: 失敗するテストを書く**（`if __name__ == "__main__":` の上に追加）

```python
class ArchiveInputsTest(unittest.TestCase):
    """書庫の項目の inputs（guild/inputs/ のファイル名のリスト）。aliases と同じ作りで、名前の形だけ検査し、存在は見ない。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.adir = self.root / "guild" / "archive"
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, **kw):
        e = {"type": "term", "name": "KGI", "aliases": ["重要目標達成指標"], "summary": "最終目標の指標", "body": "",
             "confidence": "confirmed", "source": "依頼主の登録"}
        e.update(kw)
        return e

    def put_inbox(self, name, data):
        d = self.root / "guild" / ".work" / "archive-inbox"
        d.mkdir(exist_ok=True)
        (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def draft(self, *cands):
        (self.q / "reports" / "archive-draft.json").write_text(json.dumps({"quest": "Q001", "candidates": list(cands)}, ensure_ascii=False), encoding="utf-8")

    def test_roundtrip_with_japanese_and_space_names(self):
        rel = guild.write_entry(self.adir, self.entry(inputs=["売上 2026年度.xlsx", "KGI定義.md"]))
        self.assertIn('inputs: ["売上 2026年度.xlsx", "KGI定義.md"]', (self.adir / rel).read_text(encoding="utf-8"))
        self.assertEqual(guild.read_entry(self.adir / rel)["inputs"], ["売上 2026年度.xlsx", "KGI定義.md"])

    def test_old_entry_without_inputs_reads_as_empty_and_is_rewritten_with_the_line(self):
        (self.adir / "古い.md").write_text('---\nname: "古い"\ntype: term\naliases: []\nconfidence: guess\nsource: ""\n'
                                         'confirmed: 2026-10-01\nstatus: "active"\nsummary: "s"\n---\n本文\n', encoding="utf-8")
        e = guild.read_entry(self.adir / "古い.md")
        self.assertEqual(e["inputs"], [])
        guild.write_entry(self.adir, e, "古い.md")
        self.assertIn("inputs: []", (self.adir / "古い.md").read_text(encoding="utf-8"))

    def test_missing_file_is_allowed_but_bad_shapes_are_not(self):
        guild.write_entry(self.adir, self.entry(inputs=["まだない.pdf"]))  # 存在は検査しない
        for bad in ("a.txt", ["../x.txt"], ["sub/x.txt"], ["sub\\x.txt"], ["C:x.txt"], [""], [" a.txt"], [3], [".."], ["a\nb.txt"]):
            with self.subTest(bad=bad), self.assertRaises(guild.GuildError):
                guild.check_entry(self.entry(inputs=bad))

    def test_check_input_name_and_unique_names(self):
        self.assertEqual(guild.check_input_name("議事録 10月.txt", "x"), "議事録 10月.txt")
        self.assertEqual(guild.unique_names(["a.txt", "B.csv", "A.TXT", "b.csv", "c.md"]), ["a.txt", "B.csv", "c.md"])

    def test_index_lists_inputs(self):
        guild.write_entry(self.adir, self.entry(inputs=["KGI定義.md"]))
        guild.rebuild_index(self.adir)
        idx = (self.adir / "index.md").read_text(encoding="utf-8")
        self.assertIn("| 名前 | 別名 | 確度 | 確認日 | 説明 | インプット | 場所 |", idx)
        self.assertIn("| KGI定義.md | [[KGI]] |", idx)

    def test_candidate_inputs_pass_through_and_merge_on_update(self):
        self.draft(dict(self.entry(confidence="sourced", source="https://example.com (2026-10-16)", inputs=["KGI定義.md"]), id="C1"))
        guild.archive_propose(self.q)
        guild.archive_decide(self.q, {"type": "archive", "decisions": {"C1": "register"}})
        self.assertEqual(guild.read_entry(self.adir / "KGI.md")["inputs"], ["KGI定義.md"])
        # 同名の候補は更新になり、inputs は足される（重なりは除く）
        self.draft(dict(self.entry(confidence="sourced", source="https://example.com (2026-10-16)", inputs=["kgi定義.md", "売上.csv"]), id="C1"))
        guild.archive_propose(self.q)
        guild.archive_decide(self.q, {"type": "archive", "decisions": {"C1": "register"}})
        self.assertEqual(guild.read_entry(self.adir / "KGI.md")["inputs"], ["KGI定義.md", "売上.csv"])

    def test_candidate_with_bad_inputs_is_rejected(self):
        self.draft(dict(self.entry(confidence="sourced", source="x", inputs=["../config.json"]), id="C1"))
        with self.assertRaises(guild.GuildError):
            guild.archive_propose(self.q)

    def test_board_entry_and_edit(self):
        self.put_inbox("1.json", {"type": "entry", "entry": {"type": "term", "name": "KGI", "summary": "s", "body": "", "source": "", "inputs": ["KGI定義.md"]}})
        self.assertEqual(guild.archive_ingest(self.root)["rejected"], [])
        self.assertEqual(guild.read_entry(self.adir / "KGI.md")["inputs"], ["KGI定義.md"])
        # 編集で inputs を送らなければ、今のものを残す
        self.put_inbox("2.json", {"type": "entry", "update_of": "KGI.md", "entry": {"type": "term", "name": "KGI", "summary": "編集", "body": "", "source": ""}})
        guild.archive_ingest(self.root)
        e = guild.read_entry(self.adir / "KGI.md")
        self.assertEqual((e["summary"], e["inputs"]), ("編集", ["KGI定義.md"]))
        # [] を送れば空にする
        self.put_inbox("3.json", {"type": "entry", "update_of": "KGI.md", "entry": {"type": "term", "name": "KGI", "summary": "編集", "body": "", "source": "", "inputs": []}})
        guild.archive_ingest(self.root)
        self.assertEqual(guild.read_entry(self.adir / "KGI.md")["inputs"], [])
        self.put_inbox("4.json", {"type": "entry", "update_of": "KGI.md", "entry": {"type": "term", "name": "KGI", "summary": "s", "body": "", "source": "", "inputs": ["../x"]}})
        self.assertEqual(len(guild.archive_ingest(self.root)["rejected"]), 1)

    def test_promote_retype_deprecate_keep_inputs(self):
        rel = guild.write_entry(self.adir, self.entry(confidence="guess", source="", inputs=["a.txt"]))
        for i, data in enumerate(({"type": "promote", "path": rel}, {"type": "retype", "path": rel, "to": "fact"},
                                  {"type": "deprecate", "path": rel, "reason": "使わない"})):
            with self.subTest(data=data):
                self.put_inbox(f"{i}.json", data)
                self.assertEqual(guild.archive_ingest(self.root)["rejected"], [])
                self.assertEqual(guild.read_entry(self.adir / rel)["inputs"], ["a.txt"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.ArchiveInputsTest -v`
Expected: FAIL か ERROR（`inputs` の鍵がない、`check_input_name` がない、索引の見出しが違う、など）

- [ ] **Step 3: 実装する**

`skills/quest/guild.py` の `INPUTS = "inputs"` の直後に、次を足す。

```python
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
```

`read_entry` の次の3行を、

```python
    if not isinstance(e.get("aliases"), list):
        e["aliases"] = []
    e["aliases"] = [str(a).strip() for a in e["aliases"] if str(a).strip()]
```

次に置き換える。

```python
    for k in ("aliases", "inputs"):  # どちらもリストの項目。ない・壊れているときは空
        if not isinstance(e.get(k), list):
            e[k] = []
        e[k] = [str(a).strip() for a in e[k] if str(a).strip()]
```

`entry_text` 全体を次に置き換える。

```python
def entry_text(e):
    aliases = [one_line(a) for a in e.get("aliases", []) if one_line(a)]
    inputs = [one_line(a) for a in e.get("inputs", []) if one_line(a)]
    head = ["---", f"name: {yaml_str(e['name'])}", f"type: {e['type']}",
            "aliases: " + json.dumps(aliases, ensure_ascii=False),
            "inputs: " + json.dumps(inputs, ensure_ascii=False),
            f"confidence: {e['confidence']}", f"source: {yaml_str(e.get('source'))}", f"confirmed: {e.get('confirmed') or today()}",
            f"status: {yaml_str(e.get('status') or 'active')}", f"summary: {yaml_str(e.get('summary'))}", "---"]
    return "\n".join(head) + "\n" + (e.get("body") or "").strip("\n") + "\n"
```

`check_entry` の末尾（`if e["confidence"] != "guess" and not one_line(e.get("source")):` の2行の後）に、次を足す。

```python
    inputs = e.get("inputs", [])
    if not isinstance(inputs, list):
        raise GuildError(f"inputs はファイル名の配列にしてください: {e.get('name')}")
    for n in inputs:
        check_input_name(n, f"{one_line(e.get('name'))} の inputs")  # 名前の形だけ。guild/inputs/ にあるかは見ない
```

`rebuild_index` の表の見出しと行（`out += ["| 名前 | 別名 | …` から `out.append("| " + …)` まで）を、次に置き換える。

```python
        out += ["| 名前 | 別名 | 確度 | 確認日 | 説明 | インプット | 場所 |", "|---|---|---|---|---|---|---|"]
        for rel, e in rows:
            mark = "（要確認）" if e["status"] == "要確認" else ""
            cells = [e.get("name", ""), "、".join(e["aliases"]), label.get(e.get("confidence"), "") + mark, e.get("confirmed", ""),
                     e.get("summary", ""), "、".join(e["inputs"]), f"[[{rel[:-3]}]]"]
            out.append("| " + " | ".join(c.replace("|", "／") for c in cells) + " |")
```

`apply_candidate` の

```python
        e = dict(old, aliases=sorted({*old["aliases"], *c.get("aliases", [])}), confirmed=today())
```

を次に置き換える。

```python
        e = dict(old, aliases=sorted({*old["aliases"], *c.get("aliases", [])}),
                 inputs=unique_names([*old["inputs"], *c.get("inputs", [])]), confirmed=today())
```

（新規の登録 `write_entry(adir, dict(c, confirmed=today(), status="active"))` は、候補の `inputs` をそのまま書くので変えない。）

`archive_apply` の `if kind == "entry":` の枝全体（`elif kind == "promote":` の前まで）を、次に置き換える。

```python
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
```

- [ ] **Step 4: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.ArchiveInputsTest tests.test_guild.ArchiveTest -v` → PASS。続けて `TEST` が全部通ること（既存の `test_retype_keeps_fields_and_updates_index` などは、`inputs` が `[]` のまま引き継がれるので通る）。

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "書庫の項目に inputs（インプットのファイル名のリスト）を足す。名前の形だけ検査し、索引にも載せる"
```

---

### Task 3: `inputs-list` コマンドとヒント

**Files:**
- Modify: `skills/quest/guild.py`（`existing_inputs`・`read_head`・`hint_terms`・`inputs_list` を追加、`main`、先頭の docstring）
- Test: `tests/test_guild.py`（先頭の import に `datetime`、`InputsListTest` を追加）

**Interfaces:**
- Consumes: Task 2 の書庫の項目の `inputs`（`read_entry` が `[]` で埋める）、`ARCHIVE_TITLES`、`all_entries`
- Produces（以降の Task が使う）：
  - `guild.existing_inputs(gdir) -> dict`：`guild/inputs/` の直下のファイルを `{小文字の名前: 実際の名前}` で返す（フォルダがなければ `{}`）。
  - `guild.inputs_list(root, text="") -> list`。`guild/config.json` がなければ `GuildError`。要素の形（名前順。ヒントのあるものが先）：

    ```json
    {"name": "売上_2026Q3.csv", "ext": ".csv", "size": 1234, "updated": "2026-10-01",
     "head": ["月,売上,KGI達成率", "1月,100,1%"], "hints": ["書庫の用語『KGI』→ このファイル"]}
    ```

    - `ext` は小文字の拡張子（なければ `""`）。`size` はバイト数。`updated` は更新日時（ローカル）の `YYYY-MM-DD`。
    - `head` は、`.md` `.txt` `.csv` だけ、先頭 64KB を UTF-8（読めない文字は置き換え）で読んだ最初の 5 行（1行 200 文字まで）。それ以外は `null`。
    - `hints` は理由の文字列のリスト。依頼文 `text` に名前・別名が出てくる（大文字小文字を区別しない部分一致）書庫の項目のうち、`confidence` が `confirmed` か `sourced`、`status` が `active`、`type` が用語・業務フロー・業務情報・個人（心得を除く）で、3文字以上の語だけを使う。その項目について、(1) 項目の `inputs` に挙がったファイル →「書庫の{種類名}『{項目名}』→ このファイル」(2) ファイル名にその項目の名前・別名（3文字以上）が出てくる →「ファイル名に書庫の{種類名}『{項目名}』」(3) (2) でなく、先頭の 5 行に出てくる →「先頭の行に書庫の{種類名}『{項目名}』」。`text` が空ならヒントはない（依頼に関係なくファイル名だけで一致させると、偽の一致が増えるため）。
  - CLI：`guild.py inputs-list ROOT [--text 依頼文]` → 上のリストの JSON（`ensure_ascii=False`）。形が違えば終了コード 1。
  - `inputs-list` の結果は地図師だけが使う（ボードは読まない。ボードはインプットの一覧を `S.fs.list('inputs')` で読む）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_guild.py` の先頭の `import copy` の次の行に、`import datetime` を足す。`if __name__ == "__main__":` の上に、次を足す。

```python
class InputsListTest(unittest.TestCase):
    """inputs-list：guild/inputs/ のファイルの一覧と、書庫の項目からのヒント（地図師がインプットを選ぶ材料）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.inputs = self.root / "guild" / "inputs"
        self.adir = self.root / "guild" / "archive"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, body):
        p = self.inputs / name
        p.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))  # 改行を変換しない（size を比べるため）
        return p

    def term(self, name, aliases=(), inputs=(), confidence="confirmed", status="active", etype="term"):
        guild.write_entry(self.adir, {"type": etype, "name": name, "aliases": list(aliases), "inputs": list(inputs), "summary": "s",
                                      "body": "", "confidence": confidence, "source": "" if confidence == "guess" else "依頼主の登録",
                                      "status": status})

    def by_name(self, items):
        return {x["name"]: x for x in items}

    def test_lists_files_with_shape_and_head(self):
        csv = "月,売上,KGI達成率\n" + "".join(f"{m}月,{m * 100},{m}%\n" for m in range(1, 10))
        self.put("売上_2026Q3.csv", csv)
        self.put("議事録 10月.txt", "10月の定例\n参加者：A、B\n")
        self.put("提案書.pptx", b"PK\x03\x04\x00\x00")
        (self.inputs / "old").mkdir()
        (self.inputs / "old" / "中のファイル.md").write_text("x", encoding="utf-8")  # サブフォルダは見ない
        ts = datetime.datetime(2026, 10, 1, 12, 0).timestamp()
        os.utime(self.inputs / "議事録 10月.txt", (ts, ts))
        items = guild.inputs_list(self.root)
        self.assertEqual([x["name"] for x in items], ["売上_2026Q3.csv", "提案書.pptx", "議事録 10月.txt"])  # 名前順
        got = self.by_name(items)
        c = got["売上_2026Q3.csv"]
        self.assertEqual(set(c), {"name", "ext", "size", "updated", "head", "hints"})
        self.assertEqual((c["ext"], c["size"], c["hints"]), (".csv", len(csv.encode("utf-8")), []))
        self.assertEqual(c["head"], csv.splitlines()[:5])
        self.assertRegex(c["updated"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual((got["提案書.pptx"]["ext"], got["提案書.pptx"]["head"]), (".pptx", None))
        self.assertEqual(got["議事録 10月.txt"]["updated"], "2026-10-01")
        self.assertEqual(got["議事録 10月.txt"]["head"], ["10月の定例", "参加者：A、B"])

    def test_two_hundred_files_and_unreadable_text(self):
        for i in range(200):
            self.put(f"資料 {i:03d}.txt", f"{i}行目\n" * 10)
        self.put("sjis.txt", "売上の表".encode("shift_jis"))  # UTF-8 でないファイルでも止まらない
        self.put("long.md", "x" * 500000)  # 改行のない長いファイル
        items = guild.inputs_list(self.root)
        self.assertEqual(len(items), 202)
        self.assertEqual([x["name"] for x in items[:3]], ["long.md", "sjis.txt", "資料 000.txt"])
        self.assertTrue(all(len(x["head"]) <= 5 for x in items))
        got = self.by_name(items)
        self.assertEqual(len(got["sjis.txt"]["head"]), 1)
        self.assertIsInstance(got["sjis.txt"]["head"][0], str)
        self.assertEqual(len(got["long.md"]["head"][0]), 200)

    def test_hints_from_archive_inputs(self):
        self.put("売上_2026Q3.csv", "月,売上\n")
        self.put("aaa.txt", "関係ない\n")
        # 大文字小文字は区別しない。ないファイルの名前は無視する
        self.term("KGI", aliases=["Key Goal Indicator"], inputs=["売上_2026q3.CSV", "消えたファイル.xlsx"])
        items = guild.inputs_list(self.root, "今期の kgi の達成状況をまとめて")
        self.assertEqual(items[0]["name"], "売上_2026Q3.csv")  # ヒントのあるファイルが先
        self.assertEqual(items[0]["hints"], ["書庫の用語『KGI』→ このファイル"])
        self.assertEqual(items[1]["hints"], [])
        self.assertEqual(guild.inputs_list(self.root, "Key Goal Indicator を確認")[0]["hints"], ["書庫の用語『KGI』→ このファイル"])
        self.term("出典ありの語", confidence="sourced", inputs=["aaa.txt"])
        got = self.by_name(guild.inputs_list(self.root, "出典ありの語を使う"))
        self.assertEqual(got["aaa.txt"]["hints"], ["書庫の用語『出典ありの語』→ このファイル"])

    def test_hints_from_file_name_and_head(self):
        self.term("月次報告書", etype="fact")
        self.put("月次報告書_ひな形.md", "# 見出し\n")
        self.put("メモ.txt", "来週の作業\n月次報告書の締切は5日\n")
        self.put("zzz.txt", "1\n2\n3\n4\n5\n月次報告書\n")  # 6行目は見ない
        items = guild.inputs_list(self.root, "月次報告書を作って")
        got = self.by_name(items)
        self.assertEqual(got["月次報告書_ひな形.md"]["hints"], ["ファイル名に書庫の業務情報『月次報告書』"])
        self.assertEqual(got["メモ.txt"]["hints"], ["先頭の行に書庫の業務情報『月次報告書』"])
        self.assertEqual(got["zzz.txt"]["hints"], [])
        self.assertEqual([x["name"] for x in items], ["メモ.txt", "月次報告書_ひな形.md", "zzz.txt"])
        # 依頼文に出てこない項目は、ファイル名にあってもヒントにしない。依頼文がなければヒントはない
        self.assertTrue(all(not x["hints"] for x in guild.inputs_list(self.root, "別の依頼")))
        self.assertTrue(all(not x["hints"] for x in guild.inputs_list(self.root)))

    def test_false_positive_guards(self):
        self.put("売上_2026Q3.csv", "月,売上\n推測語ABC\n")
        self.term("売上", inputs=["売上_2026Q3.csv"])  # 2文字の語は使わない
        self.term("推測語ABC", inputs=["売上_2026Q3.csv"], confidence="guess")
        self.term("廃止語ABC", inputs=["売上_2026Q3.csv"], status="廃止")
        self.term("要確認ABC", inputs=["売上_2026Q3.csv"], status="要確認")
        self.term("心得ABC", inputs=["売上_2026Q3.csv"], etype="lesson")
        items = guild.inputs_list(self.root, "売上と 推測語ABC と 廃止語ABC と 要確認ABC と 心得ABC を見る")
        self.assertEqual(items[0]["hints"], [])

    def test_without_init_or_inputs_folder(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(guild.GuildError):
                guild.inputs_list(Path(d))
        self.inputs.rmdir()
        self.assertEqual(guild.inputs_list(self.root), [])
        self.assertEqual(guild.existing_inputs(self.root / "guild"), {})

    def test_existing_inputs(self):
        self.put("KGI定義.md", "x")
        (self.inputs / "sub").mkdir()
        self.assertEqual(guild.existing_inputs(self.root / "guild"), {"kgi定義.md": "KGI定義.md"})

    def test_cli(self):
        self.put("議事録 10月.txt", "KGI の確認\n")
        self.term("KGI", inputs=["議事録 10月.txt"])
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "skills" / "quest" / "guild.py"), "inputs-list", str(self.root), *a],
                                        capture_output=True, text=True, encoding="utf-8")
        r = run("--text", "KGI をまとめる")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got[0]["name"], "議事録 10月.txt")
        self.assertIn("書庫の用語『KGI』→ このファイル", got[0]["hints"])
        self.assertEqual(run().returncode, 0)
        self.assertEqual(run("--nanika").returncode, 1)
        self.assertEqual(run("--text").returncode, 1)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.InputsListTest -v`
Expected: ERROR（`guild.inputs_list` がない、CLI は使い方を出して終了コード 1）

- [ ] **Step 3: 実装する**

`skills/quest/guild.py` の `import_inputs` の直後に、次を足す。

```python
def existing_inputs(gdir):
    """guild/inputs/ の直下のファイルを {小文字の名前: 実際の名前} で返す（同一判定は大文字小文字を区別しない）。"""
    d = Path(gdir) / INPUTS
    return {p.name.lower(): p.name for p in d.iterdir() if p.is_file()} if d.is_dir() else {}
```

`archive_ingest` の後（`def main(argv):` の前）に、次を足す。

```python
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
```

`main` のコマンドの一覧（`argv[1] not in (...)` のタプル）の末尾に `"inputs-list"` を足す。`if cmd in ("web-ingest", "web-pending", "web-reset"):` の前に、次を足す。

```python
        if cmd == "inputs-list":
            rest = argv[3:]
            if rest and (len(rest) != 2 or rest[0] != "--text"):
                raise GuildError("inputs-list ROOT [--text 依頼文] の形で指定してください")
            print(json.dumps(inputs_list(path, rest[1] if rest else ""), ensure_ascii=False))
            return 0
```

先頭の docstring の `guild.py requests ROOT: 受付待ちの依頼を一覧する。` の次の行に、次を足す。

```
guild.py inputs-list ROOT [--text 依頼文]: guild/inputs/ のファイル（名前・拡張子・大きさ・更新日・文字のファイルの先頭5行）と、依頼文に出てくる書庫の項目からのヒントを一覧する（地図師に渡す）。
```

- [ ] **Step 4: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.InputsListTest -v` → PASS。続けて `TEST` が全部通ること。

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "inputs-list を足す：インプットの一覧（先頭の行つき）と、依頼文に出てくる書庫の項目からのヒント"
```

---

### Task 4: 依頼の `inputs`（既存から選ぶ）と、計画の `inputs`・`candidates`

**Files:**
- Modify: `skills/quest/guild.py`（`picked_inputs`・`reject_request`・`request_inputs`・`user_removed`・`selected_inputs`・`check_plan_inputs` を追加、`new_quest`、`list_requests`、`validate`、`adopt`、先頭の docstring）
- Test: `tests/test_guild.py`（`InputsSelectTest` を追加）

**Interfaces:**
- Consumes: Task 2 の `check_input_name`・`unique_names`、Task 3 の `existing_inputs`
- Produces（以降の Task が使う）：
  - ボードが書く受付待ちの依頼（`.work/requests/<ID>.json`）：

    ```json
    {"type": "request", "text": "…", "start": "2026-10-16", "due": null,
     "inputs": ["KGI定義.md"], "files": ["メモ.txt"], "created": "…"}
    ```

    `inputs` は、依頼主が「既存から選ぶ」で選んだ `guild/inputs/` の名前（任意。なければ `[]`）。`files` は、アップロードしたファイルの名前（今までどおり、中身は `.work/requests/files/<ID>/`）。`template` は書かない。
  - `guild.new_quest(root, request_id)`：`inputs` の各名前は、`guild/inputs/` にある（大文字小文字を区別しない）か、同じ依頼でアップロードしたファイルの名前であること。違えば、依頼を `.work/requests/rejected/<ID>.json` へ移し、理由を `.work/requests/rejected/<ID>.json.reason.txt` に、添付を `.work/requests/rejected/files/<ID>/` に移して `GuildError`（依頼のフォルダは作らず、番号は進まない。`requests`・`arrivals` に出なくなる）。受け付けたら、`request.json` の `inputs` は「選んだ名前（実際の名前）＋取り込んだアップロードの名前」（重なりを除き、選んだものが先）。`files` はそのまま。
  - `guild.list_requests(root)` の要素：`{"id", "text", "start", "due", "inputs", "files"}`。
  - `plan.json` に、いつも次の2つ（`adopt` が書く）：

    ```json
    "inputs": [
      {"name": "KGI定義.md", "source": "user", "reason": "依頼主の指定"},
      {"name": "売上 2026Q3.csv", "source": "auto", "reason": "KGI の元データ（書庫の用語『KGI』のヒント）"}
    ],
    "candidates": [
      {"name": "古い資料.pdf", "reason": "名前だけでは関係が分からない"}
    ]
    ```

    - `source` は `user`（依頼主の指定。`reason` は「依頼主の指定」、あとから足したものは「依頼主が追加」）か `auto`（地図師の選択）。`user` が先頭。名前の重なりはない（`inputs` と `candidates` をまたいでも）。
  - `plan-draft.json`（地図師）：任意の `"inputs": [{"name", "reason"}]` と `"candidates": [{"name", "reason"}]`。`adopt` は、名前が `guild/inputs/` にない、`reason` が空、形が違う、のどれでも `GuildError`（`plan.json` は書かない。ギルドマスターが地図師に差し戻す）。依頼主の指定と重なる名前は `auto` として足さない。`inputs` に入った名前は `candidates` から除く。
  - 作り直し（`replan`）の `adopt`：旧計画に `inputs` があれば、それ（依頼主の追加・外すを反映済み）をそのまま引き継ぎ、地図師の `inputs` は、そこになく、依頼主が外したままでない名前だけ `auto` で足す。「外したまま」は、旧計画の `history` の `{"event": "inputs", "add": […], "remove": […]}` を順にたどって決める（新しい項目は足さない）。
  - `guild.validate(plan, tr)` は `inputs`・`candidates` の形を検査する（配列、`name` が `check_input_name` を通る、`inputs` の `source` が `user`/`auto`、`reason` が文字列、重なりなし）。存在は見ない（`adopt` と `ingest` が見る）。`inputs` がない古い計画も通る。

- [ ] **Step 1: 失敗するテストを書く**（`if __name__ == "__main__":` の上に追加）

```python
class InputsSelectTest(unittest.TestCase):
    """依頼で選んだインプット（request.json の inputs）と、計画の inputs・candidates（adopt）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.g = self.root / "guild"
        for n in ("KGI定義.md", "売上 2026Q3.csv", "提案書.pptx", "古い資料.pdf"):
            (self.g / "inputs" / n).write_text("x", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, rid, picked=(), uploads=None):
        w = self.g / ".work" / "requests"
        uploads = uploads or {}
        (w / f"{rid}.json").write_text(json.dumps({"type": "request", "text": "KGI をまとめて", "start": "2026-10-16", "due": None,
                                                   "inputs": list(picked), "files": list(uploads)}, ensure_ascii=False), encoding="utf-8")
        if uploads:
            f = w / "files" / rid
            f.mkdir(parents=True)
            for n, body in uploads.items():
                (f / n).write_text(body, encoding="utf-8")

    def quest(self, picked=(), old=None):
        self.request("R20261016-1", picked=picked)
        q = Path(guild.new_quest(self.root, "R20261016-1")["dir"])
        if old is not None:
            guild.save_plan(q / "plan.json", old)
        return q

    def adopt(self, q, **extra):
        draft = {"quest": "Q001", "title": "t", "todos": [{"id": "T1", "title": "a", "kind": "auto", "deps": [], "criteria": CRIT}], **extra}
        (q / "reports" / "plan-draft.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        guild.adopt(q / "plan.json", TR)
        return guild.load_json(q / "plan.json")

    def test_new_takes_picked_and_uploaded_inputs(self):
        self.request("R20261016-1", picked=["kgi定義.md", "売上 2026Q3.csv"], uploads={"メモ.txt": "v1", "KGI定義.md": "x"})
        q = guild.new_quest(self.root, "R20261016-1")
        want = ["KGI定義.md", "売上 2026Q3.csv", "メモ.txt"]  # 実際の名前。重なりを除き、選んだものが先
        self.assertEqual(q["inputs"], want)
        req = guild.load_json(Path(q["dir"]) / "request.json")
        self.assertEqual((req["inputs"], req["files"]), (want, ["メモ.txt", "KGI定義.md"]))

    def test_picked_name_uploaded_in_the_same_request_is_accepted(self):
        self.request("R20261016-1", picked=["新しい 資料.txt"], uploads={"新しい 資料.txt": "v1"})
        self.assertEqual(guild.new_quest(self.root, "R20261016-1")["inputs"], ["新しい 資料.txt"])

    def test_missing_picked_name_rejects_the_request(self):
        self.request("R20261016-1", picked=["消された.xlsx"], uploads={"メモ.txt": "v1"})
        with self.assertRaises(guild.GuildError):
            guild.new_quest(self.root, "R20261016-1")
        w = self.g / ".work"
        self.assertFalse((w / "Q001").exists())
        self.assertFalse((w / "requests" / "R20261016-1.json").exists())
        self.assertIn("消された.xlsx", (w / "requests" / "rejected" / "R20261016-1.json.reason.txt").read_text(encoding="utf-8"))
        self.assertTrue((w / "requests" / "rejected" / "R20261016-1.json").is_file())
        self.assertTrue((w / "requests" / "rejected" / "files" / "R20261016-1" / "メモ.txt").is_file())
        self.assertFalse((self.g / "inputs" / "メモ.txt").exists())  # 拒否した依頼の添付は取り込まない
        self.assertEqual([a for a in guild.arrivals(self.root) if a["kind"] == "request"], [])  # 届いたと返し続けない
        self.assertEqual(guild.list_requests(self.root), [])
        self.assertEqual(guild.new_quest(self.root)["quest"], "Q001")  # 番号は進まない

    def test_bad_inputs_shapes_reject_the_request(self):
        for i, bad in enumerate(("KGI定義.md", ["../config.json"], [3], ["sub/KGI定義.md"])):
            with self.subTest(bad=bad):
                rid = f"R20261016-{i}"
                (self.g / ".work" / "requests" / f"{rid}.json").write_text(json.dumps({"type": "request", "text": "t", "inputs": bad, "files": []}), encoding="utf-8")
                with self.assertRaises(guild.GuildError):
                    guild.new_quest(self.root, rid)
                self.assertTrue((self.g / ".work" / "requests" / "rejected" / f"{rid}.json").is_file())

    def test_list_requests_shows_start_and_inputs(self):
        self.request("R20261016-1", picked=["KGI定義.md"])
        r = guild.list_requests(self.root)[0]
        self.assertEqual((r["start"], r["inputs"], r["files"]), ("2026-10-16", ["KGI定義.md"], []))

    def test_adopt_puts_user_inputs_first_then_auto_and_keeps_candidates(self):
        q = self.quest(picked=["KGI定義.md"])
        p = self.adopt(q, inputs=[{"name": "売上 2026q3.CSV", "reason": "KGI の元データ"}, {"name": "kgi定義.md", "reason": "重複"}],
                       candidates=[{"name": "古い資料.pdf", "reason": "名前だけでは関係が分からない"},
                                   {"name": "売上 2026Q3.csv", "reason": "選んだもの"}])
        self.assertEqual(p["inputs"], [{"name": "KGI定義.md", "source": "user", "reason": "依頼主の指定"},
                                       {"name": "売上 2026Q3.csv", "source": "auto", "reason": "KGI の元データ"}])
        self.assertEqual(p["candidates"], [{"name": "古い資料.pdf", "reason": "名前だけでは関係が分からない"}])
        self.assertEqual(guild.validate(p, TR), [])

    def test_adopt_without_inputs_writes_empty_lists(self):
        p = self.adopt(self.quest())
        self.assertEqual((p["inputs"], p["candidates"]), ([], []))

    def test_adopt_rejects_unknown_names_or_missing_reasons(self):
        q = self.quest()
        for extra in ({"inputs": [{"name": "ない.xlsx", "reason": "r"}]}, {"candidates": [{"name": "ない.xlsx", "reason": "r"}]},
                      {"inputs": [{"name": "KGI定義.md"}]}, {"inputs": [{"name": "KGI定義.md", "reason": " "}]},
                      {"inputs": ["KGI定義.md"]}, {"inputs": {"name": "KGI定義.md"}},
                      {"inputs": [{"name": "../config.json", "reason": "r"}]}):
            with self.subTest(extra=extra), self.assertRaises(guild.GuildError):
                self.adopt(q, **extra)
        self.assertFalse((q / "plan.json").exists())

    def test_replan_keeps_the_user_edits(self):
        old = dict(plan(todo("T1", state="done")), status="replan",
                   inputs=[{"name": "KGI定義.md", "source": "user", "reason": "依頼主の指定"},
                           {"name": "提案書.pptx", "source": "user", "reason": "依頼主が追加"}],
                   candidates=[],
                   history=[{"t": "2026-10-16T10:00:00+09:00", "event": "inputs", "add": ["提案書.pptx"], "remove": ["売上 2026Q3.csv"]}])
        q = self.quest(picked=["KGI定義.md"], old=old)
        p = self.adopt(q, inputs=[{"name": "売上 2026Q3.csv", "reason": "元データ"}, {"name": "古い資料.pdf", "reason": "前回の資料"}])
        # 依頼主が足したものは残り、外した「売上」は、地図師が選び直しても足さない
        self.assertEqual([(x["name"], x["source"]) for x in p["inputs"]],
                         [("KGI定義.md", "user"), ("提案書.pptx", "user"), ("古い資料.pdf", "auto")])

    def test_replan_after_removing_a_requested_input_does_not_bring_it_back(self):
        old = dict(plan(todo("T1")), status="replan", inputs=[], candidates=[],
                   history=[{"t": "2026-10-16T10:00:00+09:00", "event": "inputs", "add": [], "remove": ["KGI定義.md"]}])
        q = self.quest(picked=["KGI定義.md"], old=old)
        self.assertEqual(self.adopt(q, inputs=[{"name": "KGI定義.md", "reason": "定義"}])["inputs"], [])

    def test_validate_checks_inputs_shape(self):
        p = plan(todo("T1"))
        for bad in ({"inputs": "x"}, {"inputs": [{"name": "a.txt", "source": "x", "reason": ""}]},
                    {"inputs": [{"name": "../a", "source": "auto", "reason": ""}]},
                    {"inputs": [{"name": "a.txt", "source": "auto"}]},
                    {"inputs": [{"name": "a.txt", "source": "auto", "reason": ""}, {"name": "A.TXT", "source": "user", "reason": ""}]},
                    {"inputs": [{"name": "a.txt", "source": "auto", "reason": ""}], "candidates": [{"name": "a.txt", "reason": ""}]},
                    {"candidates": [{"name": "b.txt"}]}, {"candidates": ["b.txt"]}):
            with self.subTest(bad=bad):
                self.assertTrue(guild.validate(dict(p, **bad), TR))
        self.assertEqual(guild.validate(dict(p, inputs=[], candidates=[]), TR), [])
        self.assertEqual(guild.validate(p, TR), [])  # inputs がない古い計画も通る
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.InputsSelectTest -v`
Expected: FAIL か ERROR（`inputs` が request.json で上書きされる、拒否されない、`plan.json` に `inputs` がない、`validate` が形を見ない、など）

- [ ] **Step 3: 依頼の受付（`new_quest`・`list_requests`）を実装する**

`list_requests` の `out.append(...)` の行（Task 1 で直したもの）を、次に置き換える。

```python
            out.append({"id": f.stem, "text": d.get("text", ""), "start": d.get("start"), "due": d.get("due"),
                        "inputs": d.get("inputs", []), "files": d.get("files", [])})
```

`existing_inputs`（Task 3）の直後に、次の2つを足す。

```python
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
```

`new_quest` 全体を、次に置き換える。

```python
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
```

- [ ] **Step 4: 計画の `inputs`・`candidates`（`adopt`・`validate`）を実装する**

`quest_dates` の直後（`def adopt` の前）に、次を足す。

```python
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
```

`validate` の、依頼の日付の検査（`for k in ("start", "due"):` の4行）の直後に、次の1行を足す。

```python
    errs += check_plan_inputs(plan)
```

`adopt` の次の部分（Task 1 で直したもの）を、

```python
    plan = {"quest": draft.get("quest"), "title": draft.get("title"), "approved": False, "status": "active",
            **({"archive_used": [str(x) for x in draft["archive_used"]]} if isinstance(draft.get("archive_used"), list) else {}),
            "todos": [], "history": [{"t": now(), "event": "adopted"}]}
```

次に置き換える。

```python
    inputs, candidates = selected_inputs(plan_path.parent, draft, old)  # 何も書く前に検査する（落ちたら地図師に差し戻す）
    plan = {"quest": draft.get("quest"), "title": draft.get("title"), "approved": False, "status": "active",
            **({"archive_used": [str(x) for x in draft["archive_used"]]} if isinstance(draft.get("archive_used"), list) else {}),
            "inputs": inputs, "candidates": candidates,
            "todos": [], "history": [{"t": now(), "event": "adopted"}]}
```

先頭の docstring の `guild.py new ROOT [R…]: …` の行を、次に置き換える。

```
guild.py new ROOT [R…]: ROOT/guild/.work/ に次の依頼のフォルダ（Q001…）を作る。R… を渡すと、ボードが保存した受付待ちの依頼を取り込む（選んだインプットが guild/inputs/ になければ、依頼を .work/requests/rejected/ へ移して拒否する）。
```

`adopt は PLAN と同じフォルダの reports/plan-draft.json から PLAN を作る（承認前の状態で）。` の行を、次に置き換える。

```
adopt は PLAN と同じフォルダの reports/plan-draft.json から PLAN を作る（承認前の状態で）。inputs・candidates の名前が guild/inputs/ になければエラー。
```

- [ ] **Step 5: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.InputsSelectTest tests.test_guild.InputsTest tests.test_guild.InitAndNewTest tests.test_guild.AdoptTest tests.test_guild.AdoptDatesTest -v` → PASS。続けて `TEST` が全部通ること（既存の `AdoptTest` は `guild/inputs/` のない一時フォルダで動くが、`inputs`・`candidates` を書かない下書きなので、名前の存在を見ずに `[]` になる）。

- [ ] **Step 6: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "依頼で既存のインプットを選べるようにし、計画に inputs（指定・自動と理由）と candidates を持たせる"
```

---

### Task 5: 入力 `inputs`（追加・外す）と、指示書・docs

**Files:**
- Modify: `skills/quest/guild.py`（`apply_inputs` を追加、`apply_input`、`ingest`、先頭の docstring）
- Modify: `agents/cartographer.md`、`agents/librarian.md`、`agents/adventurer.md`、`agents/appraiser.md`、`agents/scout.md`
- Modify: `skills/quest/SKILL.md`
- Modify: `docs/graph-format.md`、`docs/archive-spec.md`、`docs/spec.md`
- Test: `tests/test_guild.py`（`InputsInputTest` を追加、`BoardContractTest.CASES` に1件、`DocsContractTest` に追加）

**Interfaces:**
- Consumes: Task 2〜4 の `check_input_name`・`unique_names`・`existing_inputs`、`plan.json` の `inputs`・`candidates`
- Produces（ボードの Task 6〜12 が使う）：
  - 入力（`guild/.work/Q###/inbox/*.json`）：

    ```json
    {"type": "inputs", "add": ["古い資料.pdf"], "remove": ["売上 2026Q3.csv"]}
    ```

    - `add`・`remove` はファイル名の配列（どちらか片方は省略可。省略は `[]`）。`add` の名前は `guild/inputs/` にあること（大文字小文字を区別しない。実際の名前で入る）。`remove` の名前は `plan.json` の `inputs` にあること（`user` も `auto` も外せる）。同じ名前を足して外す、すでに入っている名前だけを足す（変更なし）、形の誤りは、拒否（`inbox/rejected/`）。全部を検査してから変える（一部だけ反映しない）。
    - 足したものは `{"name", "source": "user", "reason": "依頼主が追加"}` で `inputs` の後ろに付き、`candidates` から除かれる。外したものは `candidates` に戻さない。
    - 承認前・進行中に受け付ける。中止（`aborted`）・見直し中（`replan`）・受け取り後（`accepted`）は拒否。
    - 履歴に `{"t", "event": "inputs", "add": [実際の名前…], "remove": [実際の名前…]}` を残す（`id` は付けない。タイムラインの状態の変化として読まない）。
  - `guild.apply_input(plan, data, tr, qdir=None)`（`qdir` は依頼のフォルダ。`ingest` が渡す。`inputs` の `add` の存在の確認に使う）。
  - ボードの文字列の契約テスト（`BoardContractTest.test_board_source_writes_the_same_shapes`）に `"type: 'inputs', add:"` を足すのは、ボードがこの入力を書くようになる Task（6〜12）で行う。

- [ ] **Step 1: 失敗するテストを書く**（`if __name__ == "__main__":` の上に追加）

```python
class InputsInputTest(unittest.TestCase):
    """入力 inputs（このクエストのインプットの追加・外す）。足す名前は guild/inputs/ にあること。承認前・進行中に受け付ける。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        guild.init_guild(self.root)
        self.g = self.root / "guild"
        for n in ("a.txt", "売上 2026Q3.csv", "古い資料.pdf"):
            (self.g / "inputs" / n).write_text("x", encoding="utf-8")
        self.q = Path(guild.new_quest(self.root)["dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, **kw):
        p = dict(plan(todo("T1", state="running")),
                 inputs=[{"name": "a.txt", "source": "user", "reason": "依頼主の指定"},
                         {"name": "売上 2026Q3.csv", "source": "auto", "reason": "元データ"}],
                 candidates=[{"name": "古い資料.pdf", "reason": "関係が分からない"}])
        p.update(kw)
        return p

    def send(self, p, data):
        (self.q / "inbox" / "20261016120000-inputs.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return guild.ingest(self.q / "plan.json", p, TR)

    def names(self, p):
        return [(x["name"], x["source"]) for x in p["inputs"]]

    def test_add_a_candidate_and_remove_an_auto_input(self):
        p = self.plan()
        r = self.send(p, {"type": "inputs", "add": ["古い資料.PDF"], "remove": ["売上 2026Q3.csv"]})
        self.assertEqual(r["rejected"], [])
        self.assertEqual(self.names(p), [("a.txt", "user"), ("古い資料.pdf", "user")])
        self.assertEqual(p["inputs"][1]["reason"], "依頼主が追加")
        self.assertEqual(p["candidates"], [])
        h = p["history"][-1]
        self.assertEqual((h["event"], h["add"], h["remove"]), ("inputs", ["古い資料.pdf"], ["売上 2026Q3.csv"]))
        self.assertNotIn("id", h)  # タイムラインは id を持つ記録を状態の変化として読む
        self.assertEqual(guild.validate(p, TR), [])

    def test_user_inputs_can_be_removed_and_unapproved_plans_accept(self):
        p = self.plan(approved=False)
        self.assertEqual(self.send(p, {"type": "inputs", "add": [], "remove": ["A.TXT"]})["rejected"], [])
        self.assertEqual(self.names(p), [("売上 2026Q3.csv", "auto")])

    def test_bad_inputs_are_rejected_and_plan_is_unchanged(self):
        for bad in ({"type": "inputs", "add": ["ない.xlsx"], "remove": []},
                    {"type": "inputs", "add": [], "remove": ["古い資料.pdf"]},  # 計画の inputs にない
                    {"type": "inputs", "add": ["a.txt"], "remove": ["a.txt"]},
                    {"type": "inputs", "add": ["../config.json"]},
                    {"type": "inputs", "add": "古い資料.pdf"},
                    {"type": "inputs", "add": [], "remove": []},
                    {"type": "inputs"},
                    {"type": "inputs", "add": ["a.txt"]},  # すでに入っているだけで、変わらない
                    {"type": "inputs", "add": ["古い資料.pdf", "ない.xlsx"]}):  # 一部だけ反映しない
            with self.subTest(bad=bad):
                p = self.plan()
                before = copy.deepcopy(p)
                self.assertEqual(len(self.send(p, bad)["rejected"]), 1)
                self.assertEqual(p, before)

    def test_closed_or_replanning_plans_reject(self):
        for extra in ({"status": "aborted"}, {"status": "replan", "approved": False}, {"accepted": True}):
            with self.subTest(extra=extra):
                p = self.plan(**extra)
                self.assertEqual(len(self.send(p, {"type": "inputs", "add": ["古い資料.pdf"]})["rejected"]), 1)

    def test_old_plan_without_inputs_accepts_add(self):
        p = plan(todo("T1"))
        self.assertEqual(self.send(p, {"type": "inputs", "add": ["a.txt"]})["rejected"], [])
        self.assertEqual(p["inputs"], [{"name": "a.txt", "source": "user", "reason": "依頼主が追加"}])
```

`BoardContractTest.CASES` の末尾（`({"type": "due", "start": "2026-10-16", "due": "2026-10-30"}, …),` の次の行）に、次を足す。

```python
        ({"type": "inputs", "add": [], "remove": ["メモ.txt"]}, lambda: dict(plan(todo("T1"), approved=False), inputs=[{"name": "メモ.txt", "source": "auto", "reason": "r"}], candidates=[]), {"T1": "pending"}),
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.InputsInputTest tests.test_guild.BoardContractTest -v`
Expected: FAIL（`inputs` の入力が「入力が不正です」で拒否される）

- [ ] **Step 3: 実装する**

`skills/quest/guild.py` の `apply_dates` の直後に、次を足す。

```python
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
```

`apply_input` の1行目を `def apply_input(plan, data, tr, qdir=None):` にする。`if kind == "due":` の枝（`apply_dates(plan, data)` と `return`）の直後に、次を足す。

```python
    if kind == "inputs":
        if plan.get("accepted"):
            raise GuildError("受け取り済みの依頼のインプットは変えられません")
        apply_inputs(plan, data, gdir_of(qdir) if qdir is not None else None)
        return
```

`ingest` の `apply_input(plan, data, tr)` を、次に置き換える。

```python
                apply_input(plan, data, tr, Path(plan_path).parent)
```

先頭の docstring の `入力（inbox の JSON）の type の1つに due（…）がある。` の行を、次に置き換える。

```
入力（inbox の JSON）の type には、due（依頼の開始日・締切、Todo の予定日・締切の設定。Todo の締切だけ解除できる）と、inputs（このクエストのインプットの追加・外す。足す名前は guild/inputs/ にあること）がある。
```

- [ ] **Step 4: エンジンのテストが通ることを確かめる**

Run: `python -m unittest tests.test_guild.InputsInputTest tests.test_guild.BoardContractTest tests.test_guild.IngestTest tests.test_guild.DueTest -v` → PASS。

- [ ] **Step 5: エンジンの区切りでコミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "入力 inputs を足す：このクエストのインプットを、承認の前後に追加・外す（中止・見直し中・受け取り後は拒否）"
```

- [ ] **Step 6: 指示書・docs の失敗するテストを書く**（`DocsContractTest` の末尾、`test_readme_matches_the_new_layout` の後に追加）

```python
    def test_live_docs_have_no_template(self):
        files = ["README.md", "skills/quest/SKILL.md", "docs/graph-format.md", "docs/archive-spec.md", "docs/spec.md"]
        files += ["agents/" + p.name for p in (ROOT / "agents").glob("*.md")]
        for f in files:
            s = self.read(*f.split("/"))
            for gone in ("template", "テンプレート", "templates/"):
                self.assertNotIn(gone, s, f"{f} に {gone} が残っている")

    def test_cartographer_selects_inputs_with_reasons(self):
        s = self.read("agents", "cartographer.md")
        for needle in ("`inputs-list` の出力", "**`guild/inputs/` にない名前を書かない**", "\"candidates\": [", "中身は読んでいない",
                       "依頼主が外したファイルを、もう一度 `inputs` に書かない"):
            self.assertIn(needle, s)

    def test_roles_read_the_plan_inputs(self):
        for name in ("adventurer.md", "appraiser.md", "scout.md"):
            s = self.read("agents", name)
            self.assertIn("`plan.json` の `inputs`", s, name)
            self.assertIn("`guild/inputs/<name>`", s, name)
        self.assertIn("\"inputs\": [\"KGI定義.md\"]", self.read("agents", "librarian.md"))

    def test_quest_skill_passes_inputs_list_to_the_cartographer(self):
        s = self.read("skills", "quest", "SKILL.md")
        for needle in ("inputs-list <root> --text", "ファイルに保存せず、チャットにも書かない", "`.work/requests/rejected/`", "`guild/inputs/<name>`"):
            self.assertIn(needle, s)

    def test_graph_format_and_archive_spec_document_inputs(self):
        g = self.read("docs", "graph-format.md")
        for needle in ("inputs-list <root> [--text 依頼文]", '{"name": "KGI定義.md", "source": "user", "reason": "依頼主の指定"}',
                       '{"type": "inputs", "add": [名前…], "remove": [名前…]}', ".work/requests/rejected/", "\"candidates\": ["):
            self.assertIn(needle, g)
        a = self.read("docs", "archive-spec.md")
        for needle in ("## インプットへの紐づけ", "存在は検査しない", "書庫の用語『KGI』→ このファイル"):
            self.assertIn(needle, a)
```

Run: `python -m unittest tests.test_guild.DocsContractTest -v`
Expected: 新しい5件が FAIL（ほかは PASS）

- [ ] **Step 7: 地図師の指示書（`agents/cartographer.md`）を直す**

3行目（`description:`）を次に置き換える。

```
description: guild の地図師。依頼を Todo に分解し、使うインプットを理由つきで選び、前提関係・種別（auto/human）・確認の印・合格基準を決めて reports/plan-draft.json に書く。曖昧な点は「聞くべきこと」として返す。ギルドマスターが、新しい依頼の分解のときに呼ぶ。
```

「受け取るもの」の次の3行を、

```
- 納品物のテンプレート（依頼の `template`。`templates/` の中のファイルへのパス。なければなし）
  - テンプレートは Markdown（`.md`）だけ。
  - あれば `Read` で読み、まとめの Todo の合格基準に「テンプレートの見出し・順序に沿っている」を入れ、`plan-draft.json` の `template` にそのパスを書き写す。
```

次の2行に置き換える。

```
- 依頼主が指定したインプット（`request.json` の `inputs`。`guild/inputs/` のファイル名）
- `inputs-list` の出力（`guild/inputs/` のファイルごとの `name`・`ext`・`size`・`updated`・`head`（文字のファイルの先頭5行）・`hints`（書庫の項目からの手がかり）。ヒントのあるファイルが先頭に並ぶ）
```

「やること」の `2. 依頼を Todo に分ける。` を `3. 依頼を Todo に分ける。` に、`3. 各 Todo に次を決める。` を `4. 各 Todo に次を決める。` に、`4. 依頼の中身が、推測で埋めるしかないほど曖昧なら、` を `5. 依頼の中身が、推測で埋めるしかないほど曖昧なら、` に変え、`1. 書庫（…）` の項目の直後に、次を挿入する。

```markdown
2. この依頼で使うインプットを選び、`plan-draft.json` の `inputs` と `candidates` に書く。
   - 材料は、依頼文と `inputs-list` の出力。`hints` のあるファイルは、依頼文の語と書庫の項目が一致したもので、強い手がかりにする。ただし、ヒントだけで決めず、依頼文との関係を確かめてから選ぶ。
   - 文字のファイル（`.md` `.txt` `.csv`）は、先頭の行で分からなければ、`guild/inputs/<名前>` を `Read` で全文読んでよい。
   - 中身を読めないファイル（PDF・Excel・Word・PowerPoint・画像）は、名前・更新日・依頼文との対応から選び、`reason` に「中身は読んでいない。名前と更新日から判断」のように、その旨を書く。
   - 関係があると言い切れるものだけを `inputs` に入れる。迷うものは選ばず、理由をつけて `candidates` に入れる（依頼主が、承認の前に「追加」で入れられる）。関係のないものは、どちらにも書かない。
   - 依頼主が指定したインプットは、`guild.py` が必ず入れるので、書かなくてよい。
   - **`guild/inputs/` にない名前を書かない**（`inputs-list` の `name` を、そのまま書き写す）。ない名前があると、`adopt` が拒否して差し戻しになる。
   - 計画の作り直しのときは、計画の `inputs` は、依頼主の追加・外すを含めて引き継がれる。依頼主が外したファイルを、もう一度 `inputs` に書かない。
   - 依頼文が、あるインプットを納品物の型（見出しの並びなど）として使うよう求めているときは、まとめの Todo の合格基準に「`guild/inputs/<名前>` の見出しと順序に沿っている」を入れる。
```

「出力」の JSON の例の次の行を、

```
  "template": "templates/週次報告.md",
```

次に置き換える。

```
  "inputs": [
    {"name": "売上_2026Q3.csv", "reason": "依頼の KGI の元データ（書庫の用語『KGI』のヒント。先頭の行に月別の売上がある）"}
  ],
  "candidates": [
    {"name": "提案書_2025.pptx", "reason": "昨年の提案書。中身は読んでいない。名前からは今回の比較に使うか分からない"}
  ],
```

「出力」の注の次の行を、

```
- `template` は、依頼にテンプレートの指定があるときだけ書く（なければ、この行ごと書かない）。
```

次に置き換える。

```
- `inputs`・`candidates` の各要素は、`name`（`guild/inputs/` のファイル名）と `reason`（理由。1行）だけ。なければ `[]`。`source` は書かない（`guild.py` が付ける）。
```

- [ ] **Step 8: 司書・冒険者・鑑定士・斥候の指示書を直す**

`agents/librarian.md` の `- `source`：…` の行の次に、次の1行を足す。

```
- `inputs`（任意）：候補が `guild/inputs/` のファイルから分かったこと（例：用語の定義が書かれた資料）なら、そのファイル名を `"inputs": ["KGI定義.md"]` のように書く。次の依頼で、依頼文にこの項目の名前が出てきたとき、そのファイルが地図師に勧められる。ファイル名は `plan.json` の `inputs` の `name` を書き写す（作らない）。
```

`agents/adventurer.md` の「やること」の1の、書庫の行（`書庫（`guild/archive/`）の `index.md` を見て、…`）の次に、次の行を足す（行頭は3つの空白）。

```
   `plan.json` の `inputs`（この依頼のインプット。ファイルは `guild/inputs/<name>`）のうち、この Todo に関係するものを読んで使う（`source` が `user` は依頼主の指定、`auto` は地図師の選択。`reason` に選んだ理由がある）。読めない形式のファイルは、読めなかったことを報告の「未確認」に書く。使ったファイルは、報告の「根拠・出典」に `guild/inputs/<name>` の形で書く。
```

同じファイルの次の行を、

```
   - `plan.json` に `template`（`guild/` からのパス）があるときは、それを読み、**見出しとその順序に沿って**書く（見出しを足したり、省いたりしない。埋められない項目は、書かずに「未確認」と書く）。
```

次に置き換える。

```
   - 合格基準か依頼文が、あるインプットを納品物の型（見出しの並びなど）として使うよう求めているときは、そのファイルを読み、**見出しとその順序に沿って**書く（見出しを足したり、省いたりしない。埋められない項目は、書かずに「未確認」と書く）。
```

`agents/appraiser.md` の「やること」の1の行（`1. 報告と成果物を読む。…`）の次に、次の行を足す。

```
   `plan.json` の `inputs`（この依頼のインプット。ファイルは `guild/inputs/<name>`）は、成果物の主張の出典がそのファイルのときに読んで照合する。合格基準が、あるインプットの見出しと順序に沿うことを求めているときは、そのファイルと見比べる。
```

`agents/scout.md` の「やること」の1の、書庫の行の次に、次の行を足す。

```
   `plan.json` の `inputs`（この依頼のインプット。ファイルは `guild/inputs/<name>`）に、この Todo に関係するもの（読むページの一覧など）があれば読む。
```

- [ ] **Step 9: ギルドマスターの指示書（`skills/quest/SKILL.md`）を直す**

「1. 受付」の `- **ボードから**：…` の行全体を、次に置き換える。

```
- **ボードから**：`guild.py requests <root>` で受付待ちの依頼を一覧し、**全部を受け付ける**（どれを受け付けるかは聞かない）。古い順に、依頼ごとに `guild.py new <root> <依頼のID>` で依頼のフォルダを作る。依頼文は `text`。インプットは、既存から選んだもの（`inputs`）とアップロードしたもの（`files`）。アップロードは共通の `guild/inputs/` に1つだけ置かれ（同名で内容が違えば上書き）、依頼の `request.json` の `inputs` に、選んだものとアップロードしたものの名前が入る。選んだインプットが `guild/inputs/` から消されていると、`new` は依頼を拒否して `.work/requests/rejected/` に移す（エラーの文をチャットで短く伝え、ボードの「＋ 新規」から出し直してもらう）。開始日は `start`、締切は `due`（未指定は、開始日が登録日、締切が開始日）。
```

「2. 分解」の手順1の、次の2行を、

```
1. 地図師を呼ぶ（`subagent_type: guild:cartographer`）。メッセージに次を書く。
   - 依頼文（`<dir>/request.json`）、素材（`request.json` の `inputs` のファイル名を `guild/inputs/<ファイル名>` で）
```

次に置き換える。

```
1. 地図師を呼ぶ前に、`<python> "${CLAUDE_SKILL_DIR}/guild.py" inputs-list <root> --text "<依頼文>"` を実行する（`<依頼文>` は `request.json` の `text`。聞き取りの回答があれば、続けて足す）。出力は、`guild/inputs/` のファイルの一覧と、書庫の項目からのヒント。
2. 地図師を呼ぶ（`subagent_type: guild:cartographer`）。メッセージに次を書く。
   - 依頼文（`<dir>/request.json`）と、依頼主が指定したインプット（`request.json` の `inputs`）
   - `inputs-list` の出力（JSON）を、そのまま。**ファイルに保存せず、チャットにも書かない**（ファイルの先頭の行に秘密が含まれうるため、地図師にだけ渡す）
```

同じ手順の次の1行を削除する。

```
   - テンプレート（`template`。あれば `guild/` からのパスを、そのまま渡す。テンプレートは Markdown だけ）
```

「2. 分解」の以降の番号を1つずつ繰り下げる（`2. `plan-draft.json` を読む。` → `3.`、`3. 質問への回答が届いたら` → `4.`（中の「手順1へ」はそのまま。回答を足して `inputs-list` からやり直す）、`4. 「計画を直す」が届いたら` → `5.`）。番号を指す箇所も合わせて直す：地図師へのメッセージの `その内容（下の3・4）` → `その内容（下の4・5）`、「4. 実行ループ」の `手順2の3へ` → `手順2の4へ`、`手順2の4で地図師を呼んでいる最中` → `手順2の5で地図師を呼んでいる最中`。`3.`（旧2）の `検査に落ちたら、エラーを添えて地図師に差し戻す（2回まで）。` を、次に置き換える。

```
検査に落ちたら（`inputs`・`candidates` の名前が `guild/inputs/` にない、など）、エラーを添えて地図師に差し戻す（2回まで）。
```

`5.`（旧4）の `- `adopt` は `replan` のときだけ上書きできる。…` の行の次に、次の行を足す。

```
   - 計画の `inputs` は、依頼主の追加・外すを含めて引き継がれる（`adopt` が決める。依頼主が外したものは、地図師が選び直しても戻らない）。
```

「3. 承認」の段落の末尾に、次の文を足す。

```
承認の手紙と、ボードの「インプット」タブには、選ばれたインプットが「指定」「自動（理由つき）」の印つきで出る。依頼主が追加・外すをすると、`inputs` の入力が `inbox/` に届くので、`guild.py ingest <plan>` で反映する（承認の前でも後でも）。
```

「4. 実行ループ」の表（`| グループ | 対応 |` の表）の直後、`**納品物を置く**` の段落の前に、次の段落を足す。

```
   冒険者・斥候・鑑定士へのメッセージには、`plan.json` の `inputs` のファイルを `guild/inputs/<name>` の形で並べて書く（`source` と `reason` も添える）。各役は、その Todo に関係するものだけ読む。
```

- [ ] **Step 10: docs を直す**

`docs/graph-format.md` の `plan.json` の例の `"approved": false,` の次に、次を挿入する。

```
  "inputs": [
    {"name": "KGI定義.md", "source": "user", "reason": "依頼主の指定"},
    {"name": "売上_2026Q3.csv", "source": "auto", "reason": "KGI の元データ（書庫の用語『KGI』のヒント）"}
  ],
  "candidates": [
    {"name": "提案書_2025.pptx", "reason": "中身は読んでいない。名前からは関係が分からない"}
  ],
```

同じファイルの `deliverable: true` の行の中の、次の文を削除する。

```
`template` は納品物のテンプレート（`guild/templates/` の中のファイルのパス。あれば `adopt` が存在と形式を検査する。テンプレートは Markdown（`.md`）だけ）。
```

`deliverable: true` の行の次に、次の行を足す。

```
- `inputs` は、この依頼で使うインプット（`guild/inputs/` のファイル名）。`source` が `user` は依頼主の指定（「＋ 新規」で選んだ・アップロードした。`request.json` の `inputs`）、`auto` は地図師の選択。`reason` は理由。`user` が先頭。`candidates` は、地図師が迷って選ばなかったもの（理由つき）。名前は `inputs` と `candidates` をまたいで重ならない。冒険者・斥候・鑑定士は、`inputs` のファイルを `guild/inputs/<name>` で読む。納品物の型（見出しの並びなど）は、インプットに付けて依頼文で伝える。
  - `adopt` は、地図師が書いた名前（`plan-draft.json` の `inputs`・`candidates`。各要素は `name` と `reason`）が `guild/inputs/` にあるかを検査する。`replan` のときは、旧計画の `inputs`（依頼主の追加・外すを反映済み）を引き継ぎ、依頼主が外したままの名前は足さない。
  - ボードの `inputs` の入力で、足す・外すができる（承認前でも、進行中でも可。中止・見直し中・受け取り後は拒否）。足す名前は `guild/inputs/` にあること、外す名前は `inputs` にあること。足したものは `source` が `user`、`reason` が「依頼主が追加」になり、`candidates` から除かれる。履歴には `{event: "inputs", add, remove}` を残す（`id` は付けない）。
```

コマンドの表の `new` の行を、次に置き換える。

```
| `new <root> [依頼のID]` | 次の依頼のフォルダ（`guild/.work/Q001…`。出力の `dir`）を作る。ID を渡すと、受付待ちの依頼を取り込み、アップロードを共通の `guild/inputs/` に置く。依頼の `inputs`（既存から選んだ名前）が `guild/inputs/` になければ拒否し、依頼を `.work/requests/rejected/`（理由は `<ID>.json.reason.txt`）へ移す（番号は進まない）。`request.json` の `inputs` は、選んだ名前とアップロードの名前を合わせたもの |
```

`new` の行の次に、次の行を足す。

```
| `inputs-list <root> [--text 依頼文]` | `guild/inputs/` のファイルごとに `name`・`ext`・`size`・`updated`・`head`（`.md` `.txt` `.csv` の先頭5行。ほかは `null`）・`hints` を返す。`hints` は、依頼文に名前・別名が出てくる書庫の項目（確認済みか出典ありで、使われているもの。3文字以上の語だけ。心得は除く）の `inputs` に挙がったファイルと、ファイル名・先頭の行にその語が出てくるファイルに付く理由。ヒントのあるファイルが先。地図師にだけ渡す |
```

`adopt` の行と `validate` の行を、それぞれ次に置き換える。

```
| `adopt <plan.json>` | 同じフォルダの `reports/plan-draft.json` を検査（`validate` と同じ検査に加えて、`inputs`・`candidates` の名前が `guild/inputs/` にあるか）し、承認前の `plan.json` にする（`inputs` は依頼主の指定が先頭、`candidates` は選ばなかった候補）。すでにあれば上書きしない（`status` が `replan` のときだけ、完了済みの Todo と、依頼主が直した `inputs` を引き継いで置き換える） |
| `validate <plan.json>` | `deps` の参照切れ、循環、`kind`・`criteria` の欠け、未知の `state`、`human` の `confirm`、`inputs`・`candidates` の形の誤り（名前・`source`・`reason`・重なり）を検出する |
```

「入力ファイルの種類」の行（`  - 入力ファイルの種類: …`）全体を、次に置き換える。

```
  - 入力ファイルの種類: `approve`（計画の承認）、`accept`（全 Todo が済んだあとの、納品物の受け取り。済んでいないとき・受け取り済みのときは拒否）、`confirm`（実行前の確認：実行する／しない）、`result`（`human` の結果：できた／できなかった、添付パス）、`decision`（`failed` 時の判断 `skip`・`drop`、計画の作り直し `replan`、中止 `abort`）、`due`（日付の設定。`todo` を付けると Todo の `scheduled`・`due`、付けないと依頼の `start`・`due`。`due` の解除は Todo の締切だけ）、`inputs`（`{"type": "inputs", "add": [名前…], "remove": [名前…]}`。このクエストのインプットを足す・外す）。
```

`docs/archive-spec.md` の「1 項目 1 ファイル。先頭の見出し情報：…」の行を、次に置き換える。

```
1 項目 1 ファイル。先頭の見出し情報：`name` / `type` / `aliases` / `inputs`（関係する `guild/inputs/` のファイル名のリスト。任意）/ `confidence` / `source` / `confirmed`（確認日）/ `status`（有効・廃止）。
```

「## 種類の付け替え」の節の後（「## ボード（タブ名「書庫」）」の前）に、次の節を足す。

```markdown
## インプットへの紐づけ
項目の `inputs` に、その項目に関係する `guild/inputs/` のファイル名を並べられる（`aliases` と同じリストの見出し情報）。依頼主はボードの書庫の登録・編集欄で付け、司書は候補（`archive-draft.json`）に任意で書く（依頼主の確認を通って登録される。更新の候補では、既存の `inputs` に足される）。名前の形だけを検査し、存在は検査しない（ファイルの上書き・削除で外れても、項目は壊れない）。索引にも載る。

`guild.py inputs-list <root> --text <依頼文>` は、依頼文に名前・別名が出てくる項目（確認済みか出典ありで、使われているもの。3文字以上の語だけ。心得は除く）の `inputs` のファイルに、ヒント「書庫の用語『KGI』→ このファイル」を付けて先頭に並べる。地図師は、これを手がかりにインプットを選ぶ。
```

`docs/spec.md` の26行目の `・共通のインプット（`inputs/`）・テンプレート（`templates/`）を置き` を `・共通のインプット（`inputs/`）を置き` に置き換える。44行目（`13. 依頼主は、納品物のテンプレートを…`）を、次に置き換える。

```
13. 依頼主は、依頼を出すときに、共通のインプット（`guild/inputs/`）から既存のファイルを選べ、アップロードもできる。地図師は、依頼文と書庫のヒントから、関係するインプットを理由つきで選ぶ。依頼主は、承認の前後に追加・外すで直せる。納品物の型は、インプットに付けて依頼文で伝える。
```

- [ ] **Step 11: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.DocsContractTest -v` → PASS。続けて `TEST` が全部通ること（`test_agents_use_work_paths`・`test_live_docs_have_no_old_layout_terms` も通ること）。`docs/board-design.md` の「冒険の書」「テンプレート」は Task 13 で直す（この Task のテストの対象外）。

- [ ] **Step 12: コミット**

```bash
git add agents/ skills/quest/SKILL.md docs/graph-format.md docs/archive-spec.md docs/spec.md tests/test_guild.py
git commit -m "指示書と docs をインプットの選択に合わせる（inputs-list・plan の inputs/candidates・入力 inputs・書庫の inputs）。テンプレートの記述を消す"
```

---

---

<!-- Part B（ボード：Task 6〜12）。Part A（ヘッダー・Global Constraints・Task 1〜5）と Task 13 とあわせて、1つの計画にまとめる。 -->

## Review Focus（ボード）

- **`localStorage` が使えない**（プライベートウィンドウ・`file://` の制限・例外を投げる環境）：一覧の表示・隠す（`guild.board.listOpen`）とクエスト進捗の選択（`guild.progress.sel`）が既定値で動き、例外で画面が止まらない。`lsGet`・`lsSet` は必ず `try/catch`。→ Task 7（`lsGet`/`lsSet` と `listOpen`）、Task 11（`progLoad`・`progEffective` と、`localStorage` を例外にした `browser_evaluate`）
- **件数が多い**（クエスト 100〜200 件、`guild/inputs/` 200 件）：一覧・「既存から選ぶ」・「表示するクエスト」が、描画ごとに O(n²) にならない（`Set` で引く）。一覧は内側でスクロールする。→ Task 7（一覧）、Task 10（200 件のインプット）、Task 11（100 件の性能確認）
- **狭い画面（760px 未満）**：一覧と詳細を同時に出さず、`S.pane` で切り替え、「一覧を隠す」は出さない。隠した状態と重なっても、一覧に戻れる。→ Task 7（CSS とブラウザの確認）
- **日付の入力が不正・空**：空は「変えない」（Todo の締切だけは解除）、`input[type=date]` が返す `''` を送らない、`okDate` を通らない日付でガントが壊れない。矛盾は警告だけで送れる。→ Task 9（`dateRange`・`qGanttModel` の `browser_evaluate` と、送った JSON の確認）
- **`inbox/` の JSON の形の後戻り**：手紙・日付・インプット・依頼の入力が、`guild.py` の受け取る形のまま（`BoardContractTest` の `test_every_input_the_board_writes_is_accepted` と `test_board_source_writes_the_same_shapes`）。ポップオーバー（`Esc`・矢印キー・外側のクリック）とダイアログ（`Esc`・`Tab` の循環）でフォーカスを失わない。消したコード・CSS（冒険の書、テンプレート、台帳 `.ledger`/`.lr`、目次 `questToc`）が残らない。→ 各 Task の契約テスト、Task 10（ダイアログ）、Task 11（ポップオーバー）、Task 12（使われていない CSS の洗い出し）

> ボードの Task 共通：テストは `tests/test_guild.py` の `BoardPathsTest` の末尾（`class DocsContractTest(unittest.TestCase):` の直前）に足す。画面の確認は Playwright MCP で `file:///<プロジェクトのフォルダ>/skills/quest/board.html?demo=…` を開いて行い、毎回 `browser_console_messages`（`onlyErrors: true` 相当。エラーの件数）で **エラーが 0 件** であることを確かめる。ボードの変更は Edit ツールで行い、`old_string` には下に示す「今の行」をそのまま使う（前の Task で変わった箇所は、その Task の新しい行が今の行になる）。

---

### Task 6: ボード — 冒険の書・テンプレートを画面から消し、データ層を新しい形にする

**Files:**
- Modify: `skills/quest/board.html`（CSS の `.qtag`・`.msg`〜`.bub a`・`.trow`、`PathMap` のコメント、`parseEntry`、`S`、`loadAll`、`planList` の追加、`derive`、`buildModel`、`roleOf`・`messagesOf` の削除、`composer`、`jumpQuest`・`ledger`・`questToc` の `S.tq`、`talkTab` の削除、`delivTab`、`render`、`obsidianTab`、`sendRequest`、`refresh`、`demoTree`）
- Test: `tests/test_guild.py`（`BoardPathsTest` に `test_no_adventure_book_or_templates` を追加）

**Interfaces:**
- Consumes: Task 1（`plan.json` に `template` がない、`templates/` がない）、Task 2（書庫の項目の `inputs`：JSON の配列）、Task 4（`plan.json` の `inputs: [{name, source, reason}]`・`candidates: [{name, reason}]`、依頼の `start`・`inputs`）、Task 5（入力 `{type: 'inputs', add, remove}`）
- Produces（Task 7〜12 が使う）：
  - タブ：`[['board', 'クエスト掲示板'], ['prog', 'クエスト進捗'], ['deliv', '納品物'], ['know', '書庫'], ['web', …], ['obs', 'Obsidian'], ['help', 'ヘルプ']]`（キー `board` は変えない）。`talk` はない。
  - `S.model.inputs`：`[{ name, mtime }]`（`guild/inputs/` の直下のファイル。名前順。`mtime` はミリ秒、なければ 0）。`S.model.templates` はない。
  - `S.model.requests[i]`：`{ id, text, start, due, inputs, files, created }`（`template` はない）。
  - `S.model.quests[i].inputs`・`.candidates`：`planList(plan, 'inputs')`・`planList(plan, 'candidates')`（計画がない・古い計画は `[]`）。
  - `S.model.quests[i].q.inbox[j]`：`{ type, todo, choice, qs, due, add, remove }`（`add`・`remove` は入力 `inputs` の配列。ほかの入力は `null`）。
  - 書庫の項目（`parseEntry` の結果）：`e.inputs`（文字列の配列。ない・壊れているときは `[]`）。
  - `openReport(q, path)` は残す（Task 8 が道のりの行から使う）。`S.tq`・`S.role`・`S.msgKey`・`S.limit.msg` はない。

- [ ] **Step 1: 失敗するテストを書く**（`BoardPathsTest` の末尾、`class DocsContractTest(unittest.TestCase):` の直前に足す）

```python
    def test_no_adventure_book_or_templates(self):
        for gone in ("function talkTab(", "function messagesOf(", "function roleOf(", "['talk'", "'冒険の書'", "S.tq", "S.role", "msgKey",
                     "templates", "tplSel", "new:template", "newtpl", "template:", ".bub{", ".qtag{"):
            self.assertNotIn(gone, self.board)
        for needle in ("['board', 'クエスト掲示板']", "function openReport(", "e.inputs = (Array.isArray(e.inputs)",
                       "candidates: planList(p, 'candidates')", "mtime: e.mtime || 0"):
            self.assertIn(needle, self.board)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest -v`
Expected: `test_no_adventure_book_or_templates` が FAIL（`function talkTab(` がある）。ほかは PASS。

- [ ] **Step 3: CSS とコメントから、冒険の書・テンプレートの名残を消す**

`<style>` の次の1行を削除する。

```css
.qtag{font-family:'JetBrains Mono',Consolas,'Courier New',monospace;font-size:11.5px;background:var(--ink);color:var(--paper);border-radius:3px;padding:0 6px;margin-right:8px}
```

`<style>` の次の8行（吹き出し。冒険の書だけが使う）を削除する。

```css
.msg{display:flex;gap:12px;margin-bottom:12px}
.who{flex:none;width:70px;text-align:center;font-size:11.5px;color:var(--sub);line-height:1.3}
.av{display:flex;width:42px;height:42px;margin:0 auto 4px;border-radius:50%;align-items:center;justify-content:center;font-weight:800;font-family:'Shippori Mincho B1','Yu Mincho','Hiragino Mincho ProN','Noto Serif JP',serif;font-size:16px;color:#fff}
.av.gm{background:#3D4A5C}.av.cart{background:#4F6A70}.av.adv{background:#6B5A3E}.av.app{background:#5B4A6B}.av.me{background:var(--warn)}
.bub{flex:1 1 auto;min-width:0;background:var(--surface);border:1px solid var(--line);border-radius:4px 14px 14px 14px;padding:8px 16px}
.bub time{display:block;font-size:11.5px;color:var(--sub)}
.bub p{margin:0}
.bub a{font-size:12.5px;color:var(--gold)}
```

テンプレートの選択欄だけが使っていた `.trow` を消す。次の1行を削除し、

```css
.trow .ff{flex:1 1 300px}
```

次の1行を、

```css
.fld.wide{grid-column:1/-1}.trow{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center}.trow select{min-width:240px}
```

次に置き換える。

```css
.fld.wide{grid-column:1/-1}
```

`PathMap` の上のコメントの次の行を、

```js
// 機械用のファイルは guild/.work/ にある（Obsidian に出ない）。archive/ の項目、deliverables/、inputs/、templates/ はそのまま。
```

次に置き換える。

```js
// 機械用のファイルは guild/.work/ にある（Obsidian に出ない）。archive/ の項目、deliverables/、inputs/ はそのまま。
```

- [ ] **Step 4: 書庫の項目の `inputs` を読む**（`parseEntry`）

次の行の直後に、

```js
  e.aliases = (Array.isArray(e.aliases) ? e.aliases : []).map((x) => String(x).trim()).filter(Boolean);
```

次の1行を足す。

```js
  e.inputs = (Array.isArray(e.inputs) ? e.inputs : []).map((x) => String(x).trim()).filter(Boolean);  // 関係するインプットの名前。aliases と同じ形（ない古い項目は空）
```

- [ ] **Step 5: 状態と読み込みを直す**（`S`・`loadAll`）

`S` の次の行を、

```js
  tab: 'board', sel: null, openQ: {}, openInit: false, tq: null, role: 'all', stf: { board: {} }, kn: { cur: null }, limit: { board: 20, msg: 50 }, msgKey: '',
```

次に置き換える。

```js
  tab: 'board', sel: null, openQ: {}, openInit: false, stf: { board: {} }, kn: { cur: null }, limit: { board: 20 },
```

`loadAll` の次の行を、

```js
      if (r) requests.push({ id: e.name.slice(0, -5), text: r.text || '', due: r.due || null, files: r.files || [], created: r.created || '', template: r.template || null });
```

次に置き換える。

```js
      if (r) requests.push({ id: e.name.slice(0, -5), text: r.text || '', start: r.start || null, due: r.due || null, inputs: Array.isArray(r.inputs) ? r.inputs : [], files: r.files || [], created: r.created || '' });
```

`loadAll` の `inbox` の次の行を、

```js
      if (f.kind === 'file' && f.name.endsWith('.json')) { const j = await readJSON(`${q}/inbox/${f.name}`); if (j) inbox.push({ type: j.type, todo: j.todo || null, choice: j.choice || null, qs: null, due: j.due === undefined ? undefined : j.due }); }
```

次に置き換える（入力 `inputs` の反映待ちを、Task 10 が `add`・`remove` で見分ける）。

```js
      if (f.kind === 'file' && f.name.endsWith('.json')) { const j = await readJSON(`${q}/inbox/${f.name}`); if (j) inbox.push({ type: j.type, todo: j.todo || null, choice: j.choice || null, qs: null, due: j.due === undefined ? undefined : j.due, add: Array.isArray(j.add) ? j.add : null, remove: Array.isArray(j.remove) ? j.remove : null }); }
```

`loadAll` の末尾の次の3行を、

```js
  const templates = (await S.fs.list('templates')).filter((e) => e.kind === 'file').map((e) => e.name).sort();
  const inputs = (await S.fs.list('inputs')).filter((e) => e.kind === 'file').map((e) => e.name).sort();
  return { requests, quests, archive, archiveWait, archiveRejected, web, templates: templates.filter((n) => n.toLowerCase().endsWith('.md')), inputs, root: (cfg && cfg.root) || '' };
```

次に置き換える。

```js
  // 共通のインプット（guild/inputs/ の直下だけ。サブフォルダは見ない）。名前の同一判定は、大文字小文字を区別しない（guild.py と同じ）
  const inputs = (await S.fs.list('inputs')).filter((e) => e.kind === 'file').map((e) => ({ name: e.name, mtime: e.mtime || 0 })).sort((a, b) => a.name.localeCompare(b.name));
  return { requests, quests, archive, archiveWait, archiveRejected, web, inputs, root: (cfg && cfg.root) || '' };
```

- [ ] **Step 6: モデルに、計画のインプットと候補を持たせる**（`derive`・`buildModel`）

`function derive(q) {` の直前に、次を足す。

```js
// 計画のインプット（inputs: [{name, source, reason}]）と候補（candidates: [{name, reason}]）。ない古い計画・壊れた要素は除く
const planList = (p, k) => (p && Array.isArray(p[k]) ? p[k].filter((x) => x && typeof x.name === 'string' && x.name) : []);
```

`derive` の次の行を、

```js
  const d = { id: q.id, title, asks: [], info: null, todos: [], done: 0, total: 0, finished: false, label: '', cls: '', me: '—', q };
```

次に置き換える。

```js
  const d = { id: q.id, title, asks: [], info: null, todos: [], done: 0, total: 0, finished: false, label: '', cls: '', me: '—', q, inputs: planList(p, 'inputs'), candidates: planList(p, 'candidates') };
```

`buildModel` の次の部分を、

```js
templates: raw.templates, inputs: raw.inputs || [],
```

次に置き換える。

```js
inputs: raw.inputs || [],
```

- [ ] **Step 7: 冒険の書のコードを消す**

`// ---- 会話の材料と、タイムラインの帯` の行から、`messagesOf` の終わり（`  return out;` と `}` の2行。次の行が空行で、その次が `const BARKIND = {`）までを、次の1行に置き換える（`roleOf`・`messagesOf` を丸ごと消す。`BARKIND`・`ganttOf` はタイムラインで使うので、Task 8 まで残す）。

```js
// ---- タイムラインの帯
```

`function talkTab() {` から、その関数の終わりの `}`（次の行が空行で、その次が `function searchBox(key, placeholder) {`）までを、丸ごと削除する。

`jumpQuest` の次の行を、

```js
  S.openQ[id] = true; S.sel = id; S.tq = id; S.focusQ = id; render();
```

次に置き換える。

```js
  S.openQ[id] = true; S.sel = id; S.focusQ = id; render();
```

`ledger` の行のボタンの `onclick` の中の `S.sel = qd.id; S.tq = qd.id; render();` を `S.sel = qd.id; render();` に置き換える。

`questToc` の上のコメントの次の行を、

```js
// 依頼の目次。掲示板は押した依頼へ飛び、冒険の書は押した依頼のやりとりに切り替える（pick・cur・allLabel で指定）
```

次に置き換える（`questToc` は Task 7 で消す）。

```js
// 依頼の目次。押した依頼へ飛ぶ
```

`refresh` の次の1行を削除する。

```js
      if (!S.tq || (S.tq !== 'all' && !ids.includes(S.tq))) S.tq = S.sel;
```

`render` の次の2行を、

```js
  const tabs = [['board', '掲示板'], ['prog', 'クエスト進捗'], ['deliv', '納品物'], ['know', '書庫'], ['talk', '冒険の書'], ['web', S.model && S.model.web.pending.length && !S.model.web.wait ? `外部サイト（${S.model.web.pending.length}）` : '外部サイト'], ['obs', 'Obsidian'], ['help', 'ヘルプ']];
  const body = { board: boardTab, prog: progressTab, deliv: delivTab, know: knowTab, talk: talkTab, web: webTab, obs: obsidianTab, help: helpTab }[S.tab]();
```

次に置き換える。

```js
  const tabs = [['board', 'クエスト掲示板'], ['prog', 'クエスト進捗'], ['deliv', '納品物'], ['know', '書庫'], ['web', S.model && S.model.web.pending.length && !S.model.web.wait ? `外部サイト（${S.model.web.pending.length}）` : '外部サイト'], ['obs', 'Obsidian'], ['help', 'ヘルプ']];
  const body = { board: boardTab, prog: progressTab, deliv: delivTab, know: knowTab, web: webTab, obs: obsidianTab, help: helpTab }[S.tab]();
```

- [ ] **Step 8: テンプレートの画面・読み込み・送信・見本を消す**

`composer` の次の7行を、

```js
  const tplSel = h('select', { 'aria-label': '納品物のテンプレート' }, h('option', { value: '' }, 'なし'), ((S.model && S.model.templates) || []).map((n) => h('option', { value: 'templates/' + n }, n)));
  tplSel.value = S.form['new:template'] || ''; bindKey(tplSel, 'new:template');
  const more = h('details', { class: 'qmore', open: !!S.open.qmore }, h('summary', null, '素材ファイル・テンプレートをつける（任意）'),
    h('div', { class: 'qopts' },
      h('div', { class: 'fld wide' }, h('span', { class: 'cap' }, '素材ファイル'), fileField('new', '素材ファイル', true)),
      h('div', { class: 'fld wide' }, h('span', { class: 'cap' }, '納品物のテンプレート'), h('div', { class: 'trow' }, tplSel, h('span', { class: 'fine' }, 'または、新しく追加：'), fileField('newtpl', 'テンプレートを追加', false)),
        h('span', { class: 'fine' }, 'Markdown（.md）のテンプレートだけ追加できます。'))));
```

次の3行に置き換える。

```js
  const more = h('details', { class: 'qmore', open: !!S.open.qmore }, h('summary', null, '素材ファイルをつける（任意）'),
    h('div', { class: 'qopts' },
      h('div', { class: 'fld wide' }, h('span', { class: 'cap' }, '素材ファイル'), fileField('new', '素材ファイル', true))));
```

`delivTab` の末尾の次の3行を削除する（`return out;` は残す）。

```js
  out.push(h('h3', { class: 'sec' }, 'テンプレート'), h('p', { class: 'sub', style: 'margin:0 0 8px' }, '納品物の型です。新しい依頼で選ぶと、納品物はこの型に沿ってまとめられます。追加は、「掲示板」の「新しい依頼」からできます。'));
  const tpls = (m.templates || []).filter((n) => hit(q, n));
  out.push(tpls.length ? h('ul', { class: 'flist' }, tpls.map((n) => [fileRow('templates/' + n, n)])) : h('p', { class: 'sub' }, 'テンプレートはまだありません。'));
```

`obsidianTab` のディレクトリ構成の配列から、要素 `'  templates/          納品物のテンプレート（.md）',` を1つ削除する（前後の要素はそのまま）。

`sendRequest` 全体（`async function sendRequest() {` から、その関数の終わりまで）を、次に置き換える（Task 10 で、インプットの選択とダイアログに合わせて、もう一度置き換える）。

```js
async function sendRequest() {
  const text = (S.form['new:text'] || '').trim();
  S.newError = ''; S.newSaved = ''; S.newNote = '';
  if (!text) { S.newError = '依頼の内容を書いてください。'; render(); return; }
  if (S.conn !== 'ok') { S.newError = '保存先につながっていません。上の「フォルダを選ぶ」から選んでください。'; render(); return; }
  const id = 'R' + stamp14(new Date()).replace(/^(\d{8})/, '$1-'), files = S.files.new || [], names = [];
  const start = S.form['new:start'] || localToday();
  try {
    for (const f of files) { await S.fs.writeBlob(`requests/files/${id}/${f.name}`, f); names.push(f.name); }
    await S.fs.writeText(`requests/${id}.json`, JSON.stringify({ type: 'request', text, start, due: S.form['new:due'] || null, files: names, created: new Date().toISOString() }, null, 2));
  } catch (e) { S.newError = `保存できませんでした（${e.name || 'エラー'}：${e.message || e}）。`; render(); return; }
  S.form['new:text'] = ''; S.form['new:due'] = ''; S.form['new:start'] = ''; S.files.new = []; S.newSaved = id;
  await refresh(true);
}
```

`demoTree` の返す木の先頭の次の部分を、

```js
'config.json': J({ python: 'python', root: 'C:\\Users\\demo\\project' }), templates: { '週次報告.md': T('# 週次報告 / ## 概要 / ## 結果 / ## 課題') }, archive: {
```

次に置き換える（`questions` の場面の `'config.json': …` は `templates` を持たないので、そのまま）。

```js
'config.json': J({ python: 'python', root: 'C:\\Users\\demo\\project' }), archive: {
```

- [ ] **Step 9: 消し残しがないことを確かめる**

Grep（`skills/quest/board.html`）で、次のどれも 0 件であること：`templates`、`talkTab`、`messagesOf`、`roleOf`、`S\.tq`、`S\.role`、`msgKey`、`limit\.msg`、`'冒険の書'`、`\.av\b`、`class: 'msg'`、`class: 'bub'`、`qtag`、`tplSel`、`newtpl`。`openReport` は定義が1件残っていること（使う側は Task 8 で足す）。

- [ ] **Step 10: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest tests.test_guild.BoardContractTest tests.test_guild.RoleModelsTest -v` → PASS。続けて `TEST` が全部通ること。

- [ ] **Step 11: ブラウザで確かめる**（Playwright MCP）

1. `browser_navigate` で `file:///<プロジェクトのフォルダ>/skills/quest/board.html?demo=human` を開く。
2. `browser_evaluate`：

   ```js
   async () => {
     const tabs = () => [...document.querySelectorAll('nav.tabs > button')];
     const labels = tabs().map((b) => b.textContent);
     const shown = [];
     for (let i = 0; i < labels.length; i++) { tabs()[i].click(); await new Promise((r) => setTimeout(r, 50)); shown.push([labels[i], document.querySelector('.panel').textContent.length > 20]); }
     tabs()[0].click();
     const g = window.__guildBoard.S.model;
     return { labels, shown, inputs: g.inputs, q1: [g.quests[0].inputs, g.quests[0].candidates], entry: g.archive.map((e) => [e.name, e.inputs]), req: g.requests[0] };
   }
   ```

   Expected: `labels` が `["クエスト掲示板","クエスト進捗","納品物","書庫","外部サイト","Obsidian","ヘルプ"]` の7つ。`shown` がすべて `true`。`inputs` は `[]`（見本にはまだない）、`q1` は `[[],[]]`、`entry` の `inputs` はすべて `[]`、`req` に `start`・`inputs` があり `template` がない。
3. `browser_console_messages` で、エラーが 0 件。
4. `?demo=accept`・`?demo=failed`・`?demo=plan` でも 1〜3 を行う（`labels` と `shown` が同じで、エラー 0 件）。
5. `browser_take_screenshot`：タブ列に「冒険の書」がなく、先頭が「クエスト掲示板」であることを目で確かめる（掲示板の中身は、まだ台帳の形のまま）。

- [ ] **Step 12: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：冒険の書とテンプレートを画面から消し、インプット・計画の inputs/candidates・書庫の inputs を読めるようにする"
```

---

### Task 7: ボード — クエスト掲示板の骨格（左に一覧、右に詳細パネル）

**Files:**
- Modify: `skills/quest/board.html`（CSS の台帳・目次まわりの削除と、一覧・詳細パネルの追加、`S`、台帳の関数群の置き換え、`questDetail`、`boardTab`、`composer`、`sendRequest`、`stickyTools`・`goCompose`、`render`、`refresh`、`start`）
- Test: `tests/test_guild.py`（`BoardPathsTest` に `test_quest_board_split_view` を追加）

**Interfaces:**
- Consumes: Task 6 のタブ（`board` が「クエスト掲示板」）、`S.model.quests[i]`（`derive` の結果：`id`・`title`・`label`・`cls`・`asks`・`done`・`total`・`q.plan`）、`S.model.requests`、`letterFor`・`infoLetter`・`abortBlock`・`cancelCell`・`webLetter`（変えない）、`okDate`・`localToday`・`hit`・`stampEl`
- Produces（Task 8〜12 が使う）：
  - 状態：`S.sel`（選んだ依頼の ID）、`S.listOpen`（一覧を出すか。`localStorage` の `guild.board.listOpen`）、`S.pane`（狭い画面で `'list'`／`'detail'`）、`S.bfilter`（`'all'`／`'turn'`／`'run'`／`'wait'`／`'done'`）、`S.showClosed`（完了・中止を一覧に出すか）、`S.newOpen`（新しい依頼の欄を開いているか）、`S.form['f:bq']`（一覧の検索）、`S.form.bjump`（隠したときの「探して開く」）
  - 関数：`lsGet(key, fallback)`・`lsSet(key, value)`（`localStorage` を `try/catch` で包む。JSON で読み書きし、使えなければ `fallback`／`false`）、`boardBucket(qd) -> 'turn'|'run'|'wait'|'done'`、`boardList(m) -> { q, f, counts, open, closed, nav }`、`selectQuest(id)`、`jumpQuest(id)`、`openNew()`、`questRow(qd)`、`requestRow(r)`、`questListPane(m, L)`、`questPanel(m, L)`、`hiddenBar(m, L, i, go)`、`questDetail(qd)`（詳細パネルの本文。Task 8 で置き換える）
  - DOM：一覧は `aside.qlist#quest-list`、行は `button.qli[data-q][aria-current]`、詳細は `section.qpanel`（`container-type:inline-size`。Task 8 のコンテナクエリが使う）、ツールバーは `.qtool`（Task 11 が「進捗で見る」を足す）
  - `window.__guildBoard` に `lsGet`・`lsSet`・`boardBucket`・`boardList`・`jumpQuest` を足す（確かめ用）
  - 消すもの：`STATES`・`PAGE`・`filterQuests`・`stateFilter`・`pageOf`・旧 `jumpQuest`・`questToc`・`ledger`・`goCompose`、`S.openQ`・`S.openInit`・`S.stf`・`S.limit`・`S.focusQ`、CSS の `.qitem`・`.ledger`・`.lh`・`.lr`・`.detail`・`.topline`・`.filters`・`.fchk`・`.morebtn`
  - `inbox/` に書く JSON の形は変えない（手紙は `letterFor` のまま、置き場所が詳細パネルに移るだけ）

- [ ] **Step 1: 失敗するテストを書く**（`BoardPathsTest` の末尾、`class DocsContractTest(unittest.TestCase):` の直前に足す）

```python
    def test_quest_board_split_view(self):
        for needle in ("function boardList(", "function boardBucket(", "function questListPane(", "function questPanel(", "function hiddenBar(",
                       "function lsGet(", "function lsSet(", "'guild.board.listOpen'", "一覧を隠す", "‹ 一覧へ戻る", "件中 ${i + 1}件目",
                       "@media (max-width:760px)", ".qb.pane-detail .qlist{display:none}", "container-type:inline-size", "const KEEP_SCROLL"):
            self.assertIn(needle, self.board)
        for gone in ("function ledger(", "function questToc(", "function stateFilter(", "function pageOf(", "function filterQuests(",
                     "S.openQ", "S.focusQ", "S.stf", ".ledger", ".lr{", "goCompose", ".qitem"):
            self.assertNotIn(gone, self.board)
        # localStorage は lsGet・lsSet の中だけで使う（使えない環境で例外を出さない）
        rest = self.board.replace("window.localStorage.getItem", "").replace("window.localStorage.setItem", "")
        self.assertNotIn("localStorage", rest)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest -v`
Expected: `test_quest_board_split_view` が FAIL（`function boardList(` がない）。

- [ ] **Step 3: 台帳・目次の CSS を消す**

次の1行を、

```css
.lr,.quick{scroll-margin-top:70px}
```

次に置き換える。

```css
.quick{scroll-margin-top:70px}
```

次の6行（台帳の集中表示）を削除する。

```css
.qitem{transition:opacity .5s,background .5s}
/* 集中表示：目次などから選んだ依頼の票（行と中身）は明るいまま、ほかの票を暗く保つ。解除するまで残る */
.ledger.focusing .qitem:not(.hit){opacity:.22}
.ledger.focusing .qitem:not(.hit):hover{opacity:.6}
.qitem.hit{position:relative;z-index:2;background:var(--surface)}.qitem.hit .lr:focus-visible{outline:0}
@media (prefers-reduced-motion:reduce){.qitem{transition:none}}
```

次の2行（使われていない）を削除する。

```css
.topline{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px}
.topline .attn{flex:1 1 320px;margin:0}
```

次の8行（台帳）を削除する（その間にある `.newbtn{…}` の1行は残す。一覧の「＋ 新規」が使う）。

```css
.ledger{background:var(--paper2);border:1px solid var(--line);font-size:14px}
.lh,.lr{display:grid;grid-template-columns:86px minmax(0,1fr) 112px 70px 130px;gap:0 12px;padding:9px 14px;align-items:start;box-sizing:border-box;width:100%}
.lh{font-size:12px;color:var(--sub);background:var(--head);border-bottom:1px solid var(--line)}
.lr{border:0;border-bottom:1px solid var(--line);background:transparent;text-align:left;font:inherit;color:inherit;cursor:pointer}
.lr.plain{cursor:default}
.lr.sel{background:var(--surface);font-weight:700;box-shadow:inset 6px 0 0 var(--seal);border-bottom:0}
.lr:not(.plain):not(.sel):hover{background:var(--surface)}
.detail{padding:6px 24px 26px 30px;background:var(--surface);border-bottom:2px solid var(--seal)}
```

次の1行を削除する。

```css
@media (max-width:760px){.lh{display:none}.lr{grid-template-columns:70px 1fr}}
```

状態の絞り込み・件数の区切りだけが使っていた次の6行を削除する（`.filters` の3行は、Task 6 で冒険の書が消えたので、ほかに使う場所がない）。

```css
.filters{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px}
.fchk{display:inline-flex;align-items:center;gap:6px;font-size:13px;min-height:36px;border:1px solid var(--brass);border-radius:999px;padding:2px 12px;cursor:pointer;background:transparent}
.fchk.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.morebtn{min-height:34px}
.filters button{font:inherit;font-size:13px;min-height:36px;border:1px solid var(--brass);border-radius:999px;padding:2px 14px;background:transparent;color:var(--ink);cursor:pointer}
.filters button.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
```

（`.filters{…}` は `.tree{…}` の次の行にあり、`.fchk`〜`.filters button.on` は `.tocb .st{…}`・`.stamp.sm{…}`・2つの `@media` の後ろにある。どちらも1行ずつ削除する。）

- [ ] **Step 4: 一覧と詳細パネルの CSS を足す**（`<style>` の末尾、`.plegend .lg{…}` の行の後ろ）

```css
/* クエスト掲示板：左に一覧、右に詳細パネル。狭い画面（760px 未満）では、一覧と詳細を切り替える（S.pane） */
.wrap.wide{max-width:1400px}
.qb{display:grid;grid-template-columns:minmax(280px,380px) minmax(0,1fr);gap:18px;align-items:start}
.qb.nolist{grid-template-columns:minmax(0,1fr)}
.qb.nolist .qlist{display:none}
.qlist{display:flex;flex-direction:column;gap:10px;min-width:0;position:sticky;top:70px;max-height:calc(100vh - 90px)}
.qlhead{display:flex;align-items:center;gap:10px}
.qsearch{width:100%;box-sizing:border-box;min-height:40px;padding:6px 12px;font:inherit;font-size:14px;border:1px solid var(--brass);border-radius:4px;background:var(--surface);color:var(--ink)}
.chipbar{display:flex;flex-wrap:wrap;gap:6px}
.chipbar button{font:inherit;font-size:13px;min-height:34px;border:1px solid var(--brass);border-radius:999px;padding:2px 12px;background:var(--paper2);color:var(--ink);cursor:pointer}
.chipbar button[aria-pressed="true"]{background:var(--seal);border-color:var(--seal);color:var(--on)}
.chipbar .n{margin-left:6px;font-size:12px;opacity:.85}
.qrows{flex:1 1 auto;min-height:0;overflow:auto;border:1px solid var(--line);border-radius:4px;background:var(--paper2)}
.qli{display:grid;grid-template-columns:48px minmax(0,1fr) auto;gap:2px 10px;width:100%;box-sizing:border-box;padding:8px 12px;border:0;border-bottom:1px solid var(--line);border-left:4px solid transparent;background:transparent;text-align:left;font:inherit;font-size:13.5px;line-height:1.5;color:inherit;cursor:pointer}
.qli:hover{background:var(--surface)}
.qli[aria-current="true"]{background:var(--surface);border-left-color:var(--seal)}
.qli[aria-current="true"] .tt{font-weight:700}
.qli .id{grid-column:1;grid-row:1}
.qli .tt{grid-column:2;grid-row:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qli .st{grid-column:3;grid-row:1;text-align:right}
.qli .pg{grid-column:2;grid-row:2;display:flex;align-items:center;gap:8px;font-size:12px;color:var(--sub)}
.qli .pg .bar{flex:1 1 auto;margin:0;max-width:160px}
.qli .du{grid-column:3;grid-row:2;font-size:12px;color:var(--sub);text-align:right;white-space:nowrap}
.qli .du.late{color:var(--ng);font-weight:700}
.qli.req{cursor:default;background:var(--surface2)}
.qfold{display:block;width:100%;font:inherit;font-size:13px;border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--sub);padding:8px 12px;cursor:pointer;text-align:left}
.qpanel{min-width:0;container-type:inline-size;background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px 20px 24px}
.qtool{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;padding-bottom:10px;border-bottom:1px dotted var(--brass);margin-bottom:12px}
.hidebar{display:flex;flex:1 1 auto;flex-wrap:wrap;align-items:center;gap:8px 10px}
.hidebar .qsearch{width:auto;flex:0 1 240px;min-height:36px}
.qhead h3{font-family:'Shippori Mincho B1','Yu Mincho','Hiragino Mincho ProN','Noto Serif JP',serif;font-size:20px;margin:4px 0}
.qhl{display:flex;align-items:center;gap:10px}
.qmeta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font-size:13px;color:var(--sub)}
.qmeta .bar{width:160px;margin:0}
.qback{display:none}
@media (max-width:760px){
  .qb,.qb.nolist{grid-template-columns:minmax(0,1fr)}
  .qlist{position:static;max-height:none}
  .qb.pane-list .qlist{display:flex}
  .qb.pane-list .qpanel{display:none}
  .qb.pane-detail .qlist{display:none}
  .qhide,.hidebar{display:none}
  .qback{display:inline-flex}
}
```

（狭い画面では、`listOpen` に関係なく `S.pane` で切り替える：`.qb.pane-list .qlist` は `.qb.nolist .qlist` と同じ詳細度で後ろにあるので勝つ。）

- [ ] **Step 5: 状態を直す**（`S`）

`S` の次の行（Task 6 で直したもの）を、

```js
  tab: 'board', sel: null, openQ: {}, openInit: false, stf: { board: {} }, kn: { cur: null }, limit: { board: 20 },
```

次に置き換える。

```js
  tab: 'board', sel: null, listOpen: true, pane: 'list', bfilter: 'all', showClosed: false, newOpen: false, kn: { cur: null },
```

- [ ] **Step 6: 台帳と目次を、一覧と詳細パネルに置き換える**

`// ---- 状態で絞る・件数を区切る・目次から飛ぶ` の行から、`ledger` の終わり（`  return h('div', { class: 'ledger' + (focusing ? ' focusing' : ''), role: 'table', 'aria-label': '依頼の一覧' }, rows);` と `}` の2行。次の行が空行で、その次が `function sendWeb(obj, key) {`）までを、次に置き換える（`STATES`・`PAGE`・`filterQuests`・`stateFilter`・`pageOf`・`jumpQuest`・`questToc`・`ledger` を丸ごと置き換える。上にある `cancelCell`・`cancelRequest` は残す）。

```js
// ============================================================ クエスト掲示板（左に一覧、右に詳細パネル）
// localStorage は、使えない環境（プライベートウィンドウ、file:// の制限、保存の拒否）がある。使えなければ既定値で動く
function lsGet(key, fallback) {
  try { const v = window.localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
}
function lsSet(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
}
const LS_LIST = 'guild.board.listOpen';
const BOARD_CHIPS = [['all', 'すべて'], ['turn', 'あなたの番'], ['run', '進行中'], ['wait', '受け取り待ち'], ['done', '完了']];
// 一覧の区分（1つの依頼は1つの区分）。受け取り待ち → あなたの番（答えていない手紙がある）→ 完了・中止 → 進行中 の順に決める
function boardBucket(qd) {
  if (qd.label === '受け取り待ち') return 'wait';
  if (qd.asks.some((a) => !a.sent)) return 'turn';
  if (qd.label === '完了' || qd.label === '中止') return 'done';
  return 'run';
}
// 一覧に出す依頼。検索（番号・題名）と区分で絞る。「すべて」では完了・中止を畳み、S.showClosed のときだけ出す。
// nav は「‹ ›」と「N件中M件目」が使う順番（一覧に見えている順）。1回の描画で1度だけ呼ぶ（O(n)）
function boardList(m) {
  const q = (S.form['f:bq'] || '').trim().toLowerCase(), f = S.bfilter || 'all';
  const counts = { all: 0, turn: 0, run: 0, wait: 0, done: 0 };
  const found = m.quests.filter((x) => hit(q, x.id, x.title)).map((x) => [x, boardBucket(x)]);
  for (const [, b] of found) { counts.all++; counts[b]++; }
  const open = found.filter(([, b]) => (f === 'all' ? b !== 'done' : b === f)).map(([x]) => x);
  const closed = f === 'all' ? found.filter(([, b]) => b === 'done').map(([x]) => x) : [];
  return { q, f, counts, open, closed, nav: S.showClosed ? [...open, ...closed] : open };
}
function selectQuest(id) {
  S.sel = id; S.pane = 'detail'; render();
  const el = document.querySelector('.qpanel'), bar = document.querySelector('.tabs');
  if (el) { const top = el.getBoundingClientRect().top - (bar ? bar.offsetHeight : 0) - 8; if (top < 0 || top > window.innerHeight * 0.6) window.scrollTo(0, window.scrollY + top); }
}
// 「あなたの番」の帯・納品物タブなどから、その依頼を開く。一覧で見えないとき（区分・検索・畳んだ完了）は、見えるように戻す
function jumpQuest(id) {
  const qd = S.model && S.model.quests.find((x) => x.id === id); if (!qd) return;
  const b = boardBucket(qd);
  S.tab = 'board';
  if (S.bfilter !== 'all' && S.bfilter !== b) S.bfilter = 'all';
  if (!hit((S.form['f:bq'] || '').trim().toLowerCase(), qd.id, qd.title)) S.form['f:bq'] = '';
  if (b === 'done') S.showClosed = true;
  selectQuest(id);
}
function openNew() {
  S.tab = 'board'; S.newOpen = true; S.newSaved = ''; render();
  const ta = document.getElementById('qreq'); if (ta) { ta.scrollIntoView({ block: 'center' }); ta.focus(); }
}
const shortDate = (s) => `${Number(s.slice(5, 7))}/${Number(s.slice(8, 10))}`;
function questRow(qd) {
  const p = qd.q.plan, due = p && okDate(p.due) ? p.due : null, late = !!due && due < localToday() && boardBucket(qd) !== 'done';
  const pct = qd.total ? Math.round(qd.done / qd.total * 100) : 0;
  return h('button', { type: 'button', class: 'qli', 'aria-current': S.sel === qd.id ? 'true' : 'false', 'data-q': qd.id, 'data-key': 'q:' + qd.id, onclick: () => selectQuest(qd.id) },
    h('span', { class: 'id' }, qd.id), h('span', { class: 'tt', title: qd.title }, qd.title), h('span', { class: 'st' }, stampEl(qd.label, qd.cls + ' sm')),
    h('span', { class: 'pg' }, h('span', { class: 'bar', 'aria-hidden': 'true' }, h('span', { style: `width:${pct}%` })), qd.total ? `${qd.done}/${qd.total}` : '—'),
    h('span', { class: 'du' + (late ? ' late' : '') }, due ? `締切 ${shortDate(due)}` : ''));
}
function requestRow(r) {
  return h('div', { class: 'qli req' }, h('span', { class: 'id' }, '受付'), h('span', { class: 'tt', title: r.text }, r.text.split('\n')[0].slice(0, 80)), h('span', { class: 'st' }, stampEl('受付待ち', 'sd-wait sm')),
    h('span', { class: 'pg' }, '/guild:quest が受け付けます'), h('span', { class: 'du' }, cancelCell(r)));
}
function questListPane(m, L) {
  const reqs = L.f === 'all' || L.f === 'run' ? m.requests.filter((r) => hit(L.q, r.id, r.text)) : [];
  const search = h('input', { type: 'search', class: 'qsearch', placeholder: '番号・題名で探す', 'aria-label': 'クエストを探す' }); search.value = S.form['f:bq'] || ''; bindKey(search, 'f:bq');
  const chips = h('div', { class: 'chipbar', role: 'group', 'aria-label': '状態で絞り込む' }, BOARD_CHIPS.map(([k, l]) =>
    h('button', { type: 'button', 'aria-pressed': String(L.f === k), onclick: () => { S.bfilter = k; render(); } }, l, h('span', { class: 'n' }, L.counts[k]))));
  const empty = !reqs.length && !L.open.length && !L.closed.length;
  return h('aside', { class: 'qlist', id: 'quest-list', 'aria-label': 'クエスト一覧' },
    h('div', { class: 'qlhead' }, h('h2', { class: 'h2' }, 'クエスト掲示板'), h('button', { type: 'button', class: 'btn sm newbtn', onclick: openNew }, '＋ 新規')),
    search, chips,
    h('div', { class: 'qrows' },
      reqs.map(requestRow), L.open.map(questRow),
      L.closed.length ? h('button', { type: 'button', class: 'qfold', 'aria-expanded': String(!!S.showClosed), onclick: () => { S.showClosed = !S.showClosed; render(); } }, S.showClosed ? `完了・中止 ${L.closed.length}件を畳む` : `完了・中止 ${L.closed.length}件を表示`) : null,
      S.showClosed ? L.closed.map(questRow) : null,
      empty ? h('p', { class: 'sub', style: 'padding:10px 12px;margin:0' }, m.quests.length || m.requests.length ? '当てはまるクエストはありません。' : 'まだ依頼はありません。「＋ 新規」から出してください。') : null));
}
function questPanel(m, L) {
  const qd = m.quests.find((x) => x.id === S.sel);
  const i = qd ? L.nav.findIndex((x) => x.id === qd.id) : -1, go = (d) => { const n = L.nav[i + d]; if (n) selectQuest(n.id); };
  const tool = h('div', { class: 'qtool' },
    h('button', { type: 'button', class: 'btn ghost sm qback', onclick: () => { S.pane = 'list'; render(); } }, '‹ 一覧へ戻る'),
    h('button', { type: 'button', class: 'btn ghost sm qhide', 'aria-expanded': String(S.listOpen), 'aria-controls': 'quest-list', onclick: () => { S.listOpen = !S.listOpen; lsSet(LS_LIST, S.listOpen); render(); } }, S.listOpen ? '一覧を隠す' : '一覧を表示'),
    S.listOpen ? null : hiddenBar(m, L, i, go));
  if (!qd) return h('section', { class: 'qpanel', 'aria-label': 'クエストの詳細' }, tool, h('p', { class: 'sub' }, m.quests.length ? '一覧からクエストを選んでください。' : 'まだクエストはありません。「＋ 新規」から出してください。'));
  const p = qd.q.plan, pct = qd.total ? Math.round(qd.done / qd.total * 100) : 0;
  return h('section', { class: 'qpanel', 'aria-label': `${qd.id} の詳細` }, tool,
    h('header', { class: 'qhead' },
      h('div', { class: 'qhl' }, h('span', { class: 'tid' }, qd.id), stampEl(qd.label, qd.cls)),
      h('h3', null, qd.title),
      h('div', { class: 'qmeta' }, h('span', null, p ? `開始 ${p.start || '—'}　締切 ${p.due || '—'}` : '計画はまだありません'),
        qd.total ? [h('span', { class: 'bar', role: 'img', 'aria-label': `${qd.total} 件中 ${qd.done} 件が済み` }, h('span', { style: `width:${pct}%` })), h('span', null, `${qd.done}/${qd.total} 済み`)] : null)),
    questDetail(qd));
}
// 一覧を隠したときのツールバー：見出し・前後のクエスト・何件中何件目・探して開く・＋ 新規
function hiddenBar(m, L, i, go) {
  const jump = h('input', { type: 'search', class: 'qsearch', list: 'qjump', placeholder: 'クエストを探して開く', 'aria-label': 'クエストを探して開く' }); jump.value = S.form.bjump || ''; bindKey(jump, 'bjump');
  const pick = (exact) => {
    const v = jump.value.trim(); if (!v) return;
    const lv = v.toLowerCase(), t = m.quests.find((x) => `${x.id} ${x.title}` === v) || (exact ? null : (m.quests.find((x) => x.id.toLowerCase() === lv) || m.quests.find((x) => hit(lv, x.id, x.title))));
    if (t) { jump.value = ''; S.form.bjump = ''; jumpQuest(t.id); }
  };
  jump.addEventListener('input', () => pick(true));   // 候補（datalist）から選んだとき
  jump.addEventListener('change', () => pick(false)); // Enter で確定したとき（番号・題名の一部でもよい）
  return h('div', { class: 'hidebar' },
    h('b', { class: 'h2', style: 'font-size:17px' }, 'クエスト掲示板'),
    h('button', { type: 'button', class: 'btn ghost sm', 'aria-label': '前のクエスト', disabled: i <= 0, onclick: () => go(-1) }, '‹'),
    h('button', { type: 'button', class: 'btn ghost sm', 'aria-label': '次のクエスト', disabled: i < 0 || i >= L.nav.length - 1, onclick: () => go(1) }, '›'),
    h('span', { class: 'fine', 'aria-live': 'polite' }, i >= 0 ? `${L.nav.length}件中 ${i + 1}件目` : `${L.nav.length}件`),
    jump, h('datalist', { id: 'qjump' }, m.quests.map((x) => h('option', { value: `${x.id} ${x.title}` }))),
    h('button', { type: 'button', class: 'btn sm newbtn', onclick: openNew }, '＋ 新規'));
}
```

- [ ] **Step 7: 詳細パネルの本文と、掲示板のタブを置き換える**

`questDetail` 全体（`function questDetail(qd) {` から、その関数の終わりまで）を、次に置き換える（中身は今の道のりのまま。進み具合の帯は詳細パネルの見出しに移したので外す。Task 8 で道のり／日付／インプットのタブにする）。

```js
function questDetail(qd) {
  return h('div', { class: 'qbody' },
    qd.asks.map((a) => letterFor(qd, a)), infoLetter(qd),
    qd.todos.length ? [h('h3', { class: 'sec' }, '道のり'), questDatesRow(qd),
      h('div', { class: 'way', 'aria-label': 'Todo の順序' }, qd.todos.flatMap((t, i) => [i ? h('span', { 'aria-hidden': 'true' }, '→') : null, h('span', { class: 'n' + (t.kind === 'human' ? ' h' : '') }, `${t.id} ${t.title.length > 12 ? t.title.slice(0, 12) + '…' : t.title}`)])),
      h('h3', { class: 'sec' }, 'タイムライン'), ganttBlock(qd),
      todoTags(qd)] : null,
    abortBlock(qd));
}
```

`boardTab` 全体（`function boardTab() {` から、その関数の終わりまで）を、次に置き換える。

```js
function boardTab() {
  const m = S.model, out = [];
  if (m && m.needs.length) out.push(h('div', { class: 'attn', role: 'status' }, h('b', null, `あなたの番が${m.needs.length}件あります`),
    m.needs.map((n) => h('button', { type: 'button', class: 'linkbtn', onclick: () => jumpQuest(n.q) }, n.text))));
  if (m) { const wl = webLetter(m); if (wl) out.push(wl); }
  if (S.newSaved) out.push(h('p', { class: 'saved', role: 'status' }, `依頼 ${S.newSaved} を預かりました。一覧の先頭に「受付待ち」で入っています。/guild:quest が動いていれば、すぐ受け付けます。動いていなければ、チャットで /guild:quest と送ってください。`));
  if (S.newOpen) out.push(composer(), h('div', { class: 'btns', style: 'margin:-6px 0 16px' }, h('button', { type: 'button', class: 'btn ghost sm', onclick: () => { S.newOpen = false; S.newError = ''; render(); } }, 'やめる')));
  if (!m) return out;
  const L = boardList(m);
  out.push(h('div', { class: `qb${S.listOpen ? '' : ' nolist'} pane-${S.pane}` }, questListPane(m, L), questPanel(m, L)));
  return out;
}
```

`composer` の次の1行を削除する（預かった知らせは `boardTab` が出す）。

```js
    S.newSaved ? h('p', { class: 'saved', role: 'status' }, `依頼 ${S.newSaved} を預かりました。下の一覧に「受付待ち」で入っています。/guild:quest が動いていれば、すぐ受け付けます。動いていなければ、チャットで /guild:quest と送ってください。`) : null);
```

その直前の行の末尾 `S.newNote ? h('p', { class: 'saved', role: 'status' }, S.newNote) : null,` の最後の `,` を `);` に変える（`composer` の `return h('section', …` を閉じる）。

`sendRequest` の次の行（Task 6 で書いたもの）を、

```js
  S.form['new:text'] = ''; S.form['new:due'] = ''; S.form['new:start'] = ''; S.files.new = []; S.newSaved = id;
```

次に置き換える。

```js
  S.form['new:text'] = ''; S.form['new:due'] = ''; S.form['new:start'] = ''; S.files.new = []; S.newSaved = id; S.newOpen = false;
```

- [ ] **Step 8: タブの右の「＋ 新しい依頼」・描画・更新・起動を直す**

`stickyTools` の次の行を、

```js
    h('button', { type: 'button', class: 'tool', onclick: goCompose }, '＋ 新しい依頼'));
```

次に置き換える。

```js
    h('button', { type: 'button', class: 'tool', onclick: openNew }, '＋ 新しい依頼'));
```

`goCompose` 全体（次の4行）を削除する。

```js
function goCompose() {
  S.tab = 'board'; render();
  const ta = document.getElementById('qreq'); if (ta) { ta.scrollIntoView({ block: 'center' }); ta.focus(); }
}
```

`render` の次の部分を、

```js
  app.replaceChildren(h('div', { class: 'wrap' }, banner(),
```

次に置き換える（掲示板だけ横に広げる。ほかのタブの幅と、書庫の目次の位置は変えない）。

```js
  app.replaceChildren(h('div', { class: 'wrap' + (S.tab === 'board' ? ' wide' : '') }, banner(),
```

`function render() {` の直前に、次を足す（一覧は 200 件でも内側でスクロールする。行を押して描き直しても、スクロールの位置を保つ。`.nbox`・`.iplist` は Task 10、`.plist` は Task 11 が使う）。

```js
const KEEP_SCROLL = ['.rbox', '.qrows', '.nbox', '.iplist', '.plist'];  // 描き直しても、中でスクロールしている位置を保つ枠
```

`render` の次の行を、

```js
  const oldBox = document.querySelector('.rbox'), boxTop = oldBox ? oldBox.scrollTop : 0;
```

次に置き換え、

```js
  const tops = KEEP_SCROLL.map((s) => { const e = document.querySelector(s); return e ? e.scrollTop : 0; });
```

`render` の次の行を、

```js
  const newBox = document.querySelector('.rbox'); if (newBox && boxTop) newBox.scrollTop = boxTop;
```

次に置き換える。

```js
  KEEP_SCROLL.forEach((s, i) => { const e = document.querySelector(s); if (e && tops[i]) e.scrollTop = tops[i]; });
```

`refresh` の次の1行を削除する。

```js
      if (!S.openInit && ids.length) { S.openInit = true; const f0 = S.model.quests.find((x) => x.asks.some((a) => !a.sent)) || S.model.quests[0]; if (f0) S.openQ[f0.id] = true; }
```

`start` の、集中表示を解除する次の8行（コメントの行から `Escape` の行まで）を、

```js
  // 集中表示は、票の外をクリックすると解除する（目次と「あなたの番」の帯は、押した依頼へ移るので除く）。再描画はせず、見た目だけをその場で戻す
  document.addEventListener('click', (e) => {
    if (!S.focusQ || !(e.target instanceof Element) || e.target.closest('.qitem.hit, .tocb, .attn')) return;
    S.focusQ = null;
    document.querySelectorAll('.ledger.focusing').forEach((x) => x.classList.remove('focusing'));
    document.querySelectorAll('.qitem.hit').forEach((x) => x.classList.remove('hit'));
  }, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.focusQ && !/^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || '')) { S.focusQ = null; render(); } });
```

次の1行に置き換える。

```js
  S.listOpen = lsGet(LS_LIST, true) !== false;  // 前回の「一覧を隠す」。読めない・使えないときは、表示で開く
```

`start` の次の部分を、

```js
  window.__guildBoard = { S, render, scheduleModel, ganttSvg, refresh,
```

次に置き換える。

```js
  window.__guildBoard = { S, render, scheduleModel, ganttSvg, refresh, lsGet, lsSet, boardBucket, boardList, jumpQuest,
```

- [ ] **Step 9: 消し残しがないことを確かめる**

Grep（`skills/quest/board.html`）で、次のどれも 0 件であること：`openQ`、`openInit`、`focusQ`、`S\.stf`、`S\.limit`、`PAGE`、`filterQuests`、`stateFilter`、`pageOf`、`questToc`、`ledger`、`goCompose`、`qitem`、`class: 'lr`、`'lh'`、`fchk`、`morebtn`、`class: 'detail'`。`jumpQuest(` の呼び出しは、`boardTab`（あなたの番の帯）・`delivTab`（受け取り待ち）・`goNeed`・`hiddenBar` に残っていること。

- [ ] **Step 10: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest tests.test_guild.BoardContractTest -v` → PASS。続けて `TEST` が全部通ること。

- [ ] **Step 11: ブラウザで確かめる**（Playwright MCP。画面は 1280×900 で始める：`browser_resize`）

1. `?demo=human` を開く。`browser_evaluate`：

   ```js
   () => { const B = window.__guildBoard, L = B.boardList(B.S.model);
     return { rows: [...document.querySelectorAll('.qli')].map((b) => b.textContent.slice(0, 24)), counts: L.counts, sel: B.S.sel,
       h3: document.querySelector('.qpanel h3').textContent, letter: !!document.querySelector('.qpanel .letter'),
       fold: document.querySelector('.qfold') && document.querySelector('.qfold').textContent, list: getComputedStyle(document.querySelector('.qlist')).display }; }
   ```

   Expected: `rows` は受付待ちの行と Q001 の2行（Q002 は完了なので畳まれている）、`counts` は `{all:2, turn:1, run:0, wait:0, done:1}`、`sel` は `"Q001"`、`h3` は Q001 の題名、`letter` は `true`（T2 の「あなたの実行」の手紙が詳細パネルにある）、`fold` は `"完了・中止 1件を表示"`、`list` は `"flex"`。
2. `browser_click` で「完了・中止 1件を表示」→ Q002 の行が出る。Q002 の行を押す → `document.querySelector('.qpanel h3').textContent` が Q002 の題名、Q002 の行の `aria-current` が `"true"`。
3. 「あなたの番」のチップを押す → `.qli` が Q001 の1行だけ。「すべて」に戻し、一覧の検索に `browser_type` で `notes` を入れる → Q001 だけが残る（`.qfold` もない）。検索を空に戻す。
4. 「一覧を隠す」を押す。`browser_evaluate`：`() => ({ nolist: document.querySelector('.qb').classList.contains('nolist'), list: getComputedStyle(document.querySelector('.qlist')).display, bar: document.querySelector('.hidebar').textContent, ls: localStorage.getItem('guild.board.listOpen') })` → `nolist: true`、`list: "none"`、`bar` に「クエスト掲示板」「件中」「＋ 新規」、`ls: "false"`。`browser_take_screenshot`：詳細パネルが横幅いっぱいで、上のツールバーに見出し・‹ ›・「N件中M件目」・検索・「＋ 新規」が並ぶこと。
5. 「›」「‹」を押すと、詳細の題名が一覧の順に変わる（手順2で完了を表示しているので、Q001 と Q002 を行き来できる）。ツールバーの検索に `Q002` と入れて Enter（`browser_press_key`）→ Q002 が開く。
6. `browser_navigate` で同じ URL を開き直す → 一覧は隠れたまま（`.qb.nolist` がある）。「一覧を表示」を押す → 一覧が出て、`localStorage.getItem('guild.board.listOpen')` が `"true"`。
7. `localStorage` が使えない環境：`browser_evaluate`：

   ```js
   () => { const B = window.__guildBoard, d = Object.getOwnPropertyDescriptor(window, 'localStorage');
     Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('denied', 'SecurityError'); } });
     let r; try { r = [B.lsGet('guild.board.listOpen', true), B.lsSet('guild.board.listOpen', false)]; document.querySelector('.qhide').click(); r.push(B.S.listOpen); }
     finally { Object.defineProperty(window, 'localStorage', d); }
     return r; }
   ```

   Expected: `[true, false, false]`（例外にならず、ボタンで隠せる）。もう一度「一覧を表示」を押して戻す。
8. 狭い画面：`browser_resize` で 600×900。`browser_evaluate`：`() => ({ list: getComputedStyle(document.querySelector('.qlist')).display, panel: getComputedStyle(document.querySelector('.qpanel')).display, hide: getComputedStyle(document.querySelector('.qhide')).display })` → 最初は `S.pane` が `'list'` なので `list: "flex"`、`panel: "none"`、`hide: "none"`。Q001 の行を押す → `list: "none"`、`panel: "block"`、「‹ 一覧へ戻る」が見える。押すと一覧に戻る。一覧を隠した状態（手順4）でも、狭い画面では一覧と詳細を切り替えられることを、「一覧を隠す」を広い画面で押してから 600px にして確かめる。`browser_take_screenshot` を撮り、1280×900 に戻す。
9. `?demo=accept`（Q001 が「受け取り待ち」の区分。受け取りの手紙が詳細パネルに出る）、`?demo=questions`（Q001 は計画なしで「あなたの番」。質問の手紙が出る）、`?demo=failed`、`?demo=plan` を開き、それぞれ一覧と詳細が出ること。
10. 各 URL で `browser_console_messages` のエラーが 0 件。

- [ ] **Step 12: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：クエスト掲示板を、左の一覧（検索・状態・完了の畳み）と右の詳細パネルにし、一覧を隠せるようにする"
```

---

### Task 8: ボード — 詳細パネルのタブ（道のり／日付／インプット）と道のりの行、鑑定士の指摘

**Files:**
- Modify: `skills/quest/board.html`（CSS のタイムライン・`.way` の削除と、タブ・道のりの行の追加、`S`、`selectQuest`、`refresh`、`BARKIND`・`ganttOf`・`ganttBlock`・`todoTags` の削除、`appraiserNote`・`detailTabs`・`wayTab`・`todoRow` などの追加、`letterFor` の承認と失敗の判断、`questDetail`、`demoTree`）
- Test: `tests/test_guild.py`（`BoardPathsTest` に `test_detail_tabs_and_way_rows` を追加）

**Interfaces:**
- Consumes: Task 7 の `questPanel`（`questDetail(qd)` を呼ぶ）・`selectQuest`・`.qpanel`（`container-type:inline-size`）、Task 6 の `qd.inputs`、`qd.q.reports`（`reports/` のファイル名の配列）、`openReport(q, path)`・`copyPath(rel)`・`dateIssues(plan, t)`・`overdue(t, ms)`・`questDatesRow(qd)`・`dueRow(qd, t)`
- Produces（Task 9〜12 が使う）：
  - 状態：`S.dtab`（`'way'`／`'dates'`／`'inputs'`。クエストを替えても保つ）、`S.openTodo`（開いた行。`'<依頼>:<Todo>'` か `null`。`selectQuest` で `null`）、`S.rcache`（報告の中身。キーは `'<依頼>/reports/<名前>'`、値は文字列、読み込み中は `null`。モデルを作り直すたびに空にする）
  - 関数：`detailTabs(qd)`（タブと本文。`S.dtab` で `wayTab`／`datesTab`／`inputsTab` を呼ぶ）、`datesTab(qd)`（この Task では今の日付の欄を並べるだけ。Task 9 で置き換える）、`inputsTab(qd)`（この Task では読むだけ。Task 10 で置き換える）、`wayTab(qd)`、`todoRow(qd, t)`、`critList(t)`、`reportsOf(qd, tid) -> [{ name, label }]`、`reportText(qid, name) -> string|null`、`excerpt(text, n) -> string[]`、`reportLine(qd, r)`、`appraiserNote(qd, t)`
  - 定数：`DTABS`、`REPORT_ROLES`（`adventurer`・`scout`・`verify-scout`・`user`・`appraiser`）
  - 失敗の判断の手紙（`letterFor` の `decision`）は、鑑定士の報告があれば、その最初の6行を「鑑定士の指摘」として出す。書く入力（`{type:'decision', …}`）は変えない。
  - 消すもの：タイムライン（`BARKIND`・`ganttOf`・`ganttBlock` と CSS の `.legend2`・`.gx`・`.glab`・`.gtrack`・`.tick`・`.bar2`・`.s-*`・`.nowline`・`.gantt h3`）、`todoTags`、Todo の順序の `.way`。CSS の `.gantt{…}` は、クエスト進捗の `svg.gantt` が使うので残す。

- [ ] **Step 1: 失敗するテストを書く**（`BoardPathsTest` の末尾、`class DocsContractTest(unittest.TestCase):` の直前に足す）

```python
    def test_detail_tabs_and_way_rows(self):
        for needle in ("const DTABS = [['way', '道のり'], ['dates', '日付'], ['inputs', 'インプット']]", "function detailTabs(", "function wayTab(",
                       "function todoRow(", "function reportsOf(", "function reportText(", "function excerpt(", "function appraiserNote(",
                       "'verify-scout'", "role: 'tablist'", "@container (min-width:860px)", "S.rcache = {}", "appraiserNote(qd, t),"):
            self.assertIn(needle, self.board)
        for gone in ("function ganttBlock(", "function ganttOf(", "const BARKIND", "function todoTags(", ".bar2{", ".nowline{", ".way{", ".gx{"):
            self.assertNotIn(gone, self.board)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest -v`
Expected: `test_detail_tabs_and_way_rows` が FAIL（`const DTABS` がない）。

- [ ] **Step 3: タイムラインと `.way` の CSS を消す**

次の16行を削除する（間にある `.gantt{background:var(--surface);…}` の1行は残す。クエスト進捗の `svg.gantt` が使う）。

```css
.legend2{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12.5px;color:var(--sub);margin:0 0 12px}
.legend2 .sw{display:inline-block;width:22px;height:12px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.gantt h3{font-family:'Shippori Mincho B1','Yu Mincho','Hiragino Mincho ProN','Noto Serif JP',serif;font-size:16px;margin:0 0 8px}
.gx{display:flex;align-items:center;gap:10px;min-height:42px}
.glab{flex:0 0 140px;line-height:1.35}
.glab b{display:block;font-size:13.5px}
.gtrack{position:relative;flex:1 1 auto;height:28px;background:repeating-linear-gradient(90deg,transparent 0,transparent calc(12.5% - 1px),var(--grid) calc(12.5% - 1px),var(--grid) 12.5%);border-radius:3px}
.gtrack.axis{height:20px;background:none}
.tick{position:absolute;top:0;transform:translateX(-50%);font-size:11px;color:var(--sub);font-family:'JetBrains Mono',Consolas,'Courier New',monospace;white-space:nowrap}
.bar2{position:absolute;top:2px;height:24px;border-radius:3px;font-size:11.5px;line-height:24px;color:#fff;text-align:center;overflow:hidden;white-space:nowrap;box-sizing:border-box;font-weight:700;min-width:4px}
.s-adv{background:#6B5A3E}.s-cart{background:#4F6A70}.s-app{background:#5B4A6B}
.s-me{background:var(--warn-bg);color:var(--warn);border:2px solid var(--warn);line-height:20px}
.s-conf{background:var(--surface);color:var(--ng);border:2px dashed var(--ng);line-height:20px}
.s-ng{background:var(--ng)}
.s-blk{background:repeating-linear-gradient(45deg,var(--stripe1) 0 6px,var(--stripe2) 6px 12px);color:var(--stop);border:1px solid var(--stop-line);line-height:22px}
.nowline{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ng)}
```

次の3行を削除する。

```css
.way{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:12px;font-size:13px}
.way .n{border:1px solid var(--brass);border-radius:3px;padding:3px 10px;background:var(--surface)}
.way .n.h{border-style:dashed}
```

- [ ] **Step 4: タブと道のりの行の CSS を足す**（`<style>` の末尾、Task 7 で足した `@media (max-width:760px){…}` の後ろ）

```css
/* 詳細パネルのタブ（道のり／日付／インプット）と、道のりの行。パネルが広いとき（一覧を隠したときなど）は、選んだ Todo の合格基準を右に出す */
.dtabs{display:flex;gap:4px;margin:18px 0 0;border-bottom:2px solid var(--brass)}
.dtabs button{font:inherit;font-weight:700;font-size:14px;min-height:40px;padding:4px 18px;border:1px solid var(--brass);border-bottom:0;border-radius:6px 6px 0 0;background:var(--paper2);color:var(--sub);cursor:pointer;margin-bottom:-2px}
.dtabs button[aria-selected="true"]{background:var(--paper);color:var(--ink);border-color:var(--line)}
.dtabs .n{margin-left:6px;font-size:12px;font-weight:400}
.dpanel{background:var(--paper);border:1px solid var(--line);border-top:0;border-radius:0 0 6px 6px;padding:14px 16px 18px}
.td{border:1px solid var(--line);border-left:6px solid var(--brass);border-radius:3px;background:var(--surface);margin-bottom:6px}
.td.over{border-left-color:var(--ng)}
.td.open{border-color:var(--brass)}
.tdrow{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto auto 18px;gap:4px 12px;align-items:center;width:100%;box-sizing:border-box;padding:8px 12px;border:0;background:transparent;text-align:left;font:inherit;font-size:13.5px;color:inherit;cursor:pointer}
.tdt{min-width:0}.tdt .kind{display:block;font-size:12px}.tdt b{display:block;overflow:hidden;text-overflow:ellipsis}
.tdd{font-size:12.5px;color:var(--sub);white-space:nowrap}
.tdd.late{color:var(--ng);font-weight:700}
.caret{font-size:11px;color:var(--sub)}
.tdwarn{margin:0;padding:0 12px 8px;font-size:12.5px;color:var(--warn)}
.tdbody{padding:4px 14px 12px;border-top:1px dotted var(--brass)}
.tdbody .cap{display:block;font-size:13px;margin:8px 0 2px}
.rep{padding:6px 0;border-bottom:1px dotted var(--line)}
.rep:last-child{border-bottom:0}
.reph{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px}
.reph a{color:var(--gold);font-weight:700;word-break:break-all}
.reph .acts{margin-left:auto;display:flex;gap:6px}
.repx{margin:2px 0 0;font-size:12.5px;color:var(--sub)}
.critside{display:none}
.apnote{background:var(--surface2);border-left:4px solid var(--ng);border-radius:3px;padding:8px 12px;margin:0 0 12px;font-size:13.5px}
.apnote a{color:var(--gold);font-family:'JetBrains Mono',Consolas,'Courier New',monospace;font-size:12.5px}
.apnote ul{margin:4px 0 0;padding-left:20px}
@container (min-width:860px){
  .waygrid{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:16px;align-items:start}
  .critside{display:block;position:sticky;top:80px;background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:10px 12px;font-size:13.5px}
  .td .tdcrit{display:none}
}
@media (max-width:620px){.tdrow{grid-template-columns:auto minmax(0,1fr) auto 18px}.tdrow .tdd{display:none}}
```

- [ ] **Step 5: 状態と、報告の読み直しを足す**

`S` の次の行（Task 7 で直したもの）を、

```js
  tab: 'board', sel: null, listOpen: true, pane: 'list', bfilter: 'all', showClosed: false, newOpen: false, kn: { cur: null },
```

次に置き換える。

```js
  tab: 'board', sel: null, listOpen: true, pane: 'list', bfilter: 'all', showClosed: false, newOpen: false, dtab: 'way', openTodo: null, rcache: {}, kn: { cur: null },
```

`selectQuest` の次の行を、

```js
  S.sel = id; S.pane = 'detail'; render();
```

次に置き換える。

```js
  S.sel = id; S.pane = 'detail'; S.openTodo = null; render();
```

`refresh` の次の行を、

```js
      S.dataKey = key; S.model = buildModel(raw);
```

次に置き換える。

```js
      S.dataKey = key; S.model = buildModel(raw); S.rcache = {};  // 報告は書き換わる（やり直しで鑑定士の報告が変わる）。開いている分だけ読み直す
```

- [ ] **Step 6: タイムラインを消す**

`// ---- タイムラインの帯` の行から、`ganttOf` の終わり（`  return { rows, lo, hi, ticks, now: open ? now : null, long: hi - lo > 86400000 };` と `}` の2行。次の行が空行で、その次が `// ============================================================ 描画（部品）`）までを、削除する（`BARKIND`・`ganttOf` を丸ごと消す）。

`function ganttBlock(x) {` から、その関数の終わり（`    g.now != null ? h('p', { class: 'sub', style: 'margin:6px 0 0;padding-left:150px' }, '赤い線が「いま」です。') : null);` と `}` の2行）までを、削除する。

- [ ] **Step 7: 道のりの行・報告・タブを足す**（`todoTags` を置き換える）

`function todoTags(qd) {` から、その関数の終わり（`      d.addEventListener('toggle', () => { S.open['c:' + qd.id + t.id] = d.open; }); return d; })()));` と `}` の2行）までを、次に置き換える。

```js
// ---- 詳細パネルのタブ（道のり／日付／インプット）と、報告の読み込み
const DTABS = [['way', '道のり'], ['dates', '日付'], ['inputs', 'インプット']];
// 報告のファイル（reports/<Todo>-<役>.md）。道のりの行に、この順で並べる
const REPORT_ROLES = [['adventurer', '冒険者'], ['scout', '斥候'], ['verify-scout', '斥候（出典の確認）'], ['user', 'あなた'], ['appraiser', '鑑定士']];
function reportsOf(qd, tid) { return REPORT_ROLES.map(([r, label]) => ({ name: `${tid}-${r}.md`, label })).filter((x) => qd.q.reports.includes(x.name)); }
// 報告の中身は、行を開いたとき・判断の手紙を出すときだけ読む（S.rcache に覚える。null は読み込み中、'' は読めなかった）
function reportText(qid, name) {
  const path = `${qid}/reports/${name}`;
  if (!(path in S.rcache)) {
    S.rcache[path] = null;
    Promise.resolve(S.fs.readText(path)).then((t) => { S.rcache[path] = t == null ? '' : t; }, () => { S.rcache[path] = ''; }).then(() => { if (!S.composing) render(); });
  }
  return S.rcache[path];
}
// 報告の抜粋：フロントマターを除いた、空でない最初の n 行（見出し・箇条書きの記号は外す）
function excerpt(text, n) {
  const body = String(text || '').replace(/^﻿?---\r?\n[\s\S]*?\r?\n---\r?\n?/, '');
  return body.split(/\r?\n/).map((l) => l.replace(/^\s*(?:#+|[-*>]|\d+\.)\s*/, '').trim()).filter(Boolean).slice(0, n);
}
function critList(t) {
  const c = t.criteria || {};
  return h('dl', { class: 'c' }, h('dt', null, '観点'), h('dd', null, c.viewpoint || ''), h('dt', null, '合格ライン'), h('dd', null, c.pass_line || ''), h('dt', null, '確かめ方'), h('dd', null, c.check || ''));
}
function reportLine(qd, r) {
  const rel = `${qd.id}/reports/${r.name}`, txt = reportText(qd.id, r.name), lines = txt ? excerpt(txt, 3) : [];
  return h('div', { class: 'rep' },
    h('div', { class: 'reph' }, h('a', { href: '#', onclick: (e) => { e.preventDefault(); openReport(qd.id, `reports/${r.name}`); } }, r.name), h('span', { class: 'fine' }, r.label),
      h('span', { class: 'acts' },
        h('button', { type: 'button', class: 'btn ghost sm', 'aria-label': `${r.name} のパスをコピー`, onclick: () => copyPath(rel) }, 'パスをコピー'))),
    txt === null ? h('p', { class: 'fine', style: 'margin:2px 0 0' }, '読み込み中…') : lines.length ? h('p', { class: 'repx' }, lines.join(' ／ ')) : null);
}
function todoRow(qd, t) {
  const key = `${qd.id}:${t.id}`, open = S.openTodo === key, over = overdue(t, Date.now()), warns = dateIssues(qd.q.plan, t), reps = open ? reportsOf(qd, t.id) : [];
  return h('div', { class: 'td' + (open ? ' open' : '') + (over ? ' over' : '') },
    h('button', { type: 'button', class: 'tdrow', 'aria-expanded': String(open), 'aria-controls': `td-${key}`, 'data-key': 'td:' + key, onclick: () => { S.openTodo = open ? null : key; render(); } },
      h('span', { class: 'tid' }, t.id),
      h('span', { class: 'tdt' }, h('span', { class: 'kind' }, t.kind === 'human' ? 'あなたの実行' : t.confirm ? '自動（実行前に確認）' : '自動'), h('b', null, t.title)),
      h('span', { class: 'tdd' }, '予定 ', t.scheduled || '—'),
      h('span', { class: 'tdd' + (over ? ' late' : '') }, '締切 ', t.due || '—'),
      h('span', { class: 'tds' }, stampEl(t.stamp, t.cls)), h('span', { class: 'caret', 'aria-hidden': 'true' }, open ? '▲' : '▼')),
    warns.length ? h('p', { class: 'tdwarn' }, warns.join(' ')) : null,
    open ? h('div', { class: 'tdbody', id: `td-${key}` },
      h('div', { class: 'tdcrit' }, h('b', { class: 'cap' }, '合格基準'), critList(t)),
      t.kind === 'human' && t.instruction ? h('p', { class: 'fine', style: 'white-space:pre-wrap;margin:6px 0' }, t.instruction) : null,
      t.confirm ? h('p', { class: 'lock' }, '実行の直前に、もう一度お聞きします') : null,
      h('div', { class: 'tdrep' }, h('b', { class: 'cap' }, '報告'),
        reps.length ? reps.map((r) => reportLine(qd, r)) : h('p', { class: 'fine', style: 'margin:4px 0 0' }, 'まだ報告はありません。'))) : null);
}
function wayTab(qd) {
  if (!qd.todos.length) return h('p', { class: 'sub' }, 'Todo はありません。');
  const cur = qd.todos.find((t) => S.openTodo === `${qd.id}:${t.id}`);
  return h('div', { class: 'waygrid' },
    h('div', { class: 'waylist' }, h('p', { class: 'fine', style: 'margin:0 0 6px' }, '行を開くと、合格基準と報告が読めます。日付を直すときは「日付」タブへ。'), qd.todos.map((t) => todoRow(qd, t))),
    h('aside', { class: 'critside', 'aria-label': '選んだ Todo の合格基準' },
      cur ? [h('b', null, `${cur.id} の合格基準`), critList(cur)] : h('p', { class: 'fine', style: 'margin:0' }, '行を開くと、ここに合格基準が出ます。')));
}
// 日付タブ（Task 9 で、このクエストのガントと日付の表に置き換える）。今は、依頼と Todo ごとの日付の欄を並べる
function datesTab(qd) {
  return [questDatesRow(qd), qd.todos.map((t) => h('div', { class: 'tag' }, h('div', { class: 'row' }, h('span', { class: 'tid' }, t.id), h('span', { class: 'ttl' }, t.title)), dueRow(qd, t)))];
}
// インプットタブ（Task 10 で、追加・外す・既存から選ぶを足す）。今は、計画のインプットを読むだけ
function inputsTab(qd) {
  if (!qd.inputs.length) return h('p', { class: 'sub' }, 'このクエストのインプットはありません。');
  return h('ul', { class: 'flist' }, qd.inputs.map((x) => h('li', null, h('span', null, h('b', null, x.name), ' ', stampEl(x.source === 'user' ? '指定' : '自動', x.source === 'user' ? 'sd-ok sm' : 'sd-run sm'),
    x.reason ? h('span', { class: 'fine', style: 'display:block' }, x.reason) : null))));
}
function detailTabs(qd) {
  if (!DTABS.some(([k]) => k === S.dtab)) S.dtab = 'way';
  const badge = { way: qd.total, dates: 0, inputs: qd.inputs.length };
  const pick = (k) => { S.dtab = k; render(); const b = document.getElementById('dtab-' + k); if (b) b.focus(); };
  const keys = (e, i) => { const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0; if (d) { e.preventDefault(); pick(DTABS[(i + d + DTABS.length) % DTABS.length][0]); } };
  const body = S.dtab === 'dates' ? datesTab(qd) : S.dtab === 'inputs' ? inputsTab(qd) : wayTab(qd);
  return [h('div', { class: 'dtabs', role: 'tablist', 'aria-label': `${qd.id} の詳細` }, DTABS.map(([k, l], i) =>
      h('button', { type: 'button', role: 'tab', id: 'dtab-' + k, 'aria-selected': String(S.dtab === k), 'aria-controls': 'dtab-panel', tabindex: S.dtab === k ? '0' : '-1', onclick: () => pick(k), onkeydown: (e) => keys(e, i) },
        l, badge[k] ? h('span', { class: 'n' }, badge[k]) : null))),
    h('div', { class: 'dpanel', role: 'tabpanel', id: 'dtab-panel', 'aria-labelledby': 'dtab-' + S.dtab }, body)];
}
```

- [ ] **Step 8: 詳細パネルの本文をタブにする**

`questDetail` 全体（Task 7 で書いたもの）を、次に置き換える。

```js
function questDetail(qd) {
  return h('div', { class: 'qbody' }, qd.asks.map((a) => letterFor(qd, a)), infoLetter(qd), qd.q.plan ? detailTabs(qd) : null, abortBlock(qd));
}
```

- [ ] **Step 9: 手紙を直す**（承認の案内と、失敗の判断の鑑定士の指摘。書く入力の形は変えない）

`function letterFor(qd, a) {` の直前に、次を足す。

```js
// 失敗の判断の手紙に出す、鑑定士の指摘（reports/<Todo>-appraiser.md の、空でない最初の6行）。報告がなければ出さない
function appraiserNote(qd, t) {
  const name = `${t.id}-appraiser.md`;
  if (!qd.q.reports.includes(name)) return null;
  const txt = reportText(qd.id, name), lines = txt ? excerpt(txt, 6) : [];
  return h('div', { class: 'apnote', role: 'note', 'aria-label': '鑑定士の指摘' },
    h('div', null, h('b', null, '鑑定士の指摘'), '　', h('a', { href: '#', onclick: (e) => { e.preventDefault(); openReport(qd.id, `reports/${name}`); } }, name)),
    txt === null ? h('p', { class: 'fine', style: 'margin:4px 0 0' }, '読み込み中…')
      : lines.length ? h('ul', null, lines.map((l) => h('li', null, l))) : h('p', { class: 'fine', style: 'margin:4px 0 0' }, '報告を読めませんでした。ファイル名を押して開いてください。'));
}
```

承認の手紙の本文の次の部分を、

```js
下の「道のり」を確かめて、承認してください。日付（予定日・締切）も、下で確かめて直せます。
```

次に置き換える。

```js
下の「道のり」タブで Todo と合格基準を確かめて、承認してください。日付は「日付」タブで直せます。
```

失敗の判断（`// decision` の後ろ）の次の行の直後に、

```js
    h('p', null, `${t.id}「${t.title}」ができませんでした。` + (deps.length ? `これに続く ${names} は止まっています。` : '')),
```

次の1行を足す。

```js
    appraiserNote(qd, t),
```

- [ ] **Step 10: 見本の「失敗」の場面に、鑑定士の報告を足す**（`demoTree`）

次の行を、

```js
  if (scene === 'failed') h1.push({ t: at(67), id: 'T2', event: 'deps_done', from: 'pending', to: 'waiting_user' }, { t: at(60), id: 'T2', event: 'reported_failed', from: 'waiting_user', to: 'failed' }, { t: at(60), id: 'T3', event: 'dep_failed', from: 'pending', to: 'blocked' });
```

次に置き換える（T2 は、結果を送ったあと、鑑定士が不合格にして、やり直しの回数を超えた）。

```js
  if (scene === 'failed') h1.push({ t: at(67), id: 'T2', event: 'deps_done', from: 'pending', to: 'waiting_user' }, { t: at(62), id: 'T2', event: 'submitted', from: 'waiting_user', to: 'review' }, { t: at(60), id: 'T2', event: 'rejected', from: 'review', to: 'failed' }, { t: at(60), id: 'T3', event: 'dep_failed', from: 'pending', to: 'blocked' });
```

次の行の直後に、

```js
  ['T1-adventurer.md', 'T1-appraiser.md', 'plan-draft.json'].forEach((n) => { rep[n] = T(n.endsWith('json') ? '{ "todos": [] }' : `## 結果\n${n} の見本です。`); });
```

次の1行を足す。

```js
  if (scene === 'failed') { rep['T2-user.md'] = T('# T2 の結果\nできた：上司に口頭で共有した\nメモ：返事は「検討する」だった'); rep['T2-appraiser.md'] = T('---\ntodo: T2\n---\n# T2 の鑑定\n## 判定\n不合格\n## 指摘\n- 合格ラインの「了承する」という返事が、報告にない\n- 返事は「検討する」で、了承ではない\n- やり直しの回数（1回）を超えた\n## 未確認\n- なし'); }
```

- [ ] **Step 11: 消し残しがないことを確かめる**

Grep（`skills/quest/board.html`）で、次のどれも 0 件であること：`ganttBlock`、`ganttOf`、`BARKIND`、`todoTags`、`legend2`、`gtrack`、`nowline`、`bar2`、`class: 'way'`、`'タイムライン'`。`questDatesRow(`・`dueRow(` は `datesTab` の中だけに残ること（Task 9 で消す）。

- [ ] **Step 12: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest tests.test_guild.BoardContractTest -v` → PASS。続けて `TEST` が全部通ること。

- [ ] **Step 13: ブラウザで確かめる**（Playwright MCP。1280×900）

1. `?demo=human` を開く（Q001 が選ばれている）。`browser_evaluate`：`() => [...document.querySelectorAll('.dtabs [role=tab]')].map((b) => [b.textContent, b.getAttribute('aria-selected')])` → `[["道のり3","true"],["日付","false"],["インプット","false"]]`。
2. T1 の行（最初の `.tdrow`）を押す。`browser_wait_for` で「見本です」の文字を待つ。`browser_evaluate`：`() => ({ open: document.querySelector('.tdrow').getAttribute('aria-expanded'), reps: [...document.querySelectorAll('.reph a')].map((a) => a.textContent), crit: !!document.querySelector('.tdbody dl.c'), x: document.querySelector('.repx') && document.querySelector('.repx').textContent })` → `open: "true"`、`reps: ["T1-adventurer.md","T1-appraiser.md"]`、`crit: true`、`x` に「見本です」。
3. 「T1-appraiser.md」を押す → 報告の読み取り画面が開き、見出しが `Q001/reports/T1-appraiser.md`。「閉じる」で閉じる。「パスをコピー」を押す → `window.__guildBoard.S.toast` が空でない（クリップボードが使えない環境では「コピーできませんでした」でもよい）。
4. 広いパネル：一覧が出ている状態で `getComputedStyle(document.querySelector('.critside')).display` が `"none"`（パネルが 860px 未満）。「一覧を隠す」を押すと `"block"` になり、右に「T1 の合格基準」が出て、`.td .tdcrit` は `display: none`。`browser_take_screenshot`：道のりの行が並び、右に合格基準が出ていること。「一覧を表示」で戻す。
5. キーボード：`dtab-way` にフォーカスして（`browser_evaluate` で `document.getElementById('dtab-way').focus()`）、`browser_press_key` で `ArrowRight` → `document.activeElement.id` が `"dtab-dates"`、日付タブに `.duerow` が4つ（依頼1＋Todo 3）。`ArrowRight` をもう一度 → インプットタブ（「このクエストのインプットはありません。」）。`ArrowRight` → 道のりに戻る。
6. `?demo=failed` を開く。`browser_wait_for` で「了承ではない」を待つ。`browser_evaluate`：`() => ({ note: [...document.querySelectorAll('.apnote li')].map((l) => l.textContent), file: document.querySelector('.apnote a').textContent })` → `file: "T2-appraiser.md"`、`note` は6件以下で「合格ラインの「了承する」という返事が、報告にない」を含む。判断の手紙の「この方針で進める」は、今までどおり（押して `Q001/inbox` に `type: "decision"` の JSON が書かれることを `window.__guildBoard.S.fs.fs.list('.work/Q001/inbox')` で確かめる）。
7. `?demo=plan` を開く → 承認の手紙に「「道のり」タブで Todo と合格基準を確かめて」が出る。
8. 各 URL で `browser_console_messages` のエラーが 0 件。

- [ ] **Step 14: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：詳細パネルを道のり／日付／インプットのタブにし、道のりの行で合格基準と報告を読めるようにする。失敗の判断に鑑定士の指摘を出す"
```

---

### Task 9: ボード — 日付タブ（このクエストのガントと、日付の表）

**Files:**
- Modify: `skills/quest/board.html`（CSS の `.duerow`・`.tag` の削除と日付タブの追加、`dueRow`・`questDatesRow` の削除、`datesTab` の置き換え、`dateRange`・`qGanttModel`・`questGantt` の追加、`start` の `window.__guildBoard`）
- Test: `tests/test_guild.py`（`BoardPathsTest.test_board_sends_the_date_inputs` を置き換え）

**Interfaces:**
- Consumes: Task 8 の `detailTabs`（`S.dtab === 'dates'` のとき `datesTab(qd)` を呼ぶ）、Task 7 の `shortDate`、`okDate`・`dayNum`・`dayStr`・`localToday`・`sv`・`STATE_FILL`・`TSTATE`・`dateIssues(plan, t)`・`send(qid, obj, key)`・`sentNote(key)`・`bindKey`、入力の形 `{type:'due', todo, scheduled, due}`（Todo）と `{type:'due', start, due}`（依頼）（Part A の Task 5 より前からある形。変えない）
- Produces（Task 11・12 が使う）：
  - `dateRange(plan) -> { min, max }`（日番号。依頼の開始日・締切と Todo の予定日のうち `okDate` を通るものの最小の前日〜最大の翌日。1つもなければ今日。幅は最低7日）
  - `qGanttModel(plan) -> { min, max, today, start, due, todos: [{ id, title, state, scheduled, due }] }`（`start`・`due` は正しい日付か `null`。`due` が不正なら `start`。Todo の `scheduled` は正しくなければ `start`、それもなければ `null`＝描かない。`today` はローカルの今日の日番号）
  - `questGantt(qd)`（`svg.gantt.qgantt`）、`datesTab(qd)`（下書きは `S.form['dt:<依頼>:start' | 'dt:<依頼>:due' | 'dt:<依頼>:<Todo>:scheduled' | 'dt:<依頼>:<Todo>:due']`）
  - 「変更を送る（N件）」は、変わった Todo ごとに1つ、依頼の日付が変わればもう1つ、`send()` で入力を書く（1つ失敗したら止める）。空の欄は「変えない」（Todo の締切だけは空＝`null`＝解除）。
  - `window.__guildBoard` に `dateRange`・`qGanttModel` を足す
  - 消すもの：`dueRow`・`questDatesRow`、CSS の `.duerow`（4行）・`.tag`・`.tag.over`・`.tag .row`・`.ttl`

- [ ] **Step 1: テストを置き換える**（`BoardPathsTest` の `test_board_sends_the_date_inputs` 全体を、次に置き換える）

```python
    def test_board_sends_the_date_inputs(self):
        for needle in ("type: 'due', todo: t.id, scheduled, due: d", "type: 'due', start: st, due: du", "function datesTab(", "function dateIssues(",
                       "function dateRange(", "function qGanttModel(", "function questGantt(", "変更を送る（${n}件）", "'元に戻す'", "dateRange, qGanttModel"):
            self.assertIn(needle, self.board)
        for gone in ("function dueRow(", "function questDatesRow(", ".duerow", ".tag{"):
            self.assertNotIn(gone, self.board)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest.test_board_sends_the_date_inputs -v`
Expected: FAIL（`type: 'due', todo: t.id, scheduled, due: d` がない）。

- [ ] **Step 3: 古い日付の欄の CSS を消し、日付タブの CSS を足す**

次の4行を削除する。

```css
.duerow{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin:8px 0 0;padding-top:8px;border-top:1px dotted var(--brass);font-size:13px}
.duerow .dl{font-family:'Shippori Mincho B1','Yu Mincho','Hiragino Mincho ProN','Noto Serif JP',serif;font-weight:800}
.duerow input[type=date]{font:inherit;font-size:13px;min-height:32px;padding:2px 8px;border:1px solid var(--brass);border-radius:3px;background:var(--paper2);color:var(--ink)}
.duerow .dwarn{flex-basis:100%;margin:0;color:var(--warn)}
```

次の4行（Todo の札。Task 8 の仮の日付タブだけが使っていた）を削除する。`.tag{…}` は `.sec{…}` の次の行、`.tag.over`・`.tag .row`・`.ttl` は、上で消した `.duerow` の4行の後ろにある（その間の `.tid{…}` の1行は残す。番号の印に使う）。

```css
.tag{background:var(--surface);border:1px solid var(--line);border-left:6px solid var(--brass);border-radius:3px;padding:10px 14px;margin-bottom:8px}
.tag.over{border-left-color:var(--ng)}
.tag .row{display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px}
.ttl{font-weight:700;flex:1 1 240px}
```

`<style>` の末尾（Task 8 で足した `@media (max-width:620px){…}` の後ろ）に、次を足す。

```css
/* 日付タブ：このクエストのガントと、日付の表（変えた行は色を変える。注意は表示だけ） */
svg.qgantt{min-width:560px}
.dtq{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;padding:8px 12px;border:1px solid var(--line);border-left:6px solid var(--brass);border-radius:3px;background:var(--surface);margin-bottom:10px;font-size:13.5px}
.dtable{border:1px solid var(--line);border-radius:3px;background:var(--surface);font-size:13.5px}
.dtr{display:grid;grid-template-columns:44px minmax(0,1fr) 150px 150px minmax(0,1fr);gap:4px 10px;align-items:center;padding:6px 10px;border-bottom:1px solid var(--grid);border-left:4px solid transparent}
.dtr:last-child{border-bottom:0}
.dth{font-size:12px;color:var(--sub);background:var(--head)}
.dtr.chg,.dtq.chg{background:var(--warn-bg);border-left-color:var(--seal)}
.dtt{min-width:0;overflow:hidden;text-overflow:ellipsis}
.dtw{color:var(--warn);font-size:12.5px}
.dtq .dtw{margin:0;flex-basis:100%}
.dtr input[type=date]{min-height:34px;padding:2px 8px;font-size:13px;width:100%;box-sizing:border-box}
.dtq input[type=date]{min-height:34px;padding:2px 8px;font-size:13px}
@media (max-width:760px){.dtr{grid-template-columns:44px minmax(0,1fr)}.dth{display:none}.dtr>span:nth-child(n+3){grid-column:2}}
```

- [ ] **Step 4: 古い日付の欄を消す**

`function dueRow(qd, t) {` から、`questDatesRow` の終わり（`    editable ? [st, du, btn] : null);` と `}` の2行。次の行が `// ---- 詳細パネルのタブ（道のり／日付／インプット）と、報告の読み込み`）までを、削除する（`dueRow`・`questDatesRow` を丸ごと消す）。

- [ ] **Step 5: 日付タブを書く**

Task 8 の仮の `datesTab`（コメントの行 `// 日付タブ（Task 9 で、このクエストのガントと日付の表に置き換える）。今は、依頼と Todo ごとの日付の欄を並べる` と、続く `function datesTab(qd) {` から3行）を、次に置き換える。

```js
// ---- 日付タブ：このクエストのガントと、依頼・Todo の日付の表
// 表示の範囲（日番号）。依頼の開始日・締切と Todo の予定日のうち、正しい日付（okDate）だけを使い、前後に1日ずつ足す。
// 正しい日付が1つもなければ今日。狭すぎると読めないので、幅は最低7日
function dateRange(plan) {
  const p = plan || {}, ds = [p.start, p.due, ...(Array.isArray(p.todos) ? p.todos : []).map((t) => t && t.scheduled)].filter(okDate).map(dayNum);
  if (!ds.length) ds.push(dayNum(localToday()));
  const min = Math.min(...ds) - 1, max = Math.max(Math.max(...ds) + 1, min + 6);
  return { min, max };
}
// このクエストのガントのモデル。帯は開始日〜締切、◆ は Todo の予定日（不正なら開始日、それもなければ描かない）
function qGanttModel(plan) {
  const p = plan || {}, r = dateRange(p), start = okDate(p.start) ? p.start : null, due = okDate(p.due) ? p.due : start;
  const todos = (Array.isArray(p.todos) ? p.todos : []).map((t) => ({ id: t.id, title: t.title || '', state: t.state, scheduled: okDate(t.scheduled) ? t.scheduled : start, due: okDate(t.due) ? t.due : null }));
  return { min: r.min, max: r.max, today: dayNum(localToday()), start, due, todos };
}
function questGantt(qd) {
  const m = qGanttModel(qd.q.plan), LABEL = 200, W = 900, ROW = 24, HEAD = 30, n = m.max - m.min + 1, DW = (W - LABEL - 12) / n;
  const x = (d) => LABEL + (d - m.min) * DW + DW / 2, H = HEAD + (m.todos.length + 1) * ROW + 8, every = Math.max(1, Math.ceil(44 / DW));
  const cut = (s, k) => (s.length > k ? s.slice(0, k) + '…' : s);
  const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', role: 'img', 'aria-label': `${qd.id} の予定（帯は開始日から締切、◆ は Todo の予定日）`, class: 'gantt qgantt' });
  for (let d = m.min, k = 0; d <= m.max; d++, k++) {
    svg.append(sv('line', { x1: x(d), x2: x(d), y1: HEAD - 4, y2: H, stroke: 'var(--line)', 'stroke-width': 1, opacity: 0.5 }));
    if (k % every === 0) svg.append(sv('text', { x: x(d), y: 14, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--sub)' }, shortDate(dayStr(d))));
  }
  if (m.today >= m.min && m.today <= m.max) svg.append(sv('line', { x1: x(m.today), x2: x(m.today), y1: HEAD - 4, y2: H, stroke: 'var(--ng)', 'stroke-width': 1.5, 'stroke-dasharray': '4 3' }), sv('text', { x: x(m.today), y: 26, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--ng)' }, '今日'));
  let y = HEAD + ROW / 2;
  svg.append(sv('text', { x: 4, y: y + 4, 'font-size': 12, 'font-weight': 700, fill: 'var(--ink)' }, `${qd.id} ${cut(qd.title, 12)}`));
  if (m.start) { const x1 = x(dayNum(m.start)) - DW / 2, x2 = x(dayNum(m.due)) + DW / 2; svg.append(sv('rect', { x: x1, y: y - 7, width: Math.max(x2 - x1, 6), height: 14, rx: 3, fill: 'var(--surface2)', stroke: 'var(--brass)' })); }
  for (const t of m.todos) {
    y += ROW;
    svg.append(sv('text', { x: 16, y: y + 4, 'font-size': 11, fill: 'var(--sub)' }, `${t.id} ${cut(t.title, 13)}`));
    if (!t.scheduled) continue;
    const cx = x(dayNum(t.scheduled)), s = 6;
    svg.append(sv('path', { d: `M${cx} ${y - s} L${cx + s} ${y} L${cx} ${y + s} L${cx - s} ${y} Z`, fill: STATE_FILL[t.state] || 'var(--mute)', stroke: 'var(--ink)', 'stroke-width': 0.6 },
      sv('title', null, `${t.id} ${t.title}\n予定日 ${t.scheduled}${t.due ? '　締切 ' + t.due : ''}\n${(TSTATE[t.state] || [t.state])[0]}`)));
  }
  return svg;
}
// 依頼の開始日・締切と、Todo ごとの予定日・締切を、まとめて直して送る。下書きは S.form の dt:<依頼>:… に持つ。
// 空の欄は「変えない」（Todo の締切だけは、空にすると解除）。入力中は描き直さず、行の色・注意・ボタンだけをその場で直す（日付の欄の入力位置を保つ）
function datesTab(qd) {
  const p = qd.q.plan, editable = (p.status === 'active' || p.status === undefined) && !p.accepted, k = `dt:${qd.id}`;
  const val = (f, cur) => (S.form[`${k}:${f}`] !== undefined ? S.form[`${k}:${f}`] : (cur || ''));
  const mk = (f, cur, label) => { const i = h('input', { type: 'date', 'aria-label': label, disabled: !editable }); i.value = val(f, cur); bindKey(i, `${k}:${f}`); return i; };
  const qs = mk('start', p.start, '依頼の開始日'), qdue = mk('due', p.due, '依頼の締切'), qwarn = h('p', { class: 'dtw' });
  const qbox = h('div', { class: 'dtq' }, h('b', null, '依頼の日付'), h('label', null, '開始日 ', qs), h('label', null, '締切 ', qdue), qwarn);
  const rows = qd.todos.map((t) => {
    const sch = mk(`${t.id}:scheduled`, t.scheduled, `${t.id} の予定日`), due = mk(`${t.id}:due`, t.due, `${t.id} の締切`), warn = h('span', { class: 'dtw' });
    const tr = h('div', { class: 'dtr', role: 'row' }, h('b', { class: 'tid', role: 'cell' }, t.id), h('span', { role: 'cell', class: 'dtt' }, t.title, ' ', stampEl(t.stamp, t.cls + ' sm')),
      h('span', { role: 'cell' }, sch), h('span', { role: 'cell' }, due), h('span', { role: 'cell' }, warn));
    return { t, sch, due, warn, tr };
  });
  // 送る中身（変わったものだけ）。空の欄は今の値のまま。Todo の締切だけは空＝null（解除）
  const changes = () => {
    const out = [], st = qs.value || p.start, du = qdue.value || p.due;
    if (st !== p.start || du !== p.due) out.push({ type: 'due', start: st, due: du });
    for (const { t, sch, due } of rows) {
      const scheduled = sch.value || t.scheduled, d = due.value || null;
      if (scheduled !== t.scheduled || d !== (t.due || null)) out.push({ type: 'due', todo: t.id, scheduled, due: d });
    }
    return out;
  };
  const btn = h('button', { type: 'button', class: 'btn go sm' });
  const undo = h('button', { type: 'button', class: 'btn ghost sm', onclick: () => { for (const f of Object.keys(S.form)) if (f.startsWith(k + ':')) delete S.form[f]; render(); } }, '元に戻す');
  const sync = () => {
    const probe = { ...p, start: qs.value || p.start, due: qdue.value || p.due };
    probe.todos = qd.todos.map((t, i) => ({ ...t, scheduled: rows[i].sch.value || t.scheduled, due: rows[i].due.value || null }));
    rows.forEach((r, i) => {
      r.tr.classList.toggle('chg', probe.todos[i].scheduled !== r.t.scheduled || probe.todos[i].due !== (r.t.due || null));
      r.warn.textContent = dateIssues(probe, probe.todos[i]).join(' ');
    });
    qbox.classList.toggle('chg', probe.start !== p.start || probe.due !== p.due);
    qwarn.textContent = okDate(probe.start) && okDate(probe.due) && probe.due < probe.start ? '締切が開始日より前です。' : '';
    const n = changes().length;
    btn.textContent = `変更を送る（${n}件）`; btn.disabled = !editable || S.conn !== 'ok' || !n; undo.disabled = !n;
  };
  btn.addEventListener('click', async () => {
    const list = changes(); if (!list.length) return;
    btn.disabled = true;
    for (const body of list) { await send(qd.id, body, `${k}:sent`); if (S.fallback) return; }  // Todo ごとに別の入力（1つ失敗したら止める）
    for (const f of Object.keys(S.form)) if (f.startsWith(k + ':')) delete S.form[f];
    render();
  });
  for (const i of [qs, qdue, ...rows.flatMap((r) => [r.sch, r.due])]) { i.addEventListener('input', sync); i.addEventListener('change', sync); }
  sync();
  const pend = qd.q.inbox.some((x) => x.type === 'due');
  return [
    h('div', { class: 'ganttbox' }, questGantt(qd)),
    h('p', { class: 'fine', style: 'margin:4px 0 12px' }, '帯は依頼の開始日〜締切、◆ は Todo の予定日（色は状態）、赤い点線は今日です。'),
    qbox,
    h('div', { class: 'dtable', role: 'table', 'aria-label': 'Todo の日付' }, h('div', { class: 'dtr dth', role: 'row' }, ['番号', 'Todo', '予定日', '締切', '注意'].map((c) => h('span', { role: 'columnheader' }, c))), rows.map((r) => r.tr)),
    editable ? h('div', { class: 'btns' }, btn, undo, h('span', { class: 'fine', style: 'align-self:center' }, '注意は表示だけで、送れます。日付を変えても、ほかの Todo の日付は自動では動きません。空の欄は今の日付のままです（Todo の締切だけは、空にすると解除）。'))
      : h('p', { class: 'fine' }, '中止・見直し中・受け取り後のクエストの日付は直せません。'),
    pend ? h('p', { class: 'fine', role: 'status' }, '送った日付の変更が、反映を待っています（/guild:quest が動いていれば、すぐ反映されます）。') : null,
    sentNote(`${k}:sent`)];
}
```

`start` の次の部分（Task 7 で直したもの）を、

```js
  window.__guildBoard = { S, render, scheduleModel, ganttSvg, refresh, lsGet, lsSet, boardBucket, boardList, jumpQuest,
```

次に置き換える。

```js
  window.__guildBoard = { S, render, scheduleModel, ganttSvg, refresh, lsGet, lsSet, boardBucket, boardList, jumpQuest, dateRange, qGanttModel,
```

- [ ] **Step 6: 消し残しがないことを確かめる**

Grep（`skills/quest/board.html`）で、次のどれも 0 件であること：`dueRow`、`questDatesRow`、`duerow`、`dwarn`、`class: 'tag'`、`'ttl'`、`qdates:`。

- [ ] **Step 7: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest tests.test_guild.BoardContractTest tests.test_guild.DueTest -v` → PASS。続けて `TEST` が全部通ること。

- [ ] **Step 8: ブラウザで確かめる**（Playwright MCP。1280×900）

1. `?demo=human` を開き、Q001 の「日付」タブを押す。`browser_evaluate`：

   ```js
   () => { const B = window.__guildBoard, p = B.S.model.quests.find((q) => q.id === 'Q001').q.plan, day = (s) => Math.floor(Date.parse(s + 'T00:00:00Z') / 86400000);
     return { r: B.dateRange(p), want: [day(p.start) - 1, day(p.due) + 1], marks: document.querySelectorAll('svg.qgantt path').length,
       today: [...document.querySelectorAll('svg.qgantt text')].some((t) => t.textContent === '今日'),
       btn: [...document.querySelectorAll('.dpanel .btns .btn')].map((b) => [b.textContent, b.disabled]) }; }
   ```

   Expected：`r` が `{min: want[0], max: want[1]}`（見本の Todo の予定日は開始日〜締切の中）、`marks` が 3、`today` が `true`、`btn` が `[["変更を送る（0件）",true],["元に戻す",true]]`。
2. 不正な日付への備え：`browser_evaluate`：

   ```js
   () => { const B = window.__guildBoard, day = (s) => Math.floor(Date.parse(s + 'T00:00:00Z') / 86400000);
     return { a: B.dateRange({ start: 'x', due: '2026-13-45', todos: [{ scheduled: '' }, { scheduled: '2026-10-20' }] }), want: [day('2026-10-20') - 1, day('2026-10-20') + 5],
       b: B.qGanttModel({ todos: [{ id: 'T1', title: 't', state: 'pending', scheduled: 'bad' }] }).todos[0].scheduled, c: B.dateRange({}).max - B.dateRange({}).min }; }
   ```

   Expected：`a` が `{min: want[0], max: want[1]}`、`b` が `null`、`c` が `6`。
3. T2 の予定日を依頼の開始日より前にする：`browser_evaluate`：

   ```js
   () => { const i = document.querySelector('input[aria-label="T2 の予定日"]'); i.value = '2020-01-01'; i.dispatchEvent(new Event('input', { bubbles: true }));
     const tr = i.closest('.dtr'); return { cls: tr.className, warn: tr.querySelector('.dtw').textContent, btn: document.querySelector('.dpanel .btns .btn').textContent }; }
   ```

   Expected：`cls` が `"dtr chg"`、`warn` に「依頼の開始日」、`btn` が `"変更を送る（1件）"`。
4. 「元に戻す」を押す → T2 の予定日が元の値に戻り、ボタンが「変更を送る（0件）」。
5. もう一度手順3を行い、さらに依頼の締切を `2030-01-01` にして（同じやり方で `input[aria-label="依頼の締切"]`）、「変更を送る（2件）」を押す。`browser_evaluate`：

   ```js
   async () => { const fs = window.__guildBoard.S.fs.fs, names = (await fs.list('.work/Q001/inbox')).map((e) => e.name).filter((n) => n.includes('-due'));
     const bodies = []; for (const n of names) bodies.push(JSON.parse(await fs.readText('.work/Q001/inbox/' + n)));
     return { names, bodies, pend: document.querySelector('.dpanel').textContent.includes('反映を待っています') }; }
   ```

   Expected：`names` は `…-due.json` と `…-due-T2.json` の2つ、`bodies` は `{"type":"due","start":<開始日>,"due":"2030-01-01"}` と `{"type":"due","todo":"T2","scheduled":"2020-01-01","due":<T2 の今の締切>}`、`pend` が `true`。表の下書きは消え、ボタンは「変更を送る（0件）」。
6. `?demo=done` を開き、Q001 の日付タブ → 日付の欄が `disabled` で、「受け取り後のクエストの日付は直せません」の旨が出る。
7. `browser_resize` 600×900 で日付タブを開き、表が2列に折り返して横にはみ出さないこと（ガントは `.ganttbox` の中で横にスクロールする）を `browser_take_screenshot` で確かめる。1280×900 に戻す。
8. 各 URL で `browser_console_messages` のエラーが 0 件。

- [ ] **Step 9: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：日付タブに、このクエストのガントと、依頼・Todo の日付の表（変更を送る・元に戻す）を置く"
```

---

### Task 10: ボード — インプットタブと「＋ 新規」ダイアログ（既存から選ぶ・アップロード）、受け付けられなかった依頼

**Files:**
- Modify: `skills/quest/board.html`（CSS の `.qmain` の削除とインプット・ダイアログの追加、`loadAll`・`buildModel` の受け付けられなかった依頼、`inputsTab` の置き換えと `inputsBlock`・`inputPicker`・`sendInputs` の追加、承認の手紙、`composer` の削除、`newDialog`・`newSummary`・`closeNew`・`trapTab` の追加、`openNew`、`boardTab`、`sendRequest`、`render`、`start`、`demoTree`）
- Test: `tests/test_guild.py`（`BoardPathsTest` に `test_inputs_tab_and_new_dialog` を追加、`BoardContractTest.test_board_source_writes_the_same_shapes` に `"type: 'inputs', add:"` を追加）

**Interfaces:**
- Consumes: Task 5 の入力 `{type: 'inputs', add: [名前…], remove: [名前…]}`（`BoardContractTest.CASES` に Part A の Task 5 で足した形）、Task 4 の依頼の形 `{type:'request', text, start, due, inputs, files, created}` と `.work/requests/rejected/<ID>.json`・`<ID>.json.reason.txt`、Task 6 の `S.model.inputs`（`[{name, mtime}]`）・`qd.inputs`・`qd.candidates`・`inbox[j].add`/`.remove`、Task 7 の `openNew`・`KEEP_SCROLL`（`.nbox`・`.iplist` のスクロールを保つ）・`.qsearch`、Task 8 の `detailTabs`（`S.dtab === 'inputs'` のとき `inputsTab(qd)`）、`send`・`fileField`・`fld`・`textarea`・`openFile`・`copyPath`・`sentNote`・`localToday`
- Produces（Task 11・12 が使う）：
  - `sendInputs(qd, names, drops, key)`（`{ type: 'inputs', add: names, remove: drops }` を `send()` で書く）、`inputsEditable(qd)`（計画があり、`active`、受け取り前）、`inputsBlock(qd)`（インプットの一覧と候補。開く・パスをコピー・外す／追加。承認の手紙とインプットタブで使う）、`inputPicker(key, qkey, except)`（`S.form[key]` に選んだ名前の配列、`S.form[qkey]` に検索語。`qkey` は `f:` で始める）、`inputsTab(qd)`
  - `newDialog()`（`S.newOpen` のときだけ、`render` が重ねて出す。`role="dialog"`・`aria-modal="true"`。`Esc` と「閉じる」「やめる」と外側のクリックで閉じ、`Tab` はダイアログの中で回る）、`closeNew()`、`trapTab(e)`、`newSummary(picked, ups, over)`
  - 状態：`S.form['new:text' | 'new:start' | 'new:due' | 'new:inputs' | 'f:npq']`、`S.files.new`、`S.open['ipk:<依頼>']`（インプットタブの「既存から選ぶ」を開いているか）、`S.form['ipk:<依頼>']`、`S.form['f:ipq:<依頼>']`
  - `sendRequest()` が書く依頼：`{ type: 'request', text, start, due, inputs: picked, files: names, created }`（`picked` は `guild/inputs/` の実際の名前。`template` は書かない）。アップロードは今までどおり `requests/files/<ID>/`。
  - `S.model.rejectedRequests`：`[{ id, text, reason }]`（新しい5件）。掲示板の上に知らせを出し、「出し直す」で依頼文を入れたダイアログを開く。
  - 見本：`guild/inputs/` に4ファイル、Q001 の計画に `inputs`（指定1・自動1）と `candidates`（1）、受け付けられなかった依頼1件
  - 消すもの：`composer`（新しい依頼の欄。ダイアログに置き換え）、CSS の `.qmain`

- [ ] **Step 1: 失敗するテストを書く**

`BoardPathsTest` の末尾（`class DocsContractTest(unittest.TestCase):` の直前）に足す。

```python
    def test_inputs_tab_and_new_dialog(self):
        for needle in ("type: 'inputs', add:", "function inputsTab(", "function inputsBlock(", "function inputPicker(", "function newDialog(", "function trapTab(",
                       "'aria-modal': 'true'", "type: 'request', text, start, due, inputs: picked, files: names", "S.fs.list('requests/rejected')",
                       "同名あり（上書き）", "既存から選ぶ", "e.key === 'Escape' && S.newOpen", "rejectedRequests"):
            self.assertIn(needle, self.board)
        for gone in ("function composer(", ".qmain{", "template:", "new:template"):
            self.assertNotIn(gone, self.board)
```

`BoardContractTest.test_board_source_writes_the_same_shapes` の次の部分を、

```python
"type: 'web', add:"):
```

次に置き換える。

```python
"type: 'web', add:", "type: 'inputs', add:"):
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest tests.test_guild.BoardContractTest -v`
Expected: `test_inputs_tab_and_new_dialog` と `test_board_source_writes_the_same_shapes` が FAIL（`type: 'inputs', add:` がない）。

- [ ] **Step 3: CSS を直す**

次の1行（新しい依頼の欄だけが使っていた）を削除する。

```css
.qmain{grid-template-columns:repeat(auto-fit,minmax(220px,max-content));margin:12px 0 0}
```

`<style>` の末尾（Task 9 で足した `@media (max-width:760px){.dtr{…}…}` の後ろ）に、次を足す。

```css
/* インプット（タブ・承認の手紙・「＋ 新規」）と、新しいクエストのダイアログ */
.flist .inm{min-width:0;word-break:break-all}
.ihead{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:6px 12px;margin-bottom:8px}
.ipbox{border:1px solid var(--brass);border-radius:4px;background:var(--surface);padding:10px 12px;margin:8px 0}
.ipick{display:flex;flex-direction:column;gap:6px;min-width:0}
.iplist{max-height:240px;overflow:auto;border:1px solid var(--line);border-radius:4px;background:var(--paper2)}
.ipitem{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--grid);font-size:13.5px;cursor:pointer;word-break:break-all}
.ipitem:has(input:checked){background:var(--sel-bg);font-weight:700}
.ipitem input{width:18px;height:18px;margin:0;accent-color:var(--ok);flex:none}
.nmodal{align-items:flex-start}
.nbox{background:var(--paper2);border:2px solid var(--brass);border-radius:6px;max-width:900px;width:100%;max-height:calc(100vh - 40px);overflow:auto;padding:16px 22px 20px;box-sizing:border-box;overscroll-behavior:contain}
.nbox textarea{min-height:96px}
.ncols{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px 18px}
.ncols .cap{display:block;font-size:13px;margin-bottom:6px}
.nsum{margin:10px 0 0;padding:8px 12px;background:var(--surface);border:1px dashed var(--brass);border-radius:4px}
```

- [ ] **Step 4: 受け付けられなかった依頼を読む**（`loadAll`・`buildModel`）

`loadAll` の次の行の直前に、

```js
  // 冒険者の WebFetch の許可（フックと guild.py が書く）。答えの JSON が web/inbox/ に残っている間は「送信済み」
```

次を足す。

```js
  // 受け付けられなかった依頼（guild.py new が、選んだインプットがないなどの理由で .work/requests/rejected/ へ移したもの）。新しい5件
  const rejectedRequests = [];
  for (const f of (await S.fs.list('requests/rejected')).filter((x) => x.kind === 'file' && x.name.endsWith('.json.reason.txt')).sort((a, b) => b.name.localeCompare(a.name)).slice(0, 5)) {
    const id = f.name.replace(/\.json\.reason\.txt$/, ''), r = await readJSON(`requests/rejected/${id}.json`);
    rejectedRequests.push({ id, text: (r && r.text) || '', reason: (await S.fs.readText(`requests/rejected/${f.name}`)) || '' });
  }
```

`loadAll` の `return` の行（Task 6 で直したもの）を、

```js
  return { requests, quests, archive, archiveWait, archiveRejected, web, inputs, root: (cfg && cfg.root) || '' };
```

次に置き換える。

```js
  return { requests, rejectedRequests, quests, archive, archiveWait, archiveRejected, web, inputs, root: (cfg && cfg.root) || '' };
```

`buildModel` の次の部分を、

```js
  return { root: raw.root, requests: raw.requests,
```

次に置き換える。

```js
  return { root: raw.root, requests: raw.requests, rejectedRequests: raw.rejectedRequests || [],
```

- [ ] **Step 5: インプットタブを書く**

Task 8 の仮の `inputsTab`（コメントの行 `// インプットタブ（Task 10 で、追加・外す・既存から選ぶを足す）。今は、計画のインプットを読むだけ` と、続く `function inputsTab(qd) {` からその関数の終わりまで）を、次に置き換える。

```js
// ---- インプット：このクエストが使うファイル（guild/inputs/）。追加・外すは入力 inputs で送る（plan.json は guild.py が書く）
const TEXT_INPUT = /\.(md|txt|csv)$/i;  // 画面で開けるもの（それ以外は、パスをコピーして開く）
function inputsEditable(qd) { const p = qd.q.plan; return !!p && (p.status === 'active' || p.status === undefined) && !p.accepted; }
function sendInputs(qd, names, drops, key) { return send(qd.id, { type: 'inputs', add: names, remove: drops }, key); }
// インプットの一覧（指定・自動の印と理由）と候補。承認の手紙とインプットタブで使う。同一判定は大文字小文字を区別しない
function inputsBlock(qd) {
  const ed = inputsEditable(qd), have = new Map(S.model.inputs.map((f) => [f.name.toLowerCase(), f]));
  const pend = qd.q.inbox.filter((x) => x.type === 'inputs'), waiting = new Set(pend.flatMap((x) => [...(x.add || []), ...(x.remove || [])]).map((n) => String(n).toLowerCase()));
  const when = (n) => { const f = have.get(n.toLowerCase()); if (!f) return 'guild/inputs/ にありません'; if (!f.mtime) return ''; const d = new Date(f.mtime); return `${d.getMonth() + 1}/${d.getDate()} 更新`; };
  const row = (x, cand) => h('li', null,
    h('span', { class: 'inm' }, h('b', null, x.name), ' ',
      cand ? stampEl('候補', 'sd-draft sm') : stampEl(x.source === 'user' ? '指定' : '自動', x.source === 'user' ? 'sd-ok sm' : 'sd-run sm'),
      waiting.has(x.name.toLowerCase()) ? [' ', stampEl('反映待ち', 'sd-turn sm')] : null,
      h('span', { class: 'fine', style: 'display:block' }, [x.reason, when(x.name)].filter(Boolean).join('　'))),
    h('span', { class: 'acts' },
      TEXT_INPUT.test(x.name) && have.has(x.name.toLowerCase()) ? h('button', { type: 'button', class: 'btn ghost sm', onclick: () => openFile(`inputs/${have.get(x.name.toLowerCase()).name}`) }, '開く') : null,
      h('button', { type: 'button', class: 'btn ghost sm', 'aria-label': `${x.name} のパスをコピー`, onclick: () => copyPath(`inputs/${x.name}`) }, 'パスをコピー'),
      !ed ? null : cand
        ? h('button', { type: 'button', class: 'btn sm', disabled: !have.has(x.name.toLowerCase()) || S.conn !== 'ok', onclick: () => sendInputs(qd, [x.name], [], `in:${qd.id}`) }, '追加')
        : h('button', { type: 'button', class: 'btn ghost sm', disabled: S.conn !== 'ok', onclick: () => sendInputs(qd, [], [x.name], `in:${qd.id}`) }, '外す')));
  return [
    qd.inputs.length ? h('ul', { class: 'flist' }, qd.inputs.map((x) => row(x, false))) : h('p', { class: 'sub' }, 'このクエストのインプットはありません。'),
    qd.candidates.length ? [h('p', { class: 'fine', style: 'margin:8px 0 4px' }, '候補（地図師が迷って選ばなかったもの。「追加」で入れられます）'), h('ul', { class: 'flist' }, qd.candidates.map((x) => row(x, true)))] : null,
    sentNote(`in:${qd.id}`)];
}
// 既存のインプット（guild/inputs/）から選ぶチェックリスト。「＋ 新規」とインプットタブで使う。
// 選んだ名前は S.form[key]（配列）、検索語は S.form[qkey]（f: で始め、入力のたびに絞り込む）。except は出さない名前（小文字の Set）
function inputPicker(key, qkey, except) {
  const q = (S.form[qkey] || '').trim().toLowerCase(), picked = new Set((S.form[key] || []).map((n) => n.toLowerCase()));
  const all = S.model.inputs.filter((f) => !except.has(f.name.toLowerCase())), list = q ? all.filter((f) => f.name.toLowerCase().includes(q)) : all;
  const search = h('input', { type: 'search', class: 'qsearch', placeholder: `ファイル名で探す（全${all.length}件）`, 'aria-label': 'インプットを探す' }); search.value = S.form[qkey] || ''; bindKey(search, qkey);
  const toggle = (name, on) => { const cur = (S.form[key] || []).filter((n) => n.toLowerCase() !== name.toLowerCase()); S.form[key] = on ? [...cur, name] : cur; render(); };
  return h('div', { class: 'ipick' }, search,
    h('div', { class: 'iplist', role: 'group', 'aria-label': '既存のインプット' },
      list.length ? list.map((f) => { const c = h('input', { type: 'checkbox', checked: picked.has(f.name.toLowerCase()) }); bindKey(c, `pk:${key}:${f.name}`); c.addEventListener('change', () => toggle(f.name, c.checked));
        return h('label', { class: 'ipitem' }, c, h('span', null, f.name)); })
        : h('p', { class: 'fine', style: 'margin:6px 8px' }, all.length ? '見つかりません。' : 'guild/inputs/ に選べるファイルはありません。')));
}
function inputsTab(qd) {
  const ed = inputsEditable(qd), key = `ipk:${qd.id}`, open = !!S.open[key], chosen = S.form[key] || [];
  return [
    h('div', { class: 'ihead' }, h('p', { class: 'fine', style: 'margin:0' }, 'このクエストが使うファイル（', code('guild/inputs/'), '）。「指定」は依頼主、「自動」は地図師が選んだものです。'),
      ed ? h('button', { type: 'button', class: 'btn sm', 'aria-expanded': String(open), onclick: () => { S.open[key] = !open; render(); } }, open ? '選ぶのをやめる' : '既存から選ぶ') : null),
    inputsBlock(qd),
    ed && open ? h('div', { class: 'ipbox' }, inputPicker(key, `f:ipq:${qd.id}`, new Set(qd.inputs.map((x) => x.name.toLowerCase()))),
      h('div', { class: 'btns' }, h('button', { type: 'button', class: 'btn go sm', disabled: !chosen.length || S.conn !== 'ok', onclick: async () => { await sendInputs(qd, chosen, [], `in:${qd.id}`); S.form[key] = []; S.open[key] = false; render(); } }, `${chosen.length}件を追加`))) : null,
    h('p', { class: 'fine' }, ed ? '新しいファイルは、「＋ 新規」でクエストを出すときにアップロードします（出したあとのアップロードは、この版ではできません）。' : '中止・見直し中・受け取り後のクエストのインプットは直せません。')];
}
```

- [ ] **Step 6: 承認の手紙に、選ばれたインプットを出す**（書く入力の形は変えない）

承認の手紙（`a.kind === 'approve'`）の次の行の直前に、

```js
      h('label', { class: 'lbl', for: k + 'fix' }, '直してほしいこと（直す場合だけ）'),
```

次の1行を足す。

```js
      h('span', { class: 'lbl' }, `使うインプット（${qd.inputs.length}件。外す・候補の追加は、承認の前でもできます）`), inputsBlock(qd),
```

- [ ] **Step 7: 新しい依頼の欄を、ダイアログに置き換える**

`function composer() {` から、その関数の終わり（Task 7 で `S.newNote ? h('p', { class: 'saved', role: 'status' }, S.newNote) : null);` にした行と、`}` の行）までを、次に置き換える。

```js
// ---- 「＋ 新規」ダイアログ：依頼の内容・開始日（未指定なら今日）・締切（未定なら開始日）・インプット（既存から選ぶ／アップロード）
function newDialog() {
  if (!S.newOpen) return null;
  const have = new Map(((S.model && S.model.inputs) || []).map((f) => [f.name.toLowerCase(), f.name]));
  const ta = textarea('new:text', { id: 'qreq', rows: '4', placeholder: '例：新人向けのオンボーディング資料を見直して、PowerPoint にまとめたい（Ctrl + Enter でも出せます）' });
  ta.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); sendRequest(); } });
  const start = h('input', { type: 'date', 'aria-label': '開始日' }); start.value = S.form['new:start'] || localToday(); bindKey(start, 'new:start');
  const due = h('input', { type: 'date', 'aria-label': '締切' }); due.value = S.form['new:due'] || ''; bindKey(due, 'new:due');
  const picked = S.form['new:inputs'] || [], ups = S.files.new || [], over = ups.filter((f) => have.has(f.name.toLowerCase()));
  const box = h('div', { class: 'nbox', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'new-title' },
    h('div', { class: 'rhead' }, h('h2', { class: 'h2', id: 'new-title' }, '新しいクエスト'), h('button', { type: 'button', class: 'btn ghost sm', onclick: closeNew }, '閉じる')),
    h('label', { class: 'lbl', for: 'qreq' }, '依頼の内容'), ta,
    h('div', { class: 'qopts' }, fld('開始日（未指定なら今日）', start), fld('締切（未定なら開始日と同じ日）', due)),
    h('section', { 'aria-label': 'インプット' },
      h('p', { style: 'margin:14px 0 6px' }, h('b', null, 'インプット（任意）'), h('span', { class: 'fine' }, '　このクエストで使う資料です。納品物の型（見出しの並びなど）も、ここに付けて依頼文で伝えます。', code('guild/inputs/'), ' に1つだけ置かれ、各クエストは名前で参照します。')),
      h('div', { class: 'ncols' },
        h('div', null, h('b', { class: 'cap' }, 'すでにあるファイルから選ぶ'), inputPicker('new:inputs', 'f:npq', new Set())),
        h('div', null, h('b', { class: 'cap' }, '新しくアップロードする'),
          h('p', { class: 'fine', style: 'margin:0 0 6px' }, 'Word・Excel・PDF もそのまま置けます。', h('b', null, '同じ名前のファイルがあると上書きされます'), '（古い版は、このクエストが閉じるまでバックアップに残ります）。'),
          fileField('new', 'アップロードするファイル', true),
          over.length ? h('p', { class: 'warnline', role: 'status' }, '同名あり（上書き）：' + over.map((f) => f.name).join('、')) : null)),
      h('p', { class: 'fine nsum' }, newSummary(picked, ups, over))),
    S.newError ? h('p', { class: 'err', role: 'alert' }, S.newError) : null,
    h('div', { class: 'btns' }, h('button', { type: 'button', class: 'btn go', disabled: S.conn !== 'ok', onclick: sendRequest }, 'クエストを出す'), h('button', { type: 'button', class: 'btn ghost', onclick: closeNew }, 'やめる'),
      h('span', { class: 'fine', style: 'align-self:center' }, '出すと、地図師が Todo に分け、日付も付けて、承認を求めます。')));
  box.addEventListener('keydown', trapTab);
  return h('div', { class: 'reader nmodal', onclick: (e) => { if (e.target === e.currentTarget) closeNew(); } }, box);
}
function newSummary(picked, ups, over) {
  if (!picked.length && !ups.length) return '選んだもの：なし（インプットなしでも出せます）';
  const a = picked.length ? `${picked.join('、')}（既存 ${picked.length}件）` : '';
  const b = ups.length ? `${ups.map((f) => f.name).join('、')}（新規 ${ups.length}件${over.length ? `・うち上書き ${over.length}件` : ''}）` : '';
  return '選んだもの：' + [a, b].filter(Boolean).join(' ＋ ');
}
function closeNew() {
  S.newOpen = false; S.newError = ''; render();
  const b = document.querySelector('.tabs .tools button:last-child'); if (b) b.focus();  // 開いたボタン（タブの右の「＋ 新しい依頼」）へ戻す
}
// ダイアログの中で Tab を回す（最後の次は最初、最初の前は最後）。外の画面にフォーカスが出ないようにする
function trapTab(e) {
  if (e.key !== 'Tab') return;
  const els = [...e.currentTarget.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea, select, a[href]')];
  if (!els.length) return;
  const first = els[0], last = els[els.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
```

`openNew`（Task 7 で書いたもの）全体を、次に置き換える。

```js
function openNew() {
  S.tab = 'board'; S.newOpen = true; S.newSaved = ''; render();
  const ta = document.getElementById('qreq'); if (ta) ta.focus();
}
```

`boardTab` の次の行（Task 7 で書いたもの）を、

```js
  if (S.newOpen) out.push(composer(), h('div', { class: 'btns', style: 'margin:-6px 0 16px' }, h('button', { type: 'button', class: 'btn ghost sm', onclick: () => { S.newOpen = false; S.newError = ''; render(); } }, 'やめる')));
```

次に置き換える（受け付けられなかった依頼の知らせ。「出し直す」は依頼文を入れてダイアログを開く）。

```js
  if (m && m.rejectedRequests.length) out.push(h('div', { class: 'card', role: 'status', style: 'margin-bottom:12px' }, h('b', null, '受け付けられなかった依頼（新しい5件まで）'),
    h('ul', { style: 'margin:6px 0 0' }, m.rejectedRequests.map((r) => h('li', { class: 'fine' }, code(r.id), '「', r.text.split('\n')[0].slice(0, 40), '」：', r.reason, ' ',
      h('button', { type: 'button', class: 'linkbtn', onclick: () => { S.form['new:text'] = r.text; S.form['new:inputs'] = []; openNew(); } }, '出し直す')))),
    h('p', { class: 'fine', style: 'margin:6px 0 0' }, 'この知らせは、', code('guild/.work/requests/rejected/'), ' のファイルを消すと出なくなります。')));
```

`sendRequest` 全体（Task 6・7 で直したもの）を、次に置き換える。

```js
async function sendRequest() {
  const text = (S.form['new:text'] || '').trim();
  S.newError = ''; S.newSaved = ''; S.newNote = '';
  if (!text) { S.newError = '依頼の内容を書いてください。'; render(); return; }
  if (S.conn !== 'ok') { S.newError = '保存先につながっていません。上の「フォルダを選ぶ」から選んでください。'; render(); return; }
  // 選んだ名前が、表示のあとで guild/inputs/ から消されていたら、出さずに知らせる（guild.py new も拒否する）
  const have = new Map(((S.model && S.model.inputs) || []).map((f) => [f.name.toLowerCase(), f.name]));
  const gone = (S.form['new:inputs'] || []).filter((n) => !have.has(n.toLowerCase()));
  if (gone.length) { S.form['new:inputs'] = (S.form['new:inputs'] || []).filter((n) => have.has(n.toLowerCase())); S.newError = `選んだインプットが見つかりません（削除された可能性があります）：${gone.join('、')}。選び直してください。`; render(); return; }
  const id = 'R' + stamp14(new Date()).replace(/^(\d{8})/, '$1-'), files = S.files.new || [], names = [];
  const picked = (S.form['new:inputs'] || []).map((n) => have.get(n.toLowerCase()));
  const start = S.form['new:start'] || localToday(), due = S.form['new:due'] || null;
  try {
    for (const f of files) { await S.fs.writeBlob(`requests/files/${id}/${f.name}`, f); names.push(f.name); }
    await S.fs.writeText(`requests/${id}.json`, JSON.stringify({ type: 'request', text, start, due, inputs: picked, files: names, created: new Date().toISOString() }, null, 2));
  } catch (e) { S.newError = `保存できませんでした（${e.name || 'エラー'}：${e.message || e}）。`; render(); return; }
  S.form['new:text'] = ''; S.form['new:due'] = ''; S.form['new:start'] = ''; S.form['new:inputs'] = []; S.form['f:npq'] = ''; S.files.new = []; S.newSaved = id; S.newOpen = false;
  await refresh(true);
}
```

`render` の次の部分を、

```js
...[reader(), fallbackBox(), toastBox()].filter(Boolean));
```

次に置き換える（読み取り画面・保存失敗の枠は、ダイアログより上に出る）。

```js
...[newDialog(), reader(), fallbackBox(), toastBox()].filter(Boolean));
```

`start` の、`document.addEventListener('compositionstart', …` の行の直前に、次を足す（変換中の `Esc` は変換の取り消しなので、閉じない）。

```js
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.newOpen && !e.isComposing && !S.reader && !S.fallback) { e.preventDefault(); closeNew(); } });
```

- [ ] **Step 8: 見本にインプットを足す**（`demoTree`）

次の行の直後に、

```js
  p2.start = d0(-10); p2.due = d0(-3); p2.todos.forEach((t, i) => { t.scheduled = d0(-9 + i * 2); t.due = d0(-8 + i * 2); });
```

次の2行を足す。

```js
  p1.inputs = [{ name: 'notes.txt', source: 'user', reason: '依頼主の指定' }, { name: 'KGI定義.md', source: 'auto', reason: '要点の書き方の参考（書庫の用語『KPI』のヒント）' }];
  p1.candidates = [{ name: '古い資料.pdf', reason: '中身は読んでいない。名前からは関係が分からない' }]; p2.inputs = []; p2.candidates = [];
```

返す木の次の部分（Task 6 で直したもの）を、

```js
'config.json': J({ python: 'python', root: 'C:\\Users\\demo\\project' }), archive: {
```

次に置き換える。

```js
'config.json': J({ python: 'python', root: 'C:\\Users\\demo\\project' }), inputs: { 'notes.txt': T('- 要点1\n- 要点2\n- 要点3\n- 要点4'), 'KGI定義.md': T('# KGI の定義\n最終目標の達成度を測る指標'), '売上 2026Q3.csv': T('月,売上\n7月,100'), '古い資料.pdf': T('(PDF の見本)') }, archive: {
```

返す木の `requests` の次の部分を、

```js
    requests: { 'R20261010-112800.json': J({ type: 'request', text: '社内の議事録テンプレートを見直してほしい', due: null, files: [] }) },
```

次に置き換える。

```js
    requests: { 'R20261010-112800.json': J({ type: 'request', text: '社内の議事録テンプレートを見直してほしい', start: null, due: null, inputs: [], files: [] }),
      rejected: { 'R20261009-090000.json': J({ type: 'request', text: '売上の資料をまとめてほしい', inputs: ['消えた資料.xlsx'], files: [] }), 'R20261009-090000.json.reason.txt': T('選んだインプットが guild/inputs/ にありません（削除された可能性があります）: 消えた資料.xlsx') } },
```

- [ ] **Step 9: 消し残しがないことを確かめる**

Grep（`skills/quest/board.html`）で、次のどれも 0 件であること：`composer`、`qmain`、`template[^-]`（CSS の `grid-template-columns` は除く）、`'qreq', rows: '2'`。`id: 'qreq'` は `newDialog` の1件だけ。

- [ ] **Step 10: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest tests.test_guild.BoardContractTest tests.test_guild.InputsInputTest tests.test_guild.InputsSelectTest -v` → PASS。続けて `TEST` が全部通ること。

- [ ] **Step 11: ブラウザで確かめる**（Playwright MCP。1280×900）

1. `?demo=human` を開き、Q001 の「インプット」タブを押す。`browser_evaluate`：`() => [...document.querySelectorAll('.dpanel .flist li')].map((li) => li.textContent.replace(/\s+/g, ' ').slice(0, 60))` → `notes.txt 指定 …`、`KGI定義.md 自動 要点の書き方の参考…`、`古い資料.pdf 候補 …`（「追加」）の3行。
2. KGI定義.md の「外す」を押す。`browser_evaluate`：

   ```js
   async () => { const fs = window.__guildBoard.S.fs.fs, n = (await fs.list('.work/Q001/inbox')).map((e) => e.name).find((x) => x.includes('-inputs'));
     return { n, body: JSON.parse(await fs.readText('.work/Q001/inbox/' + n)), wait: document.querySelector('.dpanel').textContent.includes('反映待ち') }; }
   ```

   Expected：`body` が `{"type":"inputs","add":[],"remove":["KGI定義.md"]}`、`wait` が `true`。
3. 「既存から選ぶ」を押す → チェックリストは、計画にない `古い資料.pdf`・`売上 2026Q3.csv` の2件（`.ipbox .ipitem` が2つ）。検索に `browser_type` で `売上` → 1件。チェックして「1件を追加」→ `inbox` に `{"type":"inputs","add":["売上 2026Q3.csv"],"remove":[]}` が書かれる（手順2と同じやり方で、新しい `-inputs` のファイルを読む）。
4. `?demo=plan` を開く → 承認の手紙に「使うインプット（2件。…）」と、notes.txt・KGI定義.md（「外す」つき）と候補の古い資料.pdf（「追加」つき）が出る。
5. 「＋ 新規」（一覧の上）を押す。`browser_evaluate`：`() => ({ dlg: !!document.querySelector('[role=dialog][aria-modal=true]'), focus: document.activeElement.id, start: document.querySelector('.nbox input[aria-label="開始日"]').value })` → `dlg: true`、`focus: "qreq"`、`start` がローカルの今日。`browser_press_key` で `Escape` → ダイアログが消え、`document.activeElement.textContent` が「＋ 新しい依頼」。
6. もう一度開き、依頼の内容に `browser_type` で `KGI の資料を作って` と入れる。チェックリストで KGI定義.md を選ぶ。同名のアップロードを `browser_evaluate` で作る：`() => { const B = window.__guildBoard; B.S.files.new = [new File(['x'], 'kgi定義.MD')]; B.render(); return [document.querySelector('.nbox .warnline').textContent, document.querySelector('.nsum').textContent]; }` → `同名あり（上書き）：kgi定義.MD` と、`選んだもの：KGI定義.md（既存 1件） ＋ kgi定義.MD（新規 1件・うち上書き 1件）`。
7. `Tab` の循環：`browser_evaluate` で `[...document.querySelectorAll('.nbox button:not([disabled])')].pop().focus()`（「やめる」）→ `browser_press_key` で `Tab` → `document.activeElement.textContent` が「閉じる」。`Shift+Tab` → 「やめる」に戻る。
8. 「クエストを出す」を押す。`browser_evaluate`：

   ```js
   async () => { const fs = window.__guildBoard.S.fs.fs, n = (await fs.list('.work/requests')).map((e) => e.name).filter((x) => /^R.*\.json$/.test(x)).sort().pop();
     const id = n.slice(0, -5); return { body: JSON.parse(await fs.readText('.work/requests/' + n)), file: (await fs.list('.work/requests/files/' + id)).map((e) => e.name), dlg: !!document.querySelector('.nbox'), saved: document.querySelector('.saved') && document.querySelector('.saved').textContent }; }
   ```

   Expected：`body` が `{type:"request", text:"KGI の資料を作って", start:<今日>, due:null, inputs:["KGI定義.md"], files:["kgi定義.MD"], created:…}`（`template` がない）、`file` が `["kgi定義.MD"]`、`dlg` が `false`、`saved` に「依頼 R… を預かりました」。
9. 選んだあとで消された：ダイアログを開いて「古い資料.pdf」を選び、`browser_evaluate` で `async () => { const B = window.__guildBoard; delete B.S.fs.fs.root.inputs['古い資料.pdf']; await B.refresh(true); }` を実行してから「クエストを出す」を押す → ダイアログは閉じず、「選んだインプットが見つかりません（削除された可能性があります）：古い資料.pdf」が出て、`.work/requests` に新しい依頼が増えない。
10. 受け付けられなかった依頼：掲示板の上の知らせに `R20261009-090000`「売上の資料をまとめてほしい」と理由が出る。「出し直す」を押すと、依頼文が入ったダイアログが開く。`Esc` で閉じる。
11. 200 件：`browser_evaluate`：

    ```js
    async () => { const B = window.__guildBoard; for (let i = 0; i < 200; i++) B.S.fs.fs.root.inputs[`資料 ${String(i).padStart(3, '0')}.txt`] = { __t: 'x', __m: Date.now() };
      await B.refresh(true); B.S.newOpen = true; const t0 = performance.now(); B.render(); const ms = performance.now() - t0;
      return { ms, items: document.querySelectorAll('.nbox .ipitem').length }; }
    ```

    Expected：`items` が 203（見本の3件＋200件。手順9で1件消したため）、`ms` が 200 未満。検索に `資料 19` と入れると 10 件（`資料 190`〜`資料 199`）に絞られる。リストを下までスクロールしてから1件チェックしても、`.iplist` のスクロール位置が保たれる（`document.querySelector('.iplist').scrollTop` が 0 に戻らない）。
12. 各 URL で `browser_console_messages` のエラーが 0 件。`browser_take_screenshot`：ダイアログ（依頼の内容・開始日・締切・2列のインプット・選んだものの1行・クエストを出す）を目で確かめる。

- [ ] **Step 12: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：インプットタブ（外す・候補の追加・既存から選ぶ）と「＋ 新規」ダイアログ（既存から選ぶ・アップロード・同名の上書きの表示）。受け付けられなかった依頼を知らせる"
```

---

### Task 11: ボード — クエスト進捗のフィルタ（表示するクエスト）と「進捗で見る」

**Files:**
- Modify: `skills/quest/board.html`（CSS の追加、`S`、`scheduleModel` に `ids`、`planClosed`・`progGroup`・`progCandidates`・`progEffective`・`progQuick`・`progLoad`・`setProg`・`progPicker`・`showInProgress` の追加、`progressTab` の置き換え、`questPanel` のツールバー、`start`）
- Test: `tests/test_guild.py`（`BoardPathsTest` に `test_progress_filter` を追加）

**Interfaces:**
- Consumes: Task 7 の `lsGet`・`lsSet`・`boardBucket`・`KEEP_SCROLL`（`.plist` のスクロールを保つ）・`questPanel` の `.qtool`、`scheduleModel`・`ganttSvg`・`humanBars`・`STATE_FILL`・`TSTATE`・`okDate`・`hit`、`S.form['prog:closed']`（「完了・中止した依頼も含める」。今のまま）
- Produces（Task 12・13 が使う）：
  - `scheduleModel(quests, includeClosed, ids)`：`ids`（`Set` か配列。省略・`null` なら今までどおり全部）にある依頼だけを載せる。戻り値の形は変えない（`{ rows, min, max, today, humanDays }`）。
  - `planClosed(qd)`（計画が中止か受け取り済み）、`progGroup(qd) -> 'turn'|'run'|'wait'|'done'`、`progCandidates(quests, includeClosed) -> qd[]`（計画と正しい開始日がある依頼。完了・中止は `includeClosed` のときだけ）、`progEffective(quests, sel, includeClosed) -> Set<id>`（`sel` が `null` なら進行中のすべて。消えた・選べない ID は落とす）、`progQuick(quests, kind) -> id[]`（`'run'`＝進行中だけ、`'turn'`＝自分の番だけ、`'soon'`＝締切が近い5件）、`progLoad()`（`localStorage` の `guild.progress.sel` を読む。配列でなければ `null`、`Q` で始まらない要素は落とす）、`setProg(ids)`（`S.prog.sel` を変えて覚え、描き直す）、`progPicker(m0, inc, eff, base)`、`showInProgress(id)`
  - 状態：`S.prog = { sel: null | string[], open: boolean }`、`S.form['f:pq']`（ポップオーバーの検索）
  - DOM：ボタン `#pbtn`（`aria-haspopup="listbox"`・`aria-expanded`）、ポップオーバー `#ppop`（`role="dialog"`）の中の `#plist`（`role="listbox"`・`aria-multiselectable="true"`）、グループ（`role="group"`、見出し `.pgh` は `position:sticky`）、選択肢 `.popt[role=option][aria-selected]`。`Esc` で閉じてボタンへ戻る、`↑`・`↓` で選択肢を移る、`Space`・`Enter` で選ぶ、外側のクリックで閉じる。
  - 詳細パネルのツールバーに「進捗で見る」（`showInProgress(qd.id)`。計画があるときだけ）
  - `window.__guildBoard` に `progCandidates`・`progEffective`・`progQuick`・`showInProgress` を足す

- [ ] **Step 1: 失敗するテストを書く**（`BoardPathsTest` の末尾、`class DocsContractTest(unittest.TestCase):` の直前に足す）

```python
    def test_progress_filter(self):
        for needle in ("function scheduleModel(quests, includeClosed, ids)", "function progCandidates(", "function progEffective(", "function progQuick(",
                       "function progPicker(", "function showInProgress(", "'guild.progress.sel'", "'aria-haspopup': 'listbox'", "role: 'listbox'",
                       "'aria-multiselectable': 'true'", "表示中の全部を選ぶ", "選択を解除", "進行中だけ", "自分の番だけ", "期限が近い5件", "進捗で見る",
                       ".pgh{position:sticky", "progCandidates, progEffective, progQuick, showInProgress"):
            self.assertIn(needle, self.board)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest -v`
Expected: `test_progress_filter` が FAIL（`function scheduleModel(quests, includeClosed, ids)` がない）。`test_progress_tab_exists` は PASS のまま。

- [ ] **Step 3: CSS を足す**（`<style>` の末尾、Task 10 で足した `.nsum{…}` の後ろ）

```css
/* クエスト進捗のフィルタ（表示するクエスト）。ポップオーバーは、検索・状態ごとのグループ（見出しは固定）・選択の件数 */
.pbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin:8px 0}
.pwrap{position:relative}
.pbtn{font:inherit;font-size:14px;min-height:40px;padding:4px 14px;border:1px solid var(--brass);border-radius:4px;background:var(--surface);color:var(--ink);cursor:pointer}
.ppop{position:absolute;top:calc(100% + 4px);left:0;z-index:30;width:min(420px,90vw);box-sizing:border-box;background:var(--paper2);border:2px solid var(--brass);border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.25);padding:10px;display:flex;flex-direction:column;gap:8px}
.pacts{display:flex;gap:4px 12px;flex-wrap:wrap}
.plist{max-height:320px;overflow:auto;border:1px solid var(--line);border-radius:4px;background:var(--surface)}
.pgh{position:sticky;top:0;z-index:1;display:flex;justify-content:space-between;gap:8px;padding:4px 10px;background:var(--head);font-size:12px;font-weight:700;color:var(--sub)}
.popt{display:grid;grid-template-columns:20px 48px minmax(0,1fr);gap:6px;align-items:center;padding:6px 10px;border-bottom:1px solid var(--grid);font-size:13.5px;cursor:pointer}
.popt[aria-selected="true"]{background:var(--sel-bg)}
.popt .tt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.popt .pmark{display:inline-flex;width:16px;height:16px;align-items:center;justify-content:center;border:1px solid var(--brass);border-radius:3px;font-size:12px;color:var(--on)}
.popt[aria-selected="true"] .pmark{background:var(--seal);border-color:var(--seal)}
.popt:focus-visible{outline:3px solid var(--gold);outline-offset:-3px}
.pfoot{display:flex;align-items:center;justify-content:space-between}
.pquick{display:flex;flex-wrap:wrap;gap:6px}
.ptags{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:4px 0 8px}
.qprog{margin-left:auto}
```

- [ ] **Step 4: 状態と、`scheduleModel` の絞り込みを足す**

`S` の次の部分（Task 8 で直したもの）を、

```js
dtab: 'way', openTodo: null, rcache: {}, kn: { cur: null },
```

次に置き換える。

```js
dtab: 'way', openTodo: null, rcache: {}, prog: { sel: null, open: false }, kn: { cur: null },
```

`scheduleModel` の上のコメントと1行目の、次の2行を、

```js
// 予定のモデル。計画のない依頼は載せない。includeClosed が false なら、完了・中止の依頼を除く
function scheduleModel(quests, includeClosed) {
  const rows = [];
```

次に置き換える（`ids` を省けば今までどおり。描画ごとに1回、`Set` で引く）。

```js
// 予定のモデル。計画のない依頼は載せない。includeClosed が false なら、完了・中止の依頼を除く。ids（Set か配列）があれば、その依頼だけ
function scheduleModel(quests, includeClosed, ids) {
  const rows = [], only = ids == null ? null : (ids instanceof Set ? ids : new Set(ids));
```

`scheduleModel` の次の行の直後に、

```js
    if (!includeClosed && state !== 'active') continue;
```

次の1行を足す。

```js
    if (only && !only.has(q.id)) continue;
```

- [ ] **Step 5: フィルタの関数と、クエスト進捗のタブを書く**

`progressTab` 全体（`function progressTab() {` から、その関数の終わりまで）を、次に置き換える。

```js
// ---- クエスト進捗のフィルタ（表示するクエスト）。選んだ組み合わせは localStorage の guild.progress.sel に覚える（使えなければ毎回、既定）
const LS_PROG = 'guild.progress.sel';
const PROG_GROUPS = [['turn', 'あなたの番'], ['run', '進行中'], ['wait', '受け取り待ち'], ['done', '完了・中止']];
const planClosed = (x) => { const p = x.q.plan; return !!p && (p.status === 'aborted' || !!p.accepted); };  // scheduleModel の「完了・中止」と同じ
const progGroup = (x) => (planClosed(x) ? 'done' : boardBucket(x));
// 選べる依頼：ガントに載せられるもの（計画と正しい開始日がある）。完了・中止は includeClosed のときだけ
function progCandidates(quests, includeClosed) {
  return quests.filter((x) => x.q.plan && okDate(x.q.plan.start) && (includeClosed || !planClosed(x)));
}
// 表示する依頼の ID。sel が null（一度も選んでいない）なら、進行中のすべて。消えた ID・いま選べない ID は落とす
function progEffective(quests, sel, includeClosed) {
  const cands = progCandidates(quests, includeClosed);
  if (sel == null) return new Set(cands.filter((x) => !planClosed(x)).map((x) => x.id));
  const want = new Set(sel);
  return new Set(cands.filter((x) => want.has(x.id)).map((x) => x.id));
}
// すぐ選ぶ：run＝進行中だけ／turn＝自分の番だけ（答えていない手紙がある）／soon＝締切が近い5件（締切が正しい日付の、進行中の依頼）
function progQuick(quests, kind) {
  const act = progCandidates(quests, false);
  if (kind === 'turn') return act.filter((x) => x.asks.some((a) => !a.sent)).map((x) => x.id);
  if (kind === 'soon') return act.filter((x) => okDate(x.q.plan.due)).sort((a, b) => a.q.plan.due.localeCompare(b.q.plan.due) || a.id.localeCompare(b.id)).slice(0, 5).map((x) => x.id);
  return act.map((x) => x.id);
}
function progLoad() { const v = lsGet(LS_PROG, null); return Array.isArray(v) ? v.filter((x) => typeof x === 'string' && /^Q\d+$/.test(x)) : null; }
function setProg(ids) { S.prog.sel = ids == null ? null : [...ids]; lsSet(LS_PROG, S.prog.sel); render(); }
function closeProg() { S.prog.open = false; render(); const b = document.getElementById('pbtn'); if (b) b.focus(); }
// 「表示するクエスト」のボタンとポップオーバー。base は、いまの選択（既定のときは、表示中の ID）
function progPicker(m0, inc, eff, base) {
  const cands = progCandidates(m0.quests, inc), q = (S.form['f:pq'] || '').trim().toLowerCase(), shown = q ? cands.filter((x) => hit(q, x.id, x.title)) : cands;
  const btn = h('button', { type: 'button', class: 'pbtn', id: 'pbtn', 'aria-haspopup': 'listbox', 'aria-expanded': String(!!S.prog.open), 'aria-controls': 'ppop',
    onclick: () => { S.prog.open = !S.prog.open; render(); const s = document.getElementById(S.prog.open ? 'pq' : 'pbtn'); if (s) s.focus(); } },
    '表示するクエスト　', h('b', null, `${eff.size}件`), h('span', { class: 'fine' }, `／${cands.length}件`), ' ▾');
  if (!S.prog.open) return h('div', { class: 'pwrap' }, btn);
  const toggle = (id) => { const cur = new Set(base); if (cur.has(id)) cur.delete(id); else cur.add(id); setProg(cur); };
  const keys = (e, id) => {
    if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(id); return; }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const all = [...document.querySelectorAll('#ppop [role=option]')], i = all.indexOf(e.currentTarget), n = all[i + (e.key === 'ArrowDown' ? 1 : -1)];
    if (n) n.focus(); else if (e.key === 'ArrowUp') { const s = document.getElementById('pq'); if (s) s.focus(); }
  };
  const opt = (x) => h('div', { role: 'option', class: 'popt', tabindex: '-1', 'aria-selected': String(eff.has(x.id)), 'data-key': 'po:' + x.id, onclick: () => toggle(x.id), onkeydown: (e) => keys(e, x.id) },
    h('span', { class: 'pmark', 'aria-hidden': 'true' }, eff.has(x.id) ? '✓' : ''), h('b', null, x.id), h('span', { class: 'tt' }, x.title));
  const groups = PROG_GROUPS.map(([g, label]) => ({ g, label, xs: shown.filter((x) => progGroup(x) === g) })).filter((x) => x.xs.length);
  const search = h('input', { type: 'search', id: 'pq', class: 'qsearch', placeholder: '番号・題名で探す（例：Q009、KPI）', 'aria-label': 'クエストを探す', 'aria-controls': 'plist' });
  search.value = S.form['f:pq'] || ''; bindKey(search, 'f:pq');
  search.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown') { e.preventDefault(); const o = document.querySelector('#ppop [role=option]'); if (o) o.focus(); } });
  const pop = h('div', { class: 'ppop', id: 'ppop', role: 'dialog', 'aria-label': '表示するクエストを選ぶ', onkeydown: (e) => { if (e.key === 'Escape' && !e.isComposing) { e.preventDefault(); e.stopPropagation(); closeProg(); } } },
    search,
    h('div', { class: 'pacts' },
      h('button', { type: 'button', class: 'linkbtn', disabled: !shown.length, onclick: () => setProg(new Set([...base, ...shown.map((x) => x.id)])) }, '表示中の全部を選ぶ'),
      h('button', { type: 'button', class: 'linkbtn', onclick: () => setProg([]) }, '選択を解除')),
    h('div', { class: 'plist', id: 'plist', role: 'listbox', 'aria-multiselectable': 'true', 'aria-label': 'クエスト' },
      groups.length ? groups.map(({ g, label, xs }) => h('div', { role: 'group', 'aria-labelledby': 'pg-' + g },
        h('div', { class: 'pgh', id: 'pg-' + g }, h('span', null, `${label}（${xs.length}）`), h('span', null, `${xs.filter((x) => eff.has(x.id)).length}件選択`)), xs.map(opt)))
        : h('p', { class: 'fine', style: 'margin:8px' }, cands.length ? '見つかりません。' : '選べるクエストはありません。'),
      inc ? null : h('p', { class: 'fine', style: 'margin:8px' }, '完了・中止は、「完了・中止した依頼も含める」を入れると出ます。')),
    h('div', { class: 'pfoot' }, h('span', { class: 'fine' }, `${eff.size}件を選択中`), h('button', { type: 'button', class: 'btn sm', onclick: closeProg }, '閉じる')));
  return h('div', { class: 'pwrap' }, btn, pop);
}
// 詳細パネルの「進捗で見る」：そのクエストだけを選んだ状態で、クエスト進捗を開く（完了・中止なら「含める」も入れる）
function showInProgress(id) {
  const qd = S.model && S.model.quests.find((x) => x.id === id); if (!qd) return;
  if (planClosed(qd)) S.form['prog:closed'] = true;
  S.prog.sel = [id]; lsSet(LS_PROG, S.prog.sel); S.prog.open = false; S.tab = 'prog'; render(); window.scrollTo(0, 0);
}
function progressTab() {
  const m0 = S.model; if (!m0) return h('p', { class: 'sub' }, '保存先につなぐと、ここに表示されます。');
  const inc = !!S.form['prog:closed'], byId = new Map(m0.quests.map((x) => [x.id, x]));
  if (Array.isArray(S.prog.sel)) { const kept = S.prog.sel.filter((id) => byId.has(id)); if (kept.length !== S.prog.sel.length) { S.prog.sel = kept; lsSet(LS_PROG, kept); } }  // 消えた依頼を落とす
  const eff = progEffective(m0.quests, S.prog.sel, inc), base = Array.isArray(S.prog.sel) ? S.prog.sel : [...eff];
  const m = scheduleModel(m0.quests, inc, eff);
  const chk = h('input', { type: 'checkbox', id: 'prog:closed' }); chk.checked = inc; chk.addEventListener('change', () => { S.form['prog:closed'] = chk.checked; render(); });
  const legend = h('div', { class: 'plegend', style: 'margin:6px 0 12px' }, ['pending', 'running', 'waiting_user', 'review', 'done', 'failed', 'skipped'].map((s) => h('span', { class: 'lg' }, h('i', { style: `display:inline-block;width:10px;height:10px;transform:rotate(45deg);margin:0 6px 0 4px;background:${STATE_FILL[s]}` }), TSTATE[s][0])));
  const quick = h('div', { class: 'pquick', role: 'group', 'aria-label': 'すぐ選ぶ' },
    [['run', '進行中だけ'], ['turn', '自分の番だけ'], ['soon', '期限が近い5件']].map(([k, l]) => h('button', { type: 'button', class: 'btn ghost sm', onclick: () => setProg(k === 'run' ? null : progQuick(m0.quests, k)) }, l)));
  const ids = [...eff].sort(), MAX_TAGS = 12;
  const tags = h('div', { class: 'ptags', 'aria-label': '選んだクエスト' }, h('span', { class: 'fine' }, '表示中：'),
    ids.length ? ids.slice(0, MAX_TAGS).map((id) => { const x = byId.get(id); return h('span', { class: 'chip' }, h('b', null, id), ' ', x.title.length > 16 ? x.title.slice(0, 16) + '…' : x.title,
      h('button', { type: 'button', class: 'chipx', 'aria-label': `${id} を外す`, onclick: () => setProg(base.filter((y) => y !== id)) }, '×')); }) : h('span', { class: 'fine' }, 'なし'),
    ids.length > MAX_TAGS ? h('span', { class: 'fine' }, `ほか ${ids.length - MAX_TAGS}件`) : null);
  const hiddenClosed = !inc && Array.isArray(S.prog.sel) && S.prog.sel.some((id) => byId.has(id) && planClosed(byId.get(id)));
  return [h('h2', { class: 'h2' }, 'クエスト進捗'),
    h('p', { class: 'sub', style: 'margin:0 0 8px' }, '依頼は開始日から締切までの帯です（緑の塗りが、合格した Todo の割合）。◆ は Todo の予定日で、色が状態です。赤い点線は今日です。'),
    h('section', { class: 'pbar', 'aria-label': '絞り込み' }, progPicker(m0, inc, eff, base), quick, h('label', { class: 'fine', for: 'prog:closed' }, chk, ' 完了・中止した依頼も含める')),
    tags, legend,
    m.rows.length ? h('div', { class: 'ganttbox' }, ganttSvg(m))
      : h('p', { class: 'sub' }, hiddenClosed ? '選んだクエストは完了・中止です。「完了・中止した依頼も含める」を入れると出ます。' : eff.size ? '選んだクエストに、表示できる予定がありません。' : '表示するクエストが選ばれていません。「表示するクエスト」か、すぐ選ぶボタンから選んでください。'),
    h('h3', { class: 'sec' }, 'あなたの実行（human）の予定日ごとの件数', h('span', { class: 'fine' }, `　表示中の${m.rows.length}件分`)),
    h('p', { class: 'fine', style: 'margin:0 0 6px' }, 'オレンジが未了、緑が済んだ件数です。'), humanBars(m)];
}
```

- [ ] **Step 6: 詳細パネルに「進捗で見る」を足す**（`questPanel`）

`questPanel` の次の行（Task 7 で書いたもの）を、

```js
    S.listOpen ? null : hiddenBar(m, L, i, go));
```

次に置き換える。

```js
    S.listOpen ? null : hiddenBar(m, L, i, go),
    qd && qd.q.plan ? h('button', { type: 'button', class: 'linkbtn qprog', onclick: () => showInProgress(qd.id) }, '進捗で見る') : null);
```

- [ ] **Step 7: 起動時に読み、外側のクリックで閉じる**（`start`）

Task 7 で足した次の行の直後に、

```js
  S.listOpen = lsGet(LS_LIST, true) !== false;  // 前回の「一覧を隠す」。読めない・使えないときは、表示で開く
```

次を足す。

```js
  S.prog.sel = progLoad();  // 前回の「表示するクエスト」。読めない・壊れているときは null（進行中のすべて）
  // ポップオーバーは、外側をクリックすると閉じる。押した部品が描き直しで外れた（isConnected が false）ときは、中の操作なので閉じない
  document.addEventListener('click', (e) => { if (S.prog.open && e.target instanceof Element && e.target.isConnected && !e.target.closest('.pwrap')) { S.prog.open = false; render(); } });
```

`start` の次の部分（Task 9 で直したもの）を、

```js
  window.__guildBoard = { S, render, scheduleModel, ganttSvg, refresh, lsGet, lsSet, boardBucket, boardList, jumpQuest, dateRange, qGanttModel,
```

次に置き換える。

```js
  window.__guildBoard = { S, render, scheduleModel, ganttSvg, refresh, lsGet, lsSet, boardBucket, boardList, jumpQuest, dateRange, qGanttModel, progCandidates, progEffective, progQuick, showInProgress,
```

- [ ] **Step 8: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest -v` → PASS。続けて `TEST` が全部通ること。

- [ ] **Step 9: ブラウザで確かめる**（Playwright MCP。1280×900。最初に `browser_evaluate` で `localStorage.removeItem('guild.progress.sel')` を実行してから開き直す）

1. `?demo=human` を開き、「クエスト進捗」タブを押す。`browser_evaluate`：`() => { const B = window.__guildBoard, g = B.S.model.quests; return { sel: B.S.prog.sel, eff: [...B.progEffective(g, B.S.prog.sel, false)], btn: document.getElementById('pbtn').textContent, rows: B.scheduleModel(g, false, B.progEffective(g, null, false)).rows.map((r) => r.id), all: B.scheduleModel(g, true).rows.map((r) => r.id) }; }` → `sel: null`、`eff: ["Q001"]`、`btn` に「1件」「／1件」、`rows: ["Q001"]`、`all: ["Q001","Q002"]`（`ids` を省くと今までどおり）。
2. 「表示するクエスト」を押す → `#ppop` が出て、フォーカスが検索欄（`#pq`）。「完了・中止した依頼も含める」を入れる → 選択肢が2つ（「あなたの番（1）」に Q001、「完了・中止（1）」に Q002）。Q002 を押す → `localStorage.getItem('guild.progress.sel')` が `["Q001","Q002"]`、ガントに Q002 の帯が増え、件数の見出しが「表示中の2件分」。
3. キーボード：`#pq` にフォーカスして `ArrowDown` → `document.activeElement.getAttribute('role')` が `"option"`。`Space` で選択が切り替わる（`aria-selected` が変わり、フォーカスはその選択肢のまま）。`Escape` → ポップオーバーが閉じ、`document.activeElement.id` が `"pbtn"`。
4. 外側のクリック：開いてから見出し（`h2`）を押す → 閉じる。選択肢を押したときは閉じない（`S.prog.open` が `true` のまま）。
5. タグの「Q001 を外す」（×）を押す → `S.prog.sel` が `["Q002"]`。「完了・中止した依頼も含める」を外す → ガントの代わりに「選んだクエストは完了・中止です。…」が出る。
6. すぐ選ぶ：「自分の番だけ」→ `["Q001"]`、「期限が近い5件」→ `["Q001"]`、「進行中だけ」→ `null`。
7. 覚えていること：「自分の番だけ」を押してから `browser_navigate` で開き直し、クエスト進捗を開く → `S.prog.sel` が `["Q001"]`。壊れた値：`browser_evaluate` で `localStorage.setItem('guild.progress.sel', '["Q999","Q001",3]')` → 開き直してクエスト進捗を開く → `S.prog.sel` が `["Q001"]`（`3` は読み込みで、`Q999` は描画で落ち、`localStorage` も `["Q001"]` に直る）。`localStorage.setItem('guild.progress.sel', 'こわれた')` → 開き直す → `S.prog.sel` が `null`。
8. `localStorage` が使えない：Task 7 の Step 11 の7と同じやり方で `localStorage` を例外にしてから、「自分の番だけ」を押す（`document.querySelector('.pquick button:nth-child(2)').click()`）→ 例外にならず、`S.prog.sel` が `["Q001"]`。元に戻す。
9. 「進捗で見る」：クエスト掲示板で「完了・中止 1件を表示」→ Q002 を選び、ツールバーの「進捗で見る」を押す → タブが「クエスト進捗」、`S.prog.sel` が `["Q002"]`、「完了・中止した依頼も含める」が入っていて、ガントは Q002 だけ。
10. 100 件：`browser_evaluate`：

    ```js
    async () => { const B = window.__guildBoard, now = Date.now(), d0 = (n) => new Date(now + n * 864e5).toISOString().slice(0, 10), J = (o) => ({ __t: JSON.stringify(o), __m: now }), work = {};
      for (let i = 1; i <= 100; i++) { const id = 'Q' + String(i).padStart(3, '0');
        const todos = [1, 2, 3, 4, 5].map((k) => ({ id: 'T' + k, title: '作業 ' + k, kind: k === 3 ? 'human' : 'auto', deps: k > 1 ? ['T' + (k - 1)] : [], criteria: { viewpoint: 'v', pass_line: 'p', check: 'c' }, state: k <= i % 5 ? 'done' : 'pending', scheduled: d0(k + (i % 20) - 10), due: d0(k + (i % 20) - 9) }));
        work[id] = { 'plan.json': J({ quest: id, title: 'クエスト ' + i, approved: true, status: 'active', accepted: i % 10 === 0, start: d0((i % 20) - 10), due: d0((i % 20) - 4), todos, history: [], inputs: [], candidates: [] }), reports: {}, output: {}, inbox: {} }; }
      await B.useFS(new B.PathMap(new B.MemFS({ 'config.json': J({ root: '' }), '.work': work, inputs: {}, archive: {}, deliverables: {} })), true);
      B.S.prog.sel = null; B.S.prog.open = false; B.S.tab = 'prog'; let t0 = performance.now(); B.render(); const prog = performance.now() - t0;
      B.S.prog.open = true; t0 = performance.now(); B.render(); const pop = performance.now() - t0;
      const options = document.querySelectorAll('#ppop [role=option]').length;
      B.S.prog.open = false; B.S.tab = 'board'; t0 = performance.now(); B.render(); const board = performance.now() - t0;
      return { prog, pop, board, options, rows: B.scheduleModel(B.S.model.quests, false, B.progEffective(B.S.model.quests, null, false)).rows.length }; }
    ```

    Expected：`options` と `rows` が 90（10件ごとに受け取り済み＝完了なので除く）、`prog`・`pop`・`board` がそれぞれ 300 未満（ミリ秒）。続けてクエスト進捗でポップオーバーを開き、`#plist` を下までスクロールして選択肢を1つ押しても、スクロール位置が保たれ（`document.getElementById('plist').scrollTop` が 0 に戻らない）、グループの見出し（`.pgh`）が上に固定されていることを `browser_take_screenshot` で確かめる。
11. 各 URL で `browser_console_messages` のエラーが 0 件。

- [ ] **Step 10: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：クエスト進捗を、選んだクエスト（検索つきのリスト・タグ・すぐ選ぶ）で絞れるようにし、選択を覚える。詳細パネルから「進捗で見る」"
```

---

### Task 12: ボード — 書庫の `inputs` 欄、見本、案内文、使われていないコードの掃除

**Files:**
- Modify: `skills/quest/board.html`（`buildModel` の `inputSet`、`archiveForm`・`archiveCard`・`knowTab`、書庫の登録候補の手紙、`demoTree` の書庫、`webTab`・`knowTab`・`helpGrid`・`flowSvg`・`ROLES`・`obsidianTab` の文、`sendRequest` の `S.newNote`、CSS の `.drop`・`.tocb.need`・`.tocb .st`）
- Test: `tests/test_guild.py`（`BoardPathsTest` に `test_help_and_archive_inputs` を追加）

**Interfaces:**
- Consumes: Task 2 の入力 `{type: 'entry', entry: {…, inputs: [...]}, update_of?}`（編集で `inputs` を送れば置き換え、`[]` で空にする）、Task 6 の `parseEntry` の `e.inputs`、Task 6〜11 で足した画面（文の説明の対象）
- Produces（Task 13 が使う）：
  - 書庫の登録・編集欄に「インプット（任意）」（`S.form['a:inputs']`。1行に1つ。1行だけなら `,`・`、` で区切ってもよい）。送る `entry` に、いつも `inputs`（大文字小文字を区別せず重なりを除いた配列）。形の悪い名前（`/` `\` `:`・制御文字・`.`・`..`）は送る前に止める。
  - 書庫のカードに「インプット：…」（`guild/inputs/` にない名前は「（guild/inputs/ にありません）」）。検索は `inputs` も見る。登録候補の手紙に、候補の `inputs` を出す。
  - `S.model.inputSet`（`guild/inputs/` の名前の小文字の `Set`）
  - 見本：書庫の KPI に `inputs: ["KGI定義.md"]`、`archive` の場面の候補 C1 に `inputs: ['notes.txt']`
  - 案内文：ヘルプに「クエスト掲示板の使い方」（一覧・詳細・一覧を隠す・道のり・日付・インプット・進捗で見る）、言葉の説明に「インプット」「書庫の紐づけ」、困ったときに「納品物のテンプレートを使いたい」「冒険の書（やりとりの一覧）はどこ？」「依頼が受け付けられなかった」。`「掲示板」` という呼び方は残さない（「クエスト掲示板」）。
  - Task 13 が README・`docs/board-design.md` に書き写す画面の構成：タブ7つ（クエスト掲示板／クエスト進捗／納品物／書庫／外部サイト／Obsidian／ヘルプ）、詳細のタブ（道のり／日付／インプット）、`localStorage` の2つの鍵（`guild.board.listOpen`・`guild.progress.sel`）

- [ ] **Step 1: 失敗するテストを書く**（`BoardPathsTest` の末尾、`class DocsContractTest(unittest.TestCase):` の直前に足す）

```python
    def test_help_and_archive_inputs(self):
        for needle in ("sec('クエスト掲示板の使い方'", "S.form['a:inputs']", "inputs, summary,", 'inputs: ["KGI定義.md"]', "（guild/inputs/ にありません）",
                       "納品物のテンプレートを使いたい", "冒険の書はなくなりました", "依頼が受け付けられなかった", "inputSet: new Set("):
            self.assertIn(needle, self.board)
        for gone in ("「掲示板」", "掲示板の一覧・目次", "S.newNote", ".drop{", ".tocb.need", ".tocb .st"):
            self.assertNotIn(gone, self.board)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest -v`
Expected: `test_help_and_archive_inputs` が FAIL（`sec('クエスト掲示板の使い方'` がない）。

- [ ] **Step 3: 書庫の項目の `inputs` を、登録・編集・表示する**

`buildModel` の次の部分を、

```js
inputs: raw.inputs || [],
```

次に置き換える。

```js
inputs: raw.inputs || [], inputSet: new Set((raw.inputs || []).map((f) => f.name.toLowerCase())),
```

`archiveForm` の次の行を、

```js
  const reset = () => { for (const f of ['a:edit', 'a:name', 'a:aliases', 'a:summary', 'a:body', 'a:source']) S.form[f] = ''; };
```

次に置き換える。

```js
  const reset = () => { for (const f of ['a:edit', 'a:name', 'a:aliases', 'a:summary', 'a:body', 'a:source', 'a:inputs']) S.form[f] = ''; };
```

`archiveForm` の `send1` の次の行を、

```js
    const entry = { type: S.form['a:type'] || 'term', name, aliases: (S.form['a:aliases'] || '').split(/[、,，]/).map((x) => x.trim()).filter(Boolean), summary, body: (S.form['a:body'] || '').trim(), source: (S.form['a:source'] || '').trim() };
```

次に置き換える（ファイル名には読点やカンマが入りうるので、2行以上あるときは行で区切る。名前の形は guild.py の check_input_name と同じ規則で、送る前に止める）。

```js
    const raw = S.form['a:inputs'] || '', seen = new Set(), inputs = [];
    for (const n of (raw.includes('\n') ? raw.split(/\r?\n/) : raw.split(/[、,，]/)).map((x) => x.trim()).filter(Boolean)) if (!seen.has(n.toLowerCase())) { seen.add(n.toLowerCase()); inputs.push(n); }
    const bad = inputs.filter((n) => /[\\/:\x00-\x1f\x7f]/.test(n) || n === '.' || n === '..');
    if (bad.length) { S.archiveError = `インプットのファイル名に使えない文字があります（/ \\ : など）：${bad.join('、')}`; render(); return; }
    const entry = { type: S.form['a:type'] || 'term', name, aliases: (S.form['a:aliases'] || '').split(/[、,，]/).map((x) => x.trim()).filter(Boolean), inputs, summary, body: (S.form['a:body'] || '').trim(), source: (S.form['a:source'] || '').trim() };
```

`archiveForm` の次の5行を、

```js
  const more = h('details', { class: 'qmore', open: !!S.open['a:more'] }, h('summary', null, '別名・出典をつける（任意）'),
    h('div', { class: 'qopts' },
      fld('別名・略称（読点「、」かカンマで区切る）', inp('a:aliases', '例：精算、経費申請', 'a:aliases')),
      fld('出典・根拠', inp('a:source', '例：経理部の○○さんに確認', 'a:source'))));
```

次に置き換える（上の4行が対象。`more.addEventListener('toggle', …)` の行はそのまま）。

```js
  const more = h('details', { class: 'qmore', open: !!S.open['a:more'] }, h('summary', null, '別名・出典・インプットをつける（任意）'),
    h('div', { class: 'qopts' },
      fld('別名・略称（読点「、」かカンマで区切る）', inp('a:aliases', '例：精算、経費申請', 'a:aliases')),
      fld('出典・根拠', inp('a:source', '例：経理部の○○さんに確認', 'a:source')),
      h('div', { class: 'fld wide' }, h('label', { class: 'cap', for: 'a:inputs' }, 'インプット（任意。guild/inputs/ のファイル名を1行に1つ）'),
        textarea('a:inputs', { id: 'a:inputs', rows: '2', placeholder: '例：KGI定義.md' }),
        h('span', { class: 'fine' }, '依頼文にこの項目の名前・別名が出てきたとき、ここに書いたファイルが、地図師に「関係がありそう」と勧められます。ファイルがなくても保存できます。'))));
```

`archiveCard` の次の行の直後に、

```js
    e.aliases.length ? h('p', { class: 'fine', style: 'margin:0 0 6px' }, '別名：' + e.aliases.join('、')) : null,
```

次の1行を足す。

```js
    e.inputs.length ? h('p', { class: 'fine', style: 'margin:0 0 6px' }, 'インプット：', e.inputs.map((n, i) => [i ? '、' : '', n, S.model.inputSet.has(n.toLowerCase()) ? '' : '（guild/inputs/ にありません）'])) : null,
```

`archiveCard` の「編集」ボタンの `onclick` の中の次の部分を、

```js
S.form['a:source'] = e.source === '依頼主の登録' ? '' : (e.source || '');
```

次に置き換える（編集では、いまの `inputs` を入れて送る。消せば `[]` が送られ、空になる）。

```js
S.form['a:source'] = e.source === '依頼主の登録' ? '' : (e.source || ''); S.form['a:inputs'] = e.inputs.join('\n'); S.open['a:more'] = true;
```

`knowTab` の次の部分を、

```js
hit(q, e.name, e.summary, e.body, ...e.aliases)
```

次に置き換える。

```js
hit(q, e.name, e.summary, e.body, ...e.aliases, ...e.inputs)
```

書庫の登録候補の手紙（`letterFor` の `a.kind === 'archive'`）の次の行の直後に、

```js
          h('p', { class: 'fine', style: 'margin:0 0 4px' }, '出典：' + (c.source || 'なし') + (c.update_of ? `　更新先：${c.update_of}` : '')),
```

次の1行を足す。

```js
          Array.isArray(c.inputs) && c.inputs.length ? h('p', { class: 'fine', style: 'margin:0 0 4px' }, 'インプット：' + c.inputs.join('、')) : null,
```

- [ ] **Step 4: 見本の書庫に `inputs` を足す**（`demoTree`）

書庫の KPI の項目の文字列の次の部分を、

```js
type: term\naliases: ["重要業績評価指標"]\nconfidence: confirmed
```

次に置き換える。

```js
type: term\naliases: ["重要業績評価指標"]\ninputs: ["KGI定義.md"]\nconfidence: confirmed
```

`archive` の場面の候補 C1 の次の部分を、

```js
source: 'Q001/output/T1/digest.md' }
```

次に置き換える。

```js
source: 'Q001/output/T1/digest.md', inputs: ['notes.txt'] }
```

- [ ] **Step 5: 案内文を新しい画面に合わせる**

`webTab` の次の部分を、

```js
リストにないサイトを開こうとしたときは、「掲示板」の手紙でお聞きします。
```

次に置き換える。

```js
リストにないサイトを開こうとしたときは、「クエスト掲示板」の手紙でお聞きします。
```

`webTab` の `'掲示板の手紙で答える'` を `'クエスト掲示板の手紙で答える'` に置き換える。

`knowTab` の次の部分を、

```js
依頼が終わるたびに、司書が登録候補を挙げます（「掲示板」の手紙で選びます）。
```

次に置き換える。

```js
依頼が終わるたびに、司書が登録候補を挙げます（「クエスト掲示板」の手紙で選びます）。項目に「インプット」（guild/inputs/ のファイル名）を付けておくと、依頼文にその項目の名前が出てきたとき、地図師にそのファイルが勧められます。
```

`flowSvg` の次の行を、

```js
  box(20, 20, 'me', '依頼を書く', '「依頼」ボタン');
```

次に置き換える。

```js
  box(20, 20, 'me', '依頼を書く', '「＋ 新規」で出す');
```

`ROLES` の地図師の次の部分を、

```js
'依頼を Todo に分け、前提・種別（自動／あなた）・確認の印・合格基準・納品物になる Todo を決めます。
```

次に置き換える。

```js
'依頼を Todo に分け、使うインプットを理由つきで選び（迷うものは候補に）、前提・種別（自動／あなた）・確認の印・合格基準・納品物になる Todo を決めます。
```

`helpGrid` の「使い方」の次の3つの文を、それぞれ置き換える。

```js
'「掲示板」の上の欄に内容を書いて、「依頼」を押します。'
```

→

```js
'「クエスト掲示板」の「＋ 新規」で、依頼の内容・開始日・締切を書き、使う資料（インプット）を既存から選ぶかアップロードして、「クエストを出す」を押します。'
```

```js
'依頼が Todo に分けられて、「道のり」が出ます。承認はこの1回だけです。'
```

→

```js
'依頼が Todo に分けられ、承認の手紙が出ます。使うインプット（あなたの「指定」と、地図師が理由つきで選んだ「自動」）も、ここで外したり、候補から追加したりできます。承認はこの1回だけです。'
```

```js
'自動でできるものは進みます。あなたの番のときと、確認や判断が要るときだけ、「掲示板」に手紙が出ます。'
```

→

```js
'自動でできるものは進みます。あなたの番のときと、確認や判断が要るときだけ、「クエスト掲示板」の詳細に手紙が出ます。'
```

`helpGrid` の、`sec('スキルの使い方（チャットで使う）', …` の行の直前に、次を足す（「使い方」の次のカード）。

```js
    sec('クエスト掲示板の使い方', dl([
      ['一覧', '左にクエストの一覧があります。番号・題名で探せ、状態（すべて／あなたの番／進行中／受け取り待ち／完了）で絞れます。完了・中止は、ふだんは畳んであります。'],
      ['詳細', '行を押すと、右に詳細が出ます。上に「あなたの番」の手紙、下にタブ「道のり」「日付」「インプット」があります。'],
      ['一覧を隠す', '詳細を横幅いっぱいにします。上のツールバーの「‹ ›」で前後のクエストへ移り、検索で番号・題名から開けます。隠したことは、このブラウザが覚えます。狭い画面では、一覧と詳細を切り替えます（「‹ 一覧へ戻る」）。'],
      ['道のり', 'Todo の一覧です。行を開くと、合格基準と報告（冒険者・斥候・鑑定士・あなた）が読めます。失敗の判断の手紙には、鑑定士の指摘が出ます。'],
      ['日付', 'このクエストのガントと、依頼の開始日・締切、Todo の予定日・締切の表です。直して「変更を送る」を押します。順序の矛盾は注意だけで、ほかの日付は自動では動きません。'],
      ['インプット', 'このクエストが使うファイルです。「外す」「追加」「既存から選ぶ」で直せます（承認の前でも後でも）。'],
      ['進捗で見る', 'このクエストだけを選んだ状態で、「クエスト進捗」を開きます。']])),
```

`helpGrid` の「印の見方」の次の部分を、

```js
'依頼の状態（掲示板の一覧・目次・絞り込みで使います）'
```

次に置き換える。

```js
'依頼の状態（クエスト掲示板の一覧で使います）'
```

`helpGrid` の「言葉の説明」の `['心得', …]` の要素の直前に、次の2つの要素を足す。

```js
['インプット', '依頼で使う資料（guild/inputs/ に1つだけ置き、各クエストは名前で参照）。あなたが「＋ 新規」で選んだものが「指定」、地図師が依頼文と書庫をもとに理由つきで選んだものが「自動」です。地図師が迷ったものは「候補」になります。'], ['書庫の紐づけ', '書庫の項目に「インプット」を書いておくと、依頼文にその項目の名前・別名が出てきたとき、地図師にそのファイルが勧められます（確認済み・出典ありの項目の、3文字以上の語だけ）。'],
```

`helpGrid` の「困ったとき」の次の2つを、それぞれ置き換える。

```js
      faq('予定や進み具合を見たい', '「クエスト進捗」のタブに、依頼ごとの帯と Todo の予定日（◆）、あなたの実行の日ごとの件数が出ます。日付は掲示板の依頼の「道のり」で直せます。'),
```

→

```js
      faq('予定や進み具合を見たい', '「クエスト進捗」のタブに、選んだクエストの帯と Todo の予定日（◆）、あなたの実行の日ごとの件数が出ます。「表示するクエスト」で絞れ、選んだものはこのブラウザが覚えます。日付は、クエスト掲示板の詳細の「日付」タブで直せます。'),
      faq('納品物のテンプレートを使いたい', 'テンプレートの欄はありません。型にしたいファイルを「＋ 新規」でインプットとして付け、依頼文に「KGI定義.md の見出しに沿って」のように書いてください。'),
      faq('冒険の書（やりとりの一覧）はどこ？', '冒険の書はなくなりました。役の報告は、クエスト掲示板の詳細の「道のり」で、Todo の行を開くと読めます。'),
      faq('依頼が受け付けられなかった', '選んだインプットが、出したあとで guild/inputs/ から消されると、依頼は受け付けられず、クエスト掲示板の上に理由が出ます。「出し直す」から、インプットを選び直して出してください。'),
```

```js
      faq('依頼を取り消したい', '進行中なら、失敗の判断で「この依頼を中止する」を選べます。受付待ちの依頼は、', code('guild/.work/requests/'), ' の該当ファイルを削除してください。'))));
```

→

```js
      faq('依頼を取り消したい', '進行中なら、詳細の下の「この依頼を中止する」か、失敗の判断で選べます。受付待ちの依頼は、一覧の「取り消す」で取り消せます（', code('guild/.work/requests/'), ' の該当ファイルを削除しても同じです）。'))));
```

`obsidianTab` の「項目の書き方（書庫）」の例の次の部分を、

```js
'aliases: ["重要業績評価指標"]', 'confidence: confirmed',
```

次に置き換え、

```js
'aliases: ["重要業績評価指標"]', 'inputs: ["KGI定義.md"]', 'confidence: confirmed',
```

その下の `dl([['type', …], ['confidence', …], ['status', 'active／要確認／廃止']])` の `['status', 'active／要確認／廃止']` の直後に、要素 `, ['inputs', '関係する guild/inputs/ のファイル名（任意）。依頼文にこの項目の名前が出ると、地図師にそのファイルが勧められます']` を足す。

- [ ] **Step 6: 使われていないコードと CSS を消す**

`sendRequest` の次の部分を、

```js
  S.newError = ''; S.newSaved = ''; S.newNote = '';
```

次に置き換える（`S.newNote` を表示する場所は、Task 10 で新しい依頼の欄と一緒になくなった）。

```js
  S.newError = ''; S.newSaved = '';
```

使われていない CSS のクラスを洗い出す（リポジトリのルートで実行）。

```bash
python -I - <<'EOF'
import re, pathlib
s = pathlib.Path("skills/quest/board.html").read_text(encoding="utf-8")
css = s.split("<style>", 1)[1].split("</style>", 1)[0]
rest = s.replace(css, "")
names = sorted(set(re.findall(r"\.([a-zA-Z][\w-]*)", css)))
print([n for n in names if not re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", rest)])
EOF
```

Expected（Task 6〜11 のあと）：`['drop', 'need', 'pane-detail', 'pane-list']`。`pane-list`・`pane-detail` は `pane-${S.pane}` で作るので残す。ほかの名前が出たら、Grep で使われていないことを確かめてから、その規則を消す。次の2行を削除する。

```css
.drop{border:2px dashed var(--brass);border-radius:4px;padding:12px;text-align:center;font-size:13.5px;color:var(--sub);background:var(--surface2)}
```

```css
.tocb.need{box-shadow:inset 4px 0 0 var(--warn)}
```

依頼の目次（Task 7 で消した `questToc`）だけが使っていた次の1行も削除する（書庫の目次のボタンは `.id`・`.tt` だけを使う）。

```css
.tocb .st{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
```

使われていない関数を洗い出す。

```bash
python -I - <<'EOF'
import re, pathlib
s = pathlib.Path("skills/quest/board.html").read_text(encoding="utf-8")
js = s.split("<script>", 1)[1]
names = re.findall(r"function (\w+)\(", js) + re.findall(r"const (\w+) = (?:\([^)]*\)|\w+) =>", js)
print([n for n in names if len(re.findall(r"(?<![\w.])" + n + r"\b", js)) < 2])
EOF
```

Expected：`[]`。名前が出たら、Grep で呼び出しがないことを確かめてから消す。

最後に、Grep（`skills/quest/board.html`）で次のどれも 0 件であること：`「掲示板」`、`掲示板の`（「クエスト掲示板の」は除く。`[^ト]掲示板の` で探す）、`newNote`、`templates`、`talkTab`、`questToc`、`ledger`、`ganttBlock`、`dueRow`、`composer`、`S\.tq`、`openQ`、`focusQ`。

- [ ] **Step 7: 通ることを確かめる**

Run: `python -m unittest tests.test_guild.BoardPathsTest tests.test_guild.BoardContractTest tests.test_guild.RoleModelsTest tests.test_guild.ArchiveInputsTest -v` → PASS。続けて `TEST` が全部通ること（`DocsContractTest` は Task 13 で README・`docs/board-design.md` を直すまで、この Task の変更では変わらない）。

- [ ] **Step 8: ブラウザで確かめる**（Playwright MCP。1280×900）

1. `?demo=archive` を開く → 書庫の登録候補の手紙の C1 に「インプット：notes.txt」が出る。
2. 「書庫」タブ → KPI のカードを開くと「インプット：KGI定義.md」（見本の `guild/inputs/` にあるので、「ありません」は付かない）。検索に `KGI定義` と入れると KPI が見つかる。
3. KPI の「編集」を押す → 「別名・出典・インプットをつける」が開き、インプットの欄が `KGI定義.md`。`browser_evaluate` で欄を `KGI定義.md\n売上 2026Q3.csv\nkgi定義.md` にして（`document.getElementById('a:inputs')` の `value` を変え、`input` イベントを出す）、「更新」を押す。`browser_evaluate`：

   ```js
   async () => { const fs = window.__guildBoard.S.fs.fs, n = (await fs.list('.work/archive-inbox')).map((e) => e.name).filter((x) => x.includes('entry')).pop();
     return JSON.parse(await fs.readText('.work/archive-inbox/' + n)); }
   ```

   Expected：`{type:"entry", update_of:"KPI.md", entry:{…, inputs:["KGI定義.md","売上 2026Q3.csv"], …}}`（大文字小文字だけ違う重なりは除かれる）。
4. 新しい項目で、インプットに `a/b.txt` と書いて「登録」→「インプットのファイル名に使えない文字があります（/ \ : など）：a/b.txt」が出て、`archive-inbox` に増えない。
5. 「ヘルプ」タブ → 「クエスト掲示板の使い方」のカードと、「困ったとき」に「納品物のテンプレートを使いたい」「冒険の書（やりとりの一覧）はどこ？」「依頼が受け付けられなかった」がある。`browser_evaluate` で `document.querySelector('.panel').textContent.includes('「掲示板」')` が `false`。
6. 通しの確認：`?demo=human`・`?demo=accept`・`?demo=failed`・`?demo=plan`・`?demo=questions`・`?demo=archive` を順に開き、それぞれで7つのタブを全部押す（Task 6 の Step 11 の2の `browser_evaluate` を使う。`shown` がすべて `true`）。クエスト掲示板では、一覧の各行を押して詳細の3つのタブを全部開く（`browser_evaluate`：`async () => { for (const b of [...document.querySelectorAll('.qli[data-q]')]) { document.querySelector(`.qli[data-q="${b.dataset.q}"]`).click(); for (const k of ['way', 'dates', 'inputs']) { const t = document.getElementById('dtab-' + k); if (t) { t.click(); await new Promise((r) => setTimeout(r, 30)); } } } return document.querySelectorAll('.qpanel').length; }`）。
7. 各 URL で `browser_console_messages` のエラーが 0 件であることを、URL ごとに記録する（6つすべて 0 件）。`browser_take_screenshot` を `?demo=human`（クエスト掲示板）・`?demo=failed`（判断の手紙と鑑定士の指摘）・`?demo=plan`（承認の手紙とインプット）で撮り、Task 13 の報告に使う。

- [ ] **Step 9: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ボード：書庫の項目にインプットを付けられるようにし、見本と案内文を新しい画面に合わせ、使われていないコードと CSS を消す"
```

---


---

### Task 13: 総点検（README・SKILL・指示書・docs）と、動作テスト

**Files:**
- Modify: `README.md`、`skills/quest/SKILL.md`、`skills/init/SKILL.md`、`agents/*.md`（5つ）、`docs/spec.md`、`docs/graph-format.md`、`docs/board-design.md`、`docs/archive-spec.md`、`docs/roles-spec.md`、`docs/plan-guild-py.md`（古ければ）、`.claude-plugin/plugin.json`・`.claude-plugin/marketplace.json`（説明文）
- Modify: `tests/test_guild.py`（`DocsContractTest` に追加）
- 触らない: `docs/2026-*`（過去の記録）、`docs/specs/`、`docs/superpowers/plans/`

**Interfaces:**
- Consumes: Task 1〜12 のすべて。特に Part A の Task 3〜5（`inputs-list`、`plan.json` の `inputs`/`candidates`、入力 `inputs`）と、Part B の Task 7〜12（タブ構成、`localStorage` の鍵 `guild.board.listOpen`・`guild.progress.sel`）。
- Produces: なし（文書の整理と、テスト・確認の記録）。

> この Task は、機械的な置換ではなく**読んで直す**作業。1つの文書を直したら、その文書が正しいことを、コードやコマンドの実行で確かめる。置換には Edit ツールを使い、`sed` は使わない（バッククォートや `Q###` を壊した前例がある）。

- [ ] **Step 1: 棚卸し（読むだけ。何も変えない）**

次を実行して、結果を `Task 13 のメモ`（スクラッチパッドの `inspect.md`）に書き出す。

```bash
# 1) CLI のコマンド一覧（正本は guild.py の main() の許可リスト）
python skills/quest/guild.py 2>&1 | head -40
python - <<'PY'
import re
src = open("skills/quest/guild.py", encoding="utf-8").read()
m = re.search(r'argv\[1\] not in \(([^)]*)\)', src)
print(sorted(re.findall(r'"([a-z-]+)"', m.group(1))))
PY

# 2) 旧語・消した機能の残り（ライブな文書だけ。docs/2026-*、docs/specs、docs/superpowers は除く）
grep -rnE "template|テンプレート|冒険の書|questToc|\.mcp\.json|plugin_guild_browser|Node\.js|guild/Q[0-9#]|guild/requests|guild/web/|lessons/|terms/|7つ|format:" README.md skills agents docs/*.md .claude-plugin | grep -v "docs/2026-" | grep -v "__pycache__"

# 3) ボードの語（Part B の Task 13 用リスト）
grep -nE "talkTab|messagesOf|roleOf|S\.tq|S\.role|msgKey|stateFilter|pageOf|filterQuests|openQ|focusQ|S\.stf|goCompose|qitem|ganttBlock|ganttOf|BARKIND|todoTags|dueRow|questDatesRow|duerow|composer|qmain|newNote|templates|tplSel|newtpl" skills/quest/board.html
```

見るもの：(1) の出力が、README のコマンド表・`docs/graph-format.md` のコマンド表・`skills/quest/SKILL.md` の呼び出しと食い違っていないか。(2)(3) の各行が、**歴史の記述として意図して残したもの**か、**消し忘れ**か。消し忘れは次の Step で消す。(3) は `skills/quest/board.html` に**1行も出ない**のが正（出たら Task 6〜12 の消し残し。その場で消し、理由をメモに残す）。

- [ ] **Step 2: 不要な箇所と重複の削除（文書ごとに読む）**

文書ごとの役割を、次のとおりに分け、重なりは「詳しく書く場所を1つに決め、他からはリンクにする」。

| 文書 | 書くこと | 書かないこと |
|---|---|---|
| `README.md` | 何をするものか、特長、必要なもの、導入、使い方（4〜6手順）、コマンド表（利用者が打つものだけ）、役の表（1行ずつ）、ボードのタブ表（1行ずつ）、データの置き場（ツリー）、開発（構成とテストの実行）、ライセンス | 入力 JSON の形、状態遷移の細部、`guild.py` の全コマンド、画面の操作の手順（ヘルプに任せる） |
| `skills/quest/SKILL.md` | ギルドマスターがやる手順（受付→分解→承認→実行ループ→納品→書庫）と守ること。`guild.py` の呼び出し方 | 設計の理由、画面の説明 |
| `skills/init/SKILL.md` | `/guild:init` の手順（MCP の確認、Python の探し方、初期化、結果の伝え方） | 依頼の流れ |
| `agents/*.md` | 各役の入力・手順・報告の形・守ること | 他の役の手順、`guild.py` の内部 |
| `docs/graph-format.md` | `plan.json`／`transitions.json`／`request.json`／入力 JSON の形、`guild.py` の全コマンド表 | 画面の説明 |
| `docs/board-design.md` | ボードの設計（タブ、クエスト掲示板の構成、詳細のタブ、クエスト進捗のフィルタ、`localStorage` の鍵、`.work` の読み書き） | `guild.py` の使い方 |
| `docs/archive-spec.md` | 書庫の設計（項目の形、`inputs`、ヒント、確度、管理） | ボードの画面 |
| `docs/roles-spec.md` | 役の分担とモデル | 手順の細部 |
| `docs/spec.md` | 全体の目的と原則 | 個別機能の細部（上記の文書へのリンクにする） |

削除する基準（各文書を上から読み、1段落ずつ判定する）：
1. 消した機能（冒険の書、納品物のテンプレート、`format`、同梱 MCP、`Q###` を `guild/` 直下に置く説明など）の説明は、**歴史として必要な場合を除き**消す。決定ログの表の行は残してよいが、「今の仕様」の文には書かない。
2. 同じことが2か所以上に詳しく書かれていたら、正本を1つに決め、他は1文＋リンクに縮める。
3. 「〜予定」「後で」のまま、実装が済んだことを書いている文は、現在形に直す。

- [ ] **Step 3: 足りない記述の追記（チェックリスト）**

次の項目が、それぞれ指定の文書に**書かれているか**を読んで確かめ、なければ足す。

| 書くこと | 文書 |
|---|---|
| タブは7つ（クエスト掲示板／クエスト進捗／納品物／書庫／外部サイト／Obsidian／ヘルプ）。クエスト掲示板は、左に一覧・右に詳細（道のり／日付／インプット）。左は隠せる。クエスト進捗はクエストで絞れる | `README.md`、`docs/board-design.md` |
| `localStorage` の鍵 `guild.board.listOpen`、`guild.progress.sel`（使えなくても動く） | `docs/board-design.md` |
| インプットは `guild/inputs/` に1つだけ。同名は上書き、古い版は `.work/backup/` に残り、閉じたとき（`guild.py close`）に消える。地図師が自動選択（理由つき）し、依頼主が指定・追加・外す | `README.md`（要点）、`docs/graph-format.md`、`skills/quest/SKILL.md` |
| `guild.py` の全コマンド（`init` `new` `requests` `arrivals` `wait` `answers` `adopt` `validate` `sync` `next` `advance` `ingest` `publish` `close` `inputs-list` `archive-propose` `archive-ingest` `web-ingest` `web-pending` `web-reset`）が、表のどこかにある | `docs/graph-format.md` |
| 入力 JSON の種類（`approve` `accept` `confirm` `result` `decision` `due` `inputs` ほか）と形 | `docs/graph-format.md` |
| `plan.json` の `start` `due` `inputs` `candidates` と、Todo の `scheduled` `due`。日付の矛盾は警告表示だけで、連動してずらさない | `docs/graph-format.md`、`docs/board-design.md` |
| 納品物は `guild/deliverables/Q###_…` に、全 Todo が済んだとき（受け取りの入力でも）置かれる。`*.prompt.md` は Claude Code に渡すプロンプト | `README.md`、`skills/quest/SKILL.md` |
| 書庫の項目の `inputs` と、`inputs-list` のヒントの出し方（確認済み・出典ありのみ、3文字以上） | `docs/archive-spec.md` |
| Playwright MCP が必要で、`/guild:init` が確認する | `README.md`、`skills/init/SKILL.md` |
| 実フォルダで使うときは、Chrome か Edge。`.work`（先頭が `.` のフォルダ）を読み書きする | `README.md` |

- [ ] **Step 4: 誤りの修正（書いてあることを、コードで確かめる）**

文書ごとに、事実の主張（コマンド名・引数・ファイルの場所・JSON の鍵・状態名・タブ名・フォルダ名・数）を、**1つずつコードで確かめる**。確かめ方：

```bash
# コマンドと引数: guild.py の docstring と main() を読み、文書の表と突き合わせる
sed -n 1,40p skills/quest/guild.py            # Read ツールで読んでよい
# JSON の鍵: docs/graph-format.md の plan.json の例を、Step 7 の通しスクリプトが出す plan.json と見比べる
# タブ名・フォルダ名: board.html の tabs 配列、init_guild の作るフォルダ
grep -n "\['board', 'クエスト掲示板'\]" skills/quest/board.html
python - <<'PY'
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, "skills/quest")
import guild
with tempfile.TemporaryDirectory() as d:
    guild.init_guild(Path(d))
    print(sorted(p.name for p in (Path(d) / "guild").iterdir()))
PY
```

見つけた誤りは、その場で Edit で直す。直したものを、メモに `文書: 誤り → 直し` の形で残す。

- [ ] **Step 5: 契約テストを足す（失敗を確かめてから、文書を直したものが通ることを確かめる）**

`tests/test_guild.py` の `DocsContractTest` に追加する。

```python
    def test_every_cli_command_is_documented(self):
        """guild.py の main() の許可リストにあるコマンドは、docs/graph-format.md のコマンド表のどこかに出てくる。"""
        src = (ROOT / "skills" / "quest" / "guild.py").read_text(encoding="utf-8")
        m = re.search(r'argv\[1\] not in \(([^)]*)\)', src)
        cmds = re.findall(r'"([a-z-]+)"', m.group(1))
        self.assertGreater(len(cmds), 15)
        doc = self.read("docs", "graph-format.md")
        for c in cmds:
            with self.subTest(command=c):
                self.assertTrue(re.search(rf"`{re.escape(c)}[ `]", doc), c)

    def test_readme_lists_the_seven_tabs_and_no_adventure_book(self):
        readme = self.read("README.md")
        for tab in ("クエスト掲示板", "クエスト進捗", "納品物", "書庫", "外部サイト", "Obsidian", "ヘルプ"):
            self.assertIn(tab, readme)
        self.assertNotIn("冒険の書", readme)
        board = self.read("docs", "board-design.md")
        self.assertNotIn("冒険の書", board)
        for key in ("guild.board.listOpen", "guild.progress.sel"):
            self.assertIn(key, board)

    def test_no_stale_terms_in_live_docs(self):
        files = [self.read("README.md"), self.read("skills", "quest", "SKILL.md"), self.read("skills", "init", "SKILL.md")]
        files += [p.read_text(encoding="utf-8") for p in sorted((ROOT / "agents").glob("*.md"))]
        files += [self.read("docs", n) for n in ("spec.md", "graph-format.md", "board-design.md", "archive-spec.md", "roles-spec.md")]
        text = "\n".join(files)
        for stale in ("冒険の書", "納品物のテンプレート", "guild/templates", "`template`", ".mcp.json", "plugin_guild_browser", "Node.js"):
            with self.subTest(term=stale):
                self.assertNotIn(stale, text)
```

実行して、**文書を直す前に**失敗するもの（あれば）を確かめる。

Run: `python -m unittest tests.test_guild.DocsContractTest -v`
Expected: 棚卸しで見つけた消し忘れ・書き忘れがあれば、その分が FAIL。直したあと、全部 PASS。

- [ ] **Step 6: 動作テスト（a）— 全テスト**

Run: `python -m unittest tests.test_guild`
Expected: すべて PASS（件数を記録する）。

- [ ] **Step 7: 動作テスト（b）— 通しのシナリオ（`guild.py` を実際のコマンドで動かす）**

スクラッチパッドに次のスクリプトを置いて、実行する（プロジェクトの外の一時フォルダで動く）。Part A の Interfaces と食い違う箇所があれば、Part A の定義に合わせて直す（その場合は、食い違いを記録する）。

```python
# scratchpad/e2e.py — 使い方: python e2e.py（リポジトリのルートで）
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path.cwd()
GUILD = [sys.executable, str(ROOT / "skills" / "quest" / "guild.py")]


def run(*a, ok=True):
    r = subprocess.run([*GUILD, *map(str, a)], capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode != 0:
        raise SystemExit(f"FAIL {' '.join(map(str, a))}\n{r.stdout}\n{r.stderr}")
    return json.loads(r.stdout) if r.stdout.strip().startswith(("{", "[")) else r.stdout


def write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False), encoding="utf-8")


CRIT = {"viewpoint": "有無", "pass_line": "ある", "check": "開く"}
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    run("init", root)
    g = root / "guild"
    assert not (g / "templates").exists(), "テンプレートのフォルダは作らない"
    for n in ("inputs", "deliverables", ".work", "archive"):
        assert (g / n).is_dir(), n
    # 共通インプットと書庫の紐づけ
    write(g / "inputs" / "KGI定義.md", "# KGI\n売上 2026 の KGI は 1 億円")
    write(g / "inputs" / "売上 2026.csv", "月,売上\n1月,100\n")
    (g / "inputs" / "組織図.pdf").write_bytes(b"%PDF-1.4")
    write(g / "archive" / "KGI.md",
          '---\nname: "KGI"\ntype: term\naliases: ["重要目標達成指標"]\ninputs: ["組織図.pdf"]\nconfidence: confirmed\nsource: "依頼主の登録"\nconfirmed: 2026-10-16\nstatus: "active"\nsummary: "目標の指標"\n---\n本文\n')
    hints = run("inputs-list", root, "--text", "KGI の達成状況をまとめて")
    by = {x["name"]: x for x in hints}
    assert by["組織図.pdf"]["hints"], "書庫の紐づけでヒントが付く"
    assert hints[0]["hints"], "ヒントのあるファイルが先頭"
    # ボードが書く依頼（既存から選んだ inputs と、アップロードした files）
    rid = "R20261016-100000"
    write(g / ".work" / "requests" / f"{rid}.json", {"type": "request", "text": "KGI の達成状況をまとめて", "start": "2026-10-16", "due": None, "inputs": ["KGI定義.md"], "files": ["メモ.txt"], "created": "2026-10-16T10:00:00Z"})
    write(g / ".work" / "requests" / "files" / rid / "メモ.txt", "メモ")
    q = run("new", root, rid)
    qdir = Path(q["dir"])
    assert sorted(json.loads((qdir / "request.json").read_text(encoding="utf-8"))["inputs"]) == ["KGI定義.md", "メモ.txt"]
    # 存在しない名前は拒否される
    write(g / ".work" / "requests" / "R20261016-100001.json", {"type": "request", "text": "x", "inputs": ["ない.md"], "files": []})
    r = subprocess.run([*GUILD, "new", str(root), "R20261016-100001"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode != 0, "存在しない inputs は拒否"
    # 地図師の計画案 → adopt
    write(qdir / "reports" / "plan-draft.json", {"quest": q["quest"], "title": "KGI まとめ",
          "inputs": [{"name": "組織図.pdf", "reason": "書庫の KGI 項目に紐づく"}], "candidates": [{"name": "売上 2026.csv", "reason": "数字が要るかもしれない"}],
          "todos": [{"id": "T1", "title": "まとめを書く", "kind": "auto", "deps": [], "deliverable": True, "criteria": CRIT, "scheduled": "2026-10-16", "due": "2026-10-17"},
                    {"id": "T2", "title": "スライドのプロンプト", "kind": "auto", "deps": ["T1"], "criteria": CRIT}]})
    run("adopt", qdir / "plan.json")
    plan = json.loads((qdir / "plan.json").read_text(encoding="utf-8"))
    assert plan["inputs"][0]["source"] == "user" and any(i["source"] == "auto" for i in plan["inputs"])
    assert plan["candidates"][0]["name"] == "売上 2026.csv"
    assert plan["start"] and plan["due"] and plan["todos"][1]["scheduled"], "日付の既定が入る"
    # 承認 → 候補を追加 → 日付変更
    inbox = qdir / "inbox"
    write(inbox / "20261016100100-approve.json", {"type": "approve"})
    write(inbox / "20261016100101-inputs.json", {"type": "inputs", "add": ["売上 2026.csv"], "remove": ["メモ.txt"]})
    write(inbox / "20261016100102-due.json", {"type": "due", "todo": "T1", "scheduled": "2026-10-16", "due": "2026-10-18"})
    out = run("ingest", qdir / "plan.json")
    assert not out["rejected"], out
    plan = json.loads((qdir / "plan.json").read_text(encoding="utf-8"))
    names = [i["name"] for i in plan["inputs"]]
    assert "売上 2026.csv" in names and "メモ.txt" not in names and not plan["candidates"]
    # 存在しない名前の追加は拒否
    write(inbox / "20261016100103-inputs.json", {"type": "inputs", "add": ["ない.md"]})
    r = subprocess.run([*GUILD, "ingest", str(qdir / "plan.json")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode != 0 and "ない.md" in r.stdout + r.stderr
    # 実行 → 全 Todo 済み → 受け取りで納品物が置かれる
    for t in ("T1", "T2"):
        run("sync", qdir / "plan.json")
        run("advance", qdir / "plan.json", t, "submitted")
        write(qdir / "output" / t / ("まとめ.md" if t == "T1" else "スライド.prompt.md"), f"# {t}")
        run("advance", qdir / "plan.json", t, "passed")
    run("sync", qdir / "plan.json")
    nxt = run("next", qdir / "plan.json")
    assert nxt["awaiting_accept"] is True
    write(inbox / "20261016100200-accept.json", {"type": "accept"})
    run("ingest", qdir / "plan.json")
    assert sorted(p.name for p in (g / "deliverables").iterdir()) == [f"{q['quest']}_スライド.prompt.md", f"{q['quest']}_まとめ.md"]
    # 閉じたあと、バックアップが消える
    print(run("close", root))
print("E2E OK")
```

Run: `python scratchpad/e2e.py`（スクラッチパッドの実際のパスで）
Expected: `E2E OK`。失敗したら、**スクリプトではなくコードか文書を疑って**原因を調べる（Part A の Interfaces と見比べ、本当にスクリプトの誤りと分かったときだけスクリプトを直す）。

- [ ] **Step 8: 動作テスト（c）— ボードを実際に動かす（Playwright MCP）**

`mcp__playwright__browser_navigate` で `file:///<プロジェクトのフォルダ>/skills/quest/board.html?demo=<シーン>` を、**シーンごと**（`human` `accept` `failed` `plan` `questions` `archive` `done`）に開き、次を確かめる。毎回、`browser_console_messages` で**エラーが0件**であること。

1. タブ：`browser_evaluate` で `Array.from(document.querySelectorAll('nav.tabs button')).map(b => b.textContent.trim())` が、`['クエスト掲示板','クエスト進捗','納品物','書庫','外部サイト','Obsidian','ヘルプ']`（外部サイトは件数つきのことがある）。
2. クエスト掲示板（`human`）：一覧が表示されている。一覧の行を押すと右の詳細が替わる。「一覧を隠す」を押すと、詳細が広がり、ツールバーに見出し・「‹ ›」・「N件中M件目」・検索・「＋ 新規」が出る。`localStorage.getItem('guild.board.listOpen')` が `'0'`（または Part B の Task 7 で決めた値）。ページを再読み込み（`browser_navigate` を同じ URL で）しても隠れたまま。「一覧を表示」で戻る。
3. 詳細のタブ（`human`）：「道のり」で行を開くと合格基準が出る。「日付」で、ミニガントと表が出て、予定日を依頼の開始日より前に変えると赤い注意が出る（送るボタンの件数が増える）。「インプット」で、指定・自動の印と理由が出る。
4. 失敗の判断（`failed`）：手紙に鑑定士の指摘が出て、4つの選択肢がある。
5. 受け取り（`accept`）：納品物とプロンプトが分かれ、「プロンプトをコピー」でトーストが出る。
6. 「＋ 新規」ダイアログ：開く／Esc で閉じる／既存のインプットを検索して選べる／同名アップロードの注意が出る。
7. クエスト進捗：「表示するクエスト」を開く→検索→選ぶ→タグが出る→×で外れる→「進行中だけ」で戻る。`localStorage.getItem('guild.progress.sel')` が更新される。再読み込み後も選択が残る。選んでいないクエストが、ガントにも human の件数にも出ない。
8. 書庫（`archive`）：項目の編集欄に「インプット」があり、保存すると入力の JSON に `inputs` が入る。
9. ヘルプ・Obsidian タブの文が、新しい構成（クエスト掲示板、日付タブ、インプットの自動選択、テンプレートなし、冒険の書なし）になっている。
10. 画面幅 600px（`browser_resize`）で、一覧と詳細が切り替わり、横スクロールが出ない。

結果を、シーンごとに `○/×` で記録し、×があれば原因を直して再実行する。

- [ ] **Step 9: 動作テスト（d）— フックと外部サイト**

Run: `python -m unittest tests.test_guild.WebAccessTest tests.test_guild.WebGateHookTest -v`
Expected: PASS（`.work/web/` の読み書きが変わっていないことの確認）。

- [ ] **Step 10: ユーザーに頼む確認（自動化できないもの）を、最終報告に書く**

次の2つは、Playwright MCP では確かめられない（`showDirectoryPicker` が使えない）。最終報告に「依頼主に手元で確かめてほしいこと」として書く。
1. Chrome で、`guild.py init` した `guild/board.html` を開き、「フォルダを選ぶ」でそのフォルダを選ぶ。クエストを出し（インプットの選択とアップロードつき）、`guild/.work/requests/` に `R….json` ができ、`/guild:quest` で取り込まれて、ボードに出る。
2. 読めなければ、`.work` を `_work` に変える（`webaccess.WORK`、ボードの `PHYS`、`list('.work')`、`toPhysicalTree`）。

- [ ] **Step 11: コミット**

```bash
git add README.md skills agents docs/*.md .claude-plugin tests/test_guild.py
git commit -m "README・SKILL・指示書・docs を総点検する（不要・重複の削除、不足の追記、誤りの修正）と、契約テストの追加"
```

---

## Self-Review

**1. Spec coverage**

| SPEC（`docs/specs/2026-10-16_board-redesign.md`） | Task |
|---|---|
| タブ名「クエスト掲示板」、7タブ、冒険の書の廃止 | 6、7、13 |
| 左に一覧・右に詳細、一覧は既定で表示、隠すボタン、`localStorage`、狭い画面 | 7 |
| 詳細のタブ（道のり／日付／インプット）、道のりの行（合格基準・報告）、失敗の判断に鑑定士の指摘 | 8 |
| 日付タブ（このクエストのガント＋表で直す） | 9 |
| インプットタブ、「＋ 新規」ダイアログ（既存から選ぶ・アップロード）、自動選択の確認・直し | 4、5、10 |
| 納品物のテンプレートの廃止 | 1、6、13 |
| クエスト進捗のフィルタ、「進捗で見る」 | 11 |
| 書庫の `inputs`、ヒント（`inputs-list`） | 2、3、12 |
| 地図師の自動選択、`plan.json` の `inputs`/`candidates`、入力 `inputs` | 3、4、5 |
| 受入条件 7（冒険の書・テンプレートのコードが残らない） | 6、12、13（Step 1 の grep） |
| README・SKILL の総点検、動作テスト | 13 |

**2. プレースホルダーの確認**：Part A・Part B の各 Task は、完全なコードとコマンドで書かれている。Task 13 は、読んで直す作業のため、手順を表とチェックリストで書いた（直す文面そのものは、文書を読んでから決める）。

**3. 名前の整合**：Part A の `inputs_list`・`plan.inputs`・`candidates`・入力 `inputs`・書庫の `inputs` は、Part B が Consume する形と一致させてある。Task 13 の通しスクリプトは、Part A の Interfaces に合わせて書いてあり、食い違えば Step 7 に従って確かめる。

**4. Review Focus**：ヘッダーと Part B の先頭に書いた失敗の起こり方は、Task 3（短い語のヒント）、Task 4（選んだ名前が消えた依頼）、Task 7（`localStorage` が使えない・狭い画面）、Task 10・11（200件）、Task 13（旧語・誤りの残り）のテストと動作確認で押さえる。

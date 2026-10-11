# ボード改善 実装計画

> **実装者向け：** REQUIRED SUB-SKILL: superpowers:subagent-driven-development（推奨）か superpowers:executing-plans で、タスクごとに進める。ステップはチェックボックス（`- [ ]`）で追う。

**Goal:** 目次のフォーカス、書庫の絞り込み、Obsidian タブ、個人の種類、種類の付け替え、Todo の期限、ヘルプのモデル表示を実装する。

**Architecture:** 決定的な処理（検査・ファイルの移動・`plan.json` の更新）は `guild.py` に足し、画面は `inbox/`（`Q###/inbox/`、`archive/inbox/`）に JSON を書くだけにする（既存の経路）。`board.html` は1ファイルのまま変更する。`guild.py` 側を先に TDD で作り、画面は見本（`?demo=…`）を Playwright で開いて確かめる。

**Tech Stack:** Python 標準ライブラリ、unittest（`python -m unittest discover tests`。pytest は入っていない）、素の HTML/JS（`skills/quest/board.html`）。

**Spec:** `docs/2026-10-11_1635_roundtable_board-improvements/spec.md`

## Global Constraints

- 外部通信なし。`board.html` は1ファイル（正本は `skills/quest/board.html`）。
- 画面が書ける場所は `guild/` の中の `requests/`、`Q###/inbox/`、`archive/inbox/` だけ。`plan.json` は `guild.py` だけが書く。画面は `agents/` を読まない。
- 既存の書庫の項目は消さない。`init` は何度実行しても安全。
- 期限は日付のみ（`YYYY-MM-DD`）。ローカル時刻のその日の 23:59 を過ぎたら期限切れ。表示と警告だけで、実行順・自動処理・「あなたの番」は変えない。
- 心得（`lesson`）は付け替えの対象外（移す側にも移される側にもならない）。
- コミットメッセージは日本語。末尾に次の2行を付ける：
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01T7jhS2eu7YbBbWdfahap9c`
- `README.md` はないので更新しない。作業用の一時ファイルはスクラッチパッドに置く。

## Review Focus

1. 不正な期限（`2026-13-40`、`""`、数値、`20261020`）→ 取り込みで拒否され、`plan.json` は変わらない（Task 1）。
2. 完了・やめた Todo の期限 → 「期限切れ」の印を付けない（Task 6）。
3. 付け替えの衝突・不正：同種類への付け替え、移動先の同名・同別名、心得との行き来、廃止済みの項目、存在しないパス → すべて拒否され、元のファイルと索引は変わらない（Task 3）。
4. 移動先に同じファイル名があるとき → 上書きせず、連番のファイル名になる（Task 3）。
5. `personal/` がない古い `archive/` → `init` で作られ、画面は0件として出す（Task 2、Task 5）。

---

### Task 1: Todo の期限（guild.py）

**Files:**
- Modify: `skills/quest/guild.py`（`validate`、`apply_input`、docstring）
- Test: `tests/test_guild.py`（`BoardContractTest` の後ろに `DueTest` を足す）

**Interfaces:**
- Produces: 入力 `{"type": "due", "todo": "T1", "due": "2026-10-20" | null}`。`plan["todos"][i]["due"]` に `YYYY-MM-DD` か `None`。履歴に `{"t", "event": "due", "todo": "T1", "due": ...}`（`id` は付けない。タイムラインが `id` を見るため）。
- Produces: `guild.check_due(v) -> str | None`（不正なら `GuildError`）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_guild.py` の `class NextViewTest` の直前に足す：

```python
class DueTest(unittest.TestCase):
    """Todo の期限。入力 type=due で設定・変更・解除でき、plan.json を書くのは guild.py だけ。"""

    def ingest(self, p, data):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "inbox").mkdir()
            (Path(d) / "inbox" / "20261010120000-due-T1.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return guild.ingest(Path(d) / "plan.json", p, TR)

    def test_set_change_and_clear(self):
        p = plan(todo("T1", state="running"))
        self.assertEqual(self.ingest(p, {"type": "due", "todo": "T1", "due": "2026-10-20"})["rejected"], [])
        self.assertEqual(p["todos"][0]["due"], "2026-10-20")
        self.ingest(p, {"type": "due", "todo": "T1", "due": "2026-10-25"})
        self.assertEqual(p["todos"][0]["due"], "2026-10-25")
        self.ingest(p, {"type": "due", "todo": "T1", "due": None})
        self.assertIsNone(p["todos"][0]["due"])
        self.assertEqual([e["event"] for e in p["history"]], ["due", "due", "due"])
        self.assertNotIn("id", p["history"][0])  # タイムラインは id を持つ記録を状態の変化として読む

    def test_unapproved_plan_accepts_due(self):
        p = plan(todo("T1"), approved=False)
        self.assertEqual(self.ingest(p, {"type": "due", "todo": "T1", "due": "2026-10-20"})["rejected"], [])

    def test_bad_dates_are_rejected_and_plan_is_unchanged(self):
        for bad in ("2026-13-40", "", 20261020, "20261020", "2026-10-2", "2026-02-30"):
            with self.subTest(bad=bad):
                p = plan(todo("T1", due="2026-10-20"))
                r = self.ingest(p, {"type": "due", "todo": "T1", "due": bad})
                self.assertEqual(len(r["rejected"]), 1)
                self.assertEqual(p["todos"][0]["due"], "2026-10-20")

    def test_unknown_todo_and_aborted_plan_are_rejected(self):
        p = plan(todo("T1"))
        self.assertEqual(len(self.ingest(p, {"type": "due", "todo": "T9", "due": "2026-10-20"})["rejected"]), 1)
        p["status"] = "aborted"
        self.assertEqual(len(self.ingest(p, {"type": "due", "todo": "T1", "due": "2026-10-20"})["rejected"]), 1)

    def test_validate_checks_due(self):
        self.assertEqual(guild.validate(plan(todo("T1", due="2026-10-20"), todo("T2", due=None)), TR), [])
        self.assertTrue(any("T1" in e and "due" in e for e in guild.validate(plan(todo("T1", due="10/20")), TR)))

    def test_adopt_keeps_due_from_the_draft(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "Q001"
            (q / "reports").mkdir(parents=True)
            (q / "reports" / "plan-draft.json").write_text(json.dumps({"quest": "Q001", "title": "t", "todos": [
                {"id": "T1", "title": "a", "kind": "auto", "deps": [], "criteria": CRIT, "due": "2026-10-20"}]}), encoding="utf-8")
            guild.adopt(q / "plan.json", TR)
            self.assertEqual(guild.load_json(q / "plan.json")["todos"][0]["due"], "2026-10-20")
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.DueTest -v`
Expected: FAIL（`type=due` が「入力が不正です」で拒否される）

- [ ] **Step 3: 実装する**

`skills/quest/guild.py` の `CRITERIA_KEYS = ...` の次の行に足す：

```python
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
```

`validate` の `for t in todos:` の中、`if t.get("confirm") ...` の次に足す：

```python
        try:
            check_due(t.get("due"))
        except GuildError as e:
            errs.append(f"{i}: {e}")
```

`apply_input` の `if kind == "confirm":` の直前に足す：

```python
    if kind == "due":
        t["due"] = check_due(data.get("due"))
        note(plan, event="due", todo=t["id"], due=t["due"])
        return
```

docstring の「使い方」の下に1行足す：`入力（inbox の JSON）の type の1つに due（Todo の期限の設定・解除）がある。`

- [ ] **Step 4: 通ることを確かめる**

Run: `python -m unittest discover tests`
Expected: `OK`（101 + 新しい6件）

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "Todo の期限（due）を inbox 経由で設定・変更・解除できるようにする"
```

---

### Task 2: 書庫に「個人」の種類を足す（guild.py・役の指示書）

**Files:**
- Modify: `skills/quest/guild.py:466-467`（`ARCHIVE_DIRS`・`ARCHIVE_TITLES`）、`entry_path` の docstring
- Modify: `agents/librarian.md`（種類の表、description）、`agents/cartographer.md:23`、`agents/adventurer.md:17`、`agents/appraiser.md:18`、`agents/scout.md:18`、`skills/init/SKILL.md:25`
- Test: `tests/test_guild.py`（`ArchiveTest`）

**Interfaces:**
- Produces: 種類キー `personal`、フォルダ `archive/personal/`、索引の見出し「個人」。`ARCHIVE_DIRS["personal"] == "personal"`。

- [ ] **Step 1: 失敗するテストを書く**

`ArchiveTest` の `test_init_makes_archive_and_keeps_items` の `for sub in (...)` に `"personal"` を足し、さらにメソッドを2つ足す：

```python
    def test_personal_is_a_type_in_index_and_propose(self):
        self.assertEqual(guild.ARCHIVE_DIRS["personal"], "personal")
        guild.write_entry(self.adir, self.entry(type="personal", name="文体", summary="敬体で簡潔に", confidence="confirmed", source="依頼主の登録"))
        guild.rebuild_index(self.adir)
        idx = (self.adir / "index.md").read_text(encoding="utf-8")
        self.assertIn("## 個人", idx)
        self.assertIn("[[personal/文体]]", idx)
        self.draft(self.cand("C1", type="personal", name="役職", aliases=[], summary="情報システム部の課長", confidence="guess", source=""))
        self.assertEqual(guild.archive_propose(self.q)["pending"], ["C1"])  # 心得と違い、確認の手紙を通る

    def test_init_adds_personal_to_an_old_archive(self):
        import shutil as sh
        sh.rmtree(self.adir / "personal")
        guild.init_guild(self.root)
        self.assertTrue((self.adir / "personal").is_dir())
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.ArchiveTest -v`
Expected: FAIL（`KeyError: 'personal'` と `personal` フォルダなし）

- [ ] **Step 3: 実装する**

`guild.py` を書き換える：

```python
ARCHIVE_DIRS = {"term": "terms", "flow": "flows", "fact": "facts", "personal": "personal", "lesson": "lessons"}
ARCHIVE_TITLES = {"term": "用語", "flow": "業務フロー", "fact": "業務情報", "personal": "個人"}  # 心得は索引に載せない（役は読まない）
```

指示書を直す（現在の文言を `grep -n "用語・業務フロー・業務情報" agents skills` で確かめてから、各ファイルで「用語・業務フロー・業務情報」を「用語・業務フロー・業務情報・個人」に置き換える）。`agents/librarian.md` の種類の表には次の行を `fact` の次に足し、`description` と冒頭の説明にも「個人」を足す：

```
| `personal` | 個人。依頼主個人の情報。役職・文体の好み・禁止事項など。**依頼主が明言したものだけ**。推測で人物像を作らない | 敬体で簡潔に書く、社外秘の語は伏せる |
```

同じファイルに注意を1行足す：`個人は、依頼主が明言していない内容を候補にしない。迷ったら confidence を guess にする。トークン・パスワード・キーなどの秘密は、どの種類にも書かない。`

- [ ] **Step 4: 通ることを確かめる**

Run: `python -m unittest discover tests`
Expected: `OK`

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py agents skills/init/SKILL.md tests/test_guild.py
git commit -m "書庫に「個人」の種類を足す（確認の手紙を通す。全役が索引から読む）"
```

---

### Task 3: 項目の種類の付け替え（guild.py）

**Files:**
- Modify: `skills/quest/guild.py`（`archive_apply` に `retype`、docstring）
- Test: `tests/test_guild.py`（`ArchiveTest`）

**Interfaces:**
- Consumes: Task 2 の `ARCHIVE_DIRS`。
- Produces: `archive/inbox/` の入力 `{"type": "retype", "path": "terms/KPI.md", "to": "fact"}`。成功すると `facts/KPI.md`（同名ファイルがあれば `KPI-2.md`）へ移り、元のファイルは消える。確度・確認日・出典・状態・本文は引き継ぐ。

- [ ] **Step 1: 失敗するテストを書く**

```python
    def retype(self, path, to):
        self.put_inbox("20261011-retype.json", {"type": "retype", "path": path, "to": to})
        return guild.archive_ingest(self.root)

    def test_retype_moves_the_file_keeps_fields_and_updates_index(self):
        rel = guild.write_entry(self.adir, self.entry(name="料金", summary="s", body="本文", confidence="sourced", source="https://x (2026-10-01)", aliases=["fee"]))
        old = guild.read_entry(self.adir / rel)
        r = self.retype(rel, "fact")
        self.assertEqual(r["rejected"], [], r)
        self.assertFalse((self.adir / rel).exists())
        new = guild.read_entry(self.adir / "facts" / "料金.md")
        self.assertEqual(new["type"], "fact")
        for k in ("confidence", "confirmed", "source", "status", "body", "aliases", "summary"):
            self.assertEqual(new[k], old[k], k)
        idx = (self.adir / "index.md").read_text(encoding="utf-8")
        self.assertIn("[[facts/料金]]", idx)
        self.assertNotIn("[[terms/料金]]", idx)

    def test_retype_rejects_a_same_name_item_in_the_target(self):
        guild.write_entry(self.adir, self.entry(type="fact", name="料金", summary="別", confidence="guess"))
        rel = guild.write_entry(self.adir, self.entry(name="料金", summary="s", aliases=["fee"]))
        r = self.retype(rel, "fact")
        self.assertEqual(len(r["rejected"]), 1)  # 同名の項目があるので拒否
        self.assertTrue((self.adir / rel).exists())

    def test_retype_uses_a_serial_file_name_when_only_the_file_name_collides(self):
        guild.write_entry(self.adir, self.entry(type="fact", name="別の項目", summary="x"), "facts/料金.md")  # ファイル名だけ同じ
        rel = guild.write_entry(self.adir, self.entry(name="料金", summary="s"))
        self.assertEqual(self.retype(rel, "fact")["rejected"], [])
        self.assertEqual(guild.read_entry(self.adir / "facts" / "料金.md")["name"], "別の項目")
        self.assertEqual(guild.read_entry(self.adir / "facts" / "料金-2.md")["name"], "料金")

    def test_retype_rejects_bad_requests_and_changes_nothing(self):
        rel = guild.write_entry(self.adir, self.entry(name="A", summary="s"))
        les = guild.write_entry(self.adir, self.entry(type="lesson", name="L", summary="s"))
        dep = guild.write_entry(self.adir, dict(self.entry(name="D", summary="s"), status="廃止"))
        for path, to in ((rel, "term"), (rel, "lesson"), (rel, "nonsense"), (les, "term"), (dep, "fact"), ("terms/none.md", "fact"), ("../x.md", "fact")):
            with self.subTest(path=path, to=to):
                self.assertEqual(len(self.retype(path, to)["rejected"]), 1)
        self.assertTrue((self.adir / rel).exists() and (self.adir / les).exists() and (self.adir / dep).exists())
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.ArchiveTest -v`
Expected: FAIL（`入力が不正です: retype`）

- [ ] **Step 3: 実装する**

`archive_apply` の `elif kind == "deprecate":` の前に足す：

```python
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
        write_entry(adir, e)  # 新しい場所へ。ファイル名が重なれば連番になり、上書きしない
        src.unlink()  # 書けたあとで元を消す（書けなければ元は残る）
```

docstring（`archive_ingest`）の「entry（新規・編集）、promote…」に `retype（種類の付け替え）` を足す。モジュール先頭の docstring の `archive-ingest` の行にも足す。

注意：`e` に `type` を代入するだけで `entry_text` が `type:` を書く。`confirmed` は `e` にあるので引き継がれる。

- [ ] **Step 4: 通ることを確かめる**

Run: `python -m unittest discover tests`
Expected: `OK`

- [ ] **Step 5: コミット**

```bash
git add skills/quest/guild.py tests/test_guild.py
git commit -m "書庫の項目の種類を付け替えられるようにする（同名は拒否・心得は対象外）"
```

---

### Task 4: ボードが書く形の契約テスト＋見本データ

**Files:**
- Modify: `tests/test_guild.py`（`BoardContractTest`）
- Modify: `skills/quest/board.html`（見本データ：`personal` の項目、期限つきの Todo）

**Interfaces:**
- Consumes: Task 1・3 の入力の形。
- Produces: 見本 `?demo=human` に、期限つきの Todo（過去日・未来日・解除済み）と `personal/` の項目がある。後続タスクの目視確認が使う。

- [ ] **Step 1: テストを足す**

`BoardContractTest.CASES` に追加：

```python
        ({"type": "due", "todo": "T1", "due": "2026-10-20"}, lambda: plan(todo("T1", state="running")), {"T1": "running"}),
        ({"type": "due", "todo": "T1", "due": None}, lambda: plan(todo("T1"), approved=False), {"T1": "pending"}),
```

`test_board_source_writes_the_same_shapes` の `for needle in (...)` に `"type: 'due'"` と `"type: 'retype'"` を足す。

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.BoardContractTest -v`
Expected: `test_board_source_writes_the_same_shapes` が FAIL（`type: 'due'` が board.html にない）。CASES の2件は PASS。

- [ ] **Step 3: 見本データを直す**

`skills/quest/board.html` の見本（`J(p1)` の `mk('T1', …)` 行付近、`1365` 行あたり）で、`p1.todos` の T1 に `due: '2026-10-01'`（過去）、T2 に `due: '2026-12-31'`（未来）を足す。`archive` の見本に `personal: { '文体.md': T('---\nname: 文体\ntype: personal\naliases: []\nconfidence: confirmed\nsource: 依頼主の登録\nconfirmed: 2026-10-11\nstatus: active\nsummary: 敬体で簡潔に書く\n---\n見本の項目です。') }` を足し、`flows: {}, facts: {}` の並びに `personal` を含める。

- [ ] **Step 4: 目視（あとの Task で使う）**

見本の書き換えが壊れていないことを、Task 5 の Step で一緒に確かめる。ここでは `python -m unittest discover tests` が `OK`（`type: 'retype'` の needle は Task 5 で通る）にならないので、**このタスクのコミットは Task 5 のあとにまとめる**。

- [ ] **Step 5: （Task 5 の最後でコミット）**

---

### Task 5: 書庫タブ：個人・サブタブ・フィルタ・並び替え・種類の変更（board.html）

**Files:**
- Modify: `skills/quest/board.html`（`ARCH_TYPES`:336、`knowTab`:1063、`archiveCard`:1035、`archiveForm`:1006、読み込み:401）

**Interfaces:**
- Consumes: Task 3 の入力 `{type:'retype', path, to}`（`sendArchive(obj, key)`）。
- Produces: `S.kn = { tab: 'all'|<type>, conf: {}, st: 'active'|'all', sort: 'name'|'confirmed' }`。

- [ ] **Step 1: 種類に「個人」を足す**

`ARCH_TYPES` を次にする（心得は最後）：

```js
const ARCH_TYPES = [['term', 'terms', '用語'], ['flow', 'flows', '業務フロー'], ['fact', 'facts', '業務情報'], ['personal', 'personal', '個人'], ['lesson', 'lessons', '心得']];
```

登録欄の種類の説明（`archiveForm` の `p.fine`）を「社内の用語・業務フロー・業務情報・個人（文体の好みなど）…」に直す。「自分で項目を登録する」の種類のセレクトに「個人」が出ることを確かめる。心得を選べてしまう場合は `ARCH_TYPES.filter((x) => x[0] !== 'lesson')` で外す（登録欄では心得を作らない）。

- [ ] **Step 2: サブタブ・フィルタ・並び替え**

`S`（状態オブジェクト）の初期化に `kn: { tab: 'all', conf: {}, st: 'active', sort: 'name' }` を足す（`S.stf` を作っている場所を探して、その隣に置く）。`knowTab` の `searchBox(...)` の後ろ、`archiveForm()` の前に次を差し込む：

```js
  const kn = S.kn, all = m.archive || [];
  const cnt = (t) => all.filter((e) => t === 'all' || e.type === t).length;
  out.push(h('div', { class: 'filters', role: 'tablist', 'aria-label': '書庫の種類' },
    [['all', 'すべて'], ...ARCH_TYPES.map(([t, , l]) => [t, l])].map(([t, l]) =>
      h('button', { type: 'button', role: 'tab', 'aria-selected': String(kn.tab === t), class: 'fchk' + (kn.tab === t ? ' on' : ''), onclick: () => { kn.tab = t; render(); } }, `${l} ${cnt(t)}`))));
  out.push(h('div', { class: 'filters sf', role: 'group', 'aria-label': '書庫の絞り込み' }, h('span', { class: 'sub', style: 'align-self:center' }, '確度：'),
    Object.entries(CONF).map(([k, [l]]) => { const c = h('input', { type: 'checkbox' }); c.checked = !!kn.conf[k];
      c.addEventListener('change', () => { kn.conf[k] = c.checked; render(); }); return h('label', { class: 'fchk' + (c.checked ? ' on' : '') }, c, l); }),
    h('span', { class: 'sub', style: 'align-self:center;margin-left:10px' }, '状態：'),
    [['active', '使っているもの'], ['all', '廃止も含む']].map(([v, l]) => h('button', { type: 'button', class: 'fchk' + (kn.st === v ? ' on' : ''), 'aria-pressed': String(kn.st === v), onclick: () => { kn.st = v; render(); } }, l)),
    h('span', { class: 'sub', style: 'align-self:center;margin-left:10px' }, '並び：'),
    [['name', '名前順'], ['confirmed', '確認日が新しい順']].map(([v, l]) => h('button', { type: 'button', class: 'fchk' + (kn.sort === v ? ' on' : ''), 'aria-pressed': String(kn.sort === v), onclick: () => { kn.sort = v; render(); } }, l))));
```

種類ごとのループを次のように直す（絞り込みを通し、選んだ種類だけ出す）：

```js
  const confOn = Object.keys(kn.conf).filter((k) => kn.conf[k]);
  const cmp = kn.sort === 'confirmed' ? (a, b) => String(b.confirmed || '').localeCompare(String(a.confirmed || '')) || String(a.name).localeCompare(String(b.name)) : (a, b) => String(a.name).localeCompare(String(b.name));
  for (const [type, , title] of ARCH_TYPES) {
    if (kn.tab !== 'all' && kn.tab !== type) continue;
    const list = all.filter((e) => e.type === type).filter((e) => kn.st === 'all' || e.status !== '廃止')
      .filter((e) => !confOn.length || confOn.includes(e.confidence)).filter((e) => hit(q, e.name, e.summary, e.body, ...e.aliases)).sort(cmp);
    const head = type === 'lesson' ? '心得（guild の改善材料。役は読みません）' : title;
    if (!list.length) { out.push(h('p', { class: 'sub', style: 'margin:14px 0 4px' }, h('b', null, head), `　0件（${q || confOn.length ? '見つかりませんでした' : 'まだありません'}）`)); continue; }
    out.push(h('h3', { class: 'sec' }, head, `　${list.length}件`));
    for (const e of list) out.push(archiveCard(e));
  }
```

（元の `for (const [type…` ループと、`hit(...)` を使う `list` の計算は、この新しいものに置き換える。）導入文（`p.sub`）を「用語・業務フロー・業務情報・個人を…」に直す。登録欄（`archiveForm()`）は閉じたまま出る（`details` の `open` は `S.open['a:form']` が偽なら閉じる）ので、今のままでよい。

- [ ] **Step 3: 種類の変更ボタン**

`archiveCard` の「編集」ボタンの次に足す（心得・廃止済みには出さない）：

```js
      e.status !== '廃止' && e.type !== 'lesson' ? h('button', { type: 'button', class: 'btn ghost', style: 'min-height:36px', onclick: () => { S.confirm[k + ':t'] = !S.confirm[k + ':t']; S.open[k] = true; render(); } }, '種類を変更') : null,
```

`const asking = !!S.confirm[k];` の隣に `const retyping = !!S.confirm[k + ':t'];` を足し、`asking ? … : null` の次（`h('div', { class: 'btns' ...` を閉じた後ろ、カードの最後の子）に足す：

```js
    retyping ? h('div', { class: 'qa', style: 'margin-top:10px' }, h('span', { class: 'lbl' }, `いまの種類：${(ARCH_TYPES.find((x) => x[0] === e.type) || [0, 0, e.type])[2]}　→　移す先`),
      h('div', { class: 'btns' }, ARCH_TYPES.filter(([t]) => t !== e.type && t !== 'lesson').map(([t, , l]) =>
        h('button', { type: 'button', class: 'btn', onclick: async () => { S.confirm[k + ':t'] = false; await sendArchive({ type: 'retype', path: e.path, to: t }, k + ':t:' + t); } }, `${l}にする`)),
        h('button', { type: 'button', class: 'btn ghost', onclick: () => { S.confirm[k + ':t'] = false; render(); } }, 'やめておく')),
      h('p', { class: 'fine' }, '確度・出典・本文はそのままです。同じ名前の項目が移す先にあると、反映されません（「書庫への反映待ち」が残らず、元の場所のままです）。')) : null);
```

（直前の `asking ? … : null);` の末尾の `);` は `,` に直してつなぐ。）`rejected/` に落ちた入力は画面に出ないので、説明の文言は上のとおり「反映されません」とする。

- [ ] **Step 4: 読み込み**

`board.html:401` の `for (const [, dir] of ARCH_TYPES)` は `personal` も読む。`S.fs.list('archive/personal')` が存在しないフォルダで例外にならないことを、Step 5 で（見本ではなく）実フォルダで確かめる。例外なら、その行の `await S.fs.list(...)` を `.catch(() => [])` でくるむ（`S.fs.list` が既に空配列を返す実装なら不要）。

- [ ] **Step 5: 目視確認（Playwright）**

`file:///C:/Users/sioay/OneDrive/github/guild/skills/quest/board.html?demo=human` を開き、「書庫」タブで確かめる：
  1. サブタブに「すべて／用語／業務フロー／業務情報／個人／心得」が出て、個人が1件。
  2. 確度のチェックと並びで一覧が変わる。廃止のあるデータでは「使っているもの」で消え、「廃止も含む」で出る。
  3. 項目を開いて「種類を変更」→ 移す先に自分の種類と心得が出ない。押すと「送りました」相当の反映待ちが出る（見本は保存しない）。
  4. `browser_console_messages` にエラーがない。

実フォルダでの確認：スクラッチパッドに `python skills/quest/guild.py init <scratch>/proj` で `guild/` を作り（`personal/` なしの古い構成も、`personal/` を消して再現）、Chrome で `guild/board.html` を開いて接続し、書庫が開けることを確かめる（接続の操作はユーザーのブラウザが要るので、できなければ「未確認」と報告する）。

- [ ] **Step 6: テストとコミット（Task 4 の分も含める）**

Run: `python -m unittest discover tests`
Expected: `OK`

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "書庫タブ：個人・種類のサブタブ・確度/状態の絞り込み・並び替え・種類の変更"
```

---

### Task 6: Todo の期限の画面（board.html）

**Files:**
- Modify: `skills/quest/board.html`（読み込み:392、`derive`:436、`todoTags`:751、スタイル）

**Interfaces:**
- Consumes: Task 1 の入力 `{type:'due', todo, due}`。
- Produces: `overdue(t, nowMs) -> boolean`（`t.due` が日付で、`closed(t.state)` でなく、`nowMs` がその日の 23:59:59.999 を過ぎている）。`t.dueWait`（反映待ちの値：`undefined`＝なし、`null`＝解除待ち、文字列＝設定待ち）。

- [ ] **Step 1: 期限の判定を足す**

`const closed = ...`（417行）の次に足す：

```js
// 期限は日付だけ。その日の終わり（ローカル時刻の 23:59:59.999）を過ぎたら期限切れ。済んだ Todo には付けない
const overdue = (t, nowMs) => !!t.due && !closed(t.state) && nowMs > new Date(t.due + 'T23:59:59.999').getTime();
```

- [ ] **Step 2: 反映待ちを読む**

`inbox.push({ type: j.type, todo: j.todo || null, choice: j.choice || null, qs: null })`（392行）に `, due: j.due === undefined ? undefined : j.due` を足す。`derive` の `d.todos = p.todos.map((t) => {` の中を次にする：

```js
    const waitDue = q.inbox.filter((x) => x.type === 'due' && x.todo === t.id).slice(-1)[0];
    return { ...t, stamp: draft ? '案' : st[0], cls: draft ? 'sd-draft' : st[1], dueWait: waitDue ? waitDue.due : undefined };
```

- [ ] **Step 3: 札に出す・編集する**

`todoTags` の `t.confirm ? h('div', { class: 'lock' }, …) : null,` の次に足す：

```js
    dueRow(qd, t),
```

`todoTags` の上に関数を足す：

```js
function dueRow(qd, t) {
  const p = qd.q.plan, key = `due:${qd.id}:${t.id}`, over = overdue(t, Date.now());
  const reqDue = qd.q.request && qd.q.request.due;
  const inp = h('input', { type: 'date', 'aria-label': `${t.id} の期限` }); inp.value = S.form[key] !== undefined ? S.form[key] : (t.due || ''); bindKey(inp, key);
  const editable = p.status === 'active' || p.status === undefined;
  const pick = S.form[key] !== undefined ? S.form[key] : (t.due || '');
  return h('div', { class: 'duerow' },
    h('span', { class: 'fine' }, '期限：', t.due ? t.due : 'なし'), over ? [' ', stampEl('期限切れ', 'sd-ng')] : null,
    t.dueWait !== undefined ? [' ', stampEl(t.dueWait ? `反映待ち（${t.dueWait}）` : '反映待ち（解除）', 'sd-turn')] : null,
    editable ? [' ', inp,
      h('button', { type: 'button', class: 'btn ghost', style: 'min-height:34px', disabled: S.conn !== 'ok' || pick === (t.due || ''), onclick: async () => { await send(qd.id, { type: 'due', todo: t.id, due: pick || null }, key); delete S.form[key]; render(); } }, pick ? '期限を設定' : '期限を解除')] : null,
    pick && reqDue && pick > reqDue ? h('p', { class: 'fine', style: 'margin:4px 0 0;color:var(--warn)' }, `依頼の期限（${reqDue}）より後の日付です。`) : null);
}
```

スタイルを `.tag` の近くに足す：`.duerow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}`。`stampEl` の使い方は他の呼び出しに合わせる（`stampEl(ラベル, クラス)`）。

- [ ] **Step 4: 目視確認と判定の確認**

見本（`?demo=human`）で、掲示板の依頼を開いて：
  1. T1（過去の期限）に「期限切れ」が付き、T2（未来）には付かない。
  2. 日付を選ぶと「期限を設定」が有効になる。依頼の期限より後の日付で注意が出る。
  3. 完了した Todo（`?demo=done`）に過去の期限を入れても「期限切れ」が付かない。
  4. `browser_evaluate` で `overdue({due:'2026-10-11', state:'running'}, new Date('2026-10-11T23:59:59').getTime())` が `false`、`new Date('2026-10-12T00:00:00').getTime()` で `true`、`state:'done'` で `false`、`due` なしで `false`（`overdue` はトップレベルの `const` なので `window` には出ない。評価式の中で関数ごと書くか、`eval('overdue(...)')` を使う）。
  5. 中止した依頼（`?demo=…` で中止があれば）では編集欄が出ない。

- [ ] **Step 5: テストとコミット**

Run: `python -m unittest discover tests`
Expected: `OK`

```bash
git add skills/quest/board.html
git commit -m "ボード：Todo の期限の表示・設定・解除と、期限切れの印"
```

---

### Task 7: 目次のフォーカス（board.html）

**Files:**
- Modify: `skills/quest/board.html`（`jumpQuest`:879、`ledger`:911 の行、スタイル:22 付近）

**Interfaces:**
- Produces: `S.flash = { id, until }`（強調する依頼と期限のミリ秒）。

- [ ] **Step 1: 原因を再現する**

見本を開き、依頼を12件以上並べた状態を作る（`browser_evaluate` で `S.model.quests` を複製して `render()`、または `?demo=` に依頼が少なければ `Array.from` で複製）。窓の幅を 1100px と 1600px にして、目次の末尾の依頼を押し、押した行の上端と固定のタブ（`.tabs`）の下端の位置を `getBoundingClientRect()` で記録する。隠れる・ずれるなら原因（`scroll-margin-top:70px` がタブの実際の高さと合わない、など）を `docs` ではなくコミットメッセージに1行で書く。**再現できなければ、再現できなかったと報告して、ユーザーに手順を聞く**（Step 2 以降は、念のための補正として進める）。

- [ ] **Step 2: 実装する**

`jumpQuest` の末尾を次に置き換える：

```js
  S.openQ[id] = true; S.sel = id; S.tq = id; S.flash = { id, until: Date.now() + 2500 }; render();
  const el = document.querySelector(`[data-q="${id}"]`);
  if (el) {
    const bar = document.querySelector('.tabs'), top = bar ? bar.getBoundingClientRect().bottom : 0;
    window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - top - 8);
    el.focus({ preventScroll: true });
  }
  setTimeout(render, 2600);  // 強調を消す
```

`ledger` の依頼の行（`h('button', { type: 'button', class: 'lr' + (S.openQ[qd.id] ? ' sel' : ''), …`）の `class` を次にし、`'data-key': 'q:' + qd.id` を足す（`render` が再描画のあとにフォーカスを戻せるように）：

```js
class: 'lr' + (S.openQ[qd.id] ? ' sel' : '') + (S.flash && S.flash.id === qd.id && Date.now() < S.flash.until ? ' flash' : ''), 'data-key': 'q:' + qd.id,
```

スタイルを `.lr,.quick{…}` の次に足す：

```css
.lr.flash{outline:3px solid var(--seal);outline-offset:-3px;animation:flashfade 2.5s ease-out}
@keyframes flashfade{from{background:var(--head)}to{background:transparent}}
@media (prefers-reduced-motion:reduce){.lr.flash{animation:none}}
```

`.lr,.quick{scroll-margin-top:70px}` はそのまま残す。

- [ ] **Step 3: 目視確認**

Step 1 の状態で、1100px・1600px・（900px 以下では目次が出ないので「あなたの番」の帯のリンク）から押して、押した行が固定のタブの直下に来る、2.5秒枠が出て消える、フォーカスが行にある（`document.activeElement.dataset.q`）、3秒後の自動再描画のあともフォーカスが残る、古い側（20件の区切りの外）へ飛んでも行が見える、ことを確かめる。`browser_console_messages` にエラーがない。

- [ ] **Step 4: テストとコミット**

Run: `python -m unittest discover tests`
Expected: `OK`

```bash
git add skills/quest/board.html
git commit -m "目次から依頼を選んだとき、行を見える位置に出し、強調してフォーカスする"
```

---

### Task 8: Obsidian タブ（board.html）

**Files:**
- Modify: `skills/quest/board.html`（`render` のタブ表、新しい `obsidianTab`）

**Interfaces:**
- Produces: タブキー `obs`、見出し「Obsidian」。位置は「ギルド案内」の次、「ヘルプ」の前。

- [ ] **Step 1: タブを足す**

`render` の `tabs` を `…, ['flow', 'ギルド案内'], ['obs', 'Obsidian'], ['help', 'ヘルプ']` にし、`body` の対応表に `obs: obsidianTab` を足す。`helpTab` の隣にある `sec`・`dl`・`code` を使うため、`helpTab` の中の `sec`／`dl` の定義を、トップレベルの関数 `secOf(title, ...kids)`・`dlOf(rows)` に取り出して両方から使う（`helpTab` の定義が `const sec = …` のローカルなら、その1行をコピーして `obsidianTab` に置いてもよい。重複させる場合は同じ見た目になるように、1行ずつ同じ定義にする）。

- [ ] **Step 2: 内容を書く**

```js
function obsidianTab() {
  const sec = (t, ...k) => h('section', { class: 'card' }, h('h3', { class: 'sec', style: 'margin-top:0' }, t), ...k);
  const dl = (rows) => h('dl', { class: 'h' }, rows.flatMap(([a, b]) => [h('dt', null, a), h('dd', null, b)]));
  const pre = (t) => h('pre', { style: 'white-space:pre-wrap;background:var(--surface2);border-radius:4px;padding:12px;font-size:13px;margin:6px 0' }, t);
  return [h('h2', { class: 'h2' }, 'Obsidian で読む'), h('p', { class: 'sub', style: 'margin:0 0 12px' }, '書庫と納品物は Markdown で、Obsidian の記法で書かれています。Obsidian で開くと、リンクをたどり、検索や関係図が使えます。この画面から Obsidian の中身は変わりません（読むための案内です）。'),
    h('div', { class: 'grid2' },
      sec('Vault（保管庫）の作り方',
        h('ol', null,
          h('li', null, 'Obsidian で「保管庫を開く」→「フォルダを保管庫として開く」を選びます。'),
          h('li', null, h('b', null, 'プロジェクトの ', code('guild/'), ' フォルダ'), 'を選びます（書庫と納品物の両方が見えます）。'),
          h('li', null, '設定 →「ファイルとリンク」→「除外ファイル」に ', code('inbox/'), '、', code('reports/'), '、', code('requests/'), ' を足します（やりとりの JSON と報告で、検索がうるさくなるため）。')),
        h('p', { class: 'fine' }, '書庫だけ読みたいときは、', code('guild/archive/'), ' を保管庫にします。')),
      sec('ディレクトリ構成', pre(['guild/', '  archive/            書庫', '    index.md          索引（役が最初に読む）', '    terms/ flows/ facts/ personal/   用語／業務フロー／業務情報／個人', '    lessons/          心得（役は読まない）', '  Q001/               依頼ごとのフォルダ', '    output/T3/…       納品物（最後のまとめの Todo の成果物）', '    reports/          役の報告', '    plan.json         計画（guild.py だけが書く。触らない）', '  templates/          納品物のテンプレート'].join('\n'))),
      sec('納品物を見る', dl([['場所', h('span', null, code('Q###/output/<Todo>/'), '。依頼ごとのフォルダの中です。納品物は、最後の「まとめの Todo」の成果物です。')], ['書き方', 'フロントマター（YAML）、', '[[リンク]]、コールアウトで書かれていて、そのまま開けます。'], ['依頼の一覧', '「掲示板」の「納品物」から、同じファイルをこの画面で開いたり、コピーしたりもできます。']])),
      sec('項目の書き方（書庫）', pre(['---', 'name: "KPI"', 'type: term', 'aliases: ["重要業績評価指標"]', 'confidence: confirmed', 'source: "依頼主の登録"', 'confirmed: 2026-10-11', 'status: "active"', 'summary: "目標の達成度を測る指標"', '---', '本文。他の項目へは [[terms/KGI]] のようにリンクします。'].join('\n')),
        dl([['type', 'term（用語）／flow／fact／personal／lesson'], ['confidence', 'confirmed（確認済み）／sourced（出典あり）／guess（推測）'], ['status', 'active／要確認／廃止']]),
        h('p', { class: 'fine' }, '項目を Obsidian で直接編集してもかまいませんが、索引（', code('index.md'), '）は自動では更新されません。確実に反映するには、この画面の「書庫」から編集してください。')),
      sec('整形（フォーマッタ）の設定',
        h('ul', null,
          h('li', null, 'コミュニティプラグイン「Linter」を使うなら、YAML のキーの並び替えと「タイトルの自動追加」を切ってください（見出しを勝手に足されると、項目の本文が変わります）。'),
          h('li', null, 'フロントマターは、値を二重引用符で囲む書き方のままにしてください（コロンや # が入っても崩れません）。'),
          h('li', null, '改行は LF のまま。保存時に末尾の空白を削る設定は、そのままでかまいません。')),
        h('p', { class: 'fine' }, '設定を変えなくても、読むだけなら問題ありません。'))))];
}
```

`code`・`h`・`dl` のシグネチャは既存のものに合わせる（`code(...)` は子要素を取る関数）。`納品物` タブの名前が実際と違う場合は、`grep -n "'納品物'" board.html` で確かめて文言を直す。

- [ ] **Step 3: 目視確認**

見本を開き、「Obsidian」タブが「ギルド案内」と「ヘルプ」の間に出る、内容が崩れない、狭い幅（500px）で横スクロールが出ない、`browser_console_messages` にエラーがない、を確かめる。

- [ ] **Step 4: テストとコミット**

Run: `python -m unittest discover tests`
Expected: `OK`

```bash
git add skills/quest/board.html
git commit -m "Obsidian タブ：Vault の作り方・フォルダ構成・納品物の見方・書式と整形の案内"
```

---

### Task 9: ヘルプに各役のモデル（board.html・テスト）

**Files:**
- Modify: `skills/quest/board.html`（`helpTab`）
- Test: `tests/test_guild.py`

**Interfaces:**
- Produces: board.html の `const ROLE_MODELS = { <agent名>: ['<役の名前>', '<model>'], … };`（1行に1役。テストがこの形を読む）。

- [ ] **Step 1: 失敗するテストを書く**

```python
class RoleModelsTest(unittest.TestCase):
    """ヘルプに書く各役のモデルが、agents/*.md の model と一致する。"""

    def test_board_help_matches_agents(self):
        board = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
        block = board.split("const ROLE_MODELS = {", 1)[1].split("};", 1)[0]
        shown = dict((a, m) for a, _, m in re.findall(r"(\w+): \['([^']+)', '(\w+)'\]", block))
        agents = {}
        for f in (ROOT / "agents").glob("*.md"):
            m = re.search(r"^model: (\w+)$", f.read_text(encoding="utf-8"), re.M)
            self.assertIsNotNone(m, f.name)
            agents[f.stem] = m.group(1)
        self.assertEqual(shown, agents)
```

ファイル先頭の `import` に `import re` を足す。

- [ ] **Step 2: 失敗を確かめる**

Run: `python -m unittest tests.test_guild.RoleModelsTest -v`
Expected: FAIL（`ROLE_MODELS` がない）

- [ ] **Step 3: 実装する**

`helpTab` の上に足す：

```js
// 各役のモデル。正本は agents/*.md の model（tests/test_guild.py が一致を確かめる）
const ROLE_MODELS = {
  cartographer: ['地図師', 'opus'],
  adventurer: ['冒険者', 'sonnet'],
  scout: ['斥候', 'sonnet'],
  appraiser: ['鑑定士', 'sonnet'],
  librarian: ['司書', 'sonnet']
};
```

`helpTab` の「言葉の説明」の次に足す：

```js
    sec('各役のモデル', dl([...Object.values(ROLE_MODELS).map(([name, model]) => [name, model]), ['ギルドマスター', '/guild:quest を動かしているセッションのモデル（役の定義にはありません）']]),
      h('p', { class: 'fine', style: 'margin:8px 0 0' }, 'モデルは、プラグインの agents/ にある各役の定義で決まります。変えたいときは、そこの model を書き換えます。')),
```

- [ ] **Step 4: 通ることを確かめ、目視する**

Run: `python -m unittest discover tests`
Expected: `OK`

見本の「ヘルプ」に「各役のモデル」が出ることを Playwright で確かめる。

- [ ] **Step 5: コミット**

```bash
git add skills/quest/board.html tests/test_guild.py
git commit -m "ヘルプに各役のモデルを載せ、agents/*.md との一致をテストで確かめる"
```

---

### Task 10: 文書の更新とバージョン

**Files:**
- Modify: `docs/board-design.md`、`docs/archive-spec.md`、`docs/roles-spec.md`、`docs/spec.md`（Todo の期限の1行）、`docs/graph-format.md`（`due` を Todo の項目に）、`skills/quest/SKILL.md`（`archive-ingest` の入力に `retype`、`due` の入力）、`.claude-plugin/plugin.json`（`"version": "0.2.1"`）

- [ ] **Step 1: 食い違いを探す**

Run: `grep -n "用語・業務フロー・業務情報\|inbox\|type: \|タブ\|6つ" docs/*.md skills/quest/SKILL.md | cut -c1-160`
各ヒットを読み、「上のタブは6つ」→「7つ（…／Obsidian／ヘルプ）」、書庫の種類に「個人」、`archive-ingest` の入力に `retype`、画面が書ける場所に `Q###/inbox/` の `due` を足す。`docs/archive-spec.md` の構成図に `personal/`、確度の節の下に「付け替え」の節（同名は拒否・心得は対象外）を足し、決定ログに今回の決定（個人を全役が読む・確認の手紙を通す）を1行ずつ足す。`docs/board-design.md` の「決めたこと」に、目次のフォーカス・書庫の絞り込み・Obsidian タブ・期限・モデル表示を1行ずつ足す。

- [ ] **Step 2: 全体の確認**

Run: `python -m unittest discover tests`
Expected: `OK`

Run: `git status --short`
Expected: 変更は上のファイルだけ。スクラッチパッド以外に一時ファイルがない。

- [ ] **Step 3: 実際の流れの確認（できる範囲）**

スクラッチパッドに `python skills/quest/guild.py init <scratch>/proj` → `new` → 手で `plan.json` を作り、`Q001/inbox/` に `type: due` の JSON を置いて `guild.py ingest` で `plan.json` の `due` が変わること、`archive/inbox/` に `retype` を置いて `archive-ingest` でファイルが移ることを、CLI で確かめる。画面からの送信は、ユーザーのブラウザ（Chrome / Edge）が要るので、「未確認」として報告する。

- [ ] **Step 4: コミット**

```bash
git add docs skills/quest/SKILL.md .claude-plugin/plugin.json
git commit -m "ボード改善：個人の種類・種類の付け替え・Todo の期限・Obsidian タブ・モデル表示（v0.2.1）"
```

---

## Self-Review（記入済み）

- **Spec coverage**：R1→Task 7、R2→Task 5、R3→Task 8、R4→Task 2・5、R5→Task 3・5、R6→Task 1・6、R7→Task 9。受入条件 10（文書）→Task 10。受入条件 9（見本での目視）→各タスクの目視確認。
- **Placeholders**：なし。ただし Task 5 Step 4・Task 7 Step 1・Task 8 Step 1 は、既存コードの形（`S.fs.list` の戻り値、`helpTab` のローカル関数）を読んでから合わせる指示で、コードは示してある。
- **Type consistency**：入力の形 `{type:'due', todo, due}` と `{type:'retype', path, to}`、`overdue(t, nowMs)`、`ROLE_MODELS` の形は、定義したタスクと使うタスクで一致している。
- **Review Focus**：1→Task 1、2→Task 6（目視 4・3）、3・4→Task 3、5→Task 2・5。

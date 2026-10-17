# グラフ定義の形式

`docs/spec.md` の「進め方をグラフ定義のデータで持つ」を具体化する。決定済み: 実行主体は Python スクリプト、形式は JSON、遷移定義は「全目標共通の1つ＋種別ごとの差分」。

## 2つのファイル

| ファイル | 置き場 | 持つもの | 変わる頻度 |
|---|---|---|---|
| `transitions.json` | プラグイン同梱 | 状態遷移グラフ（全依頼で共通） | 開発時のみ |
| `plan.json` | `guild/.work/<依頼>/` | 目標の依存グラフと、各目標の現在の状態 | 実行中に更新 |

## transitions.json

実物は `skills/quest/transitions.json`。形は次のとおり。

```json
{
  "states": ["pending", "blocked", "awaiting_confirm", "running", "waiting_user", "review", "done", "failed", "skipped"],
  "initial": "pending",
  "terminal": ["done", "skipped"],
  "max_retries": 2,
  "transitions": [
    {"from": "pending", "event": "deps_done", "to": "awaiting_confirm", "guard": "confirm"},
    {"from": "pending", "event": "deps_done", "to": "running", "guard": "no_confirm"},
    {"from": "pending", "event": "dep_failed", "to": "blocked"},
    {"from": "blocked", "event": "unblock", "to": "pending"},
    {"from": "awaiting_confirm", "event": "confirmed", "to": "running"},
    {"from": "awaiting_confirm", "event": "declined", "to": "failed"},
    {"from": "running", "event": "submitted", "to": "review"},
    {"from": "review", "event": "passed", "to": "done"},
    {"from": "review", "event": "rejected", "to": "running", "guard": "retries_left"},
    {"from": "review", "event": "rejected", "to": "failed", "guard": "no_retries_left"},
    {"from": "failed", "event": "skip", "to": "skipped"},
    {"from": "failed", "event": "retry", "to": "awaiting_confirm", "guard": "confirm"},
    {"from": "failed", "event": "retry", "to": "running", "guard": "no_confirm"}
  ],
  "kinds": {
    "auto": {"override": []},
    "human": {
      "override": [
        {"from": "pending", "event": "deps_done", "to": "waiting_user"},
        {"from": "waiting_user", "event": "submitted", "to": "review"},
        {"from": "waiting_user", "event": "reported_failed", "to": "failed"},
        {"from": "failed", "event": "retry", "to": "waiting_user"},
        {"from": "review", "event": "rejected", "to": "waiting_user", "guard": "retries_left"},
        {"from": "review", "event": "rejected", "to": "failed", "guard": "no_retries_left"}
      ]
    }
  }
}
```

- 共通の流れ: `pending → running → review → done`。不合格なら `running` に戻り、回数を超えたら `failed`。`failed` は終端ではなく、依頼主の判断（`skip`）で `skipped` になるか、`retry`（もう一度やる）で戻る。やり直しの回数の上限は、既定は `max_retries`（2）で、目標に `max_retries`（0〜5 の整数）を書くとその目標だけ変えられる。
- `confirm: true` の目標は `running` の前に `awaiting_confirm` を通る。前提が失敗した目標は `blocked` になり、前提が済めば `pending` に戻る。
- `human` 種別だけ、`running`（自動実行中）の代わりに `waiting_user`（ボードで依頼主の入力待ち）を通る。不合格のときも `waiting_user` に戻る。差分はこの種別だけ。
- `guard` は Python 側の固定の判定名（`confirm`、`no_confirm`、`retries_left`、`no_retries_left`）。式は書かない。

## plan.json

```json
{
  "quest": "Q001",
  "title": "依頼の題名",
  "start": "2026-10-16",
  "due": "2026-10-18",
  "approved": false,
  "inputs": [
    {"name": "KGI定義.md", "source": "user", "reason": "依頼主の指定"},
    {"name": "売上_2026Q3.csv", "source": "auto", "reason": "KGI の元データ（書庫の用語『KGI』のヒント）"}
  ],
  "candidates": [
    {"name": "提案書_2025.pptx", "reason": "中身は読んでいない。名前からは関係が分からない"}
  ],
  "goals": [
    {
      "id": "G1",
      "title": "競合 3 社の価格を調べる",
      "kind": "auto",
      "class": "wizard",
      "deps": [],
      "scheduled": "2026-10-16",
      "due": "2026-10-17",
      "criteria": {
        "viewpoint": "価格の出典がある",
        "pass_line": "3 社すべてに出典 URL がある",
        "check": "出典 URL を開いて価格が一致するか確かめる"
      },
      "state": "pending",
      "retries": 0,
      "output": null
    },
    {
      "id": "G2",
      "title": "社内の承認を取る",
      "kind": "human",
      "deps": ["G1"],
      "scheduled": "2026-10-17",
      "due": "2026-10-18",
      "criteria": {"viewpoint": "...", "pass_line": "...", "check": "..."},
      "state": "pending",
      "retries": 0,
      "output": null
    }
  ]
}
```

- 辺は `deps`（前提となる目標の ID）で表す。別に辺の配列は持たない。
- `kind` は `auto` か `human`。分解時に付け、計画の承認で直す。`human` は、役（魔法使い・錬金術師・冒険者）にできない作業（他のシステムの操作、承認、依頼主の判断、冒険者にも読めない情報の入手）だけ。調査・転記・整理・執筆は `auto`。
- `class`（職業）は、`auto` の目標に必須で、実行する役を決める：`wizard`（魔法使い。調べる・比べる・出典を確かめる）、`alchemist`（錬金術師。すでにある材料から、書く・整理する。まとめの納品物を含む。Web なし）、`adventurer`（冒険者。動的ページをブラウザで読む）のどれか。`human` の目標には付けない（付いている・`auto` なのにない・上の3つ以外はエラー）。受付係が決める。旧 `needs_browser: true` は廃止し、`class: adventurer` に置き換えた。ギルドマスターは、`ready` の目標を `class` に応じて `guild:wizard`・`guild:alchemist`・`guild:adventurer` で呼ぶ（冒険者は、ブラウザが1つなので同時に1人まで）。
- 旧形式（`todos`）の `plan.json` は読めない（`guild.py` は「旧形式の計画です」で止まり、自動の移行はしない）。`arrivals`・`wait` は、その依頼の `inbox` を数えず、ボードは「旧形式の依頼」と表示する。
- `deliverable: true` は、依頼主に渡す資料（納品物）を作る目標の印。最後の「まとめの目標」に付ける。ボードの受け取りの確認には、この目標の成果物だけを納品物として出す（ほかは「途中の資料（材料）」）。出力は Markdown だけで、PowerPoint・Excel などが要るときは、Claude Code に渡すプロンプトを `*.prompt.md` で出す（受付係が目標にするか、魔法使い・錬金術師が実行中に足す。足しても目標は増えず、承認は取らない）。
- `inputs` は、この依頼で使うインプット（`guild/inputs/` のファイル名）。インプットは `guild/inputs/` に1つだけ置き、各依頼は名前で参照する（大文字小文字は区別しない）。アップロードした名前が既にあり内容が違えば上書きし、上書き前の版を `.work/backup/Q###/` に残す（`close` で、閉じた依頼の分を消す）。`source` が `user` は依頼主の指定（「＋ 新規」で選んだ・アップロードした。`request.json` の `inputs`）、`auto` は受付係の選択。`reason` は理由。`user` が先頭。`candidates` は、受付係が迷って選ばなかったもの（理由つき）。名前は `inputs` と `candidates` をまたいで重ならない。魔法使い・錬金術師・冒険者・鑑定士は、`inputs` のファイルを `guild/inputs/<name>` で読む。納品物の型（見出しの並びなど）は、インプットに付けて依頼文で伝える。
  - `adopt` は、受付係が書いた名前（`plan-draft.json` の `inputs`・`candidates`。各要素は `name` と `reason`）が `guild/inputs/` にあるかを検査する。`replan` のときは、旧計画の `inputs`（依頼主の追加・外すを反映済み）を引き継ぎ、依頼主が外したままの名前は足さない。
  - ボードの `inputs` の入力で、足す・外すができる（承認前でも、進行中でも可。中止・見直し中・受け取り後は拒否）。足す名前は `guild/inputs/` にあること、外す名前は `inputs` にあること。足したものは `source` が `user`、`reason` が「依頼主が追加」になり、`candidates` から除かれる。履歴には `{event: "inputs", add, remove}` を残す（`id` は付けない）。
- 報告のファイル名は、`reports/<id>-<class>.md`（`<id>-wizard.md`・`<id>-alchemist.md`・`<id>-adventurer.md`）。鑑定士の出典の確認（冒険者の確認モード）は `reports/<id>-verify-adventurer.md`。`<id>-user.md`（`human` の結果）・`<id>-appraiser.md` は変わらない。成果物は、どの職業でも `output/<id>/`。
- `human` の目標には `instruction`（依頼主が読んでそのまま動ける、何を・どこで・何を使って・終わったら何を教えるか）を付ける。ボードの「あなたの番」の手紙に出る。
- `criteria` は合格基準（観点・合格ライン・確かめ方）。空の目標は検証で弾く。
- 日付は `YYYY-MM-DD` の実在する日だけ（形式が違うとエラー）。表示と警告だけで、遷移には使わない。
  - 依頼の `start`（開始日）と `due`（締切）：最上位。依頼主が `request.json` に書くか、ボードで変える。
  - 目標の `scheduled`（実行予定日）：受付係が依存関係から決める。
  - 目標の `due`（締切。任意。`null` で解除）。
  - `adopt` の既定：未指定の依頼の `start` は今日、`due` は `start`。目標の `scheduled` は依頼の `start`、目標の `due` は依頼の `due`。`replan` のときは旧計画の依頼の `start`・`due` を引き継ぐ。
  - 矛盾（締切が開始日より前、予定日が前提の目標より前など）は、ボードの警告表示だけで、拒否しない。1つの日付を変えても、ほかの目標の日付は連動してずらさない。
  - ボードの `due` の入力で設定・変更する（承認前でも、進行中でも可。中止・見直し中は拒否）。履歴には `{event: "due", goal, …}` を残す（`id` は付けない）。
- `approved` が `true` になるまで、実行（`next`）は何も返さない。
- `accepted` は、依頼主が納品物を受け取ったとき（`accept` の入力）に `true` になる。全目標が済んでも、`accepted` になるまでは完了ではない。`next` の出力の `awaiting_accept`（受け取り待ち）と `complete`（完了）で見分ける。「直してほしい」は `decision` の `replan`（コメント付き）。

## request.json（依頼）

ボードの「＋ 新規」は、受付待ちの依頼を `.work/requests/R<日時>.json` に書き、アップロードの中身を `.work/requests/files/R<日時>/` に置く。`new <root> R<日時>` が取り込むと、依頼のフォルダの `request.json` になる。

```json
{"type": "request", "text": "KGI の達成状況をまとめて", "start": "2026-10-16", "due": null,
 "inputs": ["KGI定義.md"], "files": ["メモ.txt"], "created": "2026-10-16T10:00:00Z"}
```

- `text`：依頼文。`start`・`due`：依頼の開始日・締切（`null` は未指定）。
- `inputs`：既存の `guild/inputs/` から選んだ名前。1つでもなければ、依頼を `.work/requests/rejected/` に移して拒否する。
- `files`：アップロードの名前。取り込むと `guild/inputs/` に置き、`request.json` の `inputs` は「選んだ名前＋アップロードの名前」（重なりを除き、選んだものが先）になる。
- チャットから出す依頼は、ギルドマスターが `{"type": "request", "text": "<依頼文>", "files": []}` を書く。

## 入力（`.work/Q###/inbox/*.json`）

ボードが書き、`guild.py ingest`（計画がない依頼の `answers` は `guild.py answers`）が取り込む。ファイル名は `<日時>-<種類>[-<目標>].json`。

| `type` | 形 | 意味 |
|---|---|---|
| `answers` | `{"type": "answers", "answers": [{"q": "質問", "choice": "選んだもの", "note": "補足"}, …]}`（いくつでも選べる質問は `choices` に配列も） | 計画ができる前の質問への回答（`answers` が取り出して受付係に渡す） |
| `approve` | `{"type": "approve"}` | 計画の承認（承認済みなら拒否） |
| `accept` | `{"type": "accept"}` | 全目標が済んだあとの、納品物の受け取り（済んでいない・受け取り済みなら拒否） |
| `confirm` | `{"type": "confirm", "goal": "G3", "ok": true}` | 実行前の確認（実行する／しない） |
| `result` | `{"type": "result", "goal": "G2", "ok": true, "note": "…", "files": ["…"]}` | `human` の結果（できた／できなかった、一言メモ、添付は `inbox/files/`）。`reports/<id>-user.md` に書き写す |
| `decision` | `{"type": "decision", "goal": "G2", "choice": "skip"}`（`drop` も同じ形）／`{"type": "decision", "choice": "replan", "comment": "…"}`／`{"type": "decision", "choice": "abort"}` | 失敗の判断（その目標だけやめる `skip`、後続もやめる `drop`）、計画の作り直し `replan`、中止 `abort` |
| `due` | `{"type": "due", "start": "…", "due": "…"}`／`{"type": "due", "goal": "G1", "scheduled": "…", "due": "…"}` | 日付の設定。`goal` がなければ依頼の `start`・`due`、あれば目標の `scheduled`・`due`。解除（`null`）できるのは目標の `due` だけ |
| `inputs` | `{"type": "inputs", "add": [名前…], "remove": [名前…]}` | このクエストのインプットを足す・外す（上の `plan.json` の `inputs` を参照） |
| `archive` | `{"type": "archive", "decisions": {"C1": "register", "C2": "skip"}}` | 書庫の登録候補への答え（中止した依頼でも受け付ける） |

中止した依頼は、`archive` 以外の入力を拒否する。見直し中（`replan`）は、`abort` 以外を拒否する。

ほかの入力の置き場：書庫への直接の入力（`entry`・`promote`・`deprecate`・`retype`）は `.work/archive-inbox/`（`archive-ingest`、形は `docs/archive-spec.md`）、外部サイトの答え（`{"type": "web", "decisions": {ドメイン: "allow"|"once"|"deny"}, "add": [...], "remove": [...]}`）は `.work/web/inbox/`（`web-ingest`）。

## guild.py のコマンド

| コマンド | 動き |
|---|---|
| `init <root>` | `<root>/guild/`（`archive/`（`index.md`。フラット）・`inputs/`・`deliverables/`・`.work/`（`requests/` など作業用。`config.json` と `codex/` もここ）・`board.html`）を作る。依頼主が見る場所は `inputs/`・`deliverables/`・`archive/`・`board.html` の 4 つだけ。設定は `guild/.work/config.json`。`skills/quest/codex.md`（既定のギルドの掟）を `guild/.work/codex/default.md` にコピーし（毎回更新）、`guild/.work/codex/project.md`（プロジェクトの追記。あれば消さない）を置く。何度実行しても依頼のデータは消さない。`board.html` は最新の版に置き換える |
| `requests <root>` | ボードが保存した受付待ちの依頼を一覧する |
| `new <root> [依頼のID]` | 次の依頼のフォルダ（`guild/.work/Q001…`。出力の `dir`）を作る。ID を渡すと、受付待ちの依頼を取り込み、アップロードを共通の `guild/inputs/` に置く。依頼の `inputs`（既存から選んだ名前）が `guild/inputs/` になければ拒否し、依頼を `.work/requests/rejected/`（理由は `<ID>.json.reason.txt`）へ移す（番号は進まない）。`request.json` の `inputs` は、選んだ名前とアップロードの名前を合わせたもの |
| `inputs-list <root> [--text 依頼文 / --text-file パス]` | `guild/inputs/` のファイルごとに `name`・`ext`・`size`・`updated`・`head`（`.md` `.txt` `.csv` の先頭5行。ほかは `null`）・`hints` を返す。`hints` は、依頼文に名前・別名が出てくる書庫の項目（確認済みか出典ありで、使われているもの。3文字以上の語だけ。心得は除く）の `inputs` に挙がったファイルと、ファイル名・先頭の行にその語が出てくるファイルに付く理由。ヒントのあるファイルが先。受付係にだけ渡す |
| `arrivals <root>` | ボードから届いて、まだ取り込んでいない入力と依頼を一覧する |
| `wait <root> [秒]` | 入力か依頼が届くまで待つ（既定 540 秒）。届いていれば、すぐ返す |
| `answers <dir>` | 計画がない依頼の、質問への回答を取り出す |
| `archive-propose <dir>` | 司書の候補（`reports/archive-draft.json`）を検査し、心得は登録、ほかは確認待ち（`archive.json` の `status` が `proposed`）にする。同名・別名の項目は更新の候補にする。候補は12件まで |
| `archive-ingest <root>` | `.work/archive-inbox/` の入力（`entry`・`promote`・`deprecate`・`retype`）を書庫に反映し、索引（`archive/index.md`）を作り直す |
| `adopt <plan.json>` | 同じフォルダの `reports/plan-draft.json` を検査（`validate` と同じ検査に加えて、`inputs`・`candidates` の名前が `guild/inputs/` にあるか）し、承認前の `plan.json` にする（`inputs` は依頼主の指定が先頭、`candidates` は選ばなかった候補）。さらに計画の質を検査する（下の「計画の質の検査」）。すでにあれば上書きしない（`status` が `replan` のときだけ、完了済みの目標と、依頼主が直した `inputs` を引き継いで置き換える） |
| `validate <plan.json>` | `deps` の参照切れ、循環、`kind`・`criteria` の欠け、未知の `state`、`human` の `confirm`、`inputs`・`candidates` の形の誤り（名前・`source`・`reason`・重なり）を検出する |
| `sync <plan.json>` | 前提の結果に応じて `deps_done`・`dep_failed`・`unblock` を、動かなくなるまで適用する（承認前・中止・見直し中は何もしない） |
| `next <plan.json>` | 状態を変えず、`ready`・`confirm`・`waiting_user`・`review`・`blocked`・`failed` に分けて返す。`ready_by_class`（実行できる目標を、職業 `wizard`／`alchemist`／`adventurer` ごとに分けたもの）、`runnable`・`finished`・`status`・`approved`・`awaiting_accept`・`complete` も返す。書庫の記録の進み具合として `archive`（`none`／`proposed`／`done`。壊れた `archive.json` は `proposed`）、`needs_archive`（完了・中止したが書庫の記録がまだ）、`closed`（書庫の確認まで済んで、もう何もしない）も返す |
| `advance <plan.json> <ID> <event>` | `transitions.json` を引いて状態を1つ進める。定義にない遷移はエラー |
| `publish <dir>` | 全目標が済んだ依頼（`awaiting_accept`）の納品物（`deliverable` の目標の `.md` と、どの目標でも `*.prompt.md`）を `guild/deliverables/Q###_…` にコピーする。何度実行しても同じ。`replan` で取り下げられる |
| `close <root>` | 閉じた依頼（受け取り済みか中止）の、インプットのバックアップ（`.work/backup/Q###`）を消す。進行中の依頼のものは残す |
| `ingest <plan.json>` | `inbox/*.json`（下の「入力」）を検査して反映し、処理済みを `inbox/done/` に移す。不正な入力は `inbox/rejected/` に移して理由を出す。`accept` を取り込むと納品物を置き（`publish` と同じ）、`decision` の `abort`・`replan` では取り下げる |
| `web-ingest <root>` | `.work/web/inbox/` の依頼主の答え（WebFetch の許可・不許可、許可リストの追加・削除）を `.work/web/access.json` に反映する。不正な入力は `rejected/` に理由（`<入力>.reason.txt`）つきで移す |
| `web-pending <root>` | 魔法使いがフックに止められて、依頼主の答え待ちのドメイン（`access.json` の `pending`）を一覧する |
| `web-reset <root>` | 「今回だけ」の許可（`once`）と、許可しなかった記録（`denied`）を空にする（依頼の完了・中止のとき）。出力の `cleared` は消したもの、`allow` は残った許可リスト |
| `pause <root>` | 「ギルドを閉める」。`guild/.work/pause.json`（`{"type": "pause", "created": …}`）を書く。ボードの「ギルドを閉める」と `/guild:close` が使う。`guild/` がなければエラー。依頼は中止にならない |
| `pause-status <root>` | pause.json があるか（`paused`）。中身は見ず、壊れていても「あり」。ギルドマスターが周回の頭で見る。あれば、新しい役を呼ばず、実行中の役が終わるのを待って止まる |
| `pause-clear <root>` | pause.json を消す（`cleared`）。`/guild:quest` の起動時（ギルドを開ける）。なくても何も起きない |
| `stats <root>` | 効果の測定。依頼ごとの目標数・完了・失敗・やめた数と、不合格（`rejected`）・もう一度やる（`retry`）・計画の直し（`replanned`）の回数を `history` から数え、合計と「目標あたりの不合格回数」（`rejected_per_goal`）を返す。壊れた `plan.json` は読み飛ばす。計画の質を上げる施策が効いたかを見るための数 |

イベント: `deps_done`（`sync` が送る）、`submitted`（実行結果が出た／依頼主が入力した）、`passed`、`rejected`。ほかに `dep_failed`・`unblock`・`confirmed`・`declined`・`reported_failed`・`skip`・`retry`。
`advance <plan> <id> passed` は、証拠ゲートを通らないと拒否される：鑑定士の報告 `reports/<id>-appraiser.md` があり、空でなく、「## 判定」の次の語が `passed` で、その目標が鑑定待ち（`review`）になったあとに書かれていること（`needs_adventurer` の 1 回目の報告では通らない）（古い報告のままの合格を防ぐ。`rejected` には要らない）。

## 決定（未決だった3点）

- **入力の戻し方**: 旧版（`feat/guild-0.1`）と同じく、画面は `plan.json` を書かない。画面は File System Access API（`showDirectoryPicker`）で `guild/` 内の `inbox/*.json` に入力だけを書き、`guild.py ingest` が検査して `plan.json` に反映する。`plan.json` を書けるのは `guild.py` だけ。
  - 入力ファイルの種類と形は、上の「入力」の表。
  - 反映の合図は要らない。`/guild:quest` が `guild.py wait` で到着を待ち、届いたら `ingest` で取り込む。
- **入力の契約と書き込み側の方針**: 境界は『`guild/.work/Q###/inbox/*.json` に入力が置かれたら `guild.py ingest` が拾う』に固定する。最初の版の書き込み側は File System Access API とし、書けないときは『JSON をコピー』ボタンに落とす。保存の失敗は理由を画面に出す。ローカルサーバー（`guild.py serve`）は最初の版では作らない。自動で進めたくなったら書き込み側だけを差し替える。
- **確認の印**: 目標に `confirm: true` を持たせる。分解時に付け、計画の承認で見える。`next` は、`confirm: true` の目標を『確認待ち』として別に返し、確認が済むまで `running` にしない。
- **失敗の扱い**: `failed` の目標に依存する後続は止める（`blocked`）。依存しない系統は進め続ける。ボードで依頼主に『もう一度やる（`retry`。やり直しの回数を 0 に戻し、古い成果物と報告を `prev/` へ退避する。確認の印の目標は、もう一度確認を聞く）／その目標だけやめて後続は進める（`skip`）／後続もやめる（`drop`）／計画を直す（`replan`）／中止（`abort`）』を選んでもらい、`decision` として戻す。

## 排他ロックと保存の順序

- `sync`・`advance`・`ingest`・`adopt` は、`plan.json` の読みから保存までを `plan.json.lock`（`O_EXCL`）で 1 つずつにする。役を並列に呼んで同時に `advance` しても、更新が消えない。待つのは最大 15 秒で、超えるとエラー。60 秒より古いロックは、落ちたプロセスの残りとして取り上げる。
- `plan.json` などの保存は、`<ファイル>.<pid>.tmp` に書いてから置き換える。Windows・OneDrive で置き換えが `PermissionError` になったら、短い間隔で数回やり直す。
- `ingest` は、計画を保存してから `inbox/` の入力を `done/`・`rejected/` へ移す。`adopt`（replan）は、計画を保存してから古い成果物と報告を `prev/` へ移す。途中で落ちても、入力や成果物は元の場所に残る。
- replan の引き継ぎ（`carry_over`）は、完了済みで、種別・職業（`class`）・題名・合格基準・`deps` が同じで、依存先もすべて引き継がれる目標だけ。上流が変わった目標の下流は引き継がない。
- 古いロックの取り上げは `plan.json.lock.steal`（`O_EXCL`）で 1 人に絞り、その中で古さを確かめ直す。ロックの解除に失敗しても（OneDrive・ウイルス対策が掴んでいる）、例外にせず、60 秒で取り上げられる。
- `ingest` の入力の移動と `adopt` の成果物の退避が保存のあとに失敗したときは、戻りの `warnings` に出す（計画は保存済みなので、やり直さない）。
- 制約：ロックは `plan.json` だけを守る。`archive.json` を書く `archive-propose`・`archive-ingest` と、`ingest` の中の書庫の確認（`archive_decide`）は、ロックの外にある。`ingest` が計画の保存前に落ちた場合、書庫の確認の入力だけは、再実行すると「確認待ちがありません」で拒否される（登録は済んでいる）。


## 計画の質の検査（adopt）

`adopt` は、`validate` に加えて計画の質を検査する（承認前の計画だけ。進行中の計画には適用しない）。

- **エラー（受付係に差し戻す）**: `deliverable: true` の目標がちょうど 1 件でない。`human` の目標に `instruction` がない。`auto` の目標に `class` がない・`wizard`／`alchemist`／`adventurer` 以外・`human` の目標に `class` がある。`brief.coverage` が、ない目標を指している。
- **警告（`plan.json` の `check.warnings` に残り、承認の手紙に出る。承認は止めない）**: `criteria` に測れない言葉（適切・十分・適宜・なるべく・できるだけ・速やか・高品質・わかりやすく・きちんと・しっかり・必要に応じて）がある。`criteria` の値が 6 文字未満。目標が 12 件を超える。自己点検（`brief`）がない・`intent` や `coverage` が空・要件に対応する目標がない。
- **`brief`**（受付係の自己点検。`plan-draft.json` に書き、整えて `plan.json` に入る）: `intent`（依頼の言い換え）、`non_goals`、`assumptions`（推測で決めた前提）、`risks`、`coverage`（`[{requirement, goals: [id…]}]`）。
- **`workload`**（`guild.py` が計算して `plan.json` に入る）: `human`（あなたの実行の件数）、`days`（予定日ごとの件数）、`items`、`over_deadline`（依頼の締切を過ぎる予定の目標）。
- **`replan_diff`**（replan のときだけ）: `added`・`removed`・`changed`（やり直しになる目標）・`carried`（引き継がれた目標）。

## 稼働の印（heartbeat）

`guild.py wait` は待っている間、`arrivals` は呼ばれるたびに、`guild/.work/heartbeat.json`（`{"state": "waiting" か "working", "t": 時刻, "pid"}`）を書く（`wait` は 10 秒ごと）。ボードはこれを読んで、「Claude 待機中」「作業中」「停止中（最後の稼働の時刻）」を出す。ボードで答えても `/guild:quest` が動いていなければ誰にも拾われないので、それに気づくための印。書けなくても、コマンドは止まらない。

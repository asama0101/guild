# グラフ定義の形式

`docs/spec.md` の「進め方をグラフ定義のデータで持つ」を具体化する。決定済み: 実行主体は Python スクリプト、形式は JSON、遷移定義は「全 Todo 共通の1つ＋種別ごとの差分」。

## 2つのファイル

| ファイル | 置き場 | 持つもの | 変わる頻度 |
|---|---|---|---|
| `transitions.json` | プラグイン同梱 | 状態遷移グラフ（全依頼で共通） | 開発時のみ |
| `plan.json` | `guild/.work/<依頼>/` | Todo の依存グラフと、各 Todo の現在の状態 | 実行中に更新 |

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
    {"from": "failed", "event": "skip", "to": "skipped"}
  ],
  "kinds": {
    "auto": {"override": []},
    "human": {
      "override": [
        {"from": "pending", "event": "deps_done", "to": "waiting_user"},
        {"from": "waiting_user", "event": "submitted", "to": "review"},
        {"from": "waiting_user", "event": "reported_failed", "to": "failed"},
        {"from": "review", "event": "rejected", "to": "waiting_user", "guard": "retries_left"},
        {"from": "review", "event": "rejected", "to": "failed", "guard": "no_retries_left"}
      ]
    }
  }
}
```

- 共通の流れ: `pending → running → review → done`。不合格なら `running` に戻り、回数を超えたら `failed`。`failed` は終端ではなく、依頼主の判断（`skip`）で `skipped` になる。
- `confirm: true` の Todo は `running` の前に `awaiting_confirm` を通る。前提が失敗した Todo は `blocked` になり、前提が済めば `pending` に戻る。
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
  "todos": [
    {
      "id": "T1",
      "title": "競合 3 社の価格を調べる",
      "kind": "auto",
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
      "id": "T2",
      "title": "社内の承認を取る",
      "kind": "human",
      "deps": ["T1"],
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

- 辺は `deps`（前提となる Todo の ID）で表す。別に辺の配列は持たない。
- `kind` は `auto` か `human`。分解時に付け、計画の承認で直す。`human` は、冒険者にできない作業（他のシステムの操作、承認、依頼主の判断、冒険者・斥候には読めない情報の入手）だけ。調査・転記・整理・執筆は `auto`。
- `deliverable: true` は、依頼主に渡す資料（納品物）を作る Todo の印。最後の「まとめの Todo」に付ける。ボードの受け取りの確認には、この Todo の成果物だけを納品物として出す（ほかは「途中の資料（材料）」）。`template` は納品物のテンプレート（`guild/templates/` の中のファイルのパス。あれば `adopt` が存在と形式を検査する。テンプレートは Markdown（`.md`）だけ）。出力は Markdown だけで、PowerPoint・Excel などが要るときは、Claude Code に渡すプロンプトを `*.prompt.md` で出す（地図師が Todo にするか、冒険者が実行中に足す。足しても Todo は増えず、承認は取らない）。
- `auto` の Todo のうち、読む相手が動的ページのものには `needs_browser: true` を付ける。ギルドマスターが、冒険者の代わりに斥候を呼ぶ（成果物と報告は同じ `output/<id>/`、報告は `reports/<id>-scout.md`）。
- `human` の Todo には `instruction`（依頼主が読んでそのまま動ける、何を・どこで・何を使って・終わったら何を教えるか）を付ける。ボードの「あなたの番」の手紙に出る。
- `criteria` は合格基準（観点・合格ライン・確かめ方）。空の Todo は検証で弾く。
- 日付は `YYYY-MM-DD` の実在する日だけ（形式が違うとエラー）。表示と警告だけで、遷移には使わない。
  - 依頼の `start`（開始日）と `due`（締切）：最上位。依頼主が `request.json` に書くか、ボードで変える。
  - Todo の `scheduled`（実行予定日）：地図師が依存関係から決める。
  - Todo の `due`（締切。任意。`null` で解除）。
  - `adopt` の既定：未指定の依頼の `start` は今日、`due` は `start`。Todo の `scheduled` は依頼の `start`、Todo の `due` は依頼の `due`。`replan` のときは旧計画の依頼の `start`・`due` を引き継ぐ。
  - 矛盾（締切が開始日より前、予定日が前提の Todo より前など）は警告だけで、拒否しない。
  - ボードの `due` の入力で設定・変更する（承認前でも、進行中でも可。中止・見直し中は拒否）。履歴には `{event: "due", todo, …}` を残す（`id` は付けない）。
- `approved` が `true` になるまで、実行（`next`）は何も返さない。
- `accepted` は、依頼主が納品物を受け取ったとき（`accept` の入力）に `true` になる。全 Todo が済んでも、`accepted` になるまでは完了ではない。`next` の出力の `awaiting_accept`（受け取り待ち）と `complete`（完了）で見分ける。「直してほしい」は `decision` の `replan`（コメント付き）。

## guild.py のコマンド

| コマンド | 動き |
|---|---|
| `init <root>` | `<root>/guild/`（`archive/`（`index.md`。フラット）・`.work/`（`requests/` など作業用）・`config.json`・`board.html`）を作る。何度実行しても依頼のデータは消さない |
| `requests <root>` | ボードが保存した受付待ちの依頼を一覧する |
| `new <root> [依頼のID]` | 次の依頼のフォルダ（`guild/.work/Q001…`。出力の `dir`）を作る。ID を渡すと、受付待ちの依頼を取り込み、素材を共通の `guild/inputs/` に置く（`request.json` の `inputs` にファイル名） |
| `arrivals <root>` | ボードから届いて、まだ取り込んでいない入力と依頼を一覧する |
| `wait <root> [秒]` | 入力か依頼が届くまで待つ（既定 540 秒）。届いていれば、すぐ返す |
| `answers <dir>` | 計画がない依頼の、質問への回答を取り出す |
| `archive-propose <dir>` | 司書の候補（`reports/archive-draft.json`）を検査し、心得は登録、ほかは確認待ち（`archive.json` の `status` が `proposed`）にする。同名・別名の項目は更新の候補にする。候補は12件まで |
| `archive-ingest <root>` | `.work/archive-inbox/` の入力（`entry`・`promote`・`deprecate`・`retype`）を書庫に反映し、索引（`archive/index.md`）を作り直す |
| `adopt <plan.json>` | 同じフォルダの `reports/plan-draft.json` を検査（`validate` と同じ検査に加えて、`template` の存在と形式）し、承認前の `plan.json` にする。すでにあれば上書きしない（`status` が `replan` のときだけ、完了済みの Todo を引き継いで置き換える） |
| `validate <plan.json>` | `deps` の参照切れ、循環、`kind`・`criteria` の欠け、未知の `state`、`human` の `confirm` を検出する |
| `sync <plan.json>` | 前提の結果に応じて `deps_done`・`dep_failed`・`unblock` を、動かなくなるまで適用する（承認前・中止・見直し中は何もしない） |
| `next <plan.json>` | 状態を変えず、`ready`・`confirm`・`waiting_user`・`review`・`blocked`・`failed` に分けて返す。`runnable`・`finished`・`status`・`approved`・`awaiting_accept`・`complete` も返す |
| `advance <plan.json> <ID> <event>` | `transitions.json` を引いて状態を1つ進める。定義にない遷移はエラー |
| `publish <dir>` | 全 Todo が済んだ依頼（`awaiting_accept`）の納品物（`deliverable` の Todo の `.md` と、どの Todo でも `*.prompt.md`）を `guild/deliverables/Q###_…` にコピーする。何度実行しても同じ。`replan` で取り下げられる |
| `close <root>` | 閉じた依頼（受け取り済みか中止）の、インプットのバックアップ（`.work/backup/Q###`）を消す。進行中の依頼のものは残す |
| `ingest <plan.json>` | `inbox/*.json` を検査して反映し、処理済みを `inbox/done/` に移す。不正な入力は `inbox/rejected/` に移して理由を出す |

イベント: `deps_done`（`sync` が送る）、`submitted`（実行結果が出た／依頼主が入力した）、`passed`、`rejected`。ほかに `dep_failed`・`unblock`・`confirmed`・`declined`・`reported_failed`・`skip`。

## 決定（未決だった3点）

- **入力の戻し方**: 旧版（`feat/guild-0.1`）と同じく、画面は `plan.json` を書かない。画面は File System Access API（`showDirectoryPicker`）で `guild/` 内の `inbox/*.json` に入力だけを書き、`guild.py ingest` が検査して `plan.json` に反映する。`plan.json` を書けるのは `guild.py` だけ。
  - 入力ファイルの種類: `approve`（計画の承認）、`accept`（全 Todo が済んだあとの、納品物の受け取り。済んでいないとき・受け取り済みのときは拒否）、`confirm`（実行前の確認：実行する／しない）、`result`（`human` の結果：できた／できなかった、添付パス）、`decision`（`failed` 時の判断 `skip`・`drop`、計画の作り直し `replan`、中止 `abort`）、`due`（日付の設定。`todo` を付けると Todo の `scheduled`・`due`、付けないと依頼の `start`・`due`。`due` の解除は Todo の締切だけ）。
  - 反映の合図は要らない。`/guild:quest` が `guild.py wait` で到着を待ち、届いたら `ingest` で取り込む。
- **入力の契約と書き込み側の方針**: 境界は『`guild/inbox/*.json` に入力が置かれたら `guild.py ingest` が拾う』に固定する。最初の版の書き込み側は File System Access API とし、書けないときは『JSON をコピー』ボタンに落とす。保存の失敗は理由を画面に出す。ローカルサーバー（`guild.py serve`）は最初の版では作らない。自動で進めたくなったら書き込み側だけを差し替える。
- **確認の印**: Todo に `confirm: true` を持たせる。分解時に付け、計画の承認で見える。`next` は、`confirm: true` の Todo を『確認待ち』として別に返し、確認が済むまで `running` にしない。
- **失敗の扱い**: `failed` の Todo に依存する後続は止める（`blocked`）。依存しない系統は進め続ける。ボードで依頼主に『その Todo だけやめて後続は進める（`skip`）／後続もやめる（`drop`）／計画を直す（`replan`）／中止（`abort`）』を選んでもらい、`decision` として戻す。

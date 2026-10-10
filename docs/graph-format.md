# グラフ定義の形式

`docs/spec.md` の「進め方をグラフ定義のデータで持つ」を具体化する。決定済み: 実行主体は Python スクリプト、形式は JSON、遷移定義は「全 Todo 共通の1つ＋種別ごとの差分」。

## 2つのファイル

| ファイル | 置き場 | 持つもの | 変わる頻度 |
|---|---|---|---|
| `transitions.json` | プラグイン同梱 | 状態遷移グラフ（全依頼で共通） | 開発時のみ |
| `plan.json` | `guild/<依頼>/` | Todo の依存グラフと、各 Todo の現在の状態 | 実行中に更新 |

## transitions.json

```json
{
  "initial": "pending",
  "terminal": ["done", "skipped"],
  "transitions": [
    {"from": "pending",      "event": "deps_done", "to": "running"},
    {"from": "running",      "event": "submitted", "to": "review"},
    {"from": "review",       "event": "passed",    "to": "done"},
    {"from": "review",       "event": "rejected",  "to": "running", "guard": "retries_left"},
    {"from": "review",       "event": "rejected",  "to": "failed",  "guard": "no_retries_left"}
  ],
  "kinds": {
    "auto": {},
    "human": {
      "override": [
        {"from": "pending", "event": "deps_done", "to": "waiting_user"},
        {"from": "waiting_user", "event": "submitted", "to": "review"}
      ]
    }
  },
  "max_retries": 2
}
```

- 共通の流れ: `pending → running → review → done`。不合格なら `running` に戻り、回数を超えたら `failed`。
- `human` 種別だけ、`running`（自動実行中）の代わりに `waiting_user`（ボードで依頼主の入力待ち）を通る。差分はこの種別だけ。
- `guard` は Python 側の固定の判定名（`retries_left`、`no_retries_left`）。式は書かない。

## plan.json

```json
{
  "quest": "Q001",
  "title": "依頼の題名",
  "approved": false,
  "todos": [
    {
      "id": "T1",
      "title": "競合 3 社の価格を調べる",
      "kind": "auto",
      "deps": [],
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
      "criteria": {"viewpoint": "...", "pass_line": "...", "check": "..."},
      "state": "pending",
      "retries": 0,
      "output": null
    }
  ]
}
```

- 辺は `deps`（前提となる Todo の ID）で表す。別に辺の配列は持たない。
- `kind` は `auto` か `human`。分解時に付け、計画の承認で直す。`human` は、冒険者にできない作業（他のシステムの操作、承認、依頼主の判断）だけ。調査・転記・整理・執筆は `auto`。
- `deliverable: true` は、依頼主に渡す資料（納品物）を作る Todo の印。最後の「まとめの Todo」に付ける。ボードの受け取りの確認には、この Todo の成果物だけを納品物として出す（ほかは「途中の資料（材料）」）。`template` は納品物のテンプレート（`guild/templates/` の中のファイルのパス。あれば `adopt` が存在を検査する）。`format` は納品物の形式（`guild.py` の `FORMATS`。今は `md` だけ。未対応の形式は検査で落ちる）。
- `auto` の Todo のうち、読む相手が動的ページのものには `needs_browser: true` を付ける。ギルドマスターが、冒険者の代わりに斥候を呼ぶ（成果物と報告は同じ `output/<id>/`、報告は `reports/<id>-scout.md`）。
- `human` の Todo には `instruction`（依頼主が読んでそのまま動ける、何を・どこで・何を使って・終わったら何を教えるか）を付ける。ボードの「あなたの番」の手紙に出る。
- `criteria` は合格基準（観点・合格ライン・確かめ方）。空の Todo は検証で弾く。
- `approved` が `true` になるまで、実行（`next`）は何も返さない。
- `accepted` は、依頼主が納品物を受け取ったとき（`accept` の入力）に `true` になる。全 Todo が済んでも、`accepted` になるまでは完了ではない。`next` の出力の `awaiting_accept`（受け取り待ち）と `complete`（完了）で見分ける。「直してほしい」は `decision` の `replan`（コメント付き）。

## guild.py のコマンド（最初の版）

| コマンド | 動き |
|---|---|
| `validate <plan.json>` | `deps` の参照切れ、循環、`kind`・`criteria` の欠け、未知の `state` を検出する |
| `sync <plan.json>` | 前提の結果に応じて `deps_done`・`dep_failed`・`unblock` を、動かなくなるまで適用する（承認前・中止・見直し中は何もしない） |
| `next <plan.json>` | 状態を変えず、`ready`・`confirm`・`waiting_user`・`review`・`blocked`・`failed` に分けて返す。`runnable`・`finished`・`status`・`approved` も返す |
| `advance <plan.json> <ID> <event>` | `transitions.json` を引いて状態を1つ進める。定義にない遷移はエラー |

イベント: `deps_done`（`sync` が送る）、`submitted`（実行結果が出た／依頼主が入力した）、`passed`、`rejected`。ほかに `dep_failed`・`unblock`・`confirmed`・`declined`・`reported_failed`・`skip`。

（このほか、`adopt`・`ingest`・`init`・`new`・`requests`・`arrivals`・`wait`・`answers` がある。一覧は `docs/plan-guild-py.md`。）

## 決定（未決だった3点）

- **入力の戻し方**: 旧版（`feat/guild-0.1`）と同じく、画面は `plan.json` を書かない。画面は File System Access API（`showDirectoryPicker`）で `guild/` 内の `inbox/*.json` に入力だけを書き、`guild.py ingest` が検査して `plan.json` に反映する。`plan.json` を書けるのは `guild.py` だけ。
  - 入力ファイルの種類: `approve`（計画の承認・修正）、`accept`（全 Todo が済んだあとの、納品物の受け取り。済んでいないとき・受け取り済みのときは拒否）、`result`（`human` の結果：できた／できなかった、添付パス）、`decision`（`failed` 時の判断）。
  - 反映の合図は、画面で送信したあとにチャットで「完了」と伝える方式（旧版の `/guild:quest` 再実行に相当）。
- **入力の契約と書き込み側の方針**: 境界は『`guild/inbox/*.json` に入力が置かれたら `guild.py ingest` が拾う』に固定する。最初の版の書き込み側は File System Access API とし、書けないときは『JSON をコピー』ボタンに落とす。保存の失敗は理由を画面に出す。ローカルサーバー（`guild.py serve`）は最初の版では作らない。自動で進めたくなったら書き込み側だけを差し替える。
- **確認の印**: Todo に `confirm: true` を持たせる。分解時に付け、計画の承認で見える。`next` は、`confirm: true` の Todo を『確認待ち』として別に返し、確認が済むまで `running` にしない。
- **失敗の扱い**: `failed` の Todo に依存する後続は止める（`blocked`）。依存しない系統は進め続ける。ボードで依頼主に『続行（その Todo を除く）／計画を直す／中止』を選んでもらい、`decision` として戻す。

## 旧版から分かった注意点

- `showDirectoryPicker` は Chromium 系のブラウザだけで動く。旧版は選んだフォルダの権限を IndexedDB に保存していた。
- 旧版の `1c6e755`（フォルダを覚えられない不具合）は、この保存まわりの不具合だった。新版では最初から、保存に失敗したら理由を画面に出す。

## 未決

- （解決済み）`blocked` と `confirm` 待ちは `transitions.json` に入っている。`failed` は終端ではなく、`skip` で `skipped` になる。

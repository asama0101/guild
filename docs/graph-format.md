# グラフ定義の形式（案）

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
  "terminal": ["done", "failed"],
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
      ],
      "remove": [
        {"from": "running", "event": "submitted"}
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
- `kind` は `auto` か `human`。分解時に付け、計画の承認で直す。
- `criteria` は合格基準（観点・合格ライン・確かめ方）。空の Todo は検証で弾く。
- `approved` が `true` になるまで、実行（`next`）は何も返さない。

## guild.py のコマンド（最初の版）

| コマンド | 動き |
|---|---|
| `validate <plan.json>` | `deps` の参照切れ、循環、`kind`・`criteria` の欠け、未知の `state` を検出する |
| `next <plan.json>` | `approved` で、前提がすべて `done` の `pending` Todo を一覧する（並列に進められるもの） |
| `advance <plan.json> <ID> <event>` | `transitions.json` を引いて状態を1つ進める。定義にない遷移はエラー |

イベント: `deps_done`（`next` が返した Todo に対して Claude が送る）、`submitted`（実行結果が出た／依頼主が入力した）、`passed`、`rejected`。

## 未決（実装計画で決める）

- ボード（HTML）は `plan.json` を読むだけの読み取り専用にし、依頼主の入力（計画の承認、`human` の結果）はどう `plan.json` へ戻すか。
- 不可逆・外部公開の操作を持つ Todo に印を付けるか（`confirm: true` など）。
- `failed` になった Todo の後続をどう扱うか（止める／依頼主に判断を求める）。

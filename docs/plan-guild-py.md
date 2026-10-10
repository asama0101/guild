# 実装計画：transitions.json と guild.py

（最初の段階の計画。現状は、`skills/quest/SKILL.md` と `guild.py` を正とする。のちに `adopt`・`init`・`new`・`requests`・`arrivals`・`wait`・`answers` を足し、状態の移り変わりを `plan.json` の `history` に記録するようにした。）

`docs/graph-format.md` の形式を実装する最初の段階。プラグインの外枠（skills / agents / commands）は含めない。標準ライブラリだけで書く。

## 作るもの

| ファイル | 内容 |
|---|---|
| `skills/quest/transitions.json` | 状態遷移グラフ（共通1つ＋`human` の差分） |
| `skills/quest/guild.py` | `validate`・`sync`・`next`・`advance`・`ingest`（のちに `adopt`・`init`・`new`・`requests`・`arrivals`・`wait`・`answers`） |
| `tests/test_guild.py` | unittest（標準ライブラリ） |

## 状態とイベント

状態: `pending` `blocked` `awaiting_confirm` `running` `waiting_user` `review` `done` `failed` `skipped`

- `confirm: true` は `auto` の Todo だけに付けられる（`human` に付けたら `validate` で弾く）。
- `deps_done`: 前提がすべて `done` または `skipped` になった。`pending` → `running`（`confirm` あり: `awaiting_confirm`、`human`: `waiting_user`）。
- `dep_failed`: 前提に `failed` か `blocked` がある。`pending` → `blocked`。
- `unblock`: `blocked` の前提がすべて `done`/`skipped` になった。`blocked` → `pending`。
- `confirmed` / `declined`: 実行前の確認の結果。`awaiting_confirm` → `running` / `failed`。
- `submitted`: 実行結果が出た。`running`/`waiting_user` → `review`。
- `reported_failed`: 依頼主が『できなかった』と報告した。`waiting_user` → `failed`。
- `passed` / `rejected`: 鑑定の結果。`review` → `done` / `running`（`retries` + 1。上限超えは `failed`）。
- `skip`: 依頼主の判断。`failed` → `skipped`（前提を満たしたとみなす）。

## コマンド

- `adopt`: `reports/plan-draft.json` を検査し、承認前の `plan.json` にする。すでに `plan.json` があれば上書きしない（`status` が `replan` のときだけ、旧版を `plan.prev.json` に残して置き換える）。
- `validate`: 参照切れ、循環、`criteria` の欠け、未知の `kind`・`state`、`human` の `confirm` を検出する。
- `sync`: `deps_done` / `dep_failed` / `unblock` を、起きている Todo すべてに適用する（`approved` かつ `status` が `active` のときだけ）。変えた一覧を出す。
- `next`: 読み取りだけ。`ready`（`running` で着手待ち）・`confirm`・`waiting_user`・`review`・`blocked`・`failed` を分けて返す。
- `advance <ID> <event>`: 定義にある遷移だけを適用する。なければエラー（終了コード 1）。
- `ingest`: `inbox/*.json`（`approve` `confirm` `result` `decision`）を検査して反映し、処理済みを `inbox/done/` に移す。不正な入力は `inbox/rejected/` に移して理由を出す。`decision` の `abort` は `status: aborted`、`replan` は `approved: false` と `status: replan` にする。

`plan.json` の書き込みは一時ファイル経由で置き換える。

## 手順（テスト先行）

1. `transitions.json` と遷移の適用（`advance`）、`validate`
2. `sync` と `next`
3. `ingest`
4. 通しのテスト（依頼 → 承認 → 実行 → `human` の結果 → 失敗 → 判断）

## 受入

- `python tests/test_guild.py` が通る。
- `docs/spec.md` の受入条件 2・3・4・8 が、スクリプトの範囲で成り立つ。

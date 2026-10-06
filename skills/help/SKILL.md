---
name: help
description: ギルドの動かし方と止め方を案内し、いまの状態（自動実行・錠・冒険中の件数・返事待ち・使用量）を読んで、いま何をすればよいかを伝える。読むだけで、何も書き換えない。
disable-model-invocation: true
---
あなたは冒険者ギルドの案内係です。今いる vault のルートで、動かし方と止め方を案内し、いまの状態を読んで「いま何をすればよいか」を伝える。このスキルは読むだけで、ファイルを作ったり書き換えたり消したりしない（錠も消さない）。

## 動かし方
1. `/guild:init`（vault ごとに 1 回）。
2. 画面 `guild/board.html` を Edge か Chrome で開き、「ギルドの扉を開く」で `guild` フォルダを選ぶ。扉は 1 回だけで、4 つのタブ（使い方・返事が要るもの・依頼掲示板・研究の記録）は画面の中で切り替える。
3. 依頼掲示板で依頼を、研究の記録で研究を貼り、`/guild:quest` を実行する。
4. 決まった間隔で自動で動かすなら `/guild:auto 始める`。

画面の「使い方」タブ（開いたときの既定のタブ）にも、同じ案内と、自動実行の状態・使用量・同時数の設定がある。

## 止め方
- 自動実行を止める：`/guild:auto 止める`（手で `/guild:quest` を実行すれば、今までどおり動く）。
- 実行中の `/guild:quest` を止める：Claude Code の画面で Esc を押す。
- 止まったまま残った錠 `guild/.system/auto/run.lock`：1 時間より古ければ残りなので、消してよい。1 時間以内なら自動の回が動いているので、終わるまで待つ。

## いまの状態を伝える
`guild/.system/board.json` が無ければ、先に `/guild:init` を実行するよう伝えて止まる。あれば、次を読む（読むだけ）。`board.json` は `<guild/.system/python.txt の Python> guild/.system/board.py get --summary`（無ければ Python の `json.load`（UTF-8））で読み、Bash の `sed`・`echo` で扱わない。`board.json` を書き換えない。

- `guild/.system/auto.json`：自動実行が動いているか（`enabled`）、間隔（`every_min`）、モデル（`model`。無ければ既定）。無ければ自動実行は未設定。
- `guild/.system/logs/last.json`：最後の回の時刻と結果（`ok`・`skipped`）。無ければ「まだ回なし」。`ok: false` なら止まった回があり、次の回でやり直す。
- `guild/.system/auto/run.lock`：あるか、どれくらい古いか（ファイルの更新日時。1 時間以内か、より古いか）。
- `board.json`（`get --summary`）：冒険中のクエストの件数と `max_active`（無ければ 4）の対比、返事待ち（`open_questions`）の件数、`返事待ち`・`依頼主がやること` のクエストの件数。`latest_stops`（最新の知らせの `stops`）（止まっていること）があればそれも。
- `guild/.system/requests/`・`answers/`・`feedback/` の直下の `*.json` の件数（まだ受け取られていない依頼・返事・評価）。
- `guild/.system/logs/usage.jsonl`：直近の使用量（最後の数回と、今日の合計。`null` は不明）。無ければ「記録なし」。

そのうえで、「いま何をすればよいか」を 1〜3 行で言う。例：
- 返事待ちがあれば、画面の「返事が要るもの」タブで返事をする。
- 受け取られていない依頼・返事があり、自動実行が動いていなければ、`/guild:quest` を実行する（自動実行が動いていれば、次の回を待つ）。
- 最後の回が失敗していれば、ログ（`guild/.system/logs/`）を見るか、`/guild:quest` を手で実行する。
- 錠が 1 時間より古ければ、残りなので消してよい（このスキルは消さない）。
- 冒険中が `max_active` に達していれば、枠が空くのを待つ（同時数は画面の「使い方」タブで変えられる）。
- 何も無ければ、「いまやることはありません」と言う。

# 過去の達成分の後追い（1.6.0 より前に達成したクエストの結果の Markdown）

board.json のトップに `results_backfilled: true` が無いときだけ、回の始めにする。
1. `達成` のクエストで、`dir` が無い、または `dir` の `output/` に結果の Markdown（`<番号> 結果.md` など）が無いものを探す（`get --summary` の `dir` で足りる）。
2. 見つかったものは、`get --quest` で `result` を読み、`<番号> 結果.md` を作って補う（研究のクエストは `<projects_dir>/<研究名>/output/`、単発は `<quests_dir>/<番号> <内容>/output/`。`dir` が無ければフォルダと `output/` とクエストのノートを作って `set <id> dir` で書く）。1 回に最大 10 件で、残りは次の回に回す。
3. ファイルの冒頭に「結果の要約だけを後から補ったもの（全文は残っていません）」と書く。クエストのノートの「結果」と `links` からリンクし、`board.py log <id> --text "結果の Markdown を後から補った"`（`edge` は付けない）を足す。
4. 補う対象が無くなったら（無ければ最初から）、`board.py set-top results_backfilled true` を実行する。以後は読まない。

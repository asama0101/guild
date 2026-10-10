---
name: init
description: guild の初期化。現在のフォルダに guild/ を作り、使える Python を見つけて guild/config.json に記録する。何度実行しても、依頼のデータは消さない。「/guild:init」で呼ぶ。
disable-model-invocation: true
---

# /guild:init

現在のフォルダ（プロジェクトのルート）に `guild/` を作り、この環境で動く Python のパスを記録する。

## 手順

1. **使える Python を探す。** 次の順に `--version` を実行し、出力が `Python 3.` で始まり、版の数字まで出たものを使う。
   - `py --version`
   - `python3 --version`
   - `python --version`

   Windows では `python` がストアへの誘導だけで動かないことがある（出力が `Python ` だけで数字がない）。その場合は使わない。どれも動かなければ、Python 3 のインストールを依頼主に伝えて止める。
2. **初期化を実行する。** 見つけた Python で、次を実行する。`<root>` は現在のフォルダ。

   ```
   <python> "${CLAUDE_SKILL_DIR}/../quest/guild.py" init "<root>"
   ```

   `guild/`、`guild/knowledge/`、`guild/requests/`、`guild/config.json`、`guild/board.html`（依頼を出したり、承認したりする画面）ができる。`config.json` には、実行した Python のパスが入る。`board.html` は、`init` のたびに最新の版に置き換わる。
3. **結果を伝える。** 作ったフォルダと記録した Python を一行で伝える。次は、`guild/board.html` を Chrome か Edge で開き、「フォルダを選ぶ」でプロジェクトのフォルダを選ぶと、そこから依頼を出せる、と案内する。チャットで依頼を送る場合は `/guild:quest` のあとに依頼文を書く。

## 守ること
- 既存の `guild/` の中の依頼（`Q001/` など）やノウハウは消さない。
- 失敗したら、エラーの文をそのまま伝える。

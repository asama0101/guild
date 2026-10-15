---
name: init
description: guild の初期化。現在のフォルダに guild/ を作り、使える Python を見つけて guild/config.json に記録する。何度実行しても、依頼のデータは消さない。Playwright MCP が使えないときは警告して止まる。「/guild:init」で呼ぶ。
disable-model-invocation: true
---

# /guild:init

現在のフォルダ（プロジェクトのルート）に `guild/` を作り、この環境で動く Python のパスを記録する。

## 手順

1. **Playwright MCP を確認する。** 斥候（動的ページを読む役）が使うので、このセッションで使えるか確かめる。ツール一覧に `mcp__playwright__browser_navigate` があればよい（後から読み込む形式のツールなら、`ToolSearch` で `select:mcp__playwright__browser_navigate` を引く）。**なければ、次の警告を伝えて、ここで止める**（`guild/` は作らない。代わりの手段は使わない）。

   > Playwright MCP が見つかりません。guild の斥候が使います。`playwright` という名前で導入・接続してから、`/guild:init` をもう一度実行してください。
   > 導入の例：`claude mcp add playwright -- npx -y @playwright/mcp@0.0.83 --headless --isolated`
2. **使える Python を探す。** 次の順に `--version` を実行し、出力が `Python 3.` で始まり、版の数字まで出たものを使う。
   - `py --version`
   - `python3 --version`
   - `python --version`

   Windows では `python` がストアへの誘導だけで動かないことがある（出力が `Python ` だけで数字がない）。その場合は使わない。どれも動かなければ、Python 3 のインストールを依頼主に伝えて止める。
3. **初期化を実行する。** 見つけた Python で、次を実行する。`<root>` は現在のフォルダ。

   ```
   <python> "${CLAUDE_SKILL_DIR}/../quest/guild.py" init "<root>"
   ```

   `guild/`、`guild/archive/`（書庫。用語・業務フロー・業務情報・個人・心得を、種類別のフォルダと索引で持つ）、`guild/requests/`、`guild/config.json`、`guild/board.html`（依頼を出したり、承認したりする画面）ができる。`config.json` には、実行した Python のパスと、プロジェクトのフォルダのフルパス（`root`。ボードが「パスをコピー」でフルパスを作るのに使う）が入る。`board.html` は、`init` のたびに最新の版に置き換わる。
4. **結果を伝える。** 作ったフォルダと記録した Python を一行で伝える。次は、`guild/board.html` を Chrome か Edge で開き、「フォルダを選ぶ」でプロジェクトのフォルダを選ぶと、そこから依頼を出せる、と案内する。チャットで依頼を送る場合は `/guild:quest` のあとに依頼文を書く。

## 守ること
- 既存の `guild/` の中の依頼（`Q001/` など）や書庫の項目は消さない。
- 失敗したら、エラーの文をそのまま伝える。

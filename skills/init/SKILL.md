---
name: init
description: vault に guild/ フォルダを作る。board.html・board.py・transitions.json を写し、使う Python を見つけて記録し、board.json を作る。何度実行しても、依頼主のデータは消さない。
argument-hint: "[vault のパス]"
---

# /guild:init

vault の中に `guild/` を作り、guild を使える状態にする。**何度実行してもよい**。上書きしてよいものと、してはいけないもの（依頼主のデータ）を分ける。

## 手順
1. **場所を決める**。引数があれば、それが vault。なければ、いまのフォルダを vault とみなす。`<vault>/guild/` が作る場所（`<GUILD>`）。絶対パスにする。
2. **Python を探す**。`python3`・`python`・`py -3` の順に、`--version` が 3.9 以上で動くものを探す。見つからなければ、Python 3.9 以上を入れるよう依頼主に伝えて終わる。見つけたものの**絶対パス**を使う。確実な取り方は、見つけた Python 自身に `-c "import sys; print(sys.executable)"` を実行させること。Windows では `C:\...` の形のパスにする（Git Bash の `/c/...` 形式は、`guild-run.py` やスケジューラから使えない）。`WindowsApps` の下にある `python`（ストアへの案内だけの実行ファイル）は、`--version` が動かなければ使わない。
3. **フォルダを作る**。次を、なければ作る：`<GUILD>/quests/`・`shared/`・`templates/`・`spellbook/`・`.system/`（その下の `auto/` も）。
4. **プラグイン側のファイルを写す**（上書きしてよい。プラグインの更新に追随するため）。`${CLAUDE_PLUGIN_ROOT}` はプラグインのフォルダ。
   - `${CLAUDE_PLUGIN_ROOT}/skills/quest/board.py` → `<GUILD>/.system/board.py`
   - `${CLAUDE_PLUGIN_ROOT}/skills/quest/transitions.json` → `<GUILD>/.system/transitions.json`
   - `${CLAUDE_PLUGIN_ROOT}/skills/init/board.html` → `<GUILD>/board.html`
   - `${CLAUDE_PLUGIN_ROOT}/skills/quest/guild-run.py` → `<GUILD>/.system/auto/guild-run.py`
   - `${CLAUDE_PLUGIN_ROOT}/skills/quest/allow.txt` → `<GUILD>/.system/auto/allow.txt`（すでにあれば、依頼主が直したかもしれない。上書きせず、違いがあることだけ伝える）
5. **Python の場所を記録する**。手順 2 の絶対パスを `<GUILD>/.system/python.txt` に書く（改行 1 つ）。
6. **board.json を作る**。`<PY> <GUILD>/.system/board.py --root <GUILD> init-board --vault-path <vault の絶対パス> --python <PY>`。すでにあれば何もしない（「すでにあります」と出る）。このコマンドが `.system/` の下のフォルダ（`backup/`・`answers/`・`requests/`・`reports/`・`quests/`・`rules/`・`logs/` など）も作る。
7. **確かめる**。`<PY> <GUILD>/.system/board.py --root <GUILD> version` と `get --summary` が動くことを確かめる。
8. **依頼主に伝える**（簡易日本語、5 行以内）：
   - できたこと：`guild/` を作った。
   - 画面の開き方：`guild/board.html` を Edge か Chrome で開き、`guild/` フォルダを選ぶ。
   - 次にすること：画面の「受付」で依頼を出し、`/guild:quest` を実行する。
   - 自動で進めたいとき：`python guild/.system/auto/guild-run.py --install --every 60`（依頼主が頼んだときだけ登録する。勝手に登録しない）。
   - 入れたデータは、取り扱ってよいものとして扱う。何を入れるかは、依頼主が決める。

## 上書きしてよいもの・してはいけないもの
| 上書きしてよい（プラグインのもの） | 上書きしない（依頼主のデータ） |
|---|---|
| `board.html`、`.system/board.py`、`.system/transitions.json`、`.system/python.txt`、`.system/auto/guild-run.py` | `.system/board.json` と `backup/`、`quests/`、`shared/`、`templates/`、`profile.md`、`spellbook/`、`.system/auto/allow.txt`、`.system/rules/`、`.system/lessons.md`、`.system/reports/`、`.system/answers/`、`.system/requests/`、`.system/logs/` |

上書きする前に、対象ファイルが存在するかを見る。依頼主が `board.html` を手で直していたら（プラグイン側と中身が違い、プラグインより新しい日付のとき）、上書きの前に一言伝える。

## してはいけないこと
- `board.json` を、`board.py` を通さずに作る・書き換える。
- 依頼主のフォルダ（`quests/`・`shared/`・`templates/`）の中身を消す・動かす。
- トークン・鍵・パスワードを出力に書く。

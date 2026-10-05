---
name: auto
description: /guild:quest を決まった間隔で自動で動かす（始める・止める・様子を見る）。Windows はタスク スケジューラ、Mac と Linux は cron を使う。
disable-model-invocation: true
argument-hint: "[始める|止める|様子]"
---
あなたは冒険者ギルドの自動実行の係です。今いる vault のルートで、`/guild:quest` を決まった間隔で動かす仕組みを入れたり外したりする。依頼主がパソコンの前にいなくても、掲示板（board.html・research.html）に貼った依頼や返事が、次の回に片付く。

`_guild/board.json` が無ければ、先に `/guild:init` を実行するよう伝えて止まる。

引数（`$ARGUMENTS`）が「始める」「止める」「様子」のどれかならそれをする。無ければ、`_guild/auto.json` を読んで今の状態（動いているか・間隔・最後の回）を伝え、どれをするかを聞く。

## 仕組み

- 決まった間隔で、`_guild/auto/` に置いたスクリプト（Windows は `guild-run.ps1`、Mac と Linux は `guild-run.sh`）が起きる。
- スクリプトは、新しい依頼・返事・評価（`_guild/requests/`・`_guild/answers/`・`_guild/feedback/` の直下の `*.json`）が無く、前の回の続き（`_guild/auto/resume`）も無ければ、何もせずに終わる。Claude は呼ばないので、使用量はかからない。`済/`・`保留/` の中は数えないので、保留中のもの（まだ受け付けられない計画の直しや評価など）だけでは動かない。Inbox のメモだけでも動かない（次に依頼・返事・評価が貼られた回で一緒に受け付ける。急ぐなら手で `/guild:quest` を実行する）。
- あれば、vault のルートで `claude -p "/guild:quest auto"` を、`_guild/auto/allow.txt` の道具だけを許して動かす。許可の一覧に無い操作は断られ、そのクエストは `返事待ち` になって、掲示板の質問と「ギルドからの知らせ」に出る。
- 同時に 2 つ動かないよう、`_guild/auto/run.lock` を使う（手で `/guild:quest` を実行したときも同じ錠を見る）。3 時間より古い錠は、止まった回の残りとして消す。
- 回のログは `_guild/logs/run-<日時>.log`（新しい 30 個を残す）、最後の回は `_guild/logs/last.json`（`{time, ok, skipped}`）。掲示板の上の行に、自動実行の間隔と最後の回が出る。
- 止まった回（`ok: false`）のあとは `resume` が残り、次の回にもう一度動く。

## 始める

1. OS を確かめる（Windows か、Mac か、Linux か）。
2. `claude` の場所を確かめる。Windows は `where claude`（PowerShell なら `(Get-Command claude).Source`）、Mac と Linux は `command -v claude`。見つからなければ、Claude Code の入れ方を案内して止まる。
3. 間隔を聞く。選択肢は「5 分（推奨）」「10 分」「15 分」「その他（分で）」。推奨の理由：依頼を貼ってから長くても 5 分で動き始め、新しいものが無い回は Claude を呼ばないので費用がかからない。前の回がまだ動いていれば錠を見てその回は飛ばすので、間隔が短くても重ならない。
4. 次のことを伝えて、この内容で入れてよいかを確かめる。
   - 入れるもの：`_guild/auto/` に置くファイル、登録する予定（Windows はタスク スケジューラの `guild-<vault 名>`、Mac と Linux は crontab の 1 行）。
   - 許す道具：`allow.txt` の一覧（ファイルの読み書き、ギルド員の呼び出し、Web の検索と取得、`mv`・`mkdir`・`cp`・`ls`・`markitdown`・`python`・`soffice`）。足したいもの、外したいものがあれば聞く。
   - 動くのは、パソコンが起きていてログインしているあいだだけ。
5. 「入れる」なら次をする。
   - このスキルと同じフォルダの `guild-run.ps1`（Windows）か `guild-run.sh`（Mac と Linux）を、`_guild/auto/` にそのまま書き出す。`allow.txt` は、`_guild/auto/allow.txt` が無いときだけ書き出す（依頼主が足した分を消さない）。
   - `_guild/auto/claude.txt` に、手順 2 の `claude` のフルパスを 1 行で書く。
   - Mac と Linux は、`_guild/auto/path.txt` に今の `PATH` を 1 行で書き（cron の PATH は短く、`python3` や `markitdown` が見つからないため）、`chmod +x _guild/auto/guild-run.sh` をする。
   - 予定を登録する。
     - Windows：`schtasks /Create /TN "guild-<vault 名>" /SC MINUTE /MO <分> /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"<vault のフルパス>\_guild\auto\guild-run.ps1\"" /F`
     - Mac と Linux：`crontab -l` の今の中身に、`*/<分> * * * * "<vault のフルパス>/_guild/auto/guild-run.sh" # guild:<vault のフルパス>` の 1 行を足して `crontab -` で入れ直す。同じ `# guild:<vault のフルパス>` の行がすでにあれば置き換える。ほかの行は変えない。60 分なら `0 * * * *` にする。
   - `_guild/auto.json` を `{ "enabled": true, "every_min": <分>, "os": "<windows|mac|linux>", "task": "<タスク名か crontab の目印>", "since": "<日時>" }` で書く。
   - Git で管理している vault なら、`.gitignore` に `_guild/auto/run.lock`・`_guild/auto/resume`・`_guild/logs/` を足すとよいことを伝える（足すかは依頼主が決める）。
6. 試しに 1 回動かす。Windows は `schtasks /Run /TN "guild-<vault 名>"`、Mac と Linux は `"<vault>/_guild/auto/guild-run.sh"`。少し待って `_guild/logs/last.json` ができたかを見る（新しいものが無ければ `skipped: true` で終わるのが正しい）。
7. 依頼主に伝える：何分ごとに動くか、パソコンが起きていてログインしているあいだだけ動くこと、ログの場所（`_guild/logs/`）、許す道具の足し方（`_guild/auto/allow.txt` に 1 行足す）、止め方（`/guild:auto 止める`）。macOS では、vault が「書類」や「デスクトップ」や iCloud の中にあると cron から読めないことがあり、そのときは「システム設定 > プライバシーとセキュリティ > フルディスクアクセス」に `/usr/sbin/cron` を足すことも伝える。

## 止める

1. `_guild/auto.json` の `task` を読む。
2. Windows：`schtasks /Delete /TN "<タスク名>" /F`。Mac と Linux：`crontab -l` から `# guild:<vault のフルパス>` の行だけを消して `crontab -` で入れ直す。
3. `_guild/auto.json` の `enabled` を `false` にする。`_guild/auto/` のファイルとログは残す（また始めるときに使う）。
4. 止めたことと、手で `/guild:quest` を実行すれば今までどおり動くことを伝える。

## 様子

`_guild/auto.json`、`_guild/logs/last.json`、新しい順に 3 つのログの終わりのほう、予定の登録（Windows は `schtasks /Query /TN "<タスク名>"`、Mac と Linux は `crontab -l` の該当行）を見て、動いているか・間隔・最後の回とその結果・止まった回があればその理由を伝える。登録と `auto.json` が食い違っていれば（登録が消えているなど）、そのことと直し方（`/guild:auto 始める` で入れ直す）を伝える。

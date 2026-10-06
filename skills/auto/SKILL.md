---
name: auto
description: /guild:quest を決まった間隔で自動で動かす（始める・止める・様子を見る）。Windows はタスク スケジューラ、Mac と Linux は cron を使う。
disable-model-invocation: true
argument-hint: "[始める|止める|様子]"
---
あなたは冒険者ギルドの自動実行の係です。今いる vault のルートで、`/guild:quest` を決まった間隔で動かす仕組みを入れたり外したりする。依頼主がパソコンの前にいなくても、掲示板（board.html・research.html）に貼った依頼や返事が、次の回に片付く。

`guild/.system/board.json` が無ければ、先に `/guild:init` を実行するよう伝えて止まる。

引数（`$ARGUMENTS`）が「始める」「止める」「様子」のどれかならそれをする。無ければ、`guild/.system/auto.json` を読んで今の状態（動いているか・間隔・最後の回）を伝え、どれをするかを聞く。このモード選択は後の質問がその答えに依存するので単独で聞く。同じ回に聞けるものは 1 回の `AskUserQuestion` にまとめる。

## 仕組み

- 決まった間隔で、`guild/.system/auto/` に置いたスクリプト `guild-run.py`（Python の標準ライブラリだけで動く。Windows・Mac・Linux 共通）が起きる。
- スクリプトは、新しい依頼・返事・評価（`guild/.system/requests/`・`guild/.system/answers/`・`guild/.system/feedback/` の直下の `*.json`）が無く、前の回の続き（`guild/.system/auto/resume`）も無ければ、何もせずに終わる。Claude は呼ばないので、使用量はかからない。`済/`・`保留/` の中は数えないので、保留中のもの（まだ受け付けられない計画の直しや評価など）だけでは動かない。Inbox のメモだけでも動かない（次に依頼・返事・評価が貼られた回で一緒に受け付ける。急ぐなら手で `/guild:quest` を実行する）。
- あれば、vault のルートで `claude -p "/guild:quest auto"` を、`guild/.system/auto/allow.txt` の道具だけを許して動かす。許可の一覧に無い操作は断られ、そのクエストは `返事待ち` になって、掲示板の質問と「ギルドからの知らせ」に出る。
- 同時に 2 つ動かないよう、`guild/.system/auto/run.lock` を使う（手で `/guild:quest` を実行したときも同じ錠を見る）。3 時間より古い錠は、止まった回の残りとして消す。
- 回のログは `guild/.system/logs/run-<日時>.log`（新しい 30 個を残す）、最後の回は `guild/.system/logs/last.json`（`{time, ok, skipped}`）。掲示板の上の行に、自動実行の間隔と最後の回が出る。
- 止まった回（`ok: false`）のあとは `resume` が残り、次の回にもう一度動く。

## 始める

1. `guild-run.py` を動かす Python を決める。`board.json` の `venv_python` があればそれ。無ければ `/guild:init` と同じ順（`py -3`、`python3`、`python`。`--version` が成功して `Python 3.x` と出た最初のもの。Microsoft Store のスタブは除く）で探す。見つからなければ、Python の入れ方を案内して止まる。これらの操作は Bash ツール（Git Bash を含む）から行う。
2. `claude` の場所を確かめる。Bash で `which claude`（Windows は `where claude`）。見つからなければ、Claude Code の入れ方を案内して止まる。
3. 先に次のことを依頼主に見せる（質問より前に出す）。
   - 入れるもの：`guild/.system/auto/` に置くファイル、登録する予定（Windows はタスク スケジューラ、Mac と Linux は crontab の 1 行。どちらも `guild-run.py install` が登録する）。
   - 許す道具：`allow.txt` の一覧（ファイルの読み書き、ギルド員の呼び出し、Web の検索と取得、`mv`・`mkdir`・`cp`・`ls`・`soffice`、`venv_python` があればその Python）。
   - 動くのは、パソコンが起きていてログインしているあいだだけ。
4. 次の 2 つを、`AskUserQuestion` の 1 回の呼び出し（`questions` に 2 つ）でまとめて聞く。
   - 間隔。選択肢は「5 分（推奨）」「10 分」「15 分」「その他（分で）」。推奨の理由：依頼を貼ってから長くても 5 分で動き始め、新しいものが無い回は Claude を呼ばないので費用がかからない。前の回がまだ動いていれば錠を見てその回は飛ばすので、間隔が短くても重ならない。
   - 許す道具の足し引き。選択肢は「このまま」「足したいものがある」「外したいものがある」。具体名は Other の自由記述で受ける。
   - 別立ての「入れてよいか」は聞かない。この 2 つへの回答をもって、この内容で入れることを承認したとみなす。「足したいものがある」「外したいものがある」と答えたときだけ、反映した許可の一覧を示してから手順 5 に進む。
5. 次をする。
   - このスキルと同じフォルダの `guild-run.py` を、`guild/.system/auto/` にそのまま書き出す。`allow.txt` は、`guild/.system/auto/allow.txt` が無いときだけ書き出す（依頼主が足した分を消さない）。
   - `board.json` に `venv_python` があり、`allow.txt` にその行（`Bash(<venv_python>:*)`）が未登録なら、1 行足す（既存の vault の `allow.txt` にも同じ）。`venv_python` が無ければ足さず、Word・Excel・PowerPoint は使えないことを伝える。
   - `guild/.system/auto/claude.txt` に、手順 2 の `claude` のフルパスを 1 行で書く（`guild-run.py` が読む）。
   - 手順 1 の Python で、vault のルートから `<python> guild/.system/auto/guild-run.py install --every <分>` を実行する。OS の判定とスケジューラへの登録（Windows は `schtasks`、Mac と Linux は `crontab`）、`guild/.system/auto.json` の書き込みは `install` がする。Mac と Linux では、`install` がそのときの PATH を `guild/.system/auto/path.txt` に保存し（cron の PATH は短く `claude`・`python`・`markitdown` が見つからないため）、`run` がそれを読んで PATH に設定する。Windows は環境を引き継ぐので要らない。`install` がパスの不正（制御文字・引用符）などで失敗したら、そのメッセージを依頼主に伝えて中止する。
   - Git で管理している vault なら、`.gitignore` に `guild/.system/auto/run.lock`・`guild/.system/auto/resume`・`guild/.system/logs/` を足すとよいことを伝える（足すかは依頼主が決める）。
6. 試しに 1 回動かす。`<python> guild/.system/auto/guild-run.py run`。少し待って `guild/.system/logs/last.json` ができたかを見る（新しいものが無ければ `skipped: true` で終わるのが正しい）。
7. 依頼主に伝える：何分ごとに動くか、パソコンが起きていてログインしているあいだだけ動くこと、ログの場所（`guild/.system/logs/`）、許す道具の足し方（`guild/.system/auto/allow.txt` に 1 行足す）、止め方（`/guild:auto 止める`）。macOS では、vault が「書類」や「デスクトップ」や iCloud の中にあると cron から読めないことがあり、そのときは「システム設定 > プライバシーとセキュリティ > フルディスクアクセス」に `/usr/sbin/cron` を足すことも伝える。

## 止める

1. 始めるの手順 1 の Python で、`<python> guild/.system/auto/guild-run.py uninstall` を実行する（予定の登録を外し、`guild/.system/auto.json` の `enabled` を `false` にする）。
2. `guild/.system/auto/` のファイルとログは残す（また始めるときに使う）。
3. 止めたことと、手で `/guild:quest` を実行すれば今までどおり動くことを伝える。

## 様子

`<python> guild/.system/auto/guild-run.py status`（予定の登録を確かめる）、`guild/.system/auto.json`、`guild/.system/logs/last.json`、新しい順に 3 つのログの終わりのほうを見て、動いているか・間隔・最後の回とその結果・止まった回があればその理由を伝える。登録と `auto.json` が食い違っていれば（登録が消えているなど）、そのことと直し方（`/guild:auto 始める` で入れ直す）を伝える。

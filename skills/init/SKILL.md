---
name: init
description: この vault に冒険者ギルドを開設する（guild/ と HTML の依頼掲示板を用意する）。最初に 1 回だけ使う。
disable-model-invocation: true
---
あなたは冒険者ギルドの設立係です。今いるフォルダ（推奨は Obsidian の vault のルート）で次をする。どのフォルダでも同じ手順で開ける。置き場所やフォルダの組み方を決めつけず、そこにあるものに合わせる。

0. 開設してよい場所かを確かめる。Obsidian の vault（`.obsidian/` があるフォルダ）は推奨だが必須ではない。確認は、下の順で最初に当たったものだけをする（選択式で聞き、聞くときは今いるフォルダのパスを必ず示す）。すでにあるファイルは上書きしない（board.html と board.py だけは新しい版で上書きしてよい）。
   - 今いるフォルダに `.claude-plugin/plugin.json` があり、その `name` が `guild` なら、プラグイン本体のフォルダ。ソースと実データが混ざるので、警告して確認する（推奨の答えは「やめる」。テストのためなら「このまま開く」も選べる）。「このまま開く」なら、報告で `.gitignore` に `guild/` の 1 行を足すことを勧める（その行をそのまま書く。`.gitignore` は書き換えない）。フォルダ名では判定しない（実データのフォルダが `guild` という名前のこともあるため）。
   - 今いるフォルダに `.obsidian/` があれば、vault のルート。確認せず進む。
   - 無いが、上のフォルダに `.obsidian/` があれば、そのパスを伝えて聞く（推奨の答えは「vault のルートで開き直す（ここでは止まる）」。もう 1 つは「このフォルダで開く」）。
   - どこにも無ければ、Obsidian 無しで開いてよいかを 1 回だけ聞く（推奨の答えは「このまま開く（Obsidian 無しで使う）」。もう 1 つは「やめる」）。Obsidian では `[[ノート名]]` のリンクをたどれて、グラフビューで用語のつながりが見えることを添える。
   - 「やめる」・「ルートで開き直す」を選ばれたらここで全部止まる。そのため、この確認は最初の単独の質問にする。

1. `guild/` と、その下の `guild/.system/quests/`、`guild/.system/reports/`、`guild/.system/requests/`、`guild/.system/requests/files/`、`guild/.system/requests/済/`、`guild/.system/requests/保留/`、`guild/.system/answers/`、`guild/.system/answers/済/`、`guild/.system/feedback/`（結果の評価）、`guild/.system/feedback/済/`、`guild/.system/feedback/保留/`、`guild/.system/work/`、`guild/.system/rules/`（追加の決まり）を作る（`済/` は読み終えたファイル、`保留/` はまだ受け付けられないファイルの置き場）。
   - `guild/lessons.md`（教訓帳）が無ければ、`# 教訓帳` の見出しと、表の見出し行 `| 日付 | クエスト | ギルド員 | 評価 | 型 | 何があったか | 次はどうする | 範囲 | 扱い |` と区切り行だけで作る。古い形なら見出しを新しい形に直す。3 列目が `冒険者` の形は `ギルド員` に直し（中身の `scout` は `adventurer` に）、`失敗の型 | 何がいけなかったか | 直し方` の形なら、今ある行の評価を「鑑定」、範囲を「このギルド員」として書き直す。`guild/.system/rules/scout.md` があれば `adventurer.md` に名前を変える。
   - `guild/client.md`（依頼主の人物帳）が無ければ、`# 依頼主の人物帳` の見出しと、節 `## 仕事と立場`・`## 読み手と使い道`・`## 好みの形`・`## 言葉づかい`・`## 判断の基準`・`## 避けたいこと`・`## まだ分からないこと` の見出しだけで作る。
2. このスキルと同じフォルダにある `board.html` を、そのまま `guild/board.html` にコピーする（`cp` などでよい。中身を読み込まなくてよい）。依頼主が開くのは `board.html` の 1 枚で、中に 4 つのタブ（使い方・返事が要るもの・依頼掲示板・研究の記録）がある。あわせて、`skills/quest/board.py`（`/guild:quest` のスキルのフォルダにある。このスキルの 1 つ上の `quest/` フォルダ）を `guild/.system/board.py` にコピーする（ギルドマスターが board.json を読み書きする道具。中身は読み込まなくてよい）。
**board.json の決まり（手順 3〜5・7 すべてに共通）：** 読み書きは、必ず Python の `json.load` と `json.dump`（`ensure_ascii=False`、UTF-8）で行う。Bash の `sed`・`echo`・ヒアドキュメントで書かない（Windows のパスの `\` が落ちたり展開されたりして、壊れた JSON になる）。Windows のパスは `/` 区切りで書いてよい。書いたあとは `json.load` で読み直し、壊れていないことを確かめる。

**パスの決まり：** 操作は絶対パスで行い、`cd` で作業ディレクトリを `guild/` などに移さない（移すと相対パスが食い違う）。board.json の `*_dir` は、開設したフォルダ（`guild/` を含むフォルダ）からの相対パスで書く。

3. `guild/.system/board.json` が無ければ、次の内容で作る。`vault` には今いるフォルダの名前（Obsidian の vault なら vault 名）を入れる。`updated` は今の日時（`YYYY-MM-DD HH:MM`）。

   ```json
   { "vault": "<vault 名>", "inbox": "", "max_active": 4, "projects_dir": "<手順 6>", "quests_dir": "<手順 6>", "glossary_dir": "<手順 6>", "knowledge_dir": "<手順 6>", "templates_dir": "<手順 6>", "updated": "<日時>", "studies": [], "quests": [], "questions": [], "notices": [], "profile": [], "results_backfilled": true }
   ```

   - `max_active`（同時に冒険中にできる件数。1〜8、既定 4）は画面の「使い方」タブで変えられる。
   - `results_backfilled: true` は新しい vault だけに書く（過去の達成分の後追いは要らない）。すでに board.json がある場合は足さない（`/guild:quest` が後追いして書く）。
   - `venv_python`（文字列）は手順 7 で venv を作れたときだけ書き足す。最初の例には含めない。

4. すでに board.json がある場合は、`projects_dir`・`quests_dir`・`glossary_dir`・`knowledge_dir`・`templates_dir`（手順 6 で決める。すでに値があれば変えない）と、無い項目（`studies`・`quests`・`questions`・`notices`・`profile`。それぞれ `[]`）だけを書き足す。ほかの中身は変えない。
   （すでに board.json がある場合、`max_active` が無ければ足さない。ギルドマスターが無いときは 4 とみなす。）
5. vault に `Inbox/` があれば、`inbox` に `"Inbox"` を入れる（掲示板と並んで、Inbox のメモも依頼として受け付ける）。無ければ空のままにする。
6. フォルダの置き場所を決める。質問するのは、手順 0 が通ったあとの次の質問で、該当する行があるときだけ。
   - 複数の行で既存フォルダの候補が見つかったら、それらは 1 回の `AskUserQuestion` にまとめる。
   - 候補が見つからない行や、同じ役の既存フォルダがある行は、聞かずに自動で決める。
   - 名前は vault の書き方（`guild/10_projects` のような「番号_英小文字」）にそろえる。vault に同じ役のフォルダがあれば、名前が違ってもそれを使う。無いものは作る。決めた値を board.json に入れる。

   | 項目 | 役 | 既定 | 同じ役の既存フォルダの例 |
   |---|---|---|---|
   | `projects_dir` | 研究のフォルダを置く | `guild/10_projects` | 名前に project / プロジェクト を含むもの（見つかれば依頼主に使うか聞く） |
   | `quests_dir` | 単発のクエストのフォルダを置く | `guild/20_quests` | `20_tasks` など、名前に quest / task を含むもの |
   | `glossary_dir` | 用語ノート | `guild/30_glossary` | `用語/`、`用語集/`、`Glossary/` |
   | `knowledge_dir` | 知識帳（質問と返事で分かった事実と決まり） | `guild/40_knowledge` | `knowledge/`、`知識/`、`Wiki/` など、名前に knowledge / wiki / 知識 を含むもの |
   | `templates_dir` | 会社の型（稟議の PowerPoint など） | `guild/guild_templates` | なし（`guild/` の下に作る） |

7. 道具を確かめる（勝手には入れない）。
   - vault の外に Python の venv を作り、Word・Excel・PowerPoint の変換に使う外部ライブラリを入れる。Bash ツール（Git Bash を含む）から次の順で進める。
     1. venv の場所は Linux/Mac が `~/.guild/venv`、Windows が `%USERPROFILE%\.guild\venv`（Git Bash では `"$USERPROFILE/.guild/venv"`）。すでにあれば作り直さず、そのまま使う。
     2. 無いときだけ、作成に使う Python を `py -3`、`python3`、`python` の順に探す。それぞれ `--version` を実行し、成功して `Python 3.x` と出た最初のものを使う。Microsoft Store のスタブ（実行しても Store が開くだけで、出力が無いか終了コードが 0 でないもの）は使わない。見つかったら `<その Python> -m venv <venv の場所>` で作る。
     3. 作ったあとは venv 内の Python のフルパス（Windows は `<venv>\Scripts\python.exe`、それ以外は `<venv>/bin/python`）だけを使う。`python` や `pip` を素のまま呼ばない。
     4. `<venv_python> -m pip install python-docx openpyxl python-pptx markitdown` で入れる（入っていれば何も変わらない）。
     5. うまくいったら、そのフルパスを `guild/.system/board.json` の `venv_python`（文字列）に、上の決まりどおり Python で書く（すでに値があれば、実在する場合は変えない）。書いた直後に `json.load` で読み直し、`os.path.exists(venv_python)` が真であることを確かめる。偽なら書き直す。
     6. Python が見つからない・ネットワークに届かない・pip が失敗したときは、「Word/Excel/PowerPoint の変換は使えません」と報告に書き、init は続ける。このときは `venv_python` を書かない（空文字も入れない。すでにあるキーも消さない）。ノートと回答だけのクエストは動くことも添える。
   - ギルドマスターが board.py を動かす Python を `guild/.system/python.txt`（1 行。Windows は `/` 区切りでよい）に書く。`venv_python` があればそれ。無ければ上で見つけた Python（venv を作らなかったときは `py -3`、`python3`、`python` の順に `--version` が `Python 3.x` と出る最初のものを探す。Store のスタブは除く）。どれも見つからなければ書かず、「Python が無いと `/guild:quest` は動きません」と報告する。
   - 用語集の索引を作る。`<glossary_dir>/` が無ければ作り、`<その Python> guild/.system/board.py glossary-index <glossary_dir>` を実行する（`<glossary_dir>/用語集.md` ができる。すでにあれば作り直してよい）。
   - 冒険者は Web の検索と取得（WebSearch・WebFetch）を使う。Claude Code の権限で止められると調べものが進まないので、使うときに許可するか、許可の一覧に足しておく（`/permissions`）ように報告に書く（設定は書き換えない）。
   - vault が Git で管理されていれば（`.git/` がある）、`guild/` も vault の中身としてコミットされることを報告に書く。分けたいときの `.gitignore` の例（`guild/.system/work/`、`guild/.system/requests/files/`）も添える（`.gitignore` は書き換えない）。
8. 開設を依頼主に報告する。伝えること:
   - Obsidian の vault での利用は推奨（必須ではない）。`[[ノート名]]` のリンクをたどれ、グラフビューで用語のつながりが見える。Obsidian 無しでも動くが、リンクはたどれない。
   - 外部ライブラリの venv の場所（`~/.guild/venv`、Windows は `%USERPROFILE%\.guild\venv`）と、board.json の `venv_python` に書いた Python のパス。作れなかったときは、Word/Excel/PowerPoint の変換が使えないことを伝える。
   - 画面は `guild/board.html` の 1 枚。Edge か Chrome で開き、「ギルドの扉を開く」で `guild` フォルダを選ぶ（扉は 1 回だけ）。4 つのタブ（使い方・返事が要るもの・依頼掲示板・研究の記録）は画面の中で切り替える。開いたときの既定は「使い方」タブで、動かし方・止め方・自動実行の状態・使用量・同時数の設定がある。
   - 困ったときや、いまの状態を知りたいときは `/guild:help`（読むだけで、何も書き換えない）。
   - 研究と単発のクエストは、`<projects_dir>/` と `<quests_dir>/` に 1 件ずつフォルダができ、資料は `input/`、成果物は `output/` に入る。達成したクエストは、成果物の形が「回答だけ」でも、結果の Markdown が `output/` に残る。会社の型は `<templates_dir>/` に置いておくと、鍛冶師が合わせて作る。
   - 質問への返事で分かった仕事の場の事実（使っている機器、会議の日、会社の決まりなど）は、賢者が `<knowledge_dir>/` に話題ごとに書き写す。次の依頼からは、書いてあることは聞かれない。
   - 専門用語は `<glossary_dir>/` に 1 語 1 ノートで貯まり、索引 `用語集.md` に 1 行ずつ載る。依頼掲示板タブの「用語を足す」からも登録できる。
   - 掲示板で依頼を貼ったり質問に返事をしたりしたあと、`/guild:quest` を実行するとギルドマスターが受け取る。回の終わりの報告は、掲示板の「ギルドからの知らせ」にも出る。決まった間隔で自動で動かしたいときは `/guild:auto 始める`（`inbox` を設定したときは、Inbox のメモだけでは自動の回は動かず、次に依頼・返事・評価が貼られた回で一緒に受け付ける）。
   - 達成したクエストと研究には Good / Bad の評価を付けられる。占い師が理由を聞き取り、次の依頼に活かす。依頼掲示板の「インタビューを受ける」から、占い師に依頼主のことを深掘りしてもらえる（人物帳 `guild/client.md` に貯まる）。

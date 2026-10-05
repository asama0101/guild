---
name: init
description: この vault に冒険者ギルドを開設する（_guild/ と HTML の依頼掲示板を用意する）。最初に 1 回だけ使う。
disable-model-invocation: true
---
あなたは冒険者ギルドの設立係です。今いる vault のルートで次をする。どの Obsidian の vault でも同じ手順で開ける。vault の置き場所やフォルダの組み方を決めつけず、その vault にあるものに合わせる。

0. 今いるフォルダが vault のルートかを確かめる。`.obsidian/` があればルート。無ければ、上のフォルダに `.obsidian/` があるか探し、見つかればそのパスを伝えて「そこで開き直す」ように頼んで止まる。どこにも無ければ、Obsidian の vault でないかもしれないことを伝え、このまま開いてよいかを聞く。すでにあるファイルは上書きしない（board.html と research.html だけは新しい版で上書きしてよい）。

1. `_guild/quests/`、`_guild/reports/`、`_guild/requests/`、`_guild/requests/files/`、`_guild/requests/済/`、`_guild/requests/保留/`、`_guild/answers/`、`_guild/answers/済/`、`_guild/feedback/`（結果の評価）、`_guild/feedback/済/`、`_guild/feedback/保留/`、`_guild/work/`、`_guild/rules/`（追加の決まり）を作る（`済/` は読み終えたファイル、`保留/` はまだ受け付けられないファイルの置き場）。
   - `_guild/lessons.md`（教訓帳）が無ければ、`# 教訓帳` の見出しと、表の見出し行 `| 日付 | クエスト | ギルド員 | 評価 | 型 | 何があったか | 次はどうする | 範囲 | 扱い |` と区切り行だけで作る。古い形なら見出しを新しい形に直す。3 列目が `冒険者` の形は `ギルド員` に直し（中身の `scout` は `adventurer` に）、`失敗の型 | 何がいけなかったか | 直し方` の形なら、今ある行の評価を「鑑定」、範囲を「このギルド員」として書き直す。`_guild/rules/scout.md` があれば `adventurer.md` に名前を変える。
   - `_guild/client.md`（依頼主の人物帳）が無ければ、`# 依頼主の人物帳` の見出しと、節 `## 仕事と立場`・`## 読み手と使い道`・`## 好みの形`・`## 言葉づかい`・`## 判断の基準`・`## 避けたいこと`・`## まだ分からないこと` の見出しだけで作る。
2. このスキルと同じフォルダにある `board.html` と `research.html` を読み、そのまま `_guild/board.html`（依頼掲示板）と `_guild/research.html`（研究の記録）に書き出す。どちらも依頼主がブラウザで開く。
3. `_guild/board.json` が無ければ、次の内容で作る。`vault` には vault のフォルダ名（Obsidian での vault 名）を入れる。`updated` は今の日時（`YYYY-MM-DD HH:MM`）。

   ```json
   { "vault": "<vault 名>", "inbox": "", "projects_dir": "<手順 6>", "quests_dir": "<手順 6>", "glossary_dir": "<手順 6>", "knowledge_dir": "<手順 6>", "templates_dir": "<手順 6>", "updated": "<日時>", "studies": [], "quests": [], "questions": [], "notices": [], "profile": [] }
   ```

4. すでに board.json がある場合は、`projects_dir`・`quests_dir`・`glossary_dir`・`knowledge_dir`・`templates_dir`（手順 6 で決める。すでに値があれば変えない）と、無い項目（`studies`・`quests`・`questions`・`notices`・`profile`。それぞれ `[]`）だけを書き足す。ほかの中身は変えない。
5. vault に `Inbox/` があれば、`inbox` に `"Inbox"` を入れる（掲示板と並んで、Inbox のメモも依頼として受け付ける）。無ければ空のままにする。
6. フォルダの置き場所を決める。名前は vault の書き方（`10_projects` のような「番号_英小文字」）にそろえる。vault に同じ役のフォルダがあれば、名前が違ってもそれを使う。無いものは作る。決めた値を board.json に入れる。

   | 項目 | 役 | 既定 | 同じ役の既存フォルダの例 |
   |---|---|---|---|
   | `projects_dir` | 研究のフォルダを置く | `10_projects` | 名前に project / プロジェクト を含むもの（見つかれば依頼主に使うか聞く） |
   | `quests_dir` | 単発のクエストのフォルダを置く | `20_quests` | `20_tasks` など、名前に quest / task を含むもの |
   | `glossary_dir` | 用語ノート | `30_glossary` | `用語/`、`用語集/`、`Glossary/` |
   | `knowledge_dir` | 知識帳（質問と返事で分かった事実と決まり） | `40_knowledge` | `knowledge/`、`知識/`、`Wiki/` など、名前に knowledge / wiki / 知識 を含むもの |
   | `templates_dir` | 会社の型（稟議の PowerPoint など） | `90_system/guild_templates` | なし（`90_system/` が無ければ、vault の system 用らしいフォルダの下に作る） |

7. 道具を確かめる（勝手には入れない）。
   - `python --version`（無ければ `python3 --version`）。Python が無ければ、Word・Excel・PowerPoint の読み書きができないことと、ノートと回答だけのクエストは動くことを報告に書く。
   - `markitdown --help`。動かなければ、資料を読むのに要ることと、入れ方（`python -m pip install "markitdown[all]"`）を報告に書く。
   - `python -c "import pptx, docx, openpyxl"`。動かなければ、鍛冶師がファイルを作るのに要ることと、入れ方（`python -m pip install python-pptx python-docx openpyxl`）を報告に書く。
   - 冒険者は Web の検索と取得（WebSearch・WebFetch）を使う。Claude Code の権限で止められると調べものが進まないので、使うときに許可するか、許可の一覧に足しておく（`/permissions`）ように報告に書く（設定は書き換えない）。
   - vault が Git で管理されていれば（`.git/` がある）、`_guild/` も vault の中身としてコミットされることを報告に書く。分けたいときの `.gitignore` の例（`_guild/work/`、`_guild/requests/files/`）も添える（`.gitignore` は書き換えない）。
8. 開設を依頼主に報告する。伝えること:
   - `_guild/board.html`（依頼掲示板）を Edge か Chrome で開き、「ギルドの扉を開く」で `_guild` フォルダを選ぶ。研究は `_guild/research.html`（研究の記録）で同じように開く。2 枚は上の帯のタブで行き来できる。
   - 研究と単発のクエストは、`<projects_dir>/` と `<quests_dir>/` に 1 件ずつフォルダができ、資料は `input/`、成果物は `output/` に入る。会社の型は `<templates_dir>/` に置いておくと、鍛冶師が合わせて作る。
   - 質問への返事で分かった仕事の場の事実（使っている機器、会議の日、会社の決まりなど）は、賢者が `<knowledge_dir>/` に話題ごとに書き写す。次の依頼からは、書いてあることは聞かれない。
   - 専門用語は `<glossary_dir>/` に 1 語 1 ノートで貯まる。依頼掲示板の「用語を足す」からも登録できる。
   - 掲示板で依頼を貼ったり質問に返事をしたりしたあと、`/guild:quest` を実行するとギルドマスターが受け取る。回の終わりの報告は、掲示板の「ギルドからの知らせ」にも出る。決まった間隔で自動で動かしたいときは `/guild:auto 始める`（`inbox` を設定したときは、Inbox のメモだけでは自動の回は動かず、次に依頼・返事・評価が貼られた回で一緒に受け付ける）。
   - 達成したクエストと研究には Good / Bad の評価を付けられる。占い師が理由を聞き取り、次の依頼に活かす。依頼掲示板の「インタビューを受ける」から、占い師に依頼主のことを深掘りしてもらえる（人物帳 `_guild/client.md` に貯まる）。

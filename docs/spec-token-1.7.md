# SPEC：トークン削減（1.7.0）

## 概要
`/guild:quest` 1 回あたりの Claude のトークンを減らす。点検で分かった大きな要因は 2 つ：(1) `commands/quest.md`（36,815 字 ≒ 30K トークン）が毎回まるごと読み込まれる、(2) board.json を状態が変わるたびに全文 Read/Write している。これに、ギルド員の呼び出し連鎖の短縮、照合の索引化、モデルの見直しを加える。動きの意味（遷移表・人の関門・成果物の置き場）は変えない。

対象は点検の A-1〜A-3、B-1〜B-6、C のすべて。ただし B-1 の「受付嬢の取り次ぎ T と締め E の統合」は非目標にする（下の「非目標」）。

## 変更の中身

### A-1. quest.md の分割と重複除去（最優先）
- `commands/quest.md` を `skills/quest/SKILL.md` に移す（init・auto・help と同じ形。`argument-hint: "[auto]"`、`disable-model-invocation: true`。`/guild:quest` と `claude -p "/guild:quest auto"` の呼び方は変わらない）。`commands/` は空になるので消す。
- SKILL.md に残すもの（ホットパス）：冒頭の確認、ギルドの掟、フォルダ、クエストの遷移表、board.json の形、手順 1〜11 の骨格、自動実行時の短い規則、参照ファイルの読み方。**目標は、公式推奨の「SKILL.md は 500 行以下、詳細は `references/` へ」を目安にする（資料庫の追加に伴う依頼主の決定。上限は外した）。** ~~旧目標：12,000 字以下（約 10K トークン）。~~
- 頻度の低い分岐は `skills/quest/references/` に分け、その分岐に入ったときだけ Read する。SKILL.md には「〜のときは `references/<名前>.md` を読んでそのとおりにする」の 1 行だけを書く。
  | ファイル | 中身（今の quest.md の出どころ） |
  |---|---|
  | `replan.md` | 計画の直し（フォルダ `:48`、手順 1 `:217`、手順 2 `:220` の replan、手順 3 `:231`）を 1 か所に。承認の写し方・保留への退避・P ファイルの重複の扱いを含む |
  | `feedback.md` | 評価と人物帳の節 `:98-124`（Mermaid 図は削除）、手順 1 の評価・インタビューの返事 `:211-212`、手順 2 の評価の受け取り `:221`、`達成→要手直し` の写し方 |
  | `lessons.md` | 振り返りの節 `:77-96`（教訓帳の形・型・数える・決まりにする・本体の見直し）、手順 10、`kind: rule` の返事 `:213` |
  | `study.md` | 研究の計画（手順 3 の最初の計画）、承認の返事 `:216,219`、研究の締め（手順 9）、次の段階の返事 `:215` |
  | `auto.md` | 自動実行で許可が断られたときの扱い `:253`、錠の決まり `:199-201` |
  | `backfill.md` | 過去の達成分の後追い `:205`。board.json のトップに `results_backfilled: true` が無いときだけ読み、補う対象が無くなったら `true` を書いて以後は読まない |
- 重複除去の決まり：**同じ規則は 1 か所にだけ書き、ほかは「遷移表の〜の行」「`references/replan.md`」のように節名で参照する。** 特に次を 1 か所にする。
  - `保留` の研究のクエストの扱い（今 26 回）→ 遷移表の「受付済→冒険中」「要手直し→冒険中」の条件と、表の下の注 1 つだけ。
  - 「結果の Markdown を `output/` に残す」（今 7 回）→ フォルダの節 1 つと、手順 11 からの参照だけ（B-2 と合わせる）。
  - 「前の回の続き」→ 手順の冒頭 1 つ。
- 削るもの：画面のタブの説明 `:7-12`（人間向け）、Mermaid 図 `:101-111`、「スキル化を提案する」`:255`。
- 遷移表は規則の唯一の置き場にし、手順の中で遷移の条件を散文で繰り返さない（「遷移表の『冒険中→鑑定中』で」と書く）。

### A-2. board.py（board.json の読み書きを小さな Bash 呼び出しにする）
- 新しいファイル `skills/quest/board.py`（標準ライブラリだけ、Windows/Mac/Linux 共通）。`/guild:init` が `guild/.system/board.py` に写す（board.html と同じく新しい版で上書きしてよい）。`/guild:quest` は冒頭で、無いか `__version__` が古ければ写す。
- 動かす Python：board.json の `venv_python`、無ければ `system_python`（init が `py -3`→`python3`→`python` で見つけた Python の絶対パス。新しいキー。venv が作れたときも書く）。両方無ければ、今までどおり Python の `json` で読み書きする（init の決まりに従う）。
- 書き込みは load → 変更 → 一時ファイルに書いて `os.replace`（途中で止まっても壊れない）。`ensure_ascii=False`、UTF-8。書くたびに `updated` を更新する。知らない id・無い状態名・壊れた JSON は終了コード 1 とメッセージで止める。
- サブコマンド（最小限。引数の値は JSON 文字列で受ける）：
  | コマンド | すること |
  |---|---|
  | `get --summary` | ギルドマスターが読む要約。トップのキー（`max_active`・各 `*_dir`・`venv_python`・`inbox`・`results_backfilled`）、研究（id・title・status・priority・quests・`replan` の有無・`feedback.status`）、クエスト（id・study・title（30 字まで）・status・priority・due・adventurers・depends_on・notes・retries・dir・output・report・terms・`appraise`）、`未回答` の質問（id・kind・quest_id・study_id・feedback_id・interview_id・grill）。`result`・`log`・`detail`・回答済の質問は含めない |
  | `get --quest Q5` / `--study S1` / `--question A3` | その 1 件の全部 |
  | `add-quest <json>` / `add-study <json>` / `add-question <json>` | 次の番号を付けて載せ、id を印字する。`retries` 0・`log` `[]` などの既定を補う |
  | `next-id F` / `next-id I` | 評価・インタビューの次の番号 |
  | `set-status <id> <状態> --text "<理由>" [--who guildmaster]` | 状態を変え、`log` に `{time, who, edge: "今→次", text}` を足す。研究の `status` も同じコマンド（研究には `edge` を付けない） |
  | `set <id> <項目> <json>` | クエスト・研究の 1 項目を書く（retries・result・links・dir・done_when・adventurers・notes・output・report・terms・depends_on・feedback・replan・priority・next・plan・quests など）。`set-top <キー> <json>` はトップの項目 |
  | `log <id> --text "..." [--who ...]` | `edge` 無しの `log` 1 行 |
  | `answer <A3> --answer "..." --comment "..."` | 質問を `回答済` にする。`close-questions --quest Q5 --answer "取り消し"`（`--study` も）は `未回答` を全部閉じる |
  | `add-notice --text "..." [--stop "..."]...` | `notices` の先頭に足し、20 件を超えた分を消す |
  | `apply-simple` | `requests/` 直下の `M<日時>.json`（`kind: setting`）と `S<日時>.json`（`kind: study_priority`）を今の手順 2 の規則どおりに取り込み、`済/` に移す（同名は `-2`）。取り込んだ・取り込まなかったことを `add-notice`（`by: "guildmaster"`、定型文「同時数を n 件にした」「S3 の優先度を 保留 にした」「同時数 12 は範囲外なので取り込まなかった」）で残し、結果を JSON で印字する |
  | `archive [--days 30]` | `達成`・`中止` になってから N 日（最後の `log` の `time` で判定）たったクエストと、その `回答済` の質問を `guild/.system/board-archive.json` に移す。研究のクエストは、その研究も `達成`・`中止` で N 日たったときに研究ごと移す。`notices`・`profile` は触らない。番号の通し番号は board.json のトップに `last_ids: {Q, S, A, F, I}` を持たせて保ち、`add-*` はそれを使う（退避しても番号が戻らない） |
  | `glossary-index <glossary_dir>` | 用語ノートの frontmatter（`aliases`）と先頭の段落から `<glossary_dir>/用語集.md` を作り直す（B-3） |
  | `assets-index` | `assets_dir` の候補を条件つきで確定に昇格し、`資料庫.md` と `.system/assets.json` を作り直す。`{index, counts}` を印字する。`assets_dir` が無いと失敗する |
  | `assets-apply` | `requests/D*.json`（資料庫の決定）を取り込んで `済/` に移し、`add-notice` で残し、`{applied, rejected}` を印字する |
  | `assets-list` | ノートを `<id>  <状態>  <targets>  <source>  <version>` の 1 行ずつ、候補・確定・置換済の順に印字する |
  | `assets-check <ファイル>…` | 各ファイルの `{file, sha256, state, note}` を印字する。`state` は `registered`・`trashed`・`changed`・`new`・`unreadable` |
  | `assets-trash <id>…` | id の完全一致でノートを `<assets_dir>/ゴミ箱/` に移し、移した id を印字する。1 件でも不明なら何も動かさず失敗する |
  | `assets-scan [--limit N]` | 前提設定は `assets_dir` と、`projects_dir` か `quests_dir` のどちらか。案件フォルダの `input/` を走査し、庫に未登録の資料だけを `{items, remaining, unreadable, oversize}` で印字する（上限に当たると `truncated: true`）。`--limit` は 1〜20（既定 5。範囲外は `BoardError`）。20 MB 超（`MAX_SCAN_BYTES`、暫定）は `oversize` に名前を入れ、シンボリックリンク・隠しファイル・md 写しは対象外 |
  | `assets-approve [--source S] [--target T] [--all] [--yes]` | 絞り込み（3 つのどれか）が必須。`--yes` なしは `{preview, skipped}` を印字するだけで何も変えない。`--yes` ありは `conflict` なしの候補を確定にし `{approved, skipped}` を印字する。自分以外に同じ `source` の確定ノートがある候補と、`supersedes` を持つ候補は対象外。`--target` は `targets` をカンマで分けた要素との完全一致、`--source` は資料名の完全一致で、両方指定すると AND。前提設定は `assets_dir` だけ |
- SKILL.md の決まり：**ギルドマスターは board.json を Read・Write で直接触らない。** 読むのは `get --summary`（回の始めと、手順 5・7・11 の始め）と `get --quest` など、書くのは上のサブコマンドだけ。「状態が変わるたびに書き直す」は、サブコマンドごとに書かれるので自然に満たされる（画面はこれまでどおり 10 秒で追う）。
- 手順 11 の最後に `archive --days 30` を実行する。
- `/guild:help` は `get --summary` で読んでよい（無ければ今までどおり `json.load`）。
- テスト `tests/test_board.py`：純関数（要約の中身、`set-status` の `log`、`apply-simple` の規則、`archive` の判定、`glossary-index` の解析、`last_ids` の保持）。資料庫は、`assets-check` の判定、`assets-apply` の遷移（承認・却下・上書き・ゴミ箱・取り込めない決定）、自動確定、`assets-trash` の全件一致、`assets-index` の再実行で同じ結果になること、`resolve_assets_dir`。後追いは `TestAssetsScan`（走査の対象、除外、`oversize`・`unreadable`、シンボリックリンクを辿らないこと）と `TestAssetsApprove`（絞り込み必須、プレビューと `--yes`、対象外の理由）。画面側は `tests/test_static.py`（資料庫タブの有無と値のエスケープ、達成列の「もっと見る」）。
- 資料庫：構成・読み方・手順は `skills/quest/references/assets.md`。
- 後追い：起動は依頼主の明示だけ。走査の上限（深さ 20 段、調べるファイル 1000 件、1 回の原本サイズ合計 50 MB）は暫定で、超えると `truncated: true` が付き、`remaining` は「少なくとも」の意味になる。
- 一括承認：ギルドマスターは `--yes` を付けて実行しない。理由と対象外の候補は `skills/quest/references/assets.md` の「一括承認」。
- 画面：達成列は `doneShown`（既定 8 件、「もっと見る」で 8 件ずつ追加）。

### A-3. guild-run.py：値を 1 つ変える依頼では Claude を呼ばない
- `run` の `has_work` の前に、`<sysd>/board.py` があれば `apply-simple` を同じプロセスから呼ぶ（`importlib` で読み込む。無ければ飛ばす）。そのあとで `has_work` を見る。`M`・`S` だけの回は `skipped: true` で終わり、Claude を呼ばない。
- 失敗しても回は止めず、ログに traceback を残して Claude に任せる（ギルドマスターの手順 2 の `apply-simple` が拾う）。
- `--model`：`install --model <名前>` を足し、`auto.json` に `model`（無指定なら `null`）を保存する。`run` は `model` があれば `claude -p ... --model <名前>` を付ける。`/guild:auto 始める` の質問に「ギルドマスターのモデル（既定のまま / sonnet / opus）」を 1 問足す（今の 2 問と同じ 1 回の `AskUserQuestion`）。`様子` にも表示する。
- `allow.txt`：`/guild:auto 始める` は `Bash(<venv_python>:*)` に加えて、`system_python` があれば `Bash(<system_python>:*)` も足す（board.py を動かすため）。

### B-1. 呼び出し連鎖の短縮
- **用語ノートのクエストは鑑定士を呼ばない**（決定）。手順 8 で載せる「用語ノートを書く（n 語）」に `appraise: false` を付ける。手順 7 は、`appraise: false` のクエストは報告書がそろったら鑑定士を呼ばず、吟遊詩人の報告書の「## 自己点検」（1 語 1 ノート・`aliases`・「関連」に種類・相手のノートに逆向き・出典、の 5 つを満たす／満たさない）を見て、全部満たしていれば `達成`、満たさないものがあれば 1 回だけ吟遊詩人に直させ、2 回目はそのまま `達成` にして司書の次の見回りの対象にする。`agents/bard.md` に「## 自己点検」の節を足す。
- **賢者を呼ぶ条件を絞る。** 手順 8 の知識は、この回に `回答済` になった質問のうち `kind` が `question` か `confirm` のもの、または `達成` になったクエスト（用語ノートのクエストを除く）があるときだけ。`approval`・`todo`・`rule` の返事だけの回は呼ばない。
- **司書の用語集めは 2 件以上たまってから。** 手順 8 の用語は、この回に `達成` になったクエスト（用語ノートのクエストを除く）が 2 件以上、または 1 件でも報告書の「## 用語」に 3 語以上あるときに呼ぶ。それ以外は board.json のトップ `pending_term_quests`（クエスト番号の配列）に積み、次に条件を満たした回でまとめて渡す。

### B-2. 結果の文章は 1 か所に
- 全文は `output/<番号> 結果.md` だけ。クエストのノートの「結果」は要約 1〜2 行と `[[<番号> 結果]]`、研究ノートの「記録」は 1 行（クエスト・結果の要約・`[[<番号> 結果]]`）、board.json の `result` は画面用の数行（受付嬢の `## result` のまま）。`notices` は今までどおり。
- 受付嬢（締め）の `## result` は「要約（数行）」と決め、全文は書かせない。全文は担当ギルド員の報告書から、ギルドマスターが `結果.md` に写す（手順 7 の時点で作る）。

### B-3. 用語集の索引
- `<glossary_dir>/用語集.md`：表 `| 用語 | 別名 | 意味（1 行） |`。吟遊詩人が用語ノートを書く・直すたびに該当行を足す／直す（`agents/bard.md`）。`/guild:init` は、無ければ `board.py glossary-index` で作る（用語ノートが無ければ見出しだけ）。`/guild:quest` も冒頭で無ければ同じコマンドで作る。
- 「用語集に無い語」の照合は、この索引を読むだけにする（`agents/receptionist.md`・`scribe.md`・`adventurer.md`・`bard.md`・`smith.md`・`appraiser.md` の「`<glossary_dir>/` のファイル名と `aliases`」をすべて「`<glossary_dir>/用語集.md`」に直す）。依頼書の「用語集:」の行も索引のパスにする。
- 書記の語拾い（`agents/scribe.md:24-26`）は、受付嬢の報告書の「先に調べる語」「語：」の答えを写すだけにし、自分で拾い直さない。

### B-4. 過去の報告書の見回りをやめる
- `agents/receptionist.md:38` と `agents/seer.md:12` の「過去の報告書を `ls` で列挙して読む」を消す（受付嬢に Bash は無い）。
- ギルドマスターが依頼書に「関係する報告書のパス」を書く：受付（R）は前提クエストと同じ研究のクエストの報告書、評価（F）はそのクエストの報告書と鑑定の報告書（今もある）、インタビュー（I）は最近の評価 3 件のまとめ。ギルド員はそれ以外の報告書を探さない。

### B-5. エージェント定義の整理
- 全 10 ファイルの「冒険者ギルドの作業場所 `guild/` … 無ければギルドマスターに報告して止まる」を消す（ギルドマスターが冒頭で確かめている）。
- 共通の段落（人物帳・決まり・教訓帳／先に調べる語／依頼主への質問の書き方）は、文面を 1 つにそろえる（トークンは変わらないので、ここは保守のため）。

### B-6. モデルと役の分割
- **鑑定士を sonnet にする**（決定）。`agents/appraiser.md` の `model: sonnet`。戻す条件を README の開発者向けに書く：教訓帳に「鑑定の見落とし」（占い師が Bad の聞き取りで付ける型）が 2 行になったら opus に戻す。
- **受付嬢を 2 役に分ける。** `receptionist`（opus）は受付の聞き取り（R と研究の `<研究番号>-receptionist<n>.md`）だけ。新しい `herald`（伝令。sonnet。tools: Read, Glob, Grep, Write）が取り次ぎ `T<日時>-herald.md` と締め `E<日時>-herald.md` を受け持つ。報告書の節名（「## ギルド員への答え」「## 依頼主への質問」「## result」「## 依頼主への報告」「## 止まっていること」）は変えない。`questions[].from` は取り次ぎで載せたものが `herald`、`notices[].by` も `herald`（画面は `by` を表示しないので壊れない。README・init の文章の「受付嬢が書いた報告」は「伝令が書いた」に直す）。`agents/receptionist.md` から取り次ぎと締めの節を `agents/herald.md` に移す。

### C. そのほか
- `agents/smith.md:13-14`：作り方の順を「会社の型がある、または見た目の要件があるときはドキュメント作成のスキル → それ以外は `venv_python` の `python-pptx`・`python-docx`・`openpyxl` で直接作る」に入れ替える（スキルの読み込みが数千〜1 万トークン）。
- 「同じ種類のクエストが何度も来ていたらスキル化を提案」は削除。
- `/guild:auto 始める` の推奨間隔はそのまま 5 分（quest.md が小さくなるのでキャッシュに頼らない）。

### D. ドキュメントとバージョン
- README：コマンドの節（quest がスキルになっても呼び方は同じなので変更なし）、ギルドの役の表に `herald`（伝令）を足す、「ギルドからの知らせ」の書き手、用語集の節に索引 `用語集.md`、自動実行の節に `--model` と「同時数・優先度の変更だけでは Claude を呼ばない」、フォルダの節に `board.py`・`board-archive.json`、開発者向けに「鑑定士を opus に戻す条件」と「更新したら `/guild:init` をもう一度（board.html・board.py を新しい版にする）」。
- `skills/init/SKILL.md`：board.py の写し、`system_python`、`用語集.md`、報告文の「伝令」。
- `skills/help/SKILL.md`：`get --summary` で読む。
- `plugin.json`・`marketplace.json` の version を 1.7.0 に。

## 受入条件
1. `skills/quest/SKILL.md` が公式推奨の 500 行以下を目安に収まり（~~旧目標：12,000 字以下~~。資料庫の追加で上限は外した）、`commands/quest.md` は無い。`/guild:quest` と `claude -p "/guild:quest auto"` が今までどおり動く。
2. SKILL.md と `references/*.md` を合わせて、「保留」「計画の直し」「結果の Markdown」の規則がそれぞれ 1 か所にだけ書かれ、ほかは節名かファイル名で参照している。遷移の条件は遷移表にだけある。
3. 返事 1 件だけの回（例：`approval` の「この案で進める」）で、`references/` のうち読むのは `study.md` だけ（SKILL.md の文面で確かめる）。
4. SKILL.md に board.json を Read・Write で直接触る指示が無く、読み書きがすべて `board.py` のサブコマンドで書かれている。board.py は `tests/test_board.py` が通る。
5. 同時数か研究の優先度の変更だけを置いた回は、`guild-run.py run` が Claude を呼ばずに `skipped: true` で終わり、board.json に反映され、知らせに定型文が出る。
6. `達成`・`中止` から 30 日たったクエストが `board-archive.json` に移り、画面から消える。そのあとに貼った依頼の番号が戻らない。
7. 用語ノートのクエストが鑑定士を呼ばずに達成し、吟遊詩人の報告書に「## 自己点検」がある。`approval` の返事だけの回で賢者が呼ばれない。
8. 達成したクエストの全文が `output/<番号> 結果.md` にだけあり、クエストのノートと研究ノートはリンク行になっている。
9. `<glossary_dir>/用語集.md` があり、受付嬢・書記・冒険者・吟遊詩人・鍛冶師・鑑定士の定義が用語集の照合にそれを使っている。書記が語を拾い直す文が無い。
10. `agents/*.md` から「作業場所 … 止まる」の段落と、「`ls` で列挙」の文が消えている。
11. `agents/herald.md` があり、取り次ぎと締めがそこにある。`appraiser` が `model: sonnet`。
12. `/guild:auto 始める` でモデルを選べ、`auto.json` に保存され、`run` の `claude` コマンドに `--model` が付く（指定なしなら付かない）。既存のテスト（`tests/test_guild_run.py`）が通り、`apply-simple` の呼び出しと `--model` のテストが足されている。
13. 旧版の vault（board.py・用語集.md・`last_ids` が無い）で `/guild:quest` を実行すると、冒頭で補われて動く。

## 非目標
- 受付嬢の取り次ぎ T と締め E の統合（T の答えで同じ回に再出発させる必要があり、分けたまま herald に移すだけにする）。
- 遷移表の意味の変更、人の関門の追加・削除。
- 人物帳 `client.md`・決まり `rules/` の渡す量の制限（増えてから考える）。
- 画面（board.html）の変更。退避分の表示、`herald` の名前の表示。
- 手動の `/guild:quest` の使用量の記録。
- 吟遊詩人・冒険者・書記・賢者のモデル変更（今も sonnet）。

## リスク
- A-1 で参照ファイルに分けると、分岐に入る回は Read の 1 回分が増える。分岐に入らない回がほとんどなので差し引きで減るが、研究の計画が続く回は今と同程度。
- `get --summary` に無い項目が要るときに `get --quest` を忘れると、ギルドマスターが推測で書く恐れがある。SKILL.md に「要約に無い項目は `get --quest` で読む」と明記する。
- 鑑定士の sonnet 化で鑑定の見落としが増える可能性。戻す条件（教訓帳の「鑑定の見落とし」2 行）で見張る。
- 用語ノートを鑑定しないので、形の崩れは司書の見回りまで残る。
- `archive` で退避したクエストを前提（`depends_on`）にしているクエストは無いはず（達成から 30 日）だが、`archive` は前提に使われている番号を退避しない安全弁を入れる。
- `herald` の追加で `from`・`by` の値が変わる。画面は表示に使っていないが、過去の `notices` と混ざるので文章では「伝令（旧 受付嬢）」と断る。
- `claude -p` の `--model` の名前はバージョンで変わりうる。`sonnet`・`opus` の別名を使う。

## 決定ログ
- Q1：鑑定士は sonnet に下げる。戻す条件を README に書く。
- Q2：用語ノートのクエストは鑑定士を呼ばず、吟遊詩人の自己点検で達成にする。
- Q3：board.json の退避は達成・中止から 30 日。画面は board.json だけを読む。
- Q4：自動実行のギルドマスターのモデルは任意で指定（`auto.json` の `model`、既定は指定なし）。
- 質問せずに決めたこと：quest をコマンドからスキルに移す（参照ファイルを同じフォルダに置くため。init・auto・help と形がそろう）。board.json の書き出しは「節目でまとめる」ではなく board.py のサブコマンドごと（小さい書き込みなので画面の追従も保てる）。T と E の統合は非目標。司書の用語集めは 2 件以上たまってから。
- 実装での変更：board.py を動かす Python は board.json の `system_python` ではなく `guild/.system/python.txt`（1 行）にした。SKILL.md が board.json を読む前に Python を知る必要があるため。`/guild:init` と自動実行のスクリプト（`run` のたびに `sys.executable` から）が書く。自動実行の `allow.txt` には、`/guild:auto 始める` が `python.txt` の Python も足す。

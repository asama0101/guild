# 分解（受付 → 分解中 → 承認待ち）

必要なときだけ読む。SKILL.md の手順 3〜5 の詳細。

## 受付
1. 新しい依頼（`requests/R*.json`。`title`・`detail`・`due`・`form`〈納品物の形〉・`priority`〈優先／通常〉・`files`）は、`board.py add-quest --title … --detail … [--due …] [--form …] [--priority …]` でクエストにする。形が「その他（くわしくへ）」のときは、`detail` を読む。添付は `requests/files/R<日時>/` にある。`input/` へ写す。クエスト以外の登録経路はない。単純な依頼も、達成条件が 1 つのクエストになる。
2. `board.py make-brief Q1 receptionist` で、受付嬢の依頼書を作る（クエストの題名と内容、素材の場所、人物伝の要約、掟が付く）。
3. 受付嬢は `.system/reports/<Q番号>-receptionist.md` に `## 聞き取りの問い` と `## 依頼主への質問` を書く。聞くのは、目的・納品物の形・期限・素材の足りなさだけ。問いは 1 回 3〜7 個、答えが前に進むものだけ。選択式にし、推奨案と理由を付ける。
4. ギルドマスターは、`## 依頼主への質問` の各問いを `board.py add-question --quest Q1 --kind choice --text … --options '[{"label":…,"reason":…,"recommended":true},…]' --default …` で質問に出す。選択肢は 2〜4 個。
5. 未回答の問い（kind が choice／todo）がなくなったら、`board.py set-status Q1 分解中`。

## 分解
1. `board.py make-brief Q1 fortune_teller` で、占い師の依頼書を作る（クエストの内容、聞き取りの答え、素材の場所、人物伝の要約、教訓帳の抜粋、掟が付く）。
2. 占い師は `.system/reports/<Q番号>-fortune_teller.md` の `## 達成条件案` に、達成条件を書く。各達成条件に次を持たせる：題名、`done_when`（1〜3 個、確かめられる文）、`effort`（低・中・高）、納品物の形（`form`）、納品物の場所（`output_path`、`output/…` の形）、所要見積（分）、締切、前提（`depends_on`）、触るノート、元に戻せない操作があるか（`needs_execute`）。
3. ギルドマスターは `board.py add-goal …` で達成条件を載せる。前提の指定は、先に作った達成条件の id で行う。
4. `board.py route-check Q1 --write` で、閉路・前提の欠け・締切の逆算を検査する。余裕が 0 未満の警告は、承認の質問の本文に書く。
5. 検査に通ったら `board.py set-status Q1 承認待ち`。

## 承認①の質問
`board.py add-question --quest Q1 --kind approval --scope route --text "道のりを確認して、承認してください" --options '[{"label":"承認する"},{"label":"やり直す"},{"label":"あとで決める"}]'`。道のり図は、`board.py` が `.system/diagrams/route-Q1.svg` に作る。

## 道のりのやり直し（承認待ち → 分解中）
依頼主が承認①で「やり直す」を選ぶと、画面は `answers/` に `choice: "やり直す"` と、依頼主の一言（`comment`）を書く。
1. `board.py apply-simple` で回答を取り込む（`need-claude` が `answered_question` を返す）。
2. `board.py set-status Q1 分解中 --who client`。回答の記録がなければ通らない。通ると、依頼主の一言が回答の記録から使われる。
3. `board.py make-brief Q1 fortune_teller`。依頼書の「聞き取りの答え」に、「やり直す（依頼主の一言）」が付く。占い師は、その一言に沿って達成条件案を直す。
4. 直し方は、ギルドマスターが `board.py` で行う：
   - 直す項目は `board.py set G1 <項目> <json>`（題名・`done_when`・締切・前提など）。
   - 足す達成条件は `board.py add-goal …`。
   - いらなくなった案の達成条件は `board.py set-status G1 中止`（分解中のあいだだけ、ギルドマスターが外せる。その達成条件を前提にする案が残っていると通らない。先に前提を直す）。
5. `board.py route-check Q1 --write` で検査し、`set-status Q1 承認待ち`。承認①の質問を、もう一度出す。前の質問は回答済みで残る。
6. 「やり直す」は、道のりの差し戻し（下）の回数には数えない。何度でも、依頼主が決める。

## 差し戻し（fix_kind が goal）
鑑定士が `fix_kind: goal` を書いたら、依頼主に理由を伝える通知を出し、`board.py set-status Q1 分解中`。差し戻しは 1 クエストに 2 回まで。達成済みの達成条件は達成のまま、ほかは案に戻る。承認①をやり直す。

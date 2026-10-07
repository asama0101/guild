# 魔導書・蓄積・資料室・設計図・人物伝

必要なときだけ読む。「使うほど良くなる」ための仕組み。どれも、**依頼主が確定する**。ギルドマスターは、確定を代わりに行わない。

## 魔導書（`spellbook/`）
- 1 項目 1 ノート。種別は 用語／設備／取り決め。出典（`sources`）が 1 件以上ない項目は書けない（`board.py spellbook-index` が拒否する）。上限 200 項目。
- **参照**：`board.py make-brief` が、達成条件の語で一致した項目（`aliases`・名前。5 件まで）だけを依頼書に付ける。使った項目は、達成条件の `refs` と、ノートの `used_by`・`last_used` に記録される。クエスト票に「魔導書『…』を参考にした」と出る。索引は、ギルド員に読ませない。
- **候補づくり**：クエストが達成したら、`board.py accumulate-todo Q1` を見る。`wizard` に材料があるときだけ、`board.py wizard-brief Q1` で依頼書を作り、`guild:wizard` を 1 回呼ぶ。魔法使いは 1 回に 10 項目まで、候補（`status: 候補`）として書く。そのあと `board.py spellbook-index` で索引を作り直す（出典のない項目があると、終了コード 1 で知らせる。その項目は書き直させる）。`board.py accumulate-done Q1 --who wizard`。
- **確定**：`board.py apply-simple` が、候補ごとに質問（`kind: term`、確定／修正する／あとで決める）を出す。期限が来たら、候補のまま使う。使用クエストが 1 件以上ある候補だけが、依頼書に付く。
- **訂正**：要手直しの理由に出た項目と、確認から 1 年たった項目は、再確認の質問になる。
- **資料室への移動**：`board.py shared-candidates` が、`used_by` が 2 件以上の素材を出す。`apply-simple` が移動の質問（移す／移さない。推奨は移す）を出し、承認されると `board.py shared-move` が素材を `shared/` に移し、`input/` にリンクファイルを残し、`sources` を書き換える。予測では移さない。

## 吟遊詩人（教訓と人物伝）
- クエストが達成したら、`accumulate-todo Q1` の `bard` に材料があるときだけ、`board.py bard-brief Q1` で依頼書を作り、`guild:bard` を 1 回呼ぶ。材料は、bad の理由、good の評価、工房の知見メモ、インタビューの答え。
- 吟遊詩人の報告書（`.system/reports/Q1-bard.md`）を、`board.py bard-apply Q1 --file …` で取り込む。教訓は `lessons.md` に足され、人物伝の案は質問（覚える／見送る。推奨は見送る）になる。推測は、2 回以上観察されるまで質問にならない。
- 依頼主が「覚える」を選ぶと、`profile.md` に、`kind` と `evidence` つきで足される（50 項目まで）。
- インタビューは、依頼主が頼んだときだけ：`board.py interview-add --topic …`。吟遊詩人が質問を `## 依頼主への質問` に書き、`board.py interview-ask I1 --quest Q1 --file …` で質問に出す。答えがそろうと、インタビューの状態が「回答済」になり、次の `bard-brief` の材料になる。

## 工房の知見メモ
- `/guild:workshop` の終了時にできる `W<日時>-workshop.md` は、魔法使い（`## 用語・取り決め`）と吟遊詩人（`## 好み・直しの傾向`・`## 直した点`）が読む。処理したら `board.py memo-done <ファイル名> --by wizard|bard`。両方が済むと `済/` に移る。同じメモは二重に処理しない。
- 吟遊詩人の側の `memo-done` で、`## 直した点` が指摘として数えられる。同じ指摘が 2 回目になると、掟の案の質問が出る。

## 設計図（`templates/`）
- 納品物が good で、形が Word・Excel・PowerPoint・PDF のとき、`bard-apply` が「設計図にしますか」の質問（推奨は「しない」）を出す。承認されると `board.py template-add` が `templates/` に置く。
- 占い師の依頼書（`make-brief Q1 fortune_teller`）に、設計図の一覧と使用回数が付く。占い師が、達成条件の `template` を決める。鍛冶師の依頼書（`make-brief G1 smith`）に、設計図の場所が付く。

## 整理（`board.py housekeeping`）
`apply-simple` の中の `tick` が、1 日 1 回、整理候補を最大 5 件ずつ質問にする（魔導書の 1 年未使用・200 項目超え、設計図・資料室の 1 年未使用、半年再発のない掟）。選択肢は 整理する／見送る（推奨は見送る）。整理は、削除でなく `.archive/` への退避。

## 見積と費用
`board.py usage [--quest Q1]` が、呼び出し回数と概算トークンを出す（クエストの詳細にも出る）。`board.py calib` が、見積と実績の比（補正係数）と、effort 別の NG 率を `calib.json` に書く。補正係数は、占い師の依頼書に 1 行で付く。

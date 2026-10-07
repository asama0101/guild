# 承認と鑑定

必要なときだけ読む。SKILL.md の手順 7〜9 の詳細。

## 承認の決まり
- 承認①（道のり）と承認②（納品物）は必須。元に戻せない操作があるときだけ、承認③（実行）を足す。
- 承認の辺（`client`）は、`.system/answers/` に、対応する質問の回答の記録があるときだけ通る。ギルドマスターが承認を代わりに記録しない。依頼主が答えていなければ、待つ。
- 依頼主の回答は、画面が `answers/A<番号>.json` に書く。`board.py apply-simple` が質問に取り込む。チャットで答えた場合は、依頼主の言葉をそのまま `board.py answer A1 --choice … --comment …` で記録する。

## 鑑定（冒険中 → 鑑定中）
1. 冒険者が `.system/reports/<G番号>-adventurer.md` に `## result`（事実表）と `## log` を書く。
2. 錬金術師が納品物（Markdown）を `output_path` に書く（`guild:alchemist` の書式）。納品物の形が Word・Excel・PowerPoint・PDF なら、そのあと鍛冶師（`guild:smith`、依頼書は `make-brief G1 smith`）が器にして、`output_path` のファイルを作る。
3. `board.py pre-check G1`。NG なら鑑定士を呼ばず、`board.py set-status G1 要手直し --reason precheck_ng`。
4. OK なら `board.py set-status G1 鑑定中`。鑑定士に、納品物の場所と出典の一覧だけを渡す。冒険者の報告は渡さない。
5. 鑑定士は `.system/reports/<G番号>-appraiser.md` に結果を書く。合格なら、ギルドマスターが `set-status G1 確認待ち --who appraiser`。不合格なら、鑑定士の指摘（`fix_kind`・`point_code`・`target`・`point`）を `board.py add-finding G1 …` で記録し、`set-status G1 要手直し --who appraiser`。
6. 同じ指摘（`fix_kind`＋`point_code`＋`target`）が 2 回目になると、`add-finding` が掟の案の質問を作る（rules.md）。

## 補正（要手直し → 冒険中）
- `fix_kind: input` なら素材・資料室を選び直す。`brief` なら依頼書を書き換える。`goal` なら分解へ差し戻す（decompose.md）。
- `board.py make-brief G1 adventurer` で依頼書を作り直し（これまでの指摘が付く）、`set-status G1 冒険中`。手直しの上限は達成条件ごとに 3 回、クエスト全体で 6 回。上限に達すると、`board.py` が質問（続ける／工房で直す／諦める）を出す。答えを待つ。
- 錬金術師のモデルは `board.py model-for G1 alchemist` の答えに従う。opus になるのは、`effort` が高いとき、または要手直し 2 回目で指摘が「矛盾」「誤り」のときだけ。

## 承認②（確認待ち）
`board.py add-question --quest Q1 --goal G1 --kind approval --scope output --text "「…」の納品物を確認してください" --options '[{"label":"承認する"},{"label":"やり直す"},{"label":"あとで決める"}]'`。全部の達成条件が確認待ちになったら、画面は一覧で 1 回で通せる。承認されたら `set-status G1 達成 --who client`。「やり直す」なら `set-status G1 要手直し --who client --text "<依頼主の一言>"`。

## 承認③（実行）
`needs_execute` が真の達成条件だけ。承認②のあと `set-status G1 実行承認待ち --who client`、質問 `--scope execute` で、元に戻せない操作の内容を 1 画面で見せる。承認されたら、メインセッションが実行し、結果を `board.py log-append G1 --text …` で冒険日誌に残して `set-status G1 達成 --who client`。実行がエラーなら `set-status G1 要手直し --reason report_error`。拒否なら `set-status G1 失敗 --who client`。

## 記録と締め
- 冒険者の `## log` は、`board.py log-append G1 --file .system/reports/G1-adventurer.md` で冒険日誌に追記する。依頼主向けの記録は `board.py` が `quest.md` に作る（`render-quest` は自動で呼ばれる）。
- すべて達成したら、`board.py cross-check Q1`。`clean` なら `set-status Q1 達成`。`suspect` なら `set-status Q1 最終鑑定` にして、鑑定士にクエスト全体の最終鑑定を頼む。依頼主が最終鑑定を頼んだときも同じ。
- 最終鑑定で矛盾が見つかったら、直す達成条件ごとに `add-finding` を書き、`set-status Q1 進行中 --who appraiser --goals G1,G2`。
- クエストが達成したら、`lessons-append` で bad の理由を教訓にする（`board.py` が評価の依頼から取り込んだ `feedbacks` を見る）。

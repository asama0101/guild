# 掟・教訓帳・見積

必要なときだけ読む。学習のループ（観測 → 蓄積 → 次回の読み手 → 訂正）の 0.1 の分。

## 掟（`.system/rules/`）
- 同じ指摘（`fix_kind`＋`point_code`＋`target` が同じ）が 2 回目になると、`board.py add-finding` が掟の案の質問（`kind: rule`、推奨案は「掟に足す」）を出す。
- 鑑定士が掟の案を 1 行書く。`add-finding … --rule-text "<案>" --rule-actor <役 ID>` で渡す（全員向けは `_all`）。
- 依頼主が「掟に足す」を選ぶ（期限が来ても推奨案で足す）と、`.system/rules/<役 ID>.md` に 1 行足される。1 行に、掟の id・追加日・根拠（`fix_kind`＋`point_code`）・適用後の再発数が入る。1 ファイル 20 行まで。
- 採用後に同じ指摘が出ると、再発数が増える。再発が減らない掟、半年再発しない掟は、見直し候補にする（0.2 の `housekeeping`）。掟どうしが矛盾したときは、依頼主が決める。
- 掟は役ごとのファイルだけを読ませる。依頼書は `board.py make-brief` が、その役の掟と `_all.md` を付ける。

## 教訓帳（`.system/lessons.md`）
- 100 行まで。超えた分は `lessons-old.md` に畳む。
- 追記：`board.py lessons-append --kind 失敗|成功 --point-code <分類> --text <1 行>`。依頼主が bad を付けた理由、失敗した達成条件を残す。
- 読む：占い師と鑑定士だけ。`board.py lessons-brief [--point-code <分類>]`（`make-brief` が自動で付ける）。

## 人物伝（`profile.md`）
0.1 では、依頼主が自分で書く。`board.py profile-brief` が 10 行の要約を作り、受付嬢・占い師・錬金術師の依頼書に付く。0.2 で吟遊詩人が案を書く。

## 見積と費用
- 呼び出しのたびに `board.py usage-log --role … --model … --tokens … [--quest … --goal …]` を呼ぶ（取れる範囲で。失敗しても回は失敗にしない）。
- 1 回の実行で呼ぶサブエージェントは 20 まで。`board.py budget --use 1 --quest Q1` を呼び出しの前に呼び、`stop` が返ったらその回を止める。次の回は続きから始める。質問は出さない。同じクエストで 3 回続けて止まると、`board.py` が依頼主への質問を出す。
- 集計（`usage`・`calib`）は 0.2。

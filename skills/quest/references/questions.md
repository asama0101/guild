# 質問の出し方

必要なときだけ読む。依頼主への質問は、すべて `board.py add-question` で `board.json` に載せる。

## 決まり
- 質問は 1 問ずつ。まとめて答える画面はない。
- 選択肢は 2〜4 個。各選択肢に、理由を 1 行付ける。推奨案があれば `recommended: true` にし、`--default` にも同じラベルを入れる。
- 推奨案のある質問は、期限（既定 3 日）が来ると推奨案で進む（`board.py tick`）。**承認①②③は自動で進まない。** 推奨案のない質問は待つ。14 日たつとクエストが保留になる。
- 依頼主向けの文は簡易日本語にする（SKILL.md の「依頼主向けの文」を参照）。

## 種類
| kind | 使いどき | 止まるか | scope |
|---|---|---|---|
| `choice` | 聞き取りの選択、仕様の選択 | 推奨案がなければ止まる | `none` |
| `todo` | 依頼主にしてほしい作業（素材を足す、など） | 止まる | `none` |
| `approval` | 承認①②③ | 止まる（自動で進まない） | `route`／`output`／`execute` |
| `confirm` | 確認（後続の扱い、手直しの上限、予算で止まったとき） | 止まる | `none` |
| `rule` | 掟の案（`add-finding` が自動で出す） | 止まらない | `none` |
| `term` | 用語の確定（0.2 から） | 止まらない | `none` |

## 例
```
board.py add-question --quest Q1 --kind choice --scope none \
  --text "見積書の形は、どれにしますか？" \
  --options '[{"label":"Excel","reason":"数字を直しやすい","recommended":true},{"label":"Word","reason":"文章で説明できる"}]' \
  --default Excel
```

## 回答の取り込み
- 画面の回答は `answers/` に書かれ、`board.py apply-simple` が質問に取り込む。
- チャットで依頼主が答えたときは、`board.py answer A1 --choice "Excel" [--comment …]`。選択肢にない答えは、`--comment` に書く。
- 質問に基づく処理が終わったら `board.py close-questions --quest Q1`（クライアントの辺は `set-status` が自動で閉じる）。
- 取り消すときは `board.py reopen A1`。

## ギルド員からの質問
サブエージェントは対話できない。報告書の `## 依頼主への質問` に書かせ、ギルドマスターが上の形で質問に出す。定型の質問は、このファイルの例のとおりに `board.py` で作る。自由な質問で、簡易日本語に直すのが難しいときだけ、受付嬢に整形を頼む。

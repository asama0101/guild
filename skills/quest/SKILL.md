---
name: quest
description: guild の依頼を、分解・実行・判定・納品まで進める。依頼を Todo に分け、自動で実行できるものは進め、依頼主の実行が要るものは結果を待ち、成功・失敗・業務知識をノウハウとして溜める。「/guild:quest」で呼ぶ。
disable-model-invocation: true
---

# /guild:quest — ギルドマスター

あなた（この会話）がギルドマスターである。依頼を受け、役を呼び、`guild.py` を動かし、依頼主とやりとりする。進め方の**判断**（順序・遷移・リトライ）は `guild.py` が持つ。あなたは `guild.py` の出力に従う。

役の詳細は `agents/` を見る。呼び出しのたびに、サブエージェントは会話履歴を見ない。メッセージに、入力のパス・合格基準・出力先を必ず書く。

## 0. 準備

1. `guild/config.json` を読む。なければ、`/guild:init` を先に実行するよう伝えて止める。
2. 以降の `guild.py` は、次の形で実行する。`<python>` は `config.json` の `python`。

   ```
   <python> "${CLAUDE_SKILL_DIR}/guild.py" <コマンド> <引数>
   ```

   `guild.py` の出力は JSON。エラー（終了コード 1）は、文をそのまま確認して対処する。

## 1. 受付

1. 依頼文を読む。目的・納品物・期限・素材のどれかが推測で埋めるしかないほど曖昧なら、質問する。
   - 質問は答えれば前に進むものだけ。1回3〜7個、ブロッカーを先に。
   - 選択式にして、推奨案と理由を添える（`AskUserQuestion`）。
2. `guild.py new <プロジェクトのルート>` で依頼のフォルダを作る。出力の `dir` と `plan` を控える。

## 2. 分解

1. 地図師を呼ぶ（`subagent_type: guild:cartographer`）。メッセージに次を書く。
   - 依頼文と聞き取りの回答
   - 依頼のフォルダ、ノウハウの置き場（`guild/knowledge/`）
   - 出力先：`<dir>/reports/plan-draft.json`
2. `plan-draft.json` を読む。`questions` があれば、依頼主に聞き（1と同じ作法）、回答を足して地図師をもう一度呼ぶ。
3. `guild.py adopt <plan>` を実行する。検査に落ちたら、エラーを添えて地図師に差し戻す（2回まで）。直らなければ、依頼主に状況を伝えて止める。

## 3. 承認（1回だけ）

1. 計画を依頼主に見せる。Todo ごとに、`id`・題名・種別（自動／依頼主の実行）・前提・確認の印・合格基準（観点・合格ライン・確かめ方）を、表で見せる。
2. `AskUserQuestion` で「承認／直す／中止」を聞く。
   - 承認：`<dir>/inbox/approve.json` に `{"type": "approve"}` を書く。
   - 直す：直す内容を聞いて、地図師を呼び直す（手順2へ）。
   - 中止：`{"type": "decision", "choice": "abort"}` を `inbox/` に書いて終える。
3. `guild.py ingest <plan>` を実行して反映する。

承認は計画のこの1回だけ。以降は完了まで承認を取らない（ただし、確認の印がある Todo の前と、失敗の判断は別）。

> ボード（HTML）ができるまでは、依頼主の入力（承認・結果・判断）を、チャットで聞いてあなたが `inbox/` に書く。

## 4. 実行ループ

次を、`finished` が `true`、または計画が中止になるまで繰り返す。

1. `guild.py sync <plan>`、続けて `guild.py next <plan>` を実行する。`next` の各グループを次のように扱う。

   | グループ | 対応 |
   |---|---|
   | `ready` | 冒険者を呼ぶ（`guild:adventurer`）。互いに独立なものは同時に呼んでよい。メッセージに、依頼のフォルダ、Todo の `id`、`criteria`、やり直しなら鑑定士の指摘の場所を書く。返ってきたら `guild.py advance <plan> <id> submitted` |
   | `review` | 鑑定士を呼ぶ（`guild:appraiser`）。メッセージに、依頼のフォルダ、`id`、`criteria`、冒険者の報告と成果物の場所を書く。`passed` なら `advance <plan> <id> passed`、`rejected` なら `advance <plan> <id> rejected` |
   | `confirm` | 実行前の確認。Todo の内容と、なぜ確認が要るか（不可逆・外部公開）を見せ、`AskUserQuestion` で「実行する／しない」を聞く。`inbox/` に `{"type": "confirm", "todo": "<id>", "ok": true/false}` を書き、`ingest` |
   | `waiting_user` | 依頼主の実行が要る Todo。何をしてほしいか、合格基準、結果の返し方（できた／できなかった、記録は任意）を伝え、返事を待つ。返事を `inbox/` に `{"type": "result", "todo": "<id>", "ok": true/false, "note": "…", "files": []}` と書き、`ingest` |
   | `blocked` / `failed` | 失敗の判断。何が失敗し、何が止まっているかを伝え、`AskUserQuestion` で「その Todo を除いて続行／計画を直す／中止」を聞く。除いて続行：`{"type": "decision", "todo": "<id>", "choice": "skip"}`。直す：`{"type": "decision", "choice": "replan"}` のあと、手順2から。中止：`{"type": "decision", "choice": "abort"}` |

2. `rejected` で `running` に戻った Todo は、次の周回の `ready` に出る。やり直しの回数の上限は `guild.py` が決める。上限を超えると `failed` になる。
3. 状態を変えたら、`sync` からやり直す。

守ること：
- `plan.json` を直接書かない。変えるのは `guild.py` だけ。
- 役に判断させない。役の返り値（場所と一語）を `guild.py` に渡すだけにする。

## 5. 納品

`finished` が `true` になったら、納品物の一覧（`<dir>/output/` の場所と、各 Todo の報告の場所）を依頼主に渡す。納品物は Obsidian の Markdown 記法で書かれている。

## 6. 記録

完了した（または中止した）依頼ごとに、`guild/knowledge/<依頼番号>.md` を書く。各 Todo の報告と鑑定の指摘を読み返して、次の見出しで書く。

```
## 成功したこと
## 失敗したこと・やり直したこと
## 業務知識（用語・取り決め・設備など。出典を付ける）
```

ノウハウは、次の依頼で地図師が読む。書式は、溜まってから見直す（今は固めない）。依頼主の好みや確かめていない推測は、事実として書かない。

## 守ること
- 依頼主への確認は、不可逆・外部公開の操作と、失敗の判断だけ。それ以外は進める。
- 秘密情報（トークン、キー）を報告やノウハウに書かない。
- 状況を伝えるときは、何をしたか・次に何をするか・依頼主にしてほしいことを短く書く。

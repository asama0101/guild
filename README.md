# guild

依頼を Todo に分解し、自動で実行できるものは自動で、依頼主の実行が要るものは結果を待って、解決まで進める Claude Code プラグインです。用語・業務フロー・業務情報・個人・心得を「書庫」に溜め、次の依頼で全役が使います。RPG のギルドの世界観（役名・掲示板）で作っています。個人利用を前提にしています。

## 特長

- **グラフで進める**: 進め方（Todo の依存関係と状態遷移）は手順書の文章ではなくデータ（`plan.json`、`transitions.json`）で持ち、`guild.py` が辿ります。役は作業と報告だけをして、順序・合否・リトライは判断しません。
- **承認は計画の1回だけ**: 計画を承認したあとは完了まで承認を取りません。ただし不可逆・外部公開の操作の前は確認します。Markdown 以外が要るときのプロンプトの追加は、計画を変えないので承認を取りません。
- **質問はすべてボードで**: 質問・承認・結果の入力・失敗の判断は、チャットではなくボード（`guild/board.html`）の「手紙」で答えます。
- **合格基準で判定**: 各 Todo に合格基準（観点・合格ライン・確かめ方）を付け、鑑定士が判定します。満たさなければ実行に戻ります（最大2回）。
- **外部サイトは許可制**: 冒険者が WebFetch で開けるのは、依頼主が許可したドメインだけです。許可のないサイトはフックが止め、ボードの「手紙」で許可を聞きます（許可リストに加える／今回だけ／許可しない）。
- **見える化**: ボードの「クエスト進捗」に、依頼の開始日〜締切の帯と、Todo の予定日（◆）、あなたの実行（human）の日ごとの件数が出ます。
- **書庫に溜めて使う**: 依頼の完了・中止後に、司書が登録候補を挙げ、依頼主が選んだものが `guild/archive/` に溜まります。

## 必要なもの

- Claude Code
- Python 3（`/guild:init` が `py`、`python3`、`python` の順に探します）
- Chrome または Edge（ボードを開くため）
- Playwright MCP（斥候が動的ページを読むときに使う。`playwright` という名前で導入・接続しておく。未接続だと `/guild:init` が警告して止まる）

## 導入

このリポジトリをマーケットプレイスとして追加し、プラグインを入れます（`.claude-plugin/marketplace.json`）。

```
/plugin marketplace add <このリポジトリのパス>
/plugin install guild@guild-local
```

## 使い方

1. 作業するプロジェクトのフォルダで `/guild:init` を実行します。`guild/`（`archive/`、`inputs/`、`deliverables/`、`.work/`、`config.json`、`board.html`）ができます。何度実行しても、依頼や書庫の項目は消えません。`board.html` は最新の版に置き換わります。
2. `guild/board.html` を Chrome か Edge で開き、「フォルダを選ぶ」でプロジェクトのフォルダを選び、依頼を書きます。チャットから出すときは `/guild:quest <依頼文>` です。
3. `/guild:quest` を動かしている間、ギルドマスター（この会話）がボードへの答えを待ちます。ボードの「手紙」に答えると続きが進みます。
4. 全 Todo が済むと「受け取りの確認」の手紙が出ます。受け取ると完了で、納品物（Markdown）が `guild/deliverables/Q###_….md` に残ります。PowerPoint・Excel などが要るときは、Claude Code に渡すプロンプト（`*.prompt.md`）が一緒に出ます。

## コマンド

| コマンド | 内容 |
|---|---|
| `/guild:init` | 現在のフォルダに `guild/` を作り、使える Python を `config.json` に記録する |
| `/guild:quest` | 依頼の分解・実行・判定・納品までを進めるギルドマスター |

## 流れ

1. **依頼**: 依頼主が課題を伝える。
2. **分解**: 地図師が Todo の依存グラフと、各 Todo の種別（`auto`＝自動実行／`human`＝依頼主の実行）・合格基準を作る。曖昧な点は「質問」の手紙で聞く。
3. **承認（1回）**: 計画をボードに出し、依頼主が承認または直す。
4. **実行**: 前提が済んだ Todo から、冒険者（動的ページは斥候）が進める。`human` の Todo はボードで依頼し、結果の入力を待つ。
5. **合否**: 鑑定士が合格基準で判定する。不合格なら実行に戻る。
6. **記録**: 完了・中止後に司書が書庫の候補を挙げ、依頼主が選んだものを登録する。
7. **納品**: 納品物を依頼主に渡す。

Todo の状態は `pending` → `running` → `review` → `done` と進みます（`confirm` 付きは `awaiting_confirm`、`human` は `waiting_user` を挟みます）。定義は `skills/quest/transitions.json` です。

## 役

| 役 | 名前 | モデル | やること |
|---|---|---|---|
| ギルドマスター | `/guild:quest` 本体 | 利用者のモデル | 依頼の受け付け、`guild.py` の実行、役の呼び出し、ボードの答えの待機 |
| 地図師 | `cartographer` | opus | 依頼を Todo に分解し、種別・合格基準を決める |
| 冒険者 | `adventurer` | sonnet | `auto` の Todo を実行し、報告と成果物を書く |
| 斥候 | `scout` | sonnet | ブラウザで動的ページを読む（読むだけ） |
| 鑑定士 | `appraiser` | sonnet | 成果物を合格基準で判定する（成果物は直さない） |
| 司書 | `librarian` | sonnet | 書庫に残す用語などの候補を挙げる（登録はしない） |

## ボード

1ファイルの HTML で、外部通信はしません。タブは「掲示板／クエスト進捗／納品物／書庫／冒険の書／外部サイト／Obsidian／ヘルプ」の8つです。

- **掲示板**: 依頼の入力、「あなたの番」、依頼の一覧、手紙（外部サイトを開く許可の確認を含む）、Todo の道のり
- **クエスト進捗**: 依頼の開始日〜締切のガント（HTML/SVG）、Todo の予定日、あなたの実行（human）の予定日ごとの件数
- **納品物**: 納品物とプロンプト（`*.prompt.md`）の一覧とコピー
- **書庫**: 用語・業務フロー・業務情報・個人・心得の閲覧・検索・登録・編集
- **冒険の書**: 役たちとのやりとりと報告書
- **外部サイト**: 冒険者が開けるサイトの許可リスト（ドメインの追加・削除）
- **ヘルプ**: 処理フローの図、役の説明、使い方、困ったとき

## データの置き場

```
guild/
  config.json     Python のパスなどの設定
  board.html      ボード
  archive/        書庫（用語名.md と index.md。種類は項目の type）
  deliverables/   納品物と、Claude Code に渡すプロンプト（Q001_….md / .prompt.md）
  inputs/         共通のインプット（1つだけ。各依頼はファイル名で参照）
  .work/          作業用（Obsidian に出ない）
    Q001/         依頼ごとのフォルダ（plan.json、reports/、output/、inbox/）
    requests/ web/ archive-inbox/ backup/
```

書庫と納品物は Obsidian の記法で書かれるので、`guild/` を Obsidian の Vault にすると書庫・納品物・インプットが読めます（`.work/` は出ません）。

## 開発

構成:

- `skills/` — `init`、`quest`（`guild.py`、`webaccess.py`、`board.html`、`transitions.json`）
- `agents/` — 各役の定義
- `hooks/` — 冒険者の WebFetch を許可リストで判定するフック（`hooks.json`、`web_gate.py`）
- `docs/` — SPEC と設計メモ（`spec.md`、`roles-spec.md`、`archive-spec.md`、`graph-format.md`、`board-design.md`）
- `tests/` — テスト

テストは次で実行します。

```
python -m unittest tests.test_guild
```

## ライセンス

MIT ライセンスです。詳細は [LICENSE](LICENSE) を参照してください。

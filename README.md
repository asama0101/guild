# guild 0.1

Claude Code のプラグイン。依頼主（非エンジニアの日本語話者）の依頼を、ギルドの仲間（役ごとのサブエージェント）が分担して片付け、成果物（納品物）を納めます。

- 依頼は「クエスト」1 本に統一。**達成条件に分解 → 道のりを決める → 依頼主が承認 → 冒険 → 達成条件をクリア**の順に進みます。
- 状態は `board.json` に 1 か所だけ。遷移は `transitions.json` が決め、`board.py` が検査します。
- 人がすることは、依頼を出す、承認する（道のり・納品物）、聞かれたことに答える、だけです。ほかの質問は、期限が来ると推奨案で進みます。承認は自動で進みません。
- 依頼主に見せる文は、簡易日本語（`docs/style-ja.md`）と図です。

設計書は [`docs/spec-v0.1.md`](docs/spec-v0.1.md)。1.7 以前とは互換がありません（作り直しです）。

## 使い方
1. プラグインを入れる。
2. vault で `/guild:init` を実行する。`guild/` ができる。
3. `guild/board.html` を Edge か Chrome で開き、`guild/` フォルダを選ぶ。
4. 画面の「受付」で依頼を出し、`/guild:quest` を実行する。
5. 画面の先頭の「いま何をするか」に従って、質問に答え、承認する。

| コマンド | 内容 |
|---|---|
| `/guild:init` | `guild/` を作り、画面・`board.py`・`transitions.json` を写す |
| `/guild:quest` | 1 回分を進める |
| `/guild:quest auto` | 確認なしで進める（承認は自動で進まない） |
| `/guild:help` | 使い方と状態の見方 |

Python は標準ライブラリだけ（3.9 以上）。Windows・Mac・Linux で動きます。

## 入れたデータの扱い
入れたデータは、取り扱ってよいものとして扱います。トークン・鍵・パスワードを入れるかどうかは、あなたが決めます。guild は、中身を検査して拒否したり、質問で止めたりしません。

## 役
受付嬢（聞き取り）／占い師（分解）／冒険者（事実の収集）／錬金術師（納品物の中身）／鑑定士（結果の判定）。0.1.0 の範囲です。魔法使い・吟遊詩人・鍛冶師は 0.2・0.3 で入ります。

## 段階
| 版 | 中身 |
|---|---|
| 0.1.0 | 中核の 1 周（`board.py`、`transitions.json`、クエスト票、5 役、承認①②、掟の再発検知、事実と推論の書式、画面 3 タブ） |
| 0.2.0 | 資料室、魔導書、予定表、人物伝、good／bad の活用、`usage`・`calib`・`housekeeping` |
| 0.3.0 | 鍛冶師・設計図、実行の承認、工房、`lint-text`、自動実行 |

## 開発
```
python -m unittest discover -s tests
python skills/quest/board.py --root . gen-transitions --skill skills/quest/SKILL.md --svg skills/quest/references/state-diagram.svg
```
`transitions.json` を直したら、`gen-transitions` で SKILL.md の表と状態図を作り直します（テストが一致を確かめます）。

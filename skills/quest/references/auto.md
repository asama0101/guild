# 自動実行（`/guild:quest auto`）

`auto` は、SKILL.md の流れを、人の確認なしで進める。確認が要る点は質問にして、その点で止まる。

## 決まり
- 承認①②③は自動で進めない。質問を出して、依頼主の答えを待つ。
- 質問に推奨案があれば、期限（既定 3 日）が来るまで待つ。`board.py apply-simple`（`tick` を含む）が、期限後に推奨案で進める。
- 実行の最初に `board.py apply-simple`、次に `board.py need-claude` を呼ぶ。`no` なら、サブエージェントを呼ばずに終わる。
- 1 回の実行で呼ぶサブエージェントは 20 まで（手直しの呼び出しも数える）。超えたらその回を止め、`add-notice` で「作業が多いため、いったん止めました。次の回で続きから進みます。」を出す。
- 進捗のない回が 2 回続いたら、自動実行を止めて知らせる。

## スケジューラ（`guild-run.py`）
`/guild:init` が `guild/.system/auto/` に `guild-run.py` と `allow.txt` を写す。OS のスケジューラから、次の順で動く：`board.py apply-simple` → `board.py need-claude` → `yes` のときだけ `claude -p "/guild:quest auto"`。

- 登録：`python guild-run.py --install --every 60`（Windows は `schtasks`、Mac／Linux は `crontab`）。外す：`--uninstall`。確かめるだけなら `--dry-run`。
- `--model sonnet|opus|haiku` で、使うモデルを選ぶ（既定 sonnet）。
- 許すツールは `allow.txt`（1 行 1 つ、`#` から行末はコメント）。`board.py` を呼ぶための `Bash` は、`python.txt` の Python だけが許される。
- 錠（`run.lock`）で二重起動を防ぐ。成功したら消える。失敗した回は 1 時間残る（無駄な再試行を防ぐ）。1 時間たった錠は古いものとして捨てる。
- 進捗のない回が 2 回続くと、`auto/stopped.json` ができて止まる。原因を直したら `--resume`。
- 実行ごとに `logs/usage.jsonl` に 1 行を残す（書けなくても回は失敗にしない）。90 日より古い行は月ごとの集計（`usage-YYYYMM.json`）になる。実行ログは 30 件まで。

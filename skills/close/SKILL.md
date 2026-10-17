---
name: close
description: guild を閉める。実行中の /guild:quest に「新しい作業を始めず、実行中の作業が終わったら止まる」と伝える。依頼は中止にならない。再開は /guild:quest。業務終了時に使う。「/guild:close」で呼ぶ。
disable-model-invocation: true
---

# /guild:close

業務終了時に、guild を安全に止める。依頼は中止にならず、次に `/guild:quest` を実行すると続きから進む。

## 手順

1. `guild/.work/config.json` を読み、`python` のパスを得る。なければ、`/guild:init` を先に実行するよう伝えて止める。
2. 次を実行する。`<python>` は `config.json` の `python`、`<root>` はプロジェクトのルート（`guild/` の1つ上）。

   ```
   <python> "${CLAUDE_SKILL_DIR}/../quest/guild.py" pause <root>
   ```

   エラー（終了コード 1）は、文をそのまま伝えて止める。
3. 次の3行を伝えて終える。ほかのことはしない。
   - 閉める準備をしました。実行中の作業が終わると、`/guild:quest` が止まります。
   - 依頼は中止していません。
   - 再開は `/guild:quest` です。

"""AI 社員 Phase 3：ファイル画面と整形表示（Markdown・HTML・Mermaid）を、node で実行して確かめる。"""
import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_board_js import extract, node_eval  # noqa: E402

BOARD = (ROOT / "skills" / "quest" / "board.html").read_text(encoding="utf-8")
PRE = r"""
const h = (t, a, ...c) => ({ t, a: a || {}, c: c.flat(Infinity).filter((x) => x != null && x !== false) });
const mermaidBlock = (src) => h('mermaid', null, src);
const HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:";
const text = (n) => (typeof n === 'string' ? n : Array.isArray(n) ? n.map(text).join('') : n.c.map(text).join(''));
const find = (n, t, acc = []) => { if (typeof n === 'string') return acc; if (n.t === t) acc.push(n); n.c.forEach((x) => find(x, t, acc)); return acc; };
"""
FUNCS = ("mdInline", "renderMarkdown", "docKind", "docView", "canOpen")


def run(body):
    src = "".join(extract(n) + "\n" for n in FUNCS)
    src += "const TEXT_EXT = ['md', 'txt', 'csv', 'json', 'html', 'mmd', 'yaml', 'yml', 'xml', 'log', 'tsv'];\n"
    return node_eval(PRE + src + body)


@unittest.skipUnless(shutil.which("node"), "node がありません")
class MarkdownTest(unittest.TestCase):
    def md(self, src):
        return run("console.log(JSON.stringify(renderMarkdown(" + json.dumps(src, ensure_ascii=False) + ")));")

    def tags(self, src):
        return [n["t"] for n in self.md(src)]

    def test_headings_are_shifted_down_by_one_level(self):
        nodes = self.md("# 大\n## 中\n###### 小")
        self.assertEqual([n["t"] for n in nodes], ["h2", "h3", "h6"])

    def test_front_matter_is_dropped(self):
        nodes = self.md("---\nname: x\n---\n本文")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["t"], "p")

    def test_inline_marks(self):
        nodes = self.md("**太** と *斜* と `コード` と [[リンク|表示]]")
        kinds = [c["t"] for c in nodes[0]["c"] if isinstance(c, dict)]
        self.assertEqual(kinds, ["strong", "em", "code", "span"])
        self.assertEqual(nodes[0]["c"][-1]["c"], ["表示"])

    def test_only_http_links_become_anchors(self):
        nodes = self.md("[良い](https://example.com/a) と [悪い](javascript:alert(1)) と [相対](x.md)")
        anchors = [c for c in nodes[0]["c"] if isinstance(c, dict) and c["t"] == "a"]
        self.assertEqual([a["a"]["href"] for a in anchors], ["https://example.com/a"])
        self.assertEqual(anchors[0]["a"]["rel"], "noopener noreferrer")
        flat = "".join(c if isinstance(c, str) else "".join(x for x in c["c"] if isinstance(x, str)) for c in nodes[0]["c"])
        self.assertIn("悪い", flat)
        self.assertIn("相対", flat)

    def test_html_in_the_text_stays_text(self):
        nodes = self.md("<script>alert(1)</script> と <img src=x onerror=alert(2)>")
        self.assertEqual(nodes[0]["t"], "p")
        self.assertEqual(nodes[0]["c"], ["<script>alert(1)</script> と <img src=x onerror=alert(2)>"])

    def test_tables(self):
        nodes = self.md("| 項目 | 値 |\n|---|---|\n| 売上 | 100 |\n| 利益 | 20 |")
        self.assertEqual(nodes[0]["t"], "table")
        body = [c for c in nodes[0]["c"] if c["t"] == "tbody"][0]
        self.assertEqual(len(body["c"]), 2)

    def test_a_pipe_line_without_a_separator_is_a_paragraph(self):
        self.assertEqual(self.tags("| a | b |\n| c | d |"), ["p"])

    def test_lists_with_nesting_and_numbers(self):
        nodes = self.md("- あ\n- い\n  - い1\n  - い2\n- う\n\n1. 一\n2. 二")
        self.assertEqual([n["t"] for n in nodes], ["ul", "ol"])
        items = nodes[0]["c"]
        self.assertEqual(len(items), 3)
        self.assertEqual([c["t"] for c in items[1]["c"] if isinstance(c, dict)], ["ul"])

    def test_code_fence_keeps_text_and_mermaid_goes_to_the_diagram_block(self):
        nodes = self.md("```python\nprint(1)\n<b>x</b>\n```\n\n```mermaid\ngraph TD; A-->B\n```")
        self.assertEqual([n["t"] for n in nodes], ["pre", "mermaid"])
        self.assertEqual(nodes[0]["c"], ["print(1)\n<b>x</b>"])
        self.assertEqual(nodes[1]["c"], ["graph TD; A-->B"])

    def test_unterminated_fence_does_not_hang(self):
        self.assertEqual(self.tags("```\nabc"), ["pre"])

    def test_quote_callout_and_rule(self):
        nodes = self.md("> 引用\n\n> [!note] 注意\n> 中身\n\n---\n")
        self.assertEqual([n["t"] for n in nodes], ["blockquote", "div", "hr"])
        self.assertEqual(nodes[1]["a"]["class"], "md-callout")

    def test_paragraph_stops_before_a_block_and_joins_lines(self):
        nodes = self.md("一行目\n二行目\n- 箇条書き")
        self.assertEqual([n["t"] for n in nodes], ["p", "ul"])
        self.assertEqual(nodes[0]["c"], ["一行目 二行目"])

    def test_empty_and_null_input(self):
        self.assertEqual(self.md(""), [])
        self.assertEqual(run("console.log(JSON.stringify(renderMarkdown(null)));"), [])

    def test_crlf_input(self):
        self.assertEqual([n["t"] for n in self.md("# 見出し\r\n\r\n本文\r\n")], ["h2", "p"])


@unittest.skipUnless(shutil.which("node"), "node がありません")
class DocViewTest(unittest.TestCase):
    def test_doc_kind_and_can_open(self):
        out = run("console.log(JSON.stringify(['a.md', 'B.HTML', 'c.mmd', 'd.xlsx', 'e', 'f.prompt.md'].map((p) => [docKind(p), canOpen(p)])));")
        self.assertEqual(out, [["md", True], ["html", True], ["mmd", True], ["xlsx", False], ["", False], ["md", True]])

    def test_views_by_kind(self):
        out = run("""
const k = (p, t, s) => { const n = docView(p, t, s); return [n.t, n.c.map((x) => x.t || 'text').join(',')]; };
console.log(JSON.stringify([k('a.md', '# x'), k('a.md', '# x', true), k('a.txt', 'x'), k('a.mmd', 'graph TD'), k('a.html', '<p>x</p>')]));""")
        self.assertEqual(out[0], ["div", "h2"])
        self.assertEqual(out[1], ["pre", "text"])
        self.assertEqual(out[2], ["pre", "text"])
        self.assertEqual(out[3], ["div", "mermaid"])
        self.assertEqual(out[4], ["div", "p,iframe"])

    def test_html_is_shown_in_a_sandbox_without_permissions(self):
        out = run("""
const n = docView('a.html', '<script>alert(1)</script>');
const f = find(n, 'iframe')[0];
console.log(JSON.stringify({ sandbox: f.a.sandbox, srcdoc: f.a.srcdoc, csp: f.a.csp }));""")
        self.assertEqual(out["sandbox"], "")  # すべての許可なし（スクリプト・同一オリジンなし）
        self.assertIn("<script>", out["srcdoc"])
        self.assertTrue(out["srcdoc"].startswith('<meta http-equiv="Content-Security-Policy" content="default-src \'none\''))  # 外部へ通信させない
        self.assertIn("default-src 'none'", out["csp"])


@unittest.skipUnless(shutil.which("node"), "node がありません")
class FilesModelTest(unittest.TestCase):
    def model(self, m):
        src = extract("filesModel") + "\n"
        pre = "const h = () => null;\n"
        return node_eval(pre + src + "console.log(JSON.stringify(filesModel(" + json.dumps(m, ensure_ascii=False) + ")));")

    def sample(self):
        return {
            "inputs": [{"name": "notes.txt"}, {"name": "KGI定義.md"}, {"name": "未使用.csv"}],
            "archive": [{"path": "KPI.md", "name": "KPI"}],
            "quests": [
                {"id": "Q001", "title": "週報の作成", "label": "完了", "q": {"plan": {"series": "週報", "inputs": [{"name": "NOTES.txt"}, {"name": "ない.md"}]},
                                                                        "published": ["Q001_週報の作成.md"], "output": ["Q001/output/G1/a.md"], "reports": ["G1-wizard.md"]}},
                {"id": "Q002", "title": "分解中", "label": "分解中", "q": {"plan": None, "published": [], "output": [], "reports": []}}]}

    def test_quest_groups_and_used_inputs(self):
        r = self.model(self.sample())
        q1 = r["quests"][0]
        self.assertEqual(q1["series"], "週報")
        groups = dict((k, fs) for k, fs in q1["groups"])
        self.assertEqual(groups["納品物"], ["deliverables/Q001_週報の作成.md"])
        self.assertEqual(groups["成果物"], ["Q001/output/G1/a.md"])
        self.assertEqual(groups["報告"], ["Q001/reports/G1-wizard.md"])
        self.assertEqual(groups["使ったインプット"], ["inputs/notes.txt"])  # 大文字小文字は区別せず、実在するものだけ
        self.assertEqual(r["quests"][1]["groups"], [])

    def test_kinds_include_archive_and_inputs_with_users(self):
        r = self.model(self.sample())
        kinds = dict(r["kinds"])
        self.assertEqual([f["path"] for f in kinds["書庫"]], ["archive/KPI.md"])
        inputs = {f["label"]: f["by"] for f in kinds["インプット"]}
        self.assertEqual(inputs, {"notes.txt": "Q001", "KGI定義.md": "", "未使用.csv": ""})
        self.assertEqual([f["by"] for f in kinds["納品物"]], ["Q001"])


class WiringTest(unittest.TestCase):
    def test_tab_reader_and_deliverable_filter_are_wired(self):
        for needle in ("deliv: delivTab", "FKINDS", "docView(S.reader.path, S.reader.text, S.reader.source)", "ソースで見る",
                       r"/\.(md|html|mmd)$/i.test(x.name)", "securityLevel: 'strict'", "mermaid@10.9.1", "sandbox: ''", "s.integrity = MERMAID_SRI", "s.crossOrigin = 'anonymous'",
                       "function cleanSvg(root)", "foreignObject", "const HTML_CSP"):
            self.assertIn(needle, BOARD, needle)
        self.assertNotIn("filesTab", BOARD)
        self.assertNotIn("['files', 'ファイル']", BOARD)

    def test_no_inner_html_is_used_for_documents(self):
        i, j = BOARD.index("function mdInline("), BOARD.index("function reader() {")
        self.assertNotIn("innerHTML", BOARD[i:j])


if __name__ == "__main__":
    unittest.main()

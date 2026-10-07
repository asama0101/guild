"""静的な検査（SPEC 17 節）：画面のタブ、エスケープ、JS 構文、SKILL.md の長さ、節名、旧語、エージェント定義。"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import constants as C  # noqa: E402

HTML = ROOT / "skills" / "init" / "board.html"
AGENTS = sorted((ROOT / "agents").glob("*.md"))
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))

# spec 表の役ごとのツール（0.1.0 の 5 役）
AGENT_TOOLS = {
    "receptionist": {"Read", "Glob", "Grep", "Write"},
    "fortune-teller": {"Read", "Glob", "Grep", "Write"},
    "adventurer": {"Read", "Glob", "Grep", "Write", "WebSearch", "WebFetch"},
    "alchemist": {"Read", "Glob", "Grep", "Write", "Edit"},
    "appraiser": {"Read", "Glob", "Grep", "Write", "Bash"},
}


def front(path):
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} に frontmatter がありません"
    meta = {}
    for ln in m.group(1).splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


class TestSkills(unittest.TestCase):
    def test_SKILL_mdは500行以下(self):
        for p in SKILLS:
            n = len(p.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(n, C.SKILL_MAX_LINES, f"{p} は {n} 行")

    def test_quest_SKILL_mdは目標の300行以下(self):
        n = len((ROOT / "skills" / "quest" / "SKILL.md").read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(n, C.SKILL_TARGET_LINES)

    def test_frontmatter(self):
        names = set()
        for p in SKILLS:
            meta, _ = front(p)
            self.assertEqual(meta["name"], p.parent.name)
            self.assertTrue(meta["description"])
            names.add(meta["name"])
        self.assertEqual(names, {"init", "quest", "help"})

    def test_referencesの参照先がある(self):
        text = (ROOT / "skills" / "quest" / "SKILL.md").read_text(encoding="utf-8")
        for m in re.finditer(r"`(references/[\w.\-]+)`", text):
            self.assertTrue((ROOT / "skills" / "quest" / m.group(1)).exists(), m.group(1))
        for m in re.finditer(r"`([\w\-]+\.md)`", text.split("## references/")[-1]):
            self.assertTrue((ROOT / "skills" / "quest" / "references" / m.group(1)).exists(), m.group(1))

    def test_plugin_jsonの版は0_1_0(self):
        for f in ("plugin.json", "marketplace.json"):
            self.assertIn('"version": "0.1.0"', (ROOT / ".claude-plugin" / f).read_text(encoding="utf-8"))

    def test_subagent_typeの名前はエージェントと一致する(self):
        text = (ROOT / "skills" / "quest" / "SKILL.md").read_text(encoding="utf-8")
        used = set(re.findall(r"`guild:([\w\-]+)`", text))
        self.assertEqual(used, {front(p)[0]["name"] for p in AGENTS})


class TestAgents(unittest.TestCase):
    def test_5役がそろっている(self):
        self.assertEqual({front(p)[0]["name"] for p in AGENTS}, set(AGENT_TOOLS))

    def test_ツールは最小(self):
        for p in AGENTS:
            meta, _ = front(p)
            tools = {t.strip() for t in meta["tools"].split(",")}
            self.assertEqual(tools, AGENT_TOOLS[meta["name"]], p.name)

    def test_既定のモデルはsonnet(self):
        for p in AGENTS:
            self.assertEqual(front(p)[0]["model"], "sonnet", p.name)

    def test_報告書の節名は固定(self):
        allowed = set(C.REPORT_SECTIONS) | set(C.DELIVERABLE_SECTIONS)
        for p in AGENTS:
            body = front(p)[1]
            for m in re.finditer(r"^## (.+?)\s*$", body, re.M):
                name = m.group(1)
                if name in allowed:
                    continue
                # エージェント文書自身の見出し（守ること・手順・報告書の書式・納品物の書式）は除く
                self.assertIn(name, {"守ること", "手順", "報告書の書式（節の名前は固定）", "納品物の書式（節の名前は固定）"}, f"{p.name}: ## {name}")

    def test_サブエージェントは対話できないと書いてある(self):
        for p in AGENTS:
            self.assertIn("対話できません", front(p)[1], p.name)

    def test_入力データは検査しないと書いてある(self):
        for p in AGENTS:
            if front(p)[0]["name"] in ("receptionist", "adventurer", "alchemist"):
                self.assertIn("取り扱ってよいもの", front(p)[1], p.name)


class TestOldWords(unittest.TestCase):
    def test_旧語が残っていない(self):
        targets = list(AGENTS) + list(SKILLS) + list((ROOT / "skills" / "quest" / "references").glob("*.md")) + [HTML]
        targets += [ROOT / "skills" / "quest" / "board.py"]
        readme = ROOT / "README.md"
        if readme.exists():
            targets.append(readme)
        for p in targets:
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8")
            for w in C.OLD_WORDS:
                self.assertNotIn(w, text, f"{p.name} に旧語「{w}」")


@unittest.skipUnless(HTML.exists(), "board.html がまだない")
class TestBoardHtml(unittest.TestCase):
    def setUp(self):
        self.text = HTML.read_text(encoding="utf-8")

    def scripts(self):
        return re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", self.text, re.S)

    def test_CDNなし(self):
        self.assertIsNone(re.search(r"<script[^>]+src=|<link[^>]+href=\"https?:", self.text))
        self.assertIsNone(re.search(r"(src|href)=\"https?://", self.text))

    def test_タブは3つで定数と一致する(self):
        tabs = re.findall(r'role="tab"[^>]*>\s*([^<]+?)\s*(?:<|$)', self.text)
        names = [re.sub(r"\s+", "", t) for t in tabs]
        self.assertEqual(names, C.TABS_0_1)
        self.assertEqual(len(re.findall(r'role="tabpanel"', self.text)), len(C.TABS_0_1))

    def test_状態名とラベルが定数と一致する(self):
        for k, v in list(C.QUEST_LABELS.items()) + list(C.GOAL_LABELS.items()):
            self.assertIn(k, self.text)
            self.assertIn(v, self.text)

    def test_値をエスケープして描く(self):
        js = "\n".join(self.scripts())
        self.assertRegex(js, r"function\s+esc\w*\s*\(|const\s+esc\w*\s*=")
        inner = re.findall(r"\.innerHTML\s*[+]?=\s*([^;\n]+)", js)
        for expr in inner:
            # innerHTML への代入は、空文字・エスケープ関数・定数だけ
            self.assertRegex(expr.strip(), r"^(''|\"\"|``|esc\w*\(|sanitize\w*\(|\w*[Ss]afe\w*)", f"未エスケープの疑い: {expr}")

    def test_boardjsonを書かない(self):
        js = "\n".join(self.scripts())
        self.assertNotRegex(js, r"getFileHandle\(\s*['\"]board\.json['\"]\s*,\s*\{\s*create")
        self.assertIn("answers", js)
        self.assertIn("requests", js)

    def test_ボタンはbutton要素(self):
        self.assertIsNone(re.search(r"<div[^>]+onclick=", self.text))

    def test_ダークモードとviewport(self):
        self.assertIn("prefers-color-scheme", self.text)
        self.assertIn('name="viewport"', self.text)
        self.assertIn('lang="ja"', self.text)

    def test_JSの構文(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node がない")
        with tempfile.TemporaryDirectory() as d:
            for i, js in enumerate(self.scripts()):
                f = Path(d) / f"s{i}.js"
                f.write_text(js, encoding="utf-8")
                r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()

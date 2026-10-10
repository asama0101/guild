"""期待文字列（状態名・節名・タブ名・述語 ID など）を 1 か所に集約する（SPEC 17 節）。

テストはここを正として、board.py・transitions.json・SKILL.md・board.html と突き合わせる。
"""

QUEST_STATES = ["受付", "分解中", "承認待ち", "進行中", "最終鑑定", "達成", "失敗", "中止", "保留"]
GOAL_STATES = ["案", "待機", "冒険中", "鑑定中", "要手直し", "確認待ち", "実行承認待ち", "達成", "失敗", "中止"]
QUEST_TERMINAL = ["達成", "失敗", "中止"]
GOAL_TERMINAL = ["達成", "中止"]

# 5.1 / 5.2 の「画面での言い方」
QUEST_LABELS = {
    "受付": "聞き取り中", "分解中": "計画を作っている", "承認待ち": "あなたの承認を待っている",
    "進行中": "進めている", "最終鑑定": "全体を確かめている", "達成": "達成",
    "失敗": "達成できなかった", "中止": "中止", "保留": "止めている",
}
GOAL_LABELS = {
    "案": "計画の案", "待機": "順番を待っている", "冒険中": "冒険者が作業している",
    "鑑定中": "鑑定士が確かめている", "要手直し": "直している", "確認待ち": "あなたの確認を待っている",
    "実行承認待ち": "あなたの実行の承認を待っている", "達成": "達成", "失敗": "達成できなかった", "中止": "中止",
}

ACTORS = ["guildmaster", "client", "workshop", "receptionist", "fortune_teller", "adventurer",
          "alchemist", "smith", "appraiser", "wizard", "bard"]
# transitions.json にだけ現れる内部の役（放置の期限による保留）
INTERNAL_ACTORS = ["tick"]

GUARD_IDS = [
    "no_open_questions", "has_goals", "acyclic", "all_have_done_when", "approval_recorded",
    "replans_lt_limit", "all_goals_done", "cross_check_clean", "cross_check_suspect",
    "dependents_confirmed", "deps_done", "slot_free", "no_overlap", "output_present",
    "report_present", "precheck_ok", "retries_lt_limit", "done_when_met", "needs_execute",
    "fix_kind_goal",
]
# SPEC の表に述語 ID が書かれていない辺のために、実装で足した述語
EXTRA_GUARD_IDS = ["route_approved", "quest_replanning", "quest_final_review", "was_before_hold",
                   "finding_recorded", "not_needs_execute"]

WRITES_VALUES = ["board", "reports", "output", "quest_md", "adventure_log", "spellbook", "shared",
                 "profile", "rules", "templates", "inputs", "lessons"]

# 7.6 権限：役ごとに書ける場所（board は board.py 経由）
ROLE_WRITES = {
    "guildmaster": ["board", "quest_md", "adventure_log", "lessons", "rules"],
    "client": ["board", "shared", "inputs", "templates", "profile"],
    "workshop": ["board", "output", "inputs", "reports"],
    "receptionist": ["board", "reports"],
    "fortune_teller": ["board", "reports"],
    "adventurer": ["board", "reports"],
    "alchemist": ["board", "output"],
    "smith": ["board", "output"],
    "appraiser": ["board", "reports"],
    "wizard": ["board", "spellbook"],
    "bard": ["board", "reports"],
    "tick": ["board"],
}

REPORT_SECTIONS = ["聞き取りの問い", "達成条件案", "依頼主への質問", "ギルド員への答え", "result",
                   "依頼主への報告", "止まっていること", "log", "用語", "fix_kind", "基準ごとの判定"]
DELIVERABLE_SECTIONS = ["事実", "推論", "依頼主の指定", "未確認"]
FIX_KINDS = ["input", "brief", "goal"]
POINT_CODES = ["欠落", "矛盾", "誤り", "形式", "出典なし", "範囲外"]

# 画面のタブ（受付はクエストに、予定表はクエスト票に統合した）
TABS = ["使い方", "クエスト", "質問", "資料室・設計図・魔導書"]
TABS_0_2 = TABS
REQUEST_FORMS = ["おまかせ", "回答だけ", "ノート", "テキスト", "Word", "Excel", "PowerPoint", "PDF", "その他"]
# 納品物の形の説明（画面の選択欄の下に出す。依頼主向けの文）
FORM_HELP = {
    "おまかせ": "内容を見て、ギルドが形を選びます。",
    "回答だけ": "調べて答えるだけ。結論を先に、短く書きます。",
    "ノート": "魔導書やノートに残す形。見出しとリンクを付けます。",
    "テキスト": "そのまま貼って使える文章。見出しや表は使いません。",
    "Word": "Word のファイルを作ります。",
    "Excel": "表計算のファイルを作ります。",
    "PowerPoint": "スライドのファイルを作ります。",
    "PDF": "PDF のファイルを作ります。",
    "その他": "くわしくに、ほしい形を書いてください。",
}

# 旧語（0.1 の文書・コード・画面に残してはいけない）
OLD_WORDS = ["研究", "資料庫", "知識帳", "用語集", "人物帳", "chest", "規約", "ルート"]

SKILL_MAX_LINES = 500
SKILL_TARGET_LINES = 300

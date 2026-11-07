"""有料APIだった場合の費用の目安に使う料金（100万トークンあたりのドル）。

料金は変わるので、確認した日と出典を必ず残す。卒論に載せるときも、この日付を書く。
"""

# (入力, 出力) ドル / 100万トークン
PRICES = {
    # 出典: https://aistudio.google.com/docs/pricing （Paid tier・Standard、2026-11-06 に確認。出力は思考トークンを含む）
    "gemini-3.5-flash-lite（有料）": (0.30, 2.50),
    "gemini-3.8-flash（有料、2026年中の料金）": (0.75, 3.75),
    # 出典: Anthropic の料金表（Claude API、2026-10-06 時点の一覧で確認）
    "Claude Haiku 5.5": (0.10, 0.50),
    "Claude Sonnet 5.5": (2.00, 10.00),
    "Claude Opus 5.5": (4.00, 20.00),
}
PRICES_CHECKED = "2026-11-06"

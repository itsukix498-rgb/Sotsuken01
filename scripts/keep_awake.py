"""公開アプリ（Streamlit Community Cloud）を休止させないための見回りスクリプト。

Streamlit Community Cloud のアプリは、12時間アクセスがないと休止し、
「Yes, get this app back up!」ボタンを押すまで起動しない。
GitHub Actions から定期的にこのスクリプトを動かし、本物のブラウザ（Chromium）でアプリを開く。
休止していたらボタンを押して起こし、アプリの画面が出るまで待つ。

使い方（GitHub Actions 上で自動実行。手元で試すときは）:
    pip install playwright
    python -m playwright install chromium
    python scripts/keep_awake.py
"""

from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

APP_URL = os.environ.get("APP_URL", "https://sotsuken01.streamlit.app/")
# アプリが動いていると、どれかの画面にこの文字のどれかが出る
#   合言葉の画面 → 「Paper Data Finder」 / 合言葉を設定していない場合 → 「論文を検索」
APP_MARKERS = ("Paper Data Finder", "論文を検索")
WAKE_BUTTON = re.compile(r"get this app back up", re.IGNORECASE)
WAIT_FOR_APP_SECONDS = 5 * 60  # 休止から起こすと起動に数分かかる


def app_is_showing(page) -> bool:
    """アプリの画面が表示されているか（Streamlit のアプリは iframe の中に表示される）。"""
    for frame in page.frames:
        try:
            text = frame.locator("body").inner_text(timeout=2_000)
        except Exception:  # 読み込み途中の iframe などは読めないことがある
            continue
        if any(marker in text for marker in APP_MARKERS):
            return True
    return False


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        print(f"開く: {APP_URL}")
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=120_000)

        # 休止中なら「Yes, get this app back up!」ボタンが出るので押す
        button = page.get_by_role("button", name=WAKE_BUTTON)
        try:
            button.wait_for(state="visible", timeout=20_000)
            print("休止していたので、起動ボタンを押します")
            button.click()
        except PlaywrightTimeout:
            print("休止の画面は出ませんでした（起動中）")

        # アプリの画面が出るまで待つ
        deadline = time.monotonic() + WAIT_FOR_APP_SECONDS
        while time.monotonic() < deadline:
            if app_is_showing(page):
                print("アプリの表示を確認しました")
                browser.close()
                return 0
            time.sleep(10)

        print("時間内にアプリの表示を確認できませんでした", file=sys.stderr)
        browser.close()
        return 1  # 失敗すると GitHub Actions が失敗扱いになり、リポジトリの持ち主にメールが届く


if __name__ == "__main__":
    sys.exit(main())

"""OpenAlex で、DOI からオープンアクセスのPDFの場所を探す（Semantic Scholar で見つからないときの補い）。

OpenAlex は無料・APIキー不要。結果は data/cache/openalex/ に保存し、同じ問い合わせを繰り返さない。
送るのは DOI だけ。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

USER_AGENT = "paper-data-finder/0.1 (graduation research prototype)"


def oa_pdf_urls(doi: str, cache_dir: str | Path = "data/cache/openalex", session: requests.Session | None = None,
                wait=time.sleep) -> list[str]:
    """DOI の論文について、OpenAlex が知っているPDFのURLを、良さそうな順に返す（なければ空）。"""
    if not doi:
        return []
    cache = Path(cache_dir) / f"{hashlib.sha256(doi.encode('utf-8')).hexdigest()[:32]}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    session = session or requests.Session()
    urls: list[str] = []
    try:
        r = session.get(f"https://api.openalex.org/works/doi:{doi}",
                        params={"select": "best_oa_location,locations"},
                        headers={"User-Agent": USER_AGENT}, timeout=(10, 30))
        if r.status_code == 200:
            work = r.json()
            locations = [work.get("best_oa_location") or {}] + (work.get("locations") or [])
            for loc in locations:
                url = (loc or {}).get("pdf_url")
                if url and url not in urls:
                    urls.append(url)
        elif r.status_code != 404:
            return []  # 一時的なエラーはキャッシュしない
    except requests.RequestException:
        return []
    finally:
        wait(0.2)  # OpenAlex の上限（1秒10回）より十分ゆっくり
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(urls), encoding="utf-8")
    return urls

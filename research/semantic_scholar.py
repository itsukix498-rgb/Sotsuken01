"""Semantic Scholar Academic Graph API で論文を特定するクライアント。

使うエンドポイント（API仕様書 https://api.semanticscholar.org/graph/v1/swagger.json で確認）
    POST /graph/v1/paper/batch        … 最大500件のIDをまとめて問い合わせ（DOIは "DOI:10.xxx" の形）
    GET  /graph/v1/paper/search/match … タイトルに一番近い1件を返す（見つからなければ 404）

守ること
    ・APIキーは環境変数 SEMANTIC_SCHOLAR_API_KEY（.env）から読み、ヘッダー x-api-key に付ける
    ・リクエストの間は1秒以上あける（キーありの上限は1秒1回）
    ・429（回数超過）や 5xx のときは、待ってから再試行する
    ・一度取得した結果は data/cache/semantic_scholar/ に保存し、同じリクエストを送らない
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

API_BASE = "https://api.semanticscholar.org/graph/v1"
USER_AGENT = "paper-data-finder/0.1 (graduation research prototype)"
# 取得する項目（textAvailability は、S2ORC に本文があるかどうかの目安）
PAPER_FIELDS = "paperId,corpusId,title,year,venue,externalIds,isOpenAccess,openAccessPdf,textAvailability"
BATCH_SIZE = 500  # API の上限


class SemanticScholarError(Exception):
    """API の呼び出しに失敗したときの例外（再試行しても回復しなかった場合）。"""


class SemanticScholarClient:
    def __init__(self, api_key: str | None = None, cache_dir: str | Path = "data/cache/semantic_scholar",
                 min_interval: float = 1.1, max_retries: int = 6, session: requests.Session | None = None,
                 sleep=time.sleep):
        self.api_key = api_key if api_key is not None else os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key
        self._sleep = sleep  # テストでは待たないものに差し替える
        self._last_request = 0.0
        self.requests_sent = 0  # 実際にAPIへ送った回数（キャッシュから返したものは数えない）

    # --- キャッシュ ---------------------------------------------------------------

    def _cache_path(self, kind: str, key: str) -> Path:
        digest = hashlib.sha256(f"{kind}|{key}|{PAPER_FIELDS}".encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / kind / f"{digest}.json"

    def _cache_get(self, kind: str, key: str):
        path = self._cache_path(kind, key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["value"]
        raise KeyError(key)

    def _cache_put(self, kind: str, key: str, value) -> None:
        path = self._cache_path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "value": value}, ensure_ascii=False), encoding="utf-8")

    # --- 通信 ---------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """1秒以上の間隔をあけて送り、429・5xx・通信エラーは待ってから再試行する。"""
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            self._last_request = time.monotonic()
            self.requests_sent += 1
            try:
                r = self.session.request(method, f"{API_BASE}{path}", timeout=(10, 60), **kwargs)
            except requests.RequestException as e:
                error = f"通信エラー: {e}"
            else:
                if r.status_code in (429,) or r.status_code >= 500:
                    error = f"HTTP {r.status_code}"
                    retry_after = r.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        self._sleep(int(retry_after))
                        continue
                else:
                    return r
            if attempt < self.max_retries:
                self._sleep(min(2 ** attempt * 2, 60))  # 2, 4, 8, 16, 32, 60 秒
        raise SemanticScholarError(f"Semantic Scholar への問い合わせに失敗しました（{error}）")

    # --- 公開する関数 -------------------------------------------------------------

    def get_papers(self, ids: list[str]) -> dict[str, dict | None]:
        """ID（"DOI:10.xxx" など）のリストから論文情報を取る。見つからないIDの値は None。"""
        result: dict[str, dict | None] = {}
        missing = []
        for pid in ids:
            try:
                result[pid] = self._cache_get("paper", pid)
            except KeyError:
                missing.append(pid)
        for i in range(0, len(missing), BATCH_SIZE):
            chunk = missing[i:i + BATCH_SIZE]
            r = self._request("POST", "/paper/batch", params={"fields": PAPER_FIELDS}, json={"ids": chunk})
            if r.status_code == 400 and "No valid paper ids" in r.text:
                # 送ったIDがどれも Semantic Scholar に登録されていない（例: Zenodo のDOIだけ）。全部「見つからない」とする
                for pid in chunk:
                    self._cache_put("paper", pid, None)
                    result[pid] = None
                continue
            if r.status_code != 200:
                raise SemanticScholarError(f"batch の呼び出しに失敗しました（HTTP {r.status_code}: {r.text[:200]}）")
            # 返ってくるリストは送ったIDと同じ順番。見つからないIDは null になる
            for pid, paper in zip(chunk, r.json()):
                self._cache_put("paper", pid, paper)
                result[pid] = paper
        return result

    def match_title(self, title: str) -> dict | None:
        """タイトルに一番近い論文を1件返す（matchScore 付き）。見つからなければ None。"""
        key = " ".join(title.split()).lower()
        try:
            return self._cache_get("match", key)
        except KeyError:
            pass
        r = self._request("GET", "/paper/search/match", params={"query": title, "fields": PAPER_FIELDS})
        if r.status_code == 404:
            paper = None
        elif r.status_code == 200:
            data = r.json().get("data") or []
            paper = data[0] if data else None
        else:
            raise SemanticScholarError(f"タイトル検索に失敗しました（HTTP {r.status_code}: {r.text[:200]}）")
        self._cache_put("match", key, paper)
        return paper

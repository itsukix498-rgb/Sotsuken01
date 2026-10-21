"""国際会議（LAK・EDM・AIED）と国内の学会誌（J-STAGE）の論文一覧を公開APIから集め、PDFを取得するモジュール。

使うAPI（いずれも無料・APIキー不要で、プログラムからの利用が認められているもの）:
    - Crossref  … LAK（ACM）と AIED（Springer）の論文一覧
    - Zenodo    … EDM（2023年以降。論文がZenodoのコミュニティで公開されている）
    - OpenAlex  … 無料で読めるPDFの場所（オープンアクセス情報）の補完
    - J-STAGE WebAPI … 日本語の学会誌・大会論文集の論文一覧（非商用利用は申請不要。
      画面に「Powered by J-STAGE」の表示が必要。PDFの機械的な大量ダウンロードは
      利用規約で禁止されているため、1回の取得本数を少なくし、間隔も長めにとる）

Google Scholar や DBLP はボット対策があり自動収集が認められていないため使わない。
PDFの取得も、出版社がボット対策をしている場合（ACMなど）は無理に取らず「手動」とする。
"""

from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

import requests

USER_AGENT = "paper-data-finder/0.1 (graduation research prototype)"
TIMEOUT = (10, 30)  # （接続, 読み込み）秒
MAX_PDF_BYTES = 40 * 1024 * 1024

CONFERENCES = {
    "LAK": "Learning Analytics and Knowledge（ACM）",
    "EDM": "Educational Data Mining",
    "AIED": "Artificial Intelligence in Education（Springer）",
}

# J-STAGE で公開されている国内の学会誌・大会論文集
#   キー: 画面に出す短い名前（スマホでもボタンが画面に収まるように、学会の略称を使う）
#   material: J-STAGE の資料名（検索に使う） / cdjournal: J-STAGE の資料コード（結果の確認に使う）
JSTAGE_JOURNALS = {
    "JSET論文誌": {"material": "日本教育工学会論文誌", "cdjournal": "jjet"},
    "JSiSE学会誌": {"material": "教育システム情報学会誌", "cdjournal": "jsise"},
    "JSET研究報告": {"material": "日本教育工学会研究報告集", "cdjournal": "jsetstudy"},
    "JSAI全国大会": {"material": "人工知能学会全国大会論文集", "cdjournal": "pjsai"},
}

# 会議・学会誌ごとに一覧を取得できる年の範囲
YEAR_RANGES = {
    "LAK": (2011, 2026),
    "EDM": (2023, 2026),  # Zenodoのコミュニティ（edm2023〜）がある年のみ
    "AIED": (2015, 2026),
    **{name: (2000, 2026) for name in JSTAGE_JOURNALS},
}

# J-STAGEのPDF取得は利用規約（大量ダウンロードの禁止）に配慮して、少なめ・ゆっくりにする
JSTAGE_MAX_BATCH = 10
JSTAGE_INTERVAL = 3.0  # 秒

# PDFの取得可否
PDF_AUTO = "自動取得できる"
PDF_MANUAL = "手動でダウンロード"


@dataclass
class Paper:
    """論文1本分の情報。"""

    conference: str
    year: int
    title: str
    authors: list[str] = field(default_factory=list)
    doi: str = ""
    landing_url: str = ""  # 論文のページ（人がブラウザで開く用）
    pdf_url: str = ""  # 自動で取得できるPDFのURL（なければ空）
    title_en: str = ""  # 日本語論文の英語タイトル（キーワード検索に使う）

    @property
    def pdf_status(self) -> str:
        return PDF_AUTO if self.pdf_url else PDF_MANUAL

    def to_row(self) -> dict:
        row = asdict(self)
        row["authors"] = "; ".join(self.authors)
        row["pdf_status"] = self.pdf_status
        return row


class CollectError(Exception):
    """APIの呼び出しに失敗したときの例外（メッセージは利用者に表示する）。"""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _get_json(session: requests.Session, url: str, params: dict | None = None) -> dict:
    try:
        r = session.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise CollectError(f"論文データベースへの接続に失敗しました（{url}）: {e}") from e
    except ValueError as e:
        raise CollectError(f"論文データベースから想定外の応答が返りました（{url}）") from e


def clean_title(title: str) -> str:
    """タイトル中のHTMLエンティティやタグ（<i>など）、余分な空白を取り除く。"""
    title = re.sub(r"<[^>]+>", "", html.unescape(html.unescape(title)))
    return re.sub(r"\s+", " ", title).strip()


# ---------------------------------------------------------------------------
# 会議ごとの一覧取得
# ---------------------------------------------------------------------------

# Crossref の container-title（論文集の名前）で会議を見分ける
_LAK_CONTAINER = re.compile(r"Learning Analytics (?:and|&|&amp;) Knowledge", re.IGNORECASE)
_AIED_CONTAINER = re.compile(r"^Artificial Intelligence in Education\b", re.IGNORECASE)


def _crossref_authors(item: dict) -> list[str]:
    names = []
    for a in item.get("author", []):
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name", "")
        if name:
            names.append(name)
    return names


def _crossref_papers(session, conference: str, year: int, query: str, extra_filter: str, containers_ok) -> list[Paper]:
    """Crossref から会議の論文集の論文を集める。

    Crossref には「この論文集の論文をすべて」という検索がないので、論文集の名前で検索し、
    名前が会議と一致するものだけを残す（関連度順の上位1000件を対象にする）。
    """
    data = _get_json(session, "https://api.crossref.org/works", {
        "query.container-title": query,
        "filter": f"from-pub-date:{year},until-pub-date:{year}{extra_filter}",
        "rows": 1000,
        "select": "DOI,title,author,container-title,URL,type",
    })
    papers = []
    for item in data["message"]["items"]:
        if not containers_ok(item.get("container-title", [])):
            continue
        title = clean_title(" ".join(item.get("title", [])))
        # 論文集そのもの（前付け・目次など）は除く
        if not title or re.fullmatch(r"(?i)(front matter|back matter|table of contents|preface|index|author index)", title):
            continue
        doi = item["DOI"].lower()
        papers.append(Paper(
            conference=conference, year=year, title=title, authors=_crossref_authors(item),
            doi=doi, landing_url=f"https://doi.org/{doi}",
        ))
    return papers


def fetch_lak(session, year: int) -> list[Paper]:
    return _crossref_papers(
        session, "LAK", year, "Learning Analytics and Knowledge Conference",
        ",type:proceedings-article,prefix:10.1145",
        lambda cs: any(_LAK_CONTAINER.search(c) and "journal" not in c.lower() for c in cs),
    )


# AIED の論文集が入るSpringerのシリーズ。同名の一般書籍（教科書など）を除くために使う
_AIED_SERIES = ("Lecture Notes in Computer Science", "Lecture Notes in Artificial Intelligence",
                "Communications in Computer and Information Science")


def fetch_aied(session, year: int) -> list[Paper]:
    # Springer では container-title が ["Lecture Notes in Computer Science", "Artificial Intelligence in Education"] のように入る
    return _crossref_papers(
        session, "AIED", year, "Artificial Intelligence in Education",
        ",type:book-chapter,prefix:10.1007",
        lambda cs: any(_AIED_CONTAINER.search(c) for c in cs) and any(c in _AIED_SERIES for c in cs),
    )


def fetch_edm(session, year: int) -> list[Paper]:
    """EDM は Zenodo のコミュニティ（edm2023 など）に論文PDFが公開されている。"""
    papers: list[Paper] = []
    page, size = 1, 25  # Zenodo はログインなしだと1ページ25件まで
    while True:
        data = _get_json(session, f"https://zenodo.org/api/communities/edm{year}/records", {"size": size, "page": page})
        hits = data.get("hits", {}).get("hits", [])
        for h in hits:
            meta = h.get("metadata", {})
            pdfs = [f for f in h.get("files", []) if str(f.get("key", "")).lower().endswith(".pdf")]
            doi = (h.get("doi") or meta.get("doi") or "").lower()
            papers.append(Paper(
                conference="EDM", year=year, title=clean_title(meta.get("title", "")),
                authors=[c.get("name", "") for c in meta.get("creators", []) if c.get("name")],
                doi=doi,
                landing_url=h.get("links", {}).get("self_html") or (f"https://doi.org/{doi}" if doi else ""),
                pdf_url=pdfs[0]["links"]["self"] if pdfs else "",
            ))
        if len(hits) < size or page >= 40:
            break
        page += 1
    # 論文集まるごと1冊（「Proceedings of EDM2024」など、100MB超）は除く
    return [p for p in papers if p.title and not re.match(r"(?i)proceedings of|front matter", p.title)]


_JSTAGE_API = "https://api.jstage.jst.go.jp/searchapi/do"
_ATOM = "{http://www.w3.org/2005/Atom}"
_PRISM = "{http://prismstandard.org/namespaces/basic/2.0/}"
_OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"


def _jstage_text(entry: ET.Element, path: str) -> str:
    """J-STAGEの応答から、日本語（なければ英語）の値を取り出す。"""
    for lang in ("ja", "en"):
        el = entry.find(f"{_ATOM}{path}/{_ATOM}{lang}")
        if el is not None and (el.text or "").strip():
            return el.text.strip()
    return ""


def jstage_pdf_url(article_url: str) -> str:
    """論文ページのURL（…/_article/-char/ja/）から、PDFのURL（…/_pdf/-char/ja）を作る。"""
    if "/_article" not in article_url:
        return ""
    return re.sub(r"/_article.*$", "/_pdf/-char/ja", article_url)


def parse_jstage(xml_text: str, journal: str, cdjournal: str) -> tuple[list[Paper], int]:
    """J-STAGE WebAPI（Atom形式のXML）の応答を論文のリストにする。戻り値: (論文, 総件数)"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise CollectError("J-STAGEから想定外の応答が返りました") from e
    status = root.find(f"{_ATOM}result/{_ATOM}status")
    if status is not None and status.text not in (None, "0"):
        message = root.findtext(f"{_ATOM}result/{_ATOM}message") or ""
        raise CollectError(f"J-STAGEの検索でエラーが返りました（{status.text}: {message}）")
    total = int(root.findtext(f"{_OPENSEARCH}totalResults") or 0)

    papers = []
    for entry in root.findall(f"{_ATOM}entry"):
        # 資料名の検索はあいまい一致なので、資料コードで目的の学会誌か確認する
        if (entry.findtext(f"{_ATOM}cdjournal") or "") != cdjournal:
            continue
        title = clean_title(_jstage_text(entry, "article_title"))
        if not title:
            continue
        lang = "ja" if entry.find(f"{_ATOM}author/{_ATOM}ja/{_ATOM}name") is not None else "en"
        authors = [re.sub(r"\s+", " ", n.text or "").strip()
                   for n in entry.findall(f"{_ATOM}author/{_ATOM}{lang}/{_ATOM}name") if (n.text or "").strip()]
        # 著者のない記事（「研究会優秀賞論文」の発表や目次など）は論文ではないので除く
        if not authors:
            continue
        doi = (entry.findtext(f"{_PRISM}doi") or "").strip().lower()
        article = (entry.findtext(f"{_ATOM}article_link/{_ATOM}ja") or entry.findtext(f"{_ATOM}article_link/{_ATOM}en") or "").strip()
        year = entry.findtext(f"{_ATOM}pubyear") or "0"
        papers.append(Paper(
            conference=journal, year=int(year) if year.isdigit() else 0, title=title, authors=authors,
            doi=doi, landing_url=article or (f"https://doi.org/{doi}" if doi else ""),
            pdf_url=jstage_pdf_url(article),
            title_en=clean_title(entry.findtext(f"{_ATOM}article_title/{_ATOM}en") or ""),
        ))
    return papers, total


def fetch_jstage(session, journal: str, year: int) -> list[Paper]:
    """J-STAGE WebAPI で、国内の学会誌・大会論文集の論文を集める。"""
    info = JSTAGE_JOURNALS[journal]
    papers: list[Paper] = []
    start, count = 1, 1000  # J-STAGE は1回最大1000件
    while True:
        try:
            r = session.get(_JSTAGE_API, timeout=TIMEOUT, params={
                "service": 3, "material": info["material"], "pubyearfrom": year, "pubyearto": year,
                "count": count, "start": start,
            })
            r.raise_for_status()
        except requests.RequestException as e:
            raise CollectError(f"J-STAGEへの接続に失敗しました: {e}") from e
        found, total = parse_jstage(r.text, journal, info["cdjournal"])
        papers.extend(found)
        start += count
        if start > total or start > 5000:
            break
    return papers


def _fetcher(name: str):
    if name in JSTAGE_JOURNALS:
        return lambda session, year: fetch_jstage(session, name, year)
    return _FETCHERS[name]


_FETCHERS = {"LAK": fetch_lak, "EDM": fetch_edm, "AIED": fetch_aied}


def add_open_access_pdfs(session, papers: list[Paper]) -> None:
    """PDFのURLがない論文について、OpenAlex で無料で読めるPDFの場所を探して補う。"""
    targets = [p for p in papers if not p.pdf_url and p.doi]
    # OpenAlex は1回の問い合わせで最大50件のDOIをまとめて検索できる
    for i in range(0, len(targets), 50):
        chunk = targets[i:i + 50]
        by_doi = {p.doi: p for p in chunk}
        data = _get_json(session, "https://api.openalex.org/works", {
            "filter": "doi:" + "|".join(by_doi),
            "per-page": 50,
            "select": "doi,best_oa_location",
        })
        for w in data.get("results", []):
            doi = (w.get("doi") or "").lower().removeprefix("https://doi.org/")
            pdf = (w.get("best_oa_location") or {}).get("pdf_url")
            # ACM はボット対策で自動取得できないため、ACM上のPDFは「手動」のままにする
            if doi in by_doi and pdf and "dl.acm.org" not in pdf:
                by_doi[doi].pdf_url = pdf


def collect_papers(conferences: list[str], years: list[int], keyword: str = "", progress=None) -> tuple[list[Paper], list[str]]:
    """会議と年を指定して論文一覧を集める。

    戻り値: (論文のリスト, 注意メッセージのリスト)
    progress: 進み具合を受け取る関数 progress(割合0〜1, メッセージ)（画面表示用・省略可）
    """
    session = _session()
    papers: list[Paper] = []
    notes: list[str] = []
    jobs = [(c, y) for c in conferences for y in years]
    for n, (conf, year) in enumerate(jobs):
        lo, hi = YEAR_RANGES[conf]
        if not lo <= year <= hi:
            notes.append(f"{conf} {year} は一覧を取得できる範囲外です（{lo}〜{hi}年）。")
            continue
        if progress:
            progress(n / max(len(jobs), 1), f"{conf} {year} の論文を検索中…")
        try:
            found = _fetcher(conf)(session, year)
        except CollectError as e:
            notes.append(f"{conf} {year}: {e}")
            continue
        if not found:
            notes.append(f"{conf} {year} の論文は見つかりませんでした（まだ登録されていない可能性があります）。")
        papers.extend(found)

    # 同じDOIの重複（Zenodoのバージョン違いなど）を除く
    seen: set[str] = set()
    unique = []
    for p in papers:
        key = p.doi or f"{p.conference}|{p.year}|{p.title.lower()}"
        title_key = f"{p.conference}|{p.year}|{p.title.lower()}"
        if key in seen or title_key in seen:
            continue
        seen.update({key, title_key})
        unique.append(p)

    if keyword:
        words = keyword.lower().split()
        # 日本語論文は英語タイトルでも探せるようにする（「learning analytics」で日本語論文も見つかる）
        unique = [p for p in unique if all(w in f"{p.title} {p.title_en}".lower() for w in words)]

    if progress:
        progress(0.95, "無料で読めるPDFを探しています…")
    try:
        add_open_access_pdfs(session, unique)
    except CollectError as e:
        notes.append(f"オープンアクセス情報の取得に失敗しました（一覧はそのまま使えます）: {e}")
    if progress:
        progress(1.0, "完了")
    return unique, notes


# ---------------------------------------------------------------------------
# PDF取得
# ---------------------------------------------------------------------------

class PdfDownloadError(Exception):
    """PDFを取得できなかったときの例外（メッセージは利用者に表示する）。"""


def download_pdf(url: str, session: requests.Session | None = None) -> bytes:
    """PDFをダウンロードしてバイト列で返す。PDFでない応答（ログイン画面など）はエラーにする。"""
    session = session or _session()
    try:
        with session.get(url, timeout=TIMEOUT, stream=True) as r:
            if r.status_code in (401, 403):
                raise PdfDownloadError("サイトにアクセスを拒否されました（ログインが必要か、自動取得が禁止されています）")
            if r.status_code == 404:
                raise PdfDownloadError("PDFが見つかりませんでした（404）")
            r.raise_for_status()
            chunks, size = [], 0
            for chunk in r.iter_content(64 * 1024):
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise PdfDownloadError("PDFが大きすぎます（40MB超）")
                chunks.append(chunk)
    except requests.RequestException as e:
        raise PdfDownloadError(f"ダウンロードに失敗しました: {e}") from e
    data = b"".join(chunks)
    if not data.startswith(b"%PDF"):
        raise PdfDownloadError("PDFではないページが返されました（ログイン画面などの可能性）")
    return data


def polite_sleep(seconds: float = 1.0) -> None:
    """相手のサーバーに負担をかけないよう、連続ダウンロードの間に待つ。"""
    time.sleep(seconds)

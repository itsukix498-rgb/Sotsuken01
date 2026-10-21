# Paper Data Finder（論文から公開教育データを探す）

卒業研究「論文から公開教育データを自動で見つけるAIエージェント」のプロトタイプです。
学習分析系国際会議（LAK・EDM・AIED）の論文を集め、本文中のURL（データの公開先の手がかり）を一覧にします。

## できること

### ① 論文を集める
- 会議（LAK / EDM / AIED）と年を選ぶと、論文一覧（タイトル・著者・DOI・論文ページ）を取得します
- 無料で読めるPDFがある論文は、PDFを自動で取得してURLをまとめて抽出します
- 論文一覧・URL一覧をCSVで保存できます

| 会議 | 論文一覧の取得元 | 対応年 | PDFの自動取得 |
|---|---|---|---|
| LAK | Crossref | 2011〜 | ほぼ不可（ACMが自動取得を禁止しているため。論文ページから手動で保存） |
| EDM | Zenodo | 2023〜 | ほぼすべて可能（オープンアクセス） |
| AIED | Crossref | 2015〜 | 一部のみ（オープンアクセスの論文。OpenAlexで探します） |

- Google Scholar や DBLP はボット対策があり、自動収集が認められていないため使っていません
- 相手のサーバーに負担をかけないよう、PDFは1本ずつ1秒おきに取得し、1回30本までにしています
- 取得したPDFは保存しません（URL抽出が終わったら破棄します）

### ② URLを抽出する
- 手元のPDF（複数可）をアップロードして、URLを一覧にします
- ①で自動取得できなかった論文（LAKなど）は、PDFを手動で保存してここでまとめて処理できます

### URL抽出のルール
- `http://` / `https://` / `www.` で始まるURLに加え、`github.com/...` `doi.org/...` のようなスキームなしURL（パスがあるもの）も拾います
- 改行で途中が切れたURLを、可能な範囲で結合します
- URL末尾の句読点や括弧（`. , ; : ) ]` など）を取り除きます（`..._(statistics)` のように対応する括弧は残します）
- PDF内のハイパーリンク（リンク注釈）からもURLを取得し、本文の結果と統合します
- 同じURLは1件にまとめ、最初に出現したページ番号を記録します

## ファイル構成

```
app.py                     Webアプリの入口（合言葉の確認・ページ切り替え）
pages/collect.py           ① 論文を集めるページ
pages/extract.py           ② URLを抽出するページ
ui_common.py               2つのページで共通の表示部品
collect_papers.py          論文一覧の取得（Crossref / Zenodo / OpenAlex）とPDFの取得
extract_urls.py            PDFからのURL抽出（コマンドラインでも使えます）
tests/                     pytest のテスト
samples/sample_paper.pdf   動作確認用のサンプルPDF
.streamlit/config.toml     Webアプリの設定
.streamlit/secrets.toml.example  合言葉の設定例
```

## 手元で動かす

Python 3.10 以上が必要です。

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

ブラウザで http://localhost:8501 が開きます。終了するときは、ターミナルで `Ctrl + C` を押します。

手元では合言葉を聞かれません。合言葉の画面を試したいときは、`.streamlit/secrets.toml.example` をコピーして `.streamlit/secrets.toml` を作ります。

### コマンドラインでURL抽出だけ使う

```bash
python extract_urls.py paper.pdf
```

画面に一覧を表示し、PDFと同じフォルダに `<PDF名>_urls.csv` を保存します（`-o result.csv` で保存先を変更できます）。

## 公開する（Streamlit Community Cloud）

1. このリポジトリをGitHubに push します
2. https://share.streamlit.io を開き、GitHubアカウントでログインします
3. 「Create app」→「Deploy a public app from GitHub」を選び、次のように入力します
   - Repository: このリポジトリ
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: 好きな名前（例: `paper-data-finder`）
4. 「Advanced settings」で Python のバージョン（3.11 など）を選び、Secrets 欄に次の1行を入れます
   ```toml
   APP_PASSWORD = "研究室で決めた合言葉"
   ```
5. 「Deploy」を押すと、数分で `https://〇〇.streamlit.app` が使えるようになります

一度公開すれば、GitHubの `main` ブランチに push するたびに、公開中のアプリも自動で更新されます。
合言葉を変えるときは、Streamlit Community Cloud のアプリの Settings → Secrets で書き換えます（コードの変更は不要です）。

## テスト

```bash
python -m pytest
```

## 既知の制限

- LAKのPDFはACMが自動取得を禁止しているため、手動で保存する必要があります
- EDM 2022年以前は、論文がZenodoで公開されていないため一覧に出ません
- Crossref は会議名で検索しているため、まれに取りこぼしや関係ない論文が混ざる可能性があります
- URL抽出: ドメイン名の途中で改行されたスキームなしURLや、URLの途中に空白が入ったものは取れません

## 今後の拡張予定

- URLの種類分け（GitHub / Zenodo / OSF / Kaggle など）
- データ言及文の抽出、公開状況（公開 / 要依頼 / 非公開）の判定
- 研究室の人手調査の結果と比べた精度評価

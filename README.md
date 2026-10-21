# Paper Data Finder（論文から公開教育データを探す）

卒業研究「論文から公開教育データを自動で見つけるAIエージェント」のプロトタイプです。
学習分析系国際会議（LAK・EDM・AIED）と国内の学会誌・大会（J-STAGE）の論文を集め、本文中のURL（データの公開先の手がかり）を一覧にします。

## できること

左上の ☰ メニューからページを切り替えます。

### 論文を集める（3ステップ）
1. **STEP 1 論文を検索**：会議・学会誌（ボタンで複数選択）と年、タイトルのキーワードを選んで論文一覧を集めます
   （日本語の論文は英語タイトルでも探せます）
2. **STEP 2 論文を選ぶ**：一覧（タイトル・著者・論文ページ）から、URLを抽出する論文にチェックを入れます。論文一覧はCSVで保存できます
3. **STEP 3 URLを抽出**：選んだ論文の無料PDFを自動で取得し、本文中のURLを一覧にします。URL一覧はCSVで保存できます

各ページの上に進み具合（1 → 2 → 3）が表示され、「← 戻る」「次へ →」ボタンで行き来できます。チェックや検索条件はページを移動しても残ります。

| 会議 | 論文一覧の取得元 | 対応年 | PDFの自動取得 |
|---|---|---|---|
| LAK | Crossref | 2011〜 | ほぼ不可（ACMが自動取得を禁止しているため。論文ページから手動で保存） |
| EDM | Zenodo | 2023〜 | ほぼすべて可能（オープンアクセス） |
| AIED | Crossref | 2015〜 | 一部のみ（オープンアクセスの論文。OpenAlexで探します） |
| JSET論文誌（日本教育工学会論文誌） | J-STAGE | 2000〜 | 多くが可能（1回10本まで） |
| JSiSE学会誌（教育システム情報学会誌） | J-STAGE | 2000〜 | 多くが可能（1回10本まで） |
| JSET研究報告（日本教育工学会研究報告集） | J-STAGE | 2000〜 | 多くが可能（1回10本まで） |
| JSAI全国大会（人工知能学会全国大会論文集） | J-STAGE | 2000〜 | 多くが可能（1回10本まで）。1年で約1,000件あるのでキーワードで絞るのがおすすめ |

- Google Scholar や DBLP はボット対策があり、自動収集が認められていないため使っていません
- 相手のサーバーに負担をかけないよう、PDFは1本ずつ1秒おきに取得し、1回30本までにしています
- J-STAGE は利用規約で「機械的な手段による大量ダウンロード」を禁止しているため、J-STAGEの論文は1回10本まで・3秒おきにしています。
  論文一覧は J-STAGE WebAPI（非商用利用は申請不要）で取得し、画面に「Powered by J-STAGE」を表示しています
- J-STAGEの学会誌を追加するときは、`collect_papers.py` の `JSTAGE_JOURNALS` に資料名と資料コード（論文URLの `/article/〇〇/` の部分）を足します
- 取得したPDFは保存しません（URL抽出が終わったら破棄します）

### 手元のPDFからURL抽出
- 手元のPDF（複数可）をアップロードして、URLを一覧にします
- 「論文を集める」で自動取得できなかった論文（LAKなど）は、PDFを手動で保存してここでまとめて処理できます

### URL抽出のルール
- `http://` / `https://` / `www.` で始まるURLに加え、`github.com/...` `doi.org/...` のようなスキームなしURL（パスがあるもの）も拾います
- 改行で途中が切れたURLを、可能な範囲で結合します
- URL末尾の句読点や括弧（`. , ; : ) ]` など）を取り除きます（`..._(statistics)` のように対応する括弧は残します）
- PDF内のハイパーリンク（リンク注釈）からもURLを取得し、本文の結果と統合します
- 同じURLは1件にまとめ、最初に出現したページ番号を記録します
- 日本語の論文にも対応しています（「https://…を参照」「（https://…）」のように、URLの直後に日本語や全角記号が続いてもURLだけを取り出します）

## ファイル構成

```
app.py                     Webアプリの入口（合言葉の確認・☰メニューのページ切り替え）
views/step1_search.py      STEP 1 論文を検索するページ
views/step2_select.py      STEP 2 論文を選ぶページ
views/step3_extract.py     STEP 3 PDFを取得してURLを抽出するページ
views/extract.py           手元のPDFからURL抽出するページ
ui_common.py               各ページで共通の表示部品（見た目のCSS・ステップ表示・URL一覧の表）
collect_papers.py          論文一覧の取得（Crossref / Zenodo / OpenAlex / J-STAGE）とPDFの取得
extract_urls.py            PDFからのURL抽出（コマンドラインでも使えます）
tests/                     pytest のテスト
samples/sample_paper.pdf   動作確認用のサンプルPDF
.streamlit/config.toml     Webアプリの設定
.streamlit/secrets.toml.example  合言葉の設定例
```

ページのファイルは `pages/` ではなく `views/` に置いています。`pages/` という名前のフォルダがあると、Streamlit が各ページを自動で登録し、
`/extract` などのURLを直接開いたときに `app.py`（合言葉の確認）を通らずにページが動いてしまうことがあるためです。

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

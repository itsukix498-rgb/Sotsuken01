# Paper Data Finder（論文から公開教育データを探す）

卒業研究「論文から公開教育データを自動で見つけるAIエージェント」のプロトタイプです。
学習分析系国際会議（LAK・EDM・AIED）と国内の学会誌・大会（J-STAGE）の論文を集め、本文中のURL（データの公開先の手がかり）を一覧にします。
さらに、AIが論文を読んで、手に入れられる教育データセットとその入手方法を判定します（試験版）。

**今のバージョン：ver 3.4（2026-11-13）**　これまでの変更は [CHANGELOG.md（更新履歴）](CHANGELOG.md) にまとめています。

## できること

最初に開くホームに、3つの入口（論文を検索する／手元の論文を調べる／使い方）があります。
左上の ☰ メニューからもページを切り替えられます。パソコン・スマホのどちらでも使えます。

### 論文を検索して調べる（4ステップ）
1. **STEP 1 論文を検索**：会議・学会誌（ボタンで複数選択）と年、タイトルのキーワードを選んで論文一覧を集めます
   （日本語の論文は英語タイトルでも探せます）。画面を開いている間は、前の検索結果を「検索の履歴」から開き直せます
2. **STEP 2 論文を選ぶ**：一覧（タイトル・著者・論文ページ）から、PDFを取得する論文にチェックを入れます（最初は何も選ばれていません。
   「すべて選ぶ」で上から30本まで、「すべて外す」で全部外せます）。論文一覧はCSVで保存できます
3. **STEP 3 URLを抽出**：選んだ論文の無料PDFを自動で取得し、本文中のURLを一覧にします。URL一覧はCSVで保存できます
4. **STEP 4 AIで判定（試験版）**：本文を取得した論文を AI が読み、手に入れられる教育データセットと、その名前・URL・入手方法を判定します
   （英語の論文だけ。1回10本まで）

各ページの上に進み具合（1 → 2 → 3 → 4）が表示され、ボタンで行き来できます。チェックや検索条件はページを移動しても残ります。

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

### 手元の論文を調べる
- 手元のPDF（複数可）をアップロードして、URLを一覧にします
- 「論文を検索」で自動取得できなかった論文（LAKなど）は、PDFを手動で保存してここでまとめて処理できます
- 英語の論文は、「すでに公開されている論文です」の確認にチェックしたうえで、AIでも判定できます
  （投稿前の原稿などが外部のAIに送られないようにするため）

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
views/home.py              ホーム（最初に開くページ。3つの入口）
views/guide.py             使い方
views/step1_search.py      STEP 1 論文を検索するページ（検索の履歴つき）
views/step2_select.py      STEP 2 論文を選ぶページ
views/step3_extract.py     STEP 3 PDFを取得してURLを抽出するページ
views/step4_judge.py       STEP 4 AIで判定するページ
views/extract.py           手元の論文を調べるページ（URL抽出と、英語の論文のAI判定）
views/evaluation.py        研究の評価結果ページ（手元のPCに評価結果があるときだけ表示）
ui_common.py               各ページで共通の表示部品（見た目のCSS・ステップ表示・URL一覧の表）
ui_ai.py                   「AIで判定する（試験版）」の部品（STEP 4 と手元の論文のページで使う）
prompts/                   AIに渡す判定用プロンプト（版ごと）
research/                  研究用の部品（本文の取得・LLMによる判定・評価）
scripts/                   研究用のスクリプト（判定の一括実行・評価など）
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

### AIで判定する（試験版）

STEP 4「AIで判定」と「手元の論文を調べる」のページで使えます。取得した論文の本文の一部（URLの前後の文と、データについて書かれた文）を
Gemini API に送り、手に入れられる教育データセットがあるか、その名前・URL・入手方法（公開／要ログイン／要申請）を判定します
（研究で調整したプロンプト `prompts/judge_v3.md` を使います。仕組みは `ui_ai.py`）。

- Gemini API のキーがあるときだけ表示されます。公開アプリでは Settings → Secrets に次の1行を足します（手元では `.env` に書きます）
  ```toml
  GEMINI_API_KEY = "AI Studio で作ったキー"
  ```
- 無料枠を使い切らないよう、1回 10 本まで、アプリ全体で1日 200 本まで（米国太平洋時間の0時＝日本時間17時ごろに戻る）にしています。
  画面には「今日あと〇本」を表示し、判定中は1本ごとに、それ以外は10秒ごとに数え直します
- 先生のデータセットはアプリでは使いません
- 判定できるのは英語の論文だけです。日本語の論文は、AIに渡す材料（データについて書かれた文）を英語の言い回しでしか探せず、
  正しく判定できることも確かめていないため、対象外と表示します（URLの抽出は使えます）
- GitHub に送っても公開アプリが古い画面のままのときは、「Manage app」→「⋮」→「Reboot app」で再起動します

### 休止を防ぐ見回り

Streamlit Community Cloud は、12時間アクセスがないとアプリを休止し、「Yes, get this app back up!」ボタンを押すまで起動しません。
そこで、GitHub Actions（`.github/workflows/keep-awake.yml`）が6時間ごとに GitHub のサーバー上のブラウザでアプリを開き、
休止していればボタンを押して起こします（`scripts/keep_awake.py`）。手元のPCは使わず、Public リポジトリなので無料です。

- 動いたかどうかは、GitHub のリポジトリの「Actions」タブで確認できます。失敗するとリポジトリの持ち主にメールが届きます
- 「Actions」タブ →「Keep app awake」→「Run workflow」で、すぐに手動で動かすこともできます
- GitHub は、リポジトリに60日間更新がないと定期実行を自動で止めます。止まったら「Actions」タブから有効に戻してください
- 公開URLを変えたときは、`keep-awake.yml` の `APP_URL` も書き換えます

## 研究用：先生のデータセットの論文の本文を取得する

研究室の人手調査の結果（先生のデータセット）に載っている論文を Semantic Scholar で特定し、本文を取得して状況をまとめます。
先生のデータセットは研究室の未公開データなので `data/` に置き、GitHub には上げません（`.gitignore` で除外）。
外部に送るのは DOI・タイトル（Semantic Scholar・OpenAlex）と、論文PDFのダウンロードだけです。

準備

1. `.env.example` をコピーして `.env` を作り、Semantic Scholar の APIキーを書く（キーなしでも動くが、混雑で失敗しやすい）
2. 先生のデータセットを `data/teacher_dataset.xlsx` に置く
3. 列の対応を `data/column_map.json` に書く（書き方は `research/column_map.example.json`）

実行

```bash
# 列の構成を確認する（先頭の数行を表示するだけ）
python scripts/build_papers_status.py data/teacher_dataset.xlsx --describe

# 会議ごとに3本ずつ試す
python scripts/build_papers_status.py data/teacher_dataset.xlsx --per-venue 3

# 全件
python scripts/build_papers_status.py data/teacher_dataset.xlsx
```

結果は `data/papers_status.csv` に保存され、本文を取得できた割合が会議別・年別に表示されます。

本文の取り方（`research/fulltext.py`）

- S2ORC（Semantic Scholar の本文データ）は1本ずつ取るAPIがなく、一括ダウンロード（約120〜180GB）しかないため、本文があるかどうかを記録するだけにしています
- PDFは次の順に試します：Semantic Scholar のオープンアクセスPDF → arXiv 版 → OpenAlex のPDF → 先生のシートのURL（EDM公式サイトのPDFなど）
- ACM（dl.acm.org）は自動取得が禁止されているので、問い合わせません
- Semantic Scholar・OpenAlex の結果と取得した本文は `data/cache/` に保存し、再実行のときは同じリクエストを送りません

出典の表示（Semantic Scholar API の利用条件）

- 論文情報の一部は [Semantic Scholar](https://www.semanticscholar.org/) から取得しています
- 卒論・発表などで結果を使うときは、次の論文を引用します：
  Kinney, R. et al. "The Semantic Scholar Open Data Platform." arXiv:2301.10140 (2023).

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

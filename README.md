# 論文PDF URL抽出スクリプト

卒業研究「論文から公開教育データを自動で見つけるAIエージェント」の最初の機能です。
学習分析系国際会議（LAK・EDM・AIED）の英語論文PDFを1本読み込み、本文中のURLをすべて一覧にします。

## できること

- ページごとにテキストを抽出し、URLを抜き出す
  - `http://` / `https://` で始まるURL
  - `www.` で始まるURL
  - `github.com/...` や `doi.org/...` のようなスキームなしURL（パスがあるものに限る）
- 改行で途中が切れたURLを、可能な範囲で結合する
- URL末尾の句読点や括弧（`. , ; : ) ]` など）を取り除く（`..._(statistics)` のように対応する括弧は残す）
- PDF内のハイパーリンク（リンク注釈）からもURLを取得し、本文の結果と統合する
- 同じURLは1件にまとめ、最初に出現したページ番号を記録する
  （`github.com/a/b` と `https://github.com/a/b/` のような表記揺れも同一とみなします）

## ファイル構成

```
app.py                    Webアプリ（Streamlit）
extract_urls.py           本体（PDF読み込み / テキスト抽出 / URL抽出 / 出力 を関数に分割）
tests/test_extract_urls.py  pytest のテスト
requirements.txt          依存パッケージ
samples/sample_paper.pdf  動作確認用のサンプルPDF
```

## インストール

Python 3.10 以上が必要です。

```bash
pip install -r requirements.txt
```

## 実行方法（Webアプリ）

```bash
streamlit run app.py
```

ブラウザで http://localhost:8501 が開きます（開かない場合はこのURLを手で開いてください）。
PDFをアップロードするか「サンプルPDFで試す」を押すと、URLの一覧が表示されます。

- 取得元（本文テキスト / リンク注釈）やキーワード（github, zenodo など）で絞り込めます
- 「開く ↗」でURLを新しいタブで開けます
- 「CSVをダウンロード」でコマンドライン版と同じ形式のCSVを保存できます（絞り込みに関係なく全件）

終了するときは、ターミナルで `Ctrl + C` を押します。

## 実行方法（コマンドライン）

```bash
python extract_urls.py paper.pdf
```

CSVの保存先を変える場合は `-o` を指定します。

```bash
python extract_urls.py paper.pdf -o result.csv
```

ファイルが存在しない・PDFでない・パスワード付き などの場合は、エラーメッセージを表示して終了コード 1 で終了します。

```
エラー: ファイルが見つかりません: paper.pdf
```

## 出力例

画面表示:

```
page  source           url
--------------------------------------------------------------------------------
   1  text             https://analyse.kmi.open.ac.uk/open_dataset
   1  text             https://github.com/edm-lab/dropout-prediction
   1  text             osf.io/x7k2m
   1  text+annotation  https://huggingface.co/edm-lab/dropout-bert
   1  annotation       https://github.com/edm-lab/dropout-prediction/tree/main/scripts
   2  text             https://doi.org/10.1038/sdata.2017.171
--------------------------------------------------------------------------------
合計 6 件
CSVを保存しました: paper_urls.csv
```

CSV（入力PDFと同じフォルダに `<PDF名>_urls.csv` として保存。Excelで開けるよう BOM 付き UTF-8）:

```csv
page,url,source
1,https://analyse.kmi.open.ac.uk/open_dataset,text
1,https://github.com/edm-lab/dropout-prediction,text
1,https://huggingface.co/edm-lab/dropout-bert,text+annotation
```

`source` 列の意味:

| 値 | 意味 |
|---|---|
| `text` | 本文テキストから抽出 |
| `annotation` | リンク注釈（ハイパーリンク）から取得 |
| `text+annotation` | 両方から見つかった |

## テスト

```bash
python -m pytest
```

## 既知の制限

- ドメイン名の途中で改行されたスキームなしURL（`pslcdatashop.` ／ `web.cmu.edu/...`）は後半しか取れません
- PDF上でURLの途中に空白が入っている場合（`https://github. com/...`）は取れません
- スキームなしURLはパス付き（`kaggle.com/...`）のみ対象で、`kaggle.com` 単体は拾いません
- 2段組の段をまたいだURLや、ページをまたいだURLは結合しません

## 今後の拡張予定

以下は未実装で、コード内に差し込み位置のコメントを入れてあります。

- 参考文献セクションの除外（`extract_page_texts()`）
- URLの種類分け（GitHub / Zenodo / OSF / Kaggle など）（`merge_url_records()`）
- データ言及文の抽出、公開状況（公開 / 要依頼 / 非公開）の判定
- 複数PDFの一括処理（`main()`）

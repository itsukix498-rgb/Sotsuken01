"""根拠の文の確認（research/evidence.py）のテスト。文章はすべて架空のもの。"""

from research.evidence import EMPTY, MATCH, NEAR, NOT_FOUND, check_evidence, normalize

PAGES = [
    "Introduction\nWe study how students use an online tutor.\n",
    "Data\nAll interaction logs collected in this study are openly avail-\nable at https://osf.io/abcde. "
    "Due to privacy regulations, the survey responses cannot be shared.\n",
    "Results\nThe model improved accuracy by 5 points.\n",
]


def test_exact_sentence_found_with_page():
    c = check_evidence("Due to privacy regulations, the survey responses cannot be shared.", PAGES)
    assert (c.status, c.page) == (MATCH, 2)
    assert c.label == "本文の 2 ページにあり"


def test_line_break_hyphen_and_case_are_ignored():
    # 本文では「avail-（改行）able」と切れている。大文字・小文字の違いも無視する
    c = check_evidence("all interaction logs collected in this study are openly available at https://osf.io/abcde.", PAGES)
    assert (c.status, c.page) == (MATCH, 2)


def test_hyphen_space_from_excerpts():
    # AIに渡した抜粋では、行末のハイフンでの改行が空白になる（"avail- able"）。AIがそれを写しても一致とみなす
    c = check_evidence("All interaction logs collected in this study are openly avail- able at https://osf.io/abcde.",
                       PAGES)
    assert (c.status, c.page) == (MATCH, 2)


def test_quotes_and_context_marks_are_ignored():
    c = check_evidence("...“Due to privacy regulations, the survey responses cannot be shared.”...", PAGES)
    assert c.status == MATCH


def test_slightly_reworded_sentence_is_near():
    c = check_evidence("Because of privacy regulations, the survey responses cannot be shared.", PAGES)
    assert (c.status, c.page) == (NEAR, 2)


def test_invented_sentence_is_not_found():
    c = check_evidence("The full data set is available on Kaggle for all researchers.", PAGES)
    assert c.status == NOT_FOUND
    assert c.label == "本文に見つからない"


def test_empty_or_too_short_evidence():
    assert check_evidence("", PAGES).status == EMPTY
    assert check_evidence(None, PAGES).status == EMPTY
    assert check_evidence("logs", PAGES).status == EMPTY


def test_sentence_across_pages():
    pages = ["The data are available", "upon request from the authors."]
    c = check_evidence("The data are available upon request from the authors.", pages)
    assert (c.status, c.page) == (MATCH, 1)


def test_hyphenated_word_split_at_line_end():
    pages = ["We release an open-\nsource data set of essays."]
    c = check_evidence("We release an open-source data set of essays.", pages)
    assert c.status == MATCH


def test_sentence_split_by_page_break_and_footnote():
    # 文の前半が2ページ目の最後、後半が3ページ目の最初にあり、間に脚注が挟まっている。AIは脚注を除いてつないで写した
    pages = ["Intro.", "We collected learner data between the years 2019-2022\n"
             "1https://example.org/docs/indicators\n- Accessed Feb. 2024\n",
             "(n = 1, 234 learners), since the platform data were sta-\nble from 2019. Next we describe."]
    c = check_evidence("We collected learner data between the years 2019-2022 (n = 1, 234 learners), "
                       "since the platform data were stable from 2019.", pages)
    assert (c.status, c.page) == (NEAR, 2)


def test_footnote_number_removed_by_ai_is_near():
    pages = ["2.1 Data To ensure the reproducibility1, our study uses the public data set of the Example Study of 2010 (ES:10)."]
    c = check_evidence("To ensure the reproducibility, our study uses the public data set of the Example Study of 2010 (ES:10).",
                       pages)
    assert c.status == NEAR


def test_normalize():
    assert normalize("  Open-\n source  “data” ﬁle. ") == 'opensource "data" file'

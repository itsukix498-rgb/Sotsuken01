"""段階3（LLMによる判定）のテスト。LLMは呼ばず、ダミーの応答で確かめる。

使う論文の文章・URLはすべて架空のもので、先生のデータセットの内容は含めない。
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extract_urls import UrlRecord  # noqa: E402
from research.judge import STATUS_INVALID, STATUS_OK, Judge, load_prompt, validate  # noqa: E402
from research.llm import DailyLimitReached, LLMProvider, LLMResponse  # noqa: E402
from research.llm.gemini import GeminiProvider  # noqa: E402
from research.llm.ollama import OllamaProvider  # noqa: E402
from research.llm_input import build_llm_input, extract_data_sentences, find_references_start  # noqa: E402

BODY = (
    "1 Introduction\nWe study student essays. The data set is available at https://osf.io/abcde for research.\n"
    "Our code is on https://github.com/example/tool.\n" + "Some method text. " * 40 + "\n"
)
REFS = "References\n[1] A. Author. A paper. https://doi.org/10.1000/xyz\n[2] Notes https://paperpile.com/c/ab12\n"


def _records():
    return [UrlRecord(1, "https://osf.io/abcde", ["text"]), UrlRecord(1, "https://github.com/example/tool", ["text"]),
            UrlRecord(2, "https://doi.org/10.1000/xyz", ["text"]), UrlRecord(2, "https://paperpile.com/c/ab12", ["annotation"])]


def _item():
    return build_llm_input("A sample paper", [BODY, REFS], _records())


# --- LLMに渡す文章 ---------------------------------------------------------------

def test_build_input_marks_references_and_excludes_noise():
    item = _item()
    assert [u.id for u in item.urls] == ["U1", "U2", "U3"]
    assert [u.in_references for u in item.urls] == [False, False, True]
    assert "data set is available" in item.urls[0].context
    assert item.urls[2].context == ""  # 参考文献の章のURLには前後の文章を付けない
    assert item.excluded_urls == ["https://paperpile.com/c/ab12"]
    assert "[REFERENCE LIST]" in item.render_urls()


def test_data_sentences_come_from_body_only():
    item = _item()
    assert any("data set is available" in s for s in item.data_sentences)
    assert not any("A. Author" in s for s in item.data_sentences)


@pytest.mark.parametrize("sentence", [
    "Data are available upon reasonable request from the authors.",
    "Due to privacy restrictions, the logs cannot be shared.",
    "The datasets used are publicly available on Kaggle.",
])
def test_extract_data_sentences(sentence):
    assert extract_data_sentences(f"Intro text here. {sentence} Unrelated text follows.") == [sentence]


def test_find_references_start_uses_last_heading_in_second_half():
    text = "Contents\nReferences\n" + "body " * 200 + "\nREFERENCES\n[1] x"
    assert text[find_references_start(text):].startswith("REFERENCES")
    assert find_references_start("no heading here") == len("no heading here")


def test_prompt_loads_and_renders():
    prompt = load_prompt("judge_v1")
    user = prompt.render_user(_item())
    assert prompt.version == "judge_v1"
    assert '"P" = public hyperlink' in prompt.system and "{{" not in user
    assert "U1, U2, U3" in user


# --- 答えの形の確認 ----------------------------------------------------------------

def _answer(shares="yes", datasets=None, ids=("U1", "U2", "U3")):
    if datasets is None:
        datasets = [{"name": "essays", "url": "https://osf.io/abcde", "availability": "P", "evidence": "x"}]
    return {"paper": {"shares_dataset": shares, "evidence": "x"}, "datasets": datasets,
            "urls": [{"id": i, "is_data_location": i == "U1", "reason": "r"} for i in ids]}


def test_validate_accepts_correct_answer():
    assert validate(_answer(), _item()) == []
    assert validate(_answer("no", datasets=[]), _item()) == []


@pytest.mark.parametrize("answer, word", [
    (_answer("maybe"), "shares_dataset"),
    (_answer("no"), "must be empty"),  # 「なし」なのに2段目を書いている
    (_answer("yes", datasets=[]), "at least one"),
    (_answer(datasets=[{"name": "d", "url": None, "availability": "X"}]), "availability"),
    (_answer(datasets=[{"name": "d", "url": "https://made-up.org/data", "availability": "P"}]), "copied from"),
    (_answer(ids=("U1", "U2")), "exactly these ids"),
])
def test_validate_rejects(answer, word):
    assert any(word in p for p in validate(answer, _item()))


# --- やり直し・キャッシュ ------------------------------------------------------------

class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, replies):
        super().__init__("fake-model")
        self.replies, self.calls = list(replies), []

    def generate(self, system, user):
        self.calls.append(user)
        return LLMResponse(text=self.replies.pop(0), input_tokens=100, output_tokens=20, seconds=0.5, model="fake-1")


def test_judge_retries_then_succeeds_and_caches(tmp_path):
    bad = json.dumps(_answer("no"))  # 形が違う（なしなのにデータセットがある）
    good = json.dumps(_answer())
    provider = FakeProvider(["not json at all", bad, good])
    judge = Judge(provider, load_prompt("judge_v1"), cache_dir=tmp_path)
    j = judge.judge(_item())
    assert (j.status, j.attempts, j.input_tokens, j.model) == (STATUS_OK, 3, 300, "fake-1")
    assert "not in the required format" in provider.calls[1]  # どこが違ったかを伝えている
    # 同じ論文・同じ設定なら、二度目はLLMを呼ばない
    j2 = judge.judge(_item())
    assert j2.cached and j2.answer == j.answer and len(provider.calls) == 3


def test_judge_gives_up_as_invalid(tmp_path):
    provider = FakeProvider(["{}", "{}", "{}"])
    j = Judge(provider, load_prompt("judge_v1"), cache_dir=tmp_path).judge(_item())
    assert j.status == STATUS_INVALID and j.problems and j.attempts == 3


def test_cache_key_changes_with_model(tmp_path):
    good = json.dumps(_answer())
    p1, p2 = FakeProvider([good]), FakeProvider([good])
    p2.model = "another-model"
    Judge(p1, load_prompt("judge_v1"), cache_dir=tmp_path).judge(_item())
    Judge(p2, load_prompt("judge_v1"), cache_dir=tmp_path).judge(_item())
    assert len(p1.calls) == 1 and len(p2.calls) == 1  # モデルが違えば別に判定する


# --- Gemini・Ollama（通信はダミー） ---------------------------------------------------

class FakeHTTP:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers, json))
        return self.responses.pop(0)


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, str(data)

    def json(self):
        return self._data


def test_gemini_request_and_usage():
    ok = Resp(200, {"candidates": [{"content": {"parts": [{"text": "{\"a\": 1}"}]}}],
                    "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 7, "thoughtsTokenCount": 3},
                    "modelVersion": "gemini-x-001"})
    http = FakeHTTP([ok])
    g = GeminiProvider("gemini-x", api_key="k", session=http, sleep=lambda s: None)
    r = g.generate("sys", "user")
    url, headers, body = http.calls[0]
    assert url.endswith("/models/gemini-x:generateContent") and headers["x-goog-api-key"] == "k"
    assert "key=" not in url  # キーはURLに入れない
    assert body["generationConfig"] == {"temperature": 0.0, "responseMimeType": "application/json"}
    assert (r.text, r.input_tokens, r.output_tokens, r.model) == ('{"a": 1}', 50, 10, "gemini-x-001")


def test_gemini_waits_on_rate_limit_and_stops_on_daily_limit():
    per_minute = Resp(429, {"error": {"details": [{"retryDelay": "7s"}]}})
    ok = Resp(200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}], "usageMetadata": {}})
    sleeps = []
    g = GeminiProvider("m", api_key="k", session=FakeHTTP([per_minute, ok]), sleep=sleeps.append)
    g.generate("s", "u")
    assert 8.0 in sleeps  # 指定された7秒（＋1秒）待った

    daily = Resp(429, {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProject"}]}]}})
    g = GeminiProvider("m", api_key="k", session=FakeHTTP([daily]), sleep=lambda s: None)
    with pytest.raises(DailyLimitReached):
        g.generate("s", "u")


def test_ollama_request_and_usage():
    http = FakeHTTP([Resp(200, {"message": {"content": "{}"}, "prompt_eval_count": 900, "eval_count": 40,
                                "model": "local-model"})])
    o = OllamaProvider("local-model", base_url="http://localhost:11434", session=http)
    r = o.generate("sys", "user")
    url, _, body = http.calls[0]
    assert url == "http://localhost:11434/api/chat"
    assert body["format"] == "json" and body["options"]["temperature"] == 0.0 and body["options"]["num_ctx"] >= 8192
    assert (r.input_tokens, r.output_tokens) == (900, 40)

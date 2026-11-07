"""LLMに論文を判定させる（段階3）。

    1. prompts/ のプロンプト（版番号付き）に、論文ごとの材料（research/llm_input.py）を差し込む
    2. LLMに渡し、答えのJSONが決められた形かを確かめる
    3. 形が違えば、どこが違うかを伝えてやり直させる（最大2回）。それでもだめなら「判定不能」
    4. 結果は data/cache/llm/ に保存し、同じ論文・同じ設定（モデル・プロンプトの版・温度・入力）では二度呼ばない
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from research.llm import LLMProvider, LLMResponse
from research.llm_input import LlmInput, same_url

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
STATUS_OK = "ok"
STATUS_INVALID = "判定不能"
STATUS_NOT_JUDGED = "未処理"  # まだ判定していない（評価のときにキャッシュになかった論文）
SHARES = ("yes", "no", "unknown")
AVAILABILITY = ("P", "L", "O")


@dataclass
class Prompt:
    version: str  # 例: judge_v1
    system: str
    user_template: str

    def render_user(self, item: LlmInput) -> str:
        values = {
            "title": item.title,
            "urls": item.render_urls(),
            "url_ids": ", ".join(u.id for u in item.urls) or "(none; use an empty list)",
            "data_sentences": item.render_data_sentences(),
        }
        text = self.user_template
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        return text


def load_prompt(version: str = "judge_v1") -> Prompt:
    raw = (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)  # 先頭の説明（人向けのメモ）は渡さない
    system, user = raw.split("=== USER ===", 1)
    system = system.split("=== SYSTEM ===", 1)[1]
    return Prompt(version=version, system=system.strip(), user_template=user.strip())


def _parse_json(text: str):
    """答えからJSONを取り出す（```json ... ``` で囲まれていても読めるようにする）。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def validate(answer, item: LlmInput) -> list[str]:
    """答えが決められた形かを確かめ、違う点を英語の短い文で返す（空なら合格）。"""
    problems = []
    if not isinstance(answer, dict):
        return ["The answer must be a single JSON object."]
    paper = answer.get("paper")
    if not isinstance(paper, dict) or paper.get("shares_dataset") not in SHARES:
        problems.append('"paper.shares_dataset" must be "yes", "no" or "unknown".')
        shares = None
    else:
        shares = paper["shares_dataset"]
        if not isinstance(paper.get("evidence", ""), str):
            problems.append('"paper.evidence" must be a string.')

    datasets = answer.get("datasets")
    if not isinstance(datasets, list):
        problems.append('"datasets" must be a list.')
    else:
        if shares in ("no", "unknown") and datasets:
            problems.append('"datasets" must be empty when shares_dataset is "no" or "unknown".')
        if shares == "yes" and not datasets:
            problems.append('"datasets" must list at least one data set when shares_dataset is "yes".')
        for i, d in enumerate(datasets):
            if not isinstance(d, dict) or d.get("availability") not in AVAILABILITY or not d.get("name"):
                problems.append(f'datasets[{i}] needs "name" and "availability" of "P", "L" or "O".')
            elif d.get("url") not in (None, ""):
                if not isinstance(d.get("url"), str):
                    problems.append(f'datasets[{i}].url must be a string or null.')
                elif not any(same_url(d["url"], u.url) for u in item.urls):
                    # 渡していないURLを作り出していないかを確かめる
                    problems.append(f'datasets[{i}].url must be copied from the given URL list, or null.')

    urls = answer.get("urls")
    expected = [u.id for u in item.urls]
    if not isinstance(urls, list):
        problems.append('"urls" must be a list.')
    else:
        ids = [u.get("id") for u in urls if isinstance(u, dict)]
        if sorted(ids) != sorted(expected):
            problems.append(f'"urls" must contain exactly these ids, each once: {", ".join(expected) or "(none)"}.')
        if any(not isinstance(u, dict) or not isinstance(u.get("is_data_location"), bool) for u in urls):
            problems.append('Each item in "urls" needs "is_data_location": true or false.')
    return problems


@dataclass
class Judgement:
    status: str  # ok / 判定不能
    answer: dict | None = None
    problems: list[str] = field(default_factory=list)  # 最後の答えの形の問題（判定不能のとき）
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    model: str = ""  # 実際に答えたモデル名
    cached: bool = False
    raw: str = ""  # 最後の答えの文字（判定不能のときの確認用）


class Judge:
    """論文を判定する。

    repeat: 再現性を測るために同じ設定で何回目かの判定をするときの番号（0 がふつうの判定）。
            番号ごとに別のキャッシュになるので、2回目・3回目は前の答えを使い回さずに判定し直す。
    cache_only: True なら LLM を呼ばず、キャッシュにある答えだけを返す（評価のとき用）。
    """

    def __init__(self, provider: LLMProvider, prompt: Prompt, cache_dir: str | Path = "data/cache/llm",
                 max_retries: int = 2, repeat: int = 0, cache_only: bool = False):
        self.provider = provider
        self.prompt = prompt
        self.cache_dir = Path(cache_dir)
        self.max_retries = max_retries
        self.repeat = repeat
        self.cache_only = cache_only

    def settings(self) -> dict:
        return {**self.provider.settings(), "prompt_version": self.prompt.version}

    def _cache_path(self, user_text: str) -> Path:
        key_data = {**self.settings(), "system": self.prompt.system, "user": user_text}
        if self.repeat:
            key_data["repeat"] = self.repeat  # 0 のときは入れない（それまでのキャッシュと同じ鍵にするため）
        key = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        return self.cache_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:40]}.json"

    def judge(self, item: LlmInput) -> Judgement:
        user_text = self.prompt.render_user(item)
        cache = self._cache_path(user_text)
        if cache.exists():
            j = Judgement(**json.loads(cache.read_text(encoding="utf-8")))
            j.cached = True
            return j
        if self.cache_only:
            return Judgement(status=STATUS_NOT_JUDGED)

        result = Judgement(status=STATUS_INVALID)
        message = user_text
        for attempt in range(self.max_retries + 1):
            response: LLMResponse = self.provider.generate(self.prompt.system, message)
            result.attempts = attempt + 1
            result.input_tokens += response.input_tokens
            result.output_tokens += response.output_tokens
            result.seconds += response.seconds
            result.model = response.model or self.provider.model
            result.raw = response.text
            try:
                answer = _parse_json(response.text)
                problems = validate(answer, item)
            except (json.JSONDecodeError, ValueError):
                answer, problems = None, ["The answer was not valid JSON. Output only one JSON object."]
            if not problems:
                result.status, result.answer, result.problems = STATUS_OK, answer, []
                break
            result.problems = problems
            # どこが違ったかを伝えて、もう一度答えさせる
            message = (user_text + "\n\nYour previous answer was not in the required format:\n- "
                       + "\n- ".join(problems) + "\nAnswer again with the corrected JSON object only.")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(result)
        data["cached"] = False
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return result

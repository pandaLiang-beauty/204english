from __future__ import annotations

"""Compare text translations with identical prompts; never write study rows.

Load the usual English AI environment for the baseline. The candidate config
is a private JSON file containing base_url and api_key, separate from the
running application's configuration. Reports deliberately exclude secrets.
"""

import argparse
import hashlib
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.english.translator import _decode_json_object_from_text, _english_ai_options, _translation_source
from scripts.english.evaluate_translation_pipeline import _load_rows, _words_for_row

MODELS = (
    "gemini-3.6-flash-high", "gemini-3.5-flash-lite", "gemini-pro-agent",
    "gemini-3-flash", "gemini-3.1-flash-lite", "gemini-3.7-flash-high",
    "gemini-3.1-pro-low", "gemini-3.8-flash-high", "gemini-3.1-flash-image",
)
PROMPT = (
    "你是专业英汉译者和英语学习材料编辑。把每个目标句准确、自然地译成中文，并解释指定重点词。"
    "保留否定、数量、比较、条件、指代和修饰范围，不补原文没有的信息。"
    "相邻英文仅用于目标句消歧，可能跨文章，不翻译邻句或照搬邻句内容。"
    "词卡本义给常见中文词典义，句中义只解释该词在本句的用法；区分单词和固定搭配的范围。"
    "英文释义用简单、简短的英文解释同一用法，保持词性与词形，不用原词循环定义。"
    "只输出 JSON，不提供自评分。"
)
SCHEMA = (
    '按输入顺序返回 {"sentences":[{"id":"输入ID","sentence_translation":"自然中文译文",'
    '"words":[{"word":"指定原词","base_translation":"中文本义",'
    '"context_translation":"中文句中义","english_definition":"short explanation in simple English"}]}]}。'
    "每句 words 与给定列表同序同量，每个字段必填。"
)


def make_dataset(seed: int) -> dict:
    rows = _load_rows(None)
    by_id = {row["id"]: row for row in rows}
    eligible = [row for row in rows if row["id"] not in {359, 477}
                and 12 <= len(row["text"].split()) <= 38 and 2 <= len(_words_for_row(row)) <= 4
                and not row["text"].lstrip().startswith(("According to", "Which of", "The underlined"))]
    selected = random.Random(seed).sample(eligible, 4)
    criteria = {
        359: "保留另一个人的指代；被看待的被动关系；平易近人及现代时尚的比较程度。",
        477: "治理基于认识人的内在价值；each 的数量不得算入 individual；rests on 为基础关系。",
        669: "有条件现金转移/补助项目旨在减少不平等并打破贫困循环；设计目的不是已实现结果。",
        157: "只有综合项目满足无家可归者多种需求时情况才改善；保留 only when 必要条件和记者署名。",
        280: "禁令充分执行是条件；向女性及许多男性传递不让他人裁定自己美貌的观念。",
        156: "while 是让步；否定成瘾或精神疾病；缺少日常生存技能；turn lives around 改善生活境况。",
    }
    cases = []
    for row in [by_id[359], by_id[477], *selected]:
        cases.append({
            "id": f"stored-{row['id']}", "kind": "user" if row["id"] in {359, 477} else "random",
            "text": _translation_source(row["text"]), "words": _words_for_row(row),
            "context_before": row["context_before"], "context_after": row["context_after"],
            "review_criteria": criteria.get(row["id"], "逐项核对原文含义、中文自然度及中英文词义范围。"),
        })
    challenges = [
        ("not-every", "Not every policy that is popular is effective.", ["popular", "effective"],
         "不是所有受欢迎的政策都有效，不得译成所有都无效；popular 不是有效，否定不进入 effective 词义。"),
        ("rejected-claim", "The committee rejected the claim that raising fees would necessarily improve services.", ["rejected", "claim", "necessarily"],
         "拒绝的论断是提高收费必然改善服务；不等于认定提价绝无帮助；不得反转赞同与拒绝。"),
        ("amount-not-speed", "The decline was smaller than expected, not slower.", ["decline", "smaller", "slower"],
         "降幅较小，不是下降速度较慢；保留与预期的比较；slower 的词义仍是速度更慢。"),
        ("harder-not-impossible", "The reforms made it harder, rather than impossible, for small firms to enter the market.", ["reforms", "harder", "impossible"],
         "改革提高小企业入市难度，并未令其不可能；不是改革使入市更容易，也不是完全禁止。"),
        ("absence-of-evidence", "The trial found no evidence that the treatment worked; it did not prove that the treatment never works.", ["evidence", "treatment", "prove"],
         "未找到有效证据不等于证明治疗永远无效；两部分的否定作用域都须保留。"),
        ("refundable-deposit", "The company did not disclose whether the payment was a fee or a refundable deposit.", ["disclose", "refundable", "deposit"],
         "公司未披露款项性质是费用还是可退押金/订金；可退还不等于已退还，不得擅选其一。"),
    ]
    for key, text, words, criterion in challenges:
        cases.append({"id": key, "kind": "constructed", "text": text, "words": words,
                      "context_before": [], "context_after": [], "review_criteria": criterion})
    return {"seed": seed, "eligible_count": len(eligible), "random_ids": [row["id"] for row in selected], "cases": cases}


class Gate:
    def __init__(self, rate: float):
        self.lock = threading.Lock()
        self.interval = 60 / rate if rate else 0
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            delay = max(0, self.next_at - time.monotonic())
            self.next_at = max(self.next_at, time.monotonic()) + self.interval
        if delay:
            time.sleep(delay)


def format_issues(parsed, cases):
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sentences"), list):
        return ["missing_sentences_array"]
    items = parsed["sentences"]
    issues = []
    if [row.get("id") if isinstance(row, dict) else None for row in items] != [case["id"] for case in cases]:
        issues.append("sentence_ids_or_order")
    for item, case in zip(items, cases):
        if not isinstance(item, dict):
            issues.append(f"{case['id']}:not_object")
            continue
        if not isinstance(item.get("sentence_translation"), str) or not item["sentence_translation"].strip():
            issues.append(f"{case['id']}:missing_translation")
        words = item.get("words")
        if not isinstance(words, list) or [word.get("word") if isinstance(word, dict) else None for word in words] != case["words"]:
            issues.append(f"{case['id']}:word_list")
            continue
        for word in words:
            for field in ("base_translation", "context_translation", "english_definition"):
                if not isinstance(word.get(field), str) or not word[field].strip():
                    issues.append(f"{case['id']}:{word.get('word')}:{field}")
            english = str(word.get("english_definition") or "")
            if re.search(r"[\u4e00-\u9fff]", english):
                issues.append(f"{case['id']}:{word.get('word')}:chinese_in_english")
    return issues


def run_request(config, blind_id, batch_index, cases, output, gate, timeout, secrets):
    model = config["model"]
    public_cases = [{key: case[key] for key in ("id", "text", "words", "context_before", "context_after")} for case in cases]
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": SCHEMA + "\n" + json.dumps(public_cases, ensure_ascii=False)}]
    record = {"model": model, "blind_id": blind_id, "batch": batch_index, "case_ids": [case["id"] for case in cases], "messages": messages}
    gate.wait()
    started = time.monotonic()
    request = Request(config["base_url"].rstrip("/") + "/chat/completions",
                      data=json.dumps({"model": model, "messages": messages, "temperature": 0.2, "stream": False}, ensure_ascii=False).encode(),
                      headers={"Authorization": "Bearer " + config["api_key"], "Content-Type": "application/json", "User-Agent": "english-review/1.0"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
        if not isinstance(data, dict):
            raise ValueError("Response is not a JSON object")
        message = (data.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict) and "text" in item)
        raw = str(content or "")
        parsed = _decode_json_object_from_text(raw)
        issues = format_issues(parsed, cases)
        record.update(status="success" if not issues else "format_error", raw_text=raw, parsed=parsed,
                      reported_model=data.get("model"), usage=data.get("usage"), finish_reason=(data.get("choices") or [{}])[0].get("finish_reason"), format_issues=issues)
    except Exception as exc:
        detail = exc.read().decode(errors="replace")[:2500] if isinstance(exc, HTTPError) else str(exc)
        record.update(status="request_failed", error=detail, error_type=type(exc).__name__, http_status=getattr(exc, "code", None))
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record["completed_at"] = datetime.now(timezone.utc).isoformat()
    serialized = json.dumps(record, ensure_ascii=False, indent=2)
    for secret in secrets:
        if secret:
            serialized = serialized.replace(secret, "[REDACTED]")
    (output / f"{blind_id}-batch-{batch_index}.json").write_text(serialized + "\n")
    summary = {key: record.get(key) for key in ("model", "batch", "status", "reported_model", "elapsed_seconds", "http_status", "format_issues")}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return record["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--models", help="Comma-separated candidate model names; defaults to all nine.")
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--requests-per-minute", type=float, default=12)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--batch-size", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1 or args.batch_size < 1 or args.timeout <= 0 or args.requests_per_minute < 0:
        parser.error("Workers, batch size and timeout must be positive; request rate cannot be negative")
    candidate = json.loads(args.candidate_config.read_text())
    if not candidate.get("base_url") or not candidate.get("api_key"):
        parser.error("Candidate base_url and api_key are required")
    current = _english_ai_options()
    baseline = {key: current[key] for key in ("base_url", "api_key", "model")}
    names = [name.strip() for name in args.models.split(",") if name.strip()] if args.models else list(MODELS)
    configs = [{**candidate, "model": name} for name in dict.fromkeys(names)]
    if not args.no_baseline:
        configs.append(baseline)
    all_names = list(dict.fromkeys([*MODELS, baseline["model"], *names]))
    random.Random(args.seed + 1).shuffle(all_names)
    labels = {name: f"M{index + 1:02d}" for index, name in enumerate(all_names)}
    dataset = json.loads(args.dataset.read_text()) if args.dataset else make_dataset(args.seed)
    cases = dataset["cases"]
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "dataset.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n")
    manifest = {"started_at": datetime.now(timezone.utc).isoformat(), "seed": args.seed,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "prompt_sha256": hashlib.sha256((PROMPT + SCHEMA).encode()).hexdigest(),
                "models": [{"blind_id": labels[config["model"]], "model": config["model"], "base_url": config["base_url"]} for config in configs],
                "case_count": len(cases), "batch_size": args.batch_size, "workers": args.workers,
                "requests_per_minute": args.requests_per_minute, "timeout_seconds": args.timeout}
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    batches = [cases[index:index + args.batch_size] for index in range(0, len(cases), args.batch_size)]
    jobs = [(config, index + 1, batch) for config in configs for index, batch in enumerate(batches)]
    random.Random(args.seed + 2).shuffle(jobs)
    gates = {url: Gate(args.requests_per_minute) for url in {config["base_url"] for config in configs}}
    secrets = [candidate["api_key"], baseline["api_key"]]
    statuses = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_request, config, labels[config["model"]], index, batch, args.output,
                                   gates[config["base_url"]], args.timeout, secrets) for config, index, batch in jobs]
        for future in as_completed(futures):
            statuses.append(future.result())
    print(json.dumps({"completed_requests": len(statuses), "successful_requests": statuses.count("success"), "output": str(args.output)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

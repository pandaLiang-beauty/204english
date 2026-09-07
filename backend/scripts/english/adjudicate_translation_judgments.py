from __future__ import annotations

"""Recheck noisy AI-judge claims against translation candidates and context."""

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.translator import _english_ai_options  # noqa: E402
from app.platform.ai_transport import AIProviderError, _chat_completion  # noqa: E402
from scripts.english.judge_translation_evaluation import (  # noqa: E402
    _append,
    _extract_json_object,
    _load_candidates,
)


SYSTEM_PROMPT = """\
你是英汉翻译质量仲裁员。前置审校模型会误报、漏报甚至引用原文不存在的标点；你必须重新看证据，不能投票或照抄其结论。
只返回指定 JSON，不输出 Markdown 或额外字段。"""


RULES = """\
每条输入含英文原句、整句中文、英中分块、最多前后各三句受控英文上下文，以及一到两轮审校意见。上下文可能跨题或跨文章，主题不连续时必须忽略；它只可消歧目标句中的指代、词义、专名、领域和截句关系，不能成为增译目标句的理由。

翻译仲裁：只用 `translation` 判断整句译文，`translation_segments` 的问题不能算到翻译。逐项核对逻辑、范围、否定、程度、数量、指代、实体、截句状态和中文是否成立。上下文只用于确认指代/词义，不能补救译文遗漏。允许自然意译和省略不影响含义的连接词；纯风格偏好不判错。英文共享修饰语在中文中为搭配自然分配到并列项，只要没有实质加强，不算增译；`the ones that feel bad` 译成“令人不适/感觉糟糕的情感”也不能仅因可换成“负面”而判错。疑似 OCR/截断只能作最小且有搭配证据的自然修复。原文本身若缺少右引号、终止标点或后续成分，译文保留同样的未闭合状态不算错误，不得要求凭空补齐。

分块仲裁：阅读块可以是有意义的短语，不必是完整句。句首时间、地点、背景、条件短语，冒号引导部分，完整长复杂主语，并列/对照的一侧，以及句末署名，都可单独成块，只要同序中文准确对应。特别是 `We see ..., Ferraro says.` 将正文和句末署名分成两块是合格方案；位于引语前的 `saying "`／`said: "` 才必须与紧随的短引语保持同一阅读动作。以下是真错误：英中块核心含义错位；切在 such/trends、middle class/family、about/20% 等修饰语内部；功能词结尾；短主语与谓语之间；动词与必需宾语/介词/that/to 补语之间；系动词与表语之间；助动词与后续动词之间；从属连词+主语与其谓语之间；编号/范围内部；把中文已提前的句尾时间/比较成分又孤立到末块。长句分块不足只有在确有自然、安全且英中可对齐的边界时才判错；必须给出边界两边各自连续、同序的英文与中文，不能只说“句子长”，也不能依赖改写、复制、交换或拼接非连续中文。英文句末 if/when/as/due to 已在中文中调到句首或主句内部时，保留一块是合格方案；`notes/says that` 中报告动词与必需补语不是安全切点。

审校意见只是待验证的 claims：意见引用原文不存在的词或标点、只给另一种译法、或误把短语块要求成完整句时，必须驳回。你也可以补充一眼可证的漏检，但不要扩大审查范围。

返回：
{"results":[{"id":整数,"translation_ok":布尔值,"translation_issues":["仅保留已证实问题"],"segmentation_ok":布尔值,"segmentation_issues":["仅保留已证实问题"],"severity":"ok|minor|major","confidence":"high|medium|low"}]}
每个输入 id 恰好一项并保持顺序。两项都通过时 severity 必须为 ok；任一失败时不能为空 issues，severity 不能为 ok。"""


def _load_claims(paths: list[Path]) -> dict[int, list[dict[str, Any]]]:
    claims: dict[int, list[dict[str, Any]]] = {}
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                event = json.loads(line)
                if event.get("event") != "judgment_batch" or event.get("status") != "success":
                    continue
                for item in event.get("results") or []:
                    if item.get("translation_ok") is True and item.get("segmentation_ok") is True:
                        continue
                    item_id = int(item["id"])
                    claims.setdefault(item_id, []).append(
                        {
                            "translation_ok": item.get("translation_ok") is True,
                            "translation_issues": item.get("translation_issues") or [],
                            "segmentation_ok": item.get("segmentation_ok") is True,
                            "segmentation_issues": item.get("segmentation_issues") or [],
                        }
                    )
    return claims


def _inputs(source: Path, claim_paths: list[Path]) -> list[dict[str, Any]]:
    candidates = _load_candidates(source)
    claims = _load_claims(claim_paths)
    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if candidate["id"] not in claims:
            continue
        context_before = candidate.get("context_before") or [
            item["source"] for item in candidates[max(0, index - 2) : index]
        ]
        context_after = candidate.get("context_after") or [
            item["source"] for item in candidates[index + 1 : index + 3]
        ]
        result.append(
            {
                **candidate,
                "context_before": context_before,
                "context_after": context_after,
                "critic_claims": claims[candidate["id"]],
            }
        )
    return result


def _normalize(item: Any, expected_id: int) -> dict[str, Any]:
    if not isinstance(item, dict) or int(item.get("id", -1)) != expected_id:
        raise ValueError(f"missing judgment for {expected_id}")
    translation_ok = item.get("translation_ok") is True
    segmentation_ok = item.get("segmentation_ok") is True
    translation_issues = item.get("translation_issues")
    segmentation_issues = item.get("segmentation_issues")
    severity = str(item.get("severity") or "").lower()
    confidence = str(item.get("confidence") or "").lower()
    if not isinstance(translation_issues, list) or not all(isinstance(x, str) for x in translation_issues):
        raise ValueError(f"bad translation issues for {expected_id}")
    if not isinstance(segmentation_issues, list) or not all(isinstance(x, str) for x in segmentation_issues):
        raise ValueError(f"bad segmentation issues for {expected_id}")
    translation_issues = [x.strip() for x in translation_issues if x.strip()]
    segmentation_issues = [x.strip() for x in segmentation_issues if x.strip()]
    if translation_ok != (not translation_issues) or segmentation_ok != (not segmentation_issues):
        raise ValueError(f"boolean/issues mismatch for {expected_id}")
    if severity not in {"ok", "minor", "major"} or confidence not in {"high", "medium", "low"}:
        raise ValueError(f"bad enum for {expected_id}")
    if severity == "ok" and (not translation_ok or not segmentation_ok):
        raise ValueError(f"bad ok severity for {expected_id}")
    return {
        "id": expected_id,
        "translation_ok": translation_ok,
        "translation_issues": translation_issues,
        "segmentation_ok": segmentation_ok,
        "segmentation_issues": segmentation_issues,
        "severity": severity,
        "confidence": confidence,
    }


def _adjudicate(batch: list[dict[str, Any]], retries: int) -> dict[str, Any]:
    ids = [item["id"] for item in batch]
    started = time.monotonic()
    last_error = ""
    encoded = json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
    for attempt in range(1, retries + 2):
        feedback = f"\n上一次格式错误：{last_error[:500]}" if last_error else ""
        try:
            raw = _chat_completion(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"{RULES}{feedback}\n\n待仲裁数据：\n{encoded}"},
                ],
                **_english_ai_options(),
            )
            parsed = _extract_json_object(raw)
            values = parsed.get("results")
            if not isinstance(values, list):
                raise ValueError("results is not a list")
            by_id = {int(value.get("id")): value for value in values if isinstance(value, dict)}
            normalized = [_normalize(by_id.get(item_id), item_id) for item_id in ids]
            return {
                "event": "adjudication_batch",
                "status": "success",
                "ids": ids,
                "attempts": attempt,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "results": normalized,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc.diagnostic if isinstance(exc, AIProviderError) else f"{type(exc).__name__}: {exc}"
            if attempt <= retries:
                time.sleep(attempt)
    return {
        "event": "adjudication_batch",
        "status": "failed",
        "ids": ids,
        "attempts": retries + 1,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "error": last_error[:2000],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("claims", type=Path, nargs="+")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output exists: {args.output}")
    if args.batch_size < 1 or args.workers < 1 or args.retries < 0:
        parser.error("invalid batch/workers/retries")
    values = _inputs(args.source, args.claims)
    batches = [values[index : index + args.batch_size] for index in range(0, len(values), args.batch_size)]
    start = {
        "event": "adjudication_start",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": str(args.source),
        "claims": [str(path) for path in args.claims],
        "model": os.getenv("STUDY_ENGLISH_AI_MODEL", ""),
        "adjudicator_prompt_sha256": hashlib.sha256(
            f"{SYSTEM_PROMPT}\n{RULES}".encode("utf-8")
        ).hexdigest(),
        "target_count": len(values),
        "database_write_performed": False,
    }
    _append(args.output, start)
    print("START", json.dumps(start, ensure_ascii=False), flush=True)
    passed = failed = flagged = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_adjudicate, batch, args.retries) for batch in batches]
        for index, future in enumerate(as_completed(futures), start=1):
            event = future.result()
            _append(args.output, event)
            if event["status"] == "success":
                passed += len(event["results"])
                flagged += sum(item["severity"] != "ok" for item in event["results"])
            else:
                failed += len(event["ids"])
            print(
                "PROGRESS",
                json.dumps(
                    {"batches_done": index, "batches_total": len(batches), "adjudicated": passed, "failed": failed, "flagged": flagged},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    summary = {
        "event": "adjudication_summary",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "target_count": len(values),
        "adjudicated": passed,
        "failed": failed,
        "flagged": flagged,
        "database_write_performed": False,
    }
    _append(args.output, summary)
    print("DONE", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

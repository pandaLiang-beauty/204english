from __future__ import annotations

"""Audit a read-only translation-evaluation JSONL report with an AI judge.

The source report is produced by ``evaluate_translation_pipeline.py``.  This
script never opens the study database and writes only a resumable JSONL audit
report, so generated judgments cannot accidentally replace stored study data.
"""

import argparse
import hashlib
import json
import os
import re
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


JUDGE_SYSTEM_PROMPT = """\
你是严格、保守的考研英语中译与阅读分块审校员。目标英文是唯一待审译内容；
相邻上下文只能辅助判断目标句的指代、词义、专名、领域和截句关系。
你只负责找出实际错误，不因个人文风偏好判错，也不能因为中文大意通顺就忽略逻辑或分块错位。
只返回指定 JSON；不输出 Markdown、解释性前言或额外字段。"""


JUDGE_RULES = """\
逐条独立审查以下两部分：

每条数据中的 `context_before` 和 `context_after` 最多各三句，只可用于消歧。相邻项可能跨题或跨文章；主题不连续时忽略。不能把上下文内容补进目标译文，也不能因目标句没有重复上下文已给出的信息而判漏译。

A. 整句翻译
整句翻译只审查输入字段 `translation`，不要用 `translation_segments` 反推它；后者即使不自然也只属于 B 类分块问题。
1. 核对主谓宾、否定、情态、条件、让步、因果、转折、比较、并列、修饰范围、数量、时间、性别、专名、疑问语气和截句状态。
2. 检查漏译、增译、错译、指代错误、实体类型错误、强弱程度变化，以及把名词改成动作、把并列改成因果等关系漂移。
3. 允许符合中文习惯的调序和意译；仅仅有另一种更漂亮的说法，不算错误。英文一个共享修饰语在中文中为了搭配而自然分配到两个并列名词，只要没有实质加强就不算增译。但中文自身必须成立，例如孤立句首的 `Instead,` 不能机械写成缺少前项的“而是，”。`the ones that feel bad` 译成“令人感到不适/感觉糟糕的情感”属语境选词，除非真的改变了对象，不要只因可换成“负面”就判错。
4. 普通英文词无必要地残留在中文中算问题；通用缩写、品牌、专名不算。
5. 文章截句仍要保留句内实际的谓语层级。如果关系词开头的残句在定语谓语后又出现 can/may/must 等主要谓语，译文不能把后者也压成“……的人”而导致全句没有断言。
6. 原文本身若因 OCR、截断而缺少右引号、句号或后续成分，译文保留同样的未闭合状态不算标点错误；不得要求译文凭空补齐原文没有提供的内容。

B. 英中阅读分块
1. 每个英文块与同序中文块必须表达同一部分；不得把后一个英文块的核心含义提前塞进前一中文块，也不得让某个中文块只翻译前/后块。
2. “阅读块”可以是意义完整的短语或一个阅读动作，不要求每块都是独立句子。以下切法只要英中含义对齐就完全允许，不能以“悬空/不是完整句”为由判错：句首时间/地点/背景/条件状语单独一块（如 `On Tuesday,`／“周二，”）；完整的长复杂主语单独一块；冒号前的引导部分与冒号后的解释分开；并列或对照的两部分分开；句末署名单独一块。特别是 `We see ..., Ferraro says.` 切成“正文”与 `Ferraro says.`／“费拉罗说”两块是合格分块，不得以“引语与引导语应为一个动作”为由判错。
3. 真正错误的切点包括：限定词/数量词/形容词与中心名词之间（如 such / trends、middle class / family、about / 20%）；从属连词加主语之后却在从句谓语之前；短简单主语与谓语之间；动词与不可缺少的宾语、介词或 that/to 补语之间；系动词与表语之间；助动词与后续动词之间；编号和数值范围内部；非末块停在 and/or/but/while/to/of/that/such 等功能词上。已经完整列完的 either A or B 长主语可以与共同谓语分开。
4. 位于引语之前的引导语和紧随其后的短直接引语必须作为一个阅读动作：不得在 `saying "`／`said: "` 之后立即切开，把完整短引语全部放入下一块。这条限制不适用于原文句末、位于正文之后的署名。英文句尾时间状语若中文自然语序已把它提前，也不能把该时间状语单独留作最后一个中文块（如把 `after ten years of residence` 配成句末“在居住十年后。”）。
5. 中文因自然语序把英文句尾的时间、条件、比较成分提前时，不能硬把该中文含义留在前块而把相应英文留到后块；这种错位应判错。相反，句首背景短语与同义中文短语成对出现是合格分块，即使两者以逗号收尾。
6. 完整长句若有清晰的背景→主句、条件→结果、转折/并列谓语、冒号说明、句末署名等安全边界，原则上应分成 2—4 块。尤其是 18 词以上、实际含有冒号且冒号后另有完整分句、却仍只有一块时，应判为分块不足。短句、标题、文章截句，或中英调序无法逐块自然对应时，可以保留一块。特别是英文句末的 if/when/as/due to 条件、时间或原因成分已被中文调到句首或主句内部时，一块往往是唯一不错位的方案，必须判分块正确。不要只因字数长或出现一个从句就机械要求切分；要求新切点时，issue 必须明确给出切点两边各自连续、同序的英文片段和中文片段。若建议必须改写、复制、交换中文，或把非连续中文拼成一块，说明并无可用边界，不得判错。
7. 引号内的句号以及 U.S.、Dr. 等缩写不能被误判为新句。核对原文真实字符后再引用证据；原句没有冒号就绝不能声称“冒号后未分块”。
8. `reporter notes that ...`、`the study says that ...` 中的报告动词与 that 补语不能为了增加块数而拆开；不得一边称该结构必需补语，一边又把它当成“安全边界”。

判定尺度：
- severity="major"：实质意义错误、逻辑关系错误、明显漏译/增译，或英中块严重错位/切在不可拆单位中。
- severity="minor"：局部但真实的译义、自然度或分块问题，不显著改变整句主旨。
- severity="ok"：翻译和分块都无实际问题。
- translation_ok 和 segmentation_ok 必须分别判断；任一为 false 时 severity 不得为 ok。
- issue 必须指出具体英文或具体边界，不能只写“翻译不够自然”“建议优化”。

返回结构：
{"results":[{"id":整数,"translation_ok":布尔值,"translation_issues":["具体问题"],"segmentation_ok":布尔值,"segmentation_issues":["具体问题"],"severity":"ok|minor|major"}]}
必须为输入中的每个 id 恰好返回一项，顺序一致。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_candidates(path: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}") from exc
            if event.get("event") == "translation" and event.get("status") == "success":
                result = event.get("v2") if isinstance(event.get("v2"), dict) else {}
                candidates.append(
                    {
                        "id": int(event["id"]),
                        "source": str(event.get("source_text") or event.get("text") or ""),
                        "context_before": event.get("context_before") or [],
                        "context_after": event.get("context_after") or [],
                        "translation": str(result.get("sentence_translation") or ""),
                        "sentence_segments": result.get("sentence_segments") or [],
                        "translation_segments": result.get("translation_segments") or [],
                    }
                )
    candidates.sort(key=lambda item: item["id"])
    return candidates


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(parsed, dict):
        raise ValueError("judge response is not a JSON object")
    return parsed


def _normalize_judgment(value: Any, expected_id: int) -> dict[str, Any]:
    if not isinstance(value, dict) or int(value.get("id", -1)) != expected_id:
        raise ValueError(f"missing or mismatched judgment for id {expected_id}")
    translation_ok = value.get("translation_ok") is True
    segmentation_ok = value.get("segmentation_ok") is True
    translation_issues = value.get("translation_issues")
    segmentation_issues = value.get("segmentation_issues")
    if not isinstance(translation_issues, list) or not all(isinstance(item, str) for item in translation_issues):
        raise ValueError(f"invalid translation_issues for id {expected_id}")
    if not isinstance(segmentation_issues, list) or not all(isinstance(item, str) for item in segmentation_issues):
        raise ValueError(f"invalid segmentation_issues for id {expected_id}")
    severity = str(value.get("severity") or "").lower()
    if severity not in {"ok", "minor", "major"}:
        raise ValueError(f"invalid severity for id {expected_id}")
    if (not translation_ok or not segmentation_ok) and severity == "ok":
        raise ValueError(f"inconsistent severity for id {expected_id}")
    if translation_ok and translation_issues:
        raise ValueError(f"translation_ok conflicts with issues for id {expected_id}")
    if segmentation_ok and segmentation_issues:
        raise ValueError(f"segmentation_ok conflicts with issues for id {expected_id}")
    return {
        "id": expected_id,
        "translation_ok": translation_ok,
        "translation_issues": [item.strip() for item in translation_issues if item.strip()],
        "segmentation_ok": segmentation_ok,
        "segmentation_issues": [item.strip() for item in segmentation_issues if item.strip()],
        "severity": severity,
    }


def _judge_batch(batch: list[dict[str, Any]], retries: int) -> dict[str, Any]:
    started = time.monotonic()
    ids = [item["id"] for item in batch]
    payload_text = json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
    last_error = ""
    for attempt in range(1, retries + 2):
        feedback = (
            f"\n上一次输出无效：{last_error[:600]}。本次务必返回全部 {len(ids)} 个 id。"
            if last_error
            else ""
        )
        try:
            raw = _chat_completion(
                [
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"{JUDGE_RULES}{feedback}\n\n待审查数据：\n{payload_text}",
                    },
                ],
                **_english_ai_options(),
            )
            parsed = _extract_json_object(raw)
            results = parsed.get("results")
            if not isinstance(results, list):
                raise ValueError("results is not an array")
            by_id: dict[int, Any] = {}
            for result in results:
                if isinstance(result, dict):
                    try:
                        result_id = int(result.get("id"))
                    except (TypeError, ValueError):
                        continue
                    if result_id in by_id:
                        raise ValueError(f"duplicate id {result_id}")
                    by_id[result_id] = result
            normalized = [_normalize_judgment(by_id.get(item_id), item_id) for item_id in ids]
            return {
                "event": "judgment_batch",
                "status": "success",
                "ids": ids,
                "attempts": attempt,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "results": normalized,
            }
        except Exception as exc:  # noqa: BLE001 - retain malformed provider batches for audit.
            if isinstance(exc, AIProviderError):
                last_error = exc.diagnostic
            else:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt <= retries:
                time.sleep(float(attempt))
    return {
        "event": "judgment_batch",
        "status": "failed",
        "ids": ids,
        "attempts": retries + 1,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "error": last_error[:2000],
    }


def _completed_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    completed: set[int] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            if event.get("event") == "judgment_batch" and event.get("status") == "success":
                completed.update(int(item["id"]) for item in event.get("results") or [])
    return completed


def _append(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-judge a read-only translation evaluation report.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1 or args.workers < 1 or args.retries < 0:
        parser.error("batch size/workers must be positive and retries cannot be negative")
    if args.output.exists() and not args.resume:
        parser.error(f"output already exists: {args.output}; use --resume to append")

    candidates = _load_candidates(args.source)
    completed = _completed_ids(args.output) if args.resume else set()
    pending = [item for item in candidates if item["id"] not in completed]
    batches = [pending[index : index + args.batch_size] for index in range(0, len(pending), args.batch_size)]
    start = {
        "event": "judgment_start",
        "started_at": _utc_now(),
        "source": str(args.source),
        "model": os.getenv("STUDY_ENGLISH_AI_MODEL", ""),
        "judge_prompt_sha256": hashlib.sha256(
            f"{JUDGE_SYSTEM_PROMPT}\n{JUDGE_RULES}".encode("utf-8")
        ).hexdigest(),
        "target_count": len(candidates),
        "skipped_completed": len(candidates) - len(pending),
        "pending_count": len(pending),
        "batch_size": args.batch_size,
        "workers": args.workers,
        "database_write_performed": False,
    }
    _append(args.output, start)
    print("START", json.dumps(start, ensure_ascii=False), flush=True)

    successful = 0
    failed = 0
    issue_count = 0
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="translation-judge") as executor:
        futures = {executor.submit(_judge_batch, batch, args.retries): batch for batch in batches}
        for index, future in enumerate(as_completed(futures), start=1):
            event = future.result()
            _append(args.output, event)
            if event["status"] == "success":
                successful += len(event["results"])
                issue_count += sum(item["severity"] != "ok" for item in event["results"])
            else:
                failed += len(event["ids"])
            print(
                "PROGRESS",
                json.dumps(
                    {
                        "batches_done": index,
                        "batches_total": len(batches),
                        "last_ids": event["ids"],
                        "status": event["status"],
                        "judged": successful,
                        "failed": failed,
                        "flagged": issue_count,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    done = {
        "event": "judgment_summary",
        "completed_at": _utc_now(),
        "target_count": len(candidates),
        "skipped_completed": len(candidates) - len(pending),
        "judged_this_run": successful,
        "failed_this_run": failed,
        "flagged_this_run": issue_count,
        "database_write_performed": False,
    }
    _append(args.output, done)
    print("DONE", json.dumps(done, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

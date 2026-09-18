from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.english import audio_generation, repository, review_rounds  # noqa: E402
from app.english import translation_generation  # noqa: E402
from app.english import translator  # noqa: E402
from app.english import translation_transport  # noqa: E402
from app.english.translation_glossary import expand_unique_quote, ground_word_cards  # noqa: E402
from app.english.ranking import (  # noqa: E402
    build_review_schedule,
    sentence_exposure_metrics,
    sentence_word_network_metrics,
)
from app.english.schema import initialize_schema as initialize_english_schema  # noqa: E402
from app.platform import db as platform_db  # noqa: E402
from app.platform.db import get_connection, initialize_database  # noqa: E402
from scripts.english import evaluate_translation_pipeline  # noqa: E402
from scripts.english import finalize_translation_evaluation, repair_translation_evaluation
from scripts.english import reconcile_translation_focus
from scripts.english import backfill_english_definitions
from scripts.english.review_round_checks import (
    check_review_round_length_preserves_progress_without_daily_limits,
    check_review_round_catch_up_uses_each_snapshot_length,
    check_review_round_deadline_is_frozen_and_early_completion_still_works,
)
from scripts.english.review_regression_checks import REGRESSION_CHECKS


def _decode_json(raw: object, fallback):
    try:
        return json.loads(str(raw or ""))
    except json.JSONDecodeError:
        return fallback


def _mark_sentence_audio_ready(sentence_id: int) -> dict:
    sentence = repository.get_sentence(sentence_id)
    assert sentence, sentence_id
    provider = str(sentence["audio_effective_provider"])
    voice = str(sentence["audio_effective_voice"])
    audio_hash = repository.sentence_audio_hash(
        str(sentence["text"]),
        provider=provider,
        voice=voice,
    )
    audio_path = repository.ENGLISH_AUDIO_DIR / f"sentence-{sentence_id}-{audio_hash[:12]}.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"ready-audio")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE english_sentences
            SET audio_path = ?, audio_provider = ?, audio_voice = ?, audio_hash = ?,
                audio_status = 'ready', audio_error = ''
            WHERE id = ?
            """,
            (audio_path.name, provider, voice, audio_hash, sentence_id),
        )
    ready = repository.get_sentence(sentence_id)
    assert ready and ready["audio_available"] is True, ready
    return ready


def check_evaluation_review_feedback() -> None:
    evaluator = evaluate_translation_pipeline
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "feedback.json"
        path.write_text('{"12":" 保留否定范围 ","2":"只修正词义"}', encoding="utf-8")
        feedback = evaluator._load_review_feedback(path)
        assert feedback == {12: "保留否定范围", 2: "只修正词义"}, feedback
        assert evaluator._load_review_feedback(None) == {}
        assert evaluator._review_feedback_fingerprint({}) == ""
        assert evaluator._review_feedback_fingerprint(feedback) == evaluator._review_feedback_fingerprint(dict(reversed(list(feedback.items()))))
        for invalid in ('[]', '{"0":"invalid"}', '{"one":"invalid"}', '{"1":""}', '{"1":false}', '{"1":"first","01":"second"}'):
            path.write_text(invalid, encoding="utf-8")
            try:
                evaluator._load_review_feedback(path)
            except ValueError:
                pass
            else:
                raise AssertionError(invalid)
    row = {"id": 12, "text": "The change is not inevitable.", "review_feedback": "保留否定范围"}
    candidate = {
        "sentence_translation": "这一变化并非不可避免。",
        "sentence_segments": [row["text"]],
        "translation_segments": ["这一变化并非不可避免。"],
        "word_translations": {},
        "word_tips": {},
    }
    with (
        patch.object(evaluator, "translate_text", side_effect=[RuntimeError("transient_failure"), candidate]) as translate,
        patch.object(evaluator, "translation_result_issues", return_value=[]),
        patch.object(evaluator, "segmentation_advisory_issues", return_value=[]),
        patch.object(evaluator.time, "sleep"),
    ):
        event = evaluator._translate_one(row, retries=1)
    assert event["status"] == "success", event
    assert event["review_feedback"] == row["review_feedback"], event
    assert translate.call_args_list[0].kwargs["feedback"] == "保留否定范围"
    assert translate.call_args_list[1].kwargs["feedback"] == "保留否定范围\n\ntransient_failure"
    with patch.object(evaluator, "translate_text", side_effect=RuntimeError("failed generation")):
        failed = evaluator._translate_one({**row, "sentence_translation": "旧译文"}, retries=0)
    assert failed["status"] == "failed"
    assert failed["previous"]["sentence_translation"] == "旧译文"
    assert failed["previous"]["word_translations"] == {}
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "report.jsonl"
        start = {
            "event": "start",
            "pipeline": "split_translation_v2",
            "provider_base_url": os.getenv("STUDY_ENGLISH_AI_BASE_URL", ""),
            "model": os.getenv("STUDY_ENGLISH_AI_MODEL", ""),
            "prompt_sha256": evaluator._prompt_fingerprint(),
            "pipeline_sha256": evaluator._pipeline_fingerprint(),
            "context_window_each_side": evaluator.MAX_REFERENCE_CONTEXT_ITEMS,
        }
        path.write_text(json.dumps(start) + "\n", encoding="utf-8")
        evaluator._validate_resume_compatibility(path)
        try:
            evaluator._validate_resume_compatibility(path, review_feedback_sha256="changed-feedback")
        except ValueError:
            pass
        else:
            raise AssertionError("resume accepted changed review feedback")


def check_fact_clause_segmentation_is_advisory() -> None:
    source = "alluding to the fact that before the birth of proper dentistry, mouths were often in a shocking state of hygiene."
    translation = "暗指在正规牙科出现之前，口腔卫生状况常常令人震惊。"
    candidate = {"sentence_translation": translation, "sentence_segments": [source], "translation_segments": [translation], "word_translations": {}, "word_tips": {}}
    assert not translator.translation_result_issues(candidate, [], source_text=source)
    advisory = translator.segmentation_advisory_issues(candidate, source_text=source)
    assert any(issue.startswith("undersegmented_fact_that_sentence") for issue in advisory), advisory
    corrupted = {**candidate, "sentence_segments": ["mouths were often in a shocking state of hygiene."]}
    assert translator.translation_result_issues(corrupted, [], source_text=source)
    with (
        patch.object(translator, "_translate_sentence_only", return_value=translation),
        patch.object(translator, "_review_sentence_only", return_value=translation),
        patch.object(translator, "_translate_verified_words", return_value={"items": [], "word_translations": {}, "word_tips": {}}),
        patch.object(translator, "segment_translation", return_value=candidate) as segments,
    ):
        result = translator.translate_text(source, words=[])
    assert result["sentence_translation"] == translation
    assert result["sentence_segments"] == [source]
    assert 2 <= segments.call_count <= 4
    assert not translator.translation_result_issues(result, [], source_text=source)


def check_pipeline_review_feedback_propagation() -> None:
    source = "New rules apply."
    feedback = "保持原始语义并修正分块"
    word_payload = {"items": [], "word_translations": {}, "word_tips": {}}
    with (
        patch.object(translator, "_translate_sentence_only", return_value="新规则适用。") as draft,
        patch.object(translator, "_review_sentence_only", side_effect=["新规则适用。", "新的规则适用。"]) as review,
        patch.object(translator, "ground_sentence_terms", side_effect=lambda _source, translation, **_kwargs: translation),
        patch.object(translator, "_translate_verified_words", return_value=word_payload) as words,
        patch.object(translator, "segment_translation", side_effect=lambda sentence, translation, **_kwargs: {"sentence_segments": [sentence], "translation_segments": [translation]}) as segments,
        patch.object(translator, "translation_result_issues", return_value=["literal_translation:repair"]),
        patch.object(translator, "segmentation_advisory_issues", return_value=[]),
        patch.object(translator, "_segmentation_problem_set", side_effect=[(["bad_segment_count"], []), ([], [])]),
        patch.object(translator, "_segmentation_candidate_score", return_value=0),
        patch.object(translator, "_valid_translation_candidate", return_value=(True, "")),
    ):
        result = translator.translate_text(source, words=[], feedback=feedback)
    assert result["sentence_translation"] == "新的规则适用。"
    assert draft.call_count == 1 and review.call_count == 2 and words.call_count == 2 and segments.call_count == 3
    for stage in (draft, review, words, segments):
        assert all(feedback in call.kwargs.get("feedback", "") for call in stage.call_args_list), stage.call_args_list
    assert "literal_translation:repair" in review.call_args_list[1].kwargs["feedback"]
    assert "bad_segment_count" in segments.call_args_list[-1].kwargs["feedback"]
    with patch.object(translator, "_translate_verified_words", return_value=word_payload) as words:
        translator.translate_words(source, words=["rules"], sentence_translation="新规则适用。", feedback=feedback)
    assert words.call_args.kwargs["feedback"] == feedback


def check_translation_prompt_scope_safeguards() -> None:
    source = "A charter, or a basic agreement, guides their work."
    approved = "一份章程，也就是一项基本协议，指导着他们的工作。"
    with patch.object(translator, "_json_from_chat", return_value={"issues_found": [], "sentence_translation": approved}) as completion:
        assert translator._review_sentence_only(source, approved) == approved
    prompt = json.dumps(completion.call_args.args[0], ensure_ascii=False)
    assert "同位解释" in prompt
    assert "or 不能改成" not in prompt
    assert "不静默替换词形" in translator.TRANSLATION_PRECISION_RULES
    assert "只烤到刚上色" not in translator.TRANSLATION_PRECISION_RULES
    assert "劝阻 X 不要做" in translator.TRANSLATION_PRECISION_RULES
    fragment = "When we consider that Shakespeare, who earns their living"
    fragment_translation = "当我们考虑到莎士比亚——他们靠他谋生——……"
    with patch.object(translator, "_json_from_chat", return_value={"structure": "未完的宾语从句", "sentence_translation": fragment_translation}) as completion:
        assert translator._review_from_source_structure(fragment, "保留截句", feedback="不补缺失谓语") == fragment_translation
    prompt = json.dumps(completion.call_args.args[0], ensure_ascii=False)
    assert "保留未完成状态" in prompt
    assert "不补缺失谓语" in prompt
    assert "中文每个分句必须有完整主谓" not in prompt


def check_translation_repair_feedback_history() -> None:
    repair = repair_translation_evaluation
    first_feedback = "不新增竞选时间背景"
    second_feedback = "相当一部分不一定是多数"
    current_feedback = "统一专名，保留已有修正"
    first = {
        "event": "translation", "status": "success", "id": 1, "words": [], "previous": {},
        "v2": {"sentence_translation": "上一轮中文候选。"}, "review_feedback": first_feedback,
        "review_history": [first_feedback],
    }
    second = {**first, "review_feedback": second_feedback, "review_history": []}
    with tempfile.TemporaryDirectory() as temp_dir:
        directory = Path(temp_dir)
        first_path, second_path, decisions_path = [directory / name for name in ("first.jsonl", "second.jsonl", "decisions.jsonl")]
        first_path.write_text(json.dumps(first) + "\n", encoding="utf-8")
        second_path.write_text(json.dumps(second) + "\n", encoding="utf-8")
        decisions_path.write_text(json.dumps({"report": second_path.name, "revision_requests": {"1": current_feedback}}) + "\n", encoding="utf-8")
        plan = repair._build_plan([first_path, second_path], decisions_path, {})
    assert plan[1]["candidate"]["review_history"] == [first_feedback, second_feedback]
    assert plan[1]["feedback"] == current_feedback
    with (
        patch.object(repair, "_repair_once", side_effect=[RuntimeError("transient_retry"), ({}, ["sentence_review"])]) as repair_call,
        patch.object(repair.time, "sleep"),
    ):
        result = repair._repair_one(plan[1], retries=1)
    for call in repair_call.call_args_list:
        feedback = call.args[1]
        assert all(value in feedback for value in (first_feedback, second_feedback, current_feedback, "上一轮中文候选。"))
        assert feedback.index(current_feedback) > feedback.index(second_feedback)
    assert "transient_retry" in repair_call.call_args_list[1].args[1]
    assert result["review_history"] == [first_feedback, second_feedback, current_feedback]
    assert result["review_feedback"] == current_feedback
    assert first["review_history"] == [first_feedback]


def check_translation_audit_repairs() -> None:
    repair = repair_translation_evaluation
    finalize = finalize_translation_evaluation
    source = "New rules apply."
    translation = "新规则适用。"
    rule_card = {"word": "rules", "translation": "本义：规则；句中：规则", "source_quote": "rules", "translation_quote": "规则"}
    apply_card = {"word": "apply", "translation": "本义：适用；句中：适用", "source_quote": "apply", "translation_quote": "适用"}
    baseline = {
        "event": "translation", "status": "success", "id": 1, "report": "baseline.jsonl",
        "text": source, "source_text": source, "context_before": [], "context_after": [],
        "words": ["rules", "apply"],
        "previous": {"sentence_translation": "旧译", "sentence_segments": [], "translation_segments": [], "word_translations": {}, "word_tips": {}},
        "v2": {
            "sentence_translation": translation, "sentence_segments": [source], "translation_segments": [translation],
            "word_translations": {"rules": rule_card["translation"], "apply": apply_card["translation"]},
            "word_tips": {"rules": "保留提示", "apply": "旧提示"},
            "word_items": [rule_card, apply_card], "quality_audit": {"review_strategy": "preserved"},
        },
    }
    original = copy.deepcopy(baseline)
    replacement = {"items": [apply_card], "word_translations": {"apply": apply_card["translation"]}, "word_tips": {}}
    job = {"candidate": baseline, "stage": "words", "words": ["apply"], "feedback": "只修这个词，保留整句"}
    with (
        patch.object(translator, "translate_words", side_effect=[RuntimeError("transport_retry"), replacement]) as word_call,
        patch.object(translator, "translate_text") as sentence_call,
        patch.object(translator, "segment_translation") as segment_call,
        patch.object(repair.time, "sleep"),
    ):
        repaired = repair._repair_one(job, retries=1)
    assert repaired["status"] == "success", repaired
    assert word_call.call_count == 2
    assert word_call.call_args_list[0].kwargs["feedback"] == job["feedback"]
    assert job["feedback"] in word_call.call_args_list[1].kwargs["feedback"]
    assert "transport_retry" in word_call.call_args_list[1].kwargs["feedback"]
    assert all(call.kwargs["sentence_translation"] == translation for call in word_call.call_args_list)
    assert not sentence_call.called and not segment_call.called
    assert baseline == original
    assert repaired["v2"]["word_items"][0] == original["v2"]["word_items"][0]
    assert repaired["v2"]["word_tips"] == {"rules": "保留提示"}
    for field in ("sentence_translation", "sentence_segments", "translation_segments", "quality_audit"):
        assert repaired["v2"][field] == original["v2"][field], field
    assert repaired["previous"] == original["previous"]
    assert repaired["repair"]["inherited_full_pipeline_candidate"] is True
    assert repaired["repair"]["executed_stages"] == ["word_cards"]

    segment_job = {**job, "stage": "segments", "words": []}
    with (
        patch.object(translator, "segment_translation", return_value={"sentence_segments": ["New rules"], "translation_segments": [translation]}) as segment_call,
        patch.object(translator, "translate_words") as word_call,
    ):
        segmented = repair._repair_one(segment_job, retries=0)
    assert segmented["status"] == "success", segmented
    assert segment_call.call_args.kwargs["feedback"] == job["feedback"]
    assert not word_call.called
    assert segmented["v2"]["sentence_segments"] == [source]
    assert segmented["v2"]["translation_segments"] == [translation]
    assert "safe_single_block_fallback" in segmented["repair"]["executed_stages"]

    new_translation = "新的规则适用。"
    full_result = {**copy.deepcopy(baseline["v2"]), "sentence_translation": new_translation, "translation_segments": [new_translation], "items": [rule_card, apply_card]}
    with patch.object(translator, "translate_text", return_value=full_result) as sentence_call:
        full = repair._repair_one({**job, "stage": "sentence", "words": []}, retries=0)
    assert full["status"] == "success", full
    assert full["v2"]["translation_segments"] == [new_translation]
    assert full["repair"]["inherited_full_pipeline_candidate"] is False
    assert sentence_call.call_args.kwargs["feedback"] == job["feedback"]

    with tempfile.TemporaryDirectory() as temp_dir:
        directory = Path(temp_dir)
        baseline_path = directory / "baseline.jsonl"
        repaired_path = directory / "repaired.jsonl"
        ledger_path = directory / "reviews.jsonl"
        routes_path = directory / "routes.json"
        baseline_path.write_text(json.dumps(baseline) + "\n", encoding="utf-8")
        repaired_path.write_text(json.dumps(repaired) + "\n", encoding="utf-8")
        rejected = {"report": baseline_path.name, "revision_requests": {"1": "source grounded feedback"}}
        accepted = {"report": baseline_path.name, "accepted_ids": [1]}
        ledger_path.write_text(json.dumps(rejected) + "\n" + json.dumps(accepted) + "\n", encoding="utf-8")
        assert repair._build_plan([baseline_path], ledger_path, {}) == {}
        assert set(finalize._accepted_candidates([baseline_path], ledger_path)) == {1}
        ledger_path.write_text(json.dumps(rejected) + "\n", encoding="utf-8")
        routes_path.write_text('{"1":{"stage":"words","words":["apply"]}}', encoding="utf-8")
        plan = repair._build_plan([baseline_path], ledger_path, repair._load_routes(routes_path))
        assert plan[1]["stage"] == "words" and plan[1]["words"] == ["apply"]
        assert plan[1]["feedback"] == rejected["revision_requests"]["1"]
        for route in ({1: {"stage": "words", "words": ["unknown"]}}, {1: {"stage": "words", "words": []}}):
            try:
                repair._build_plan([baseline_path], ledger_path, route)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid partial-stage selection accepted")
        routes_path.write_text('{"1":{"stage":"sentence"},"01":{"stage":"sentence"}}', encoding="utf-8")
        try:
            repair._load_routes(routes_path)
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate normalized route ids accepted")
        for reports in ([baseline_path], [baseline_path, repaired_path]):
            try:
                finalize._accepted_candidates(reports, ledger_path)
            except ValueError:
                pass
            else:
                raise AssertionError("unreviewed candidate was exportable")
        ledger_path.write_text(json.dumps({"report": repaired_path.name, "accepted_ids": [1]}) + "\n", encoding="utf-8")
        assert set(finalize._accepted_candidates([baseline_path, repaired_path], ledger_path)) == {1}
        for changed_field in ("previous", "evidence"):
            corrupted = copy.deepcopy(repaired)
            if changed_field == "previous":
                corrupted["previous"]["sentence_translation"] = "another snapshot"
            else:
                corrupted["v2"]["word_items"][0]["translation_quote"] = "不存在的引文"
            repaired_path.write_text(json.dumps(corrupted) + "\n", encoding="utf-8")
            try:
                finalize._accepted_candidates([baseline_path, repaired_path], ledger_path)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid {changed_field} was exportable")
        contract = {"plan_sha256": "expected"}
        resume_path = directory / "resume.jsonl"
        resume_path.write_text(json.dumps({"event": "repair_start", "contract": contract}) + "\n" + json.dumps(repaired) + "\n", encoding="utf-8")
        assert repair._validate_resume(resume_path, contract) == {1}
        try:
            repair._validate_resume(resume_path, {"plan_sha256": "changed"})
        except ValueError:
            pass
        else:
            raise AssertionError("changed repair contract accepted on resume")
        resume_path.write_text(resume_path.read_text(encoding="utf-8") + '{"event":', encoding="utf-8")
        try:
            repair._validate_resume(resume_path, contract)
        except ValueError:
            pass
        else:
            raise AssertionError("truncated report accepted on resume")


def check_translation_focus_reconciliation() -> None:
    reconcile = reconcile_translation_focus
    source = "New rules apply."
    translation = "新规则适用。"
    rules = {"word": "rules", "translation": "本义：规则；句中：规则", "source_quote": "rules", "translation_quote": "规则"}
    apply_word = {"word": "apply", "translation": "本义：适用；句中：适用", "source_quote": "apply", "translation_quote": "适用"}
    original = {
        "event": "translation", "status": "success", "id": 1, "report": "baseline.jsonl",
        "text": "New **rules** apply.", "source_text": source, "words": ["rules"],
        "context_before": [], "context_after": [],
        "previous": {"sentence_translation": "旧译文", "sentence_segments": [], "translation_segments": [], "word_translations": {"rules": "原释义"}, "word_tips": {}},
        "v2": {"sentence_translation": translation, "sentence_segments": [source], "translation_segments": [translation], "word_translations": {"rules": rules["translation"]}, "word_tips": {}, "word_items": [rules]},
    }
    row = {
        "id": 1, "text": "New **rules** **apply**.", "sentence_translation": "旧译文",
        "sentence_segments_json": "[]", "translation_segments_json": "[]",
        "word_translations_json": json.dumps({"rules": "原释义", "apply": ""}), "word_tips_json": "{}",
        "context_before": [], "context_after": [],
    }
    originals = {1: original}
    approvals = {("baseline.jsonl", 1): "accepted"}
    jobs = reconcile._focus_jobs(originals, originals, [row], approvals)
    assert list(jobs) == [1]
    with (
        patch.object(translator, "translate_words", return_value={"items": [apply_word], "word_translations": {"apply": apply_word["translation"]}, "word_tips": {}}) as words,
        patch.object(translator, "translate_text") as sentences,
        patch.object(translator, "segment_translation") as segments,
    ):
        event = reconcile._reconcile_one(jobs[1])
    assert words.call_args.kwargs["words"] == ["apply"]
    assert words.call_args.kwargs["sentence_translation"] == translation
    assert not sentences.called and not segments.called
    assert event["text"] == row["text"] and event["words"] == ["rules", "apply"]
    assert event["v2"]["sentence_translation"] == translation
    assert event["v2"]["sentence_segments"] == original["v2"]["sentence_segments"]
    assert event["v2"]["word_items"][0] == rules
    assert event["previous"]["word_translations"]["apply"] == ""
    assert event["focus_rebase"]["added_words"] == ["apply"]
    reconcile._validate_rebase_provenance(original, event)
    for changes in (
        {"text": "Old **rules** **apply**."},
        {"sentence_translation": "用户重新编辑的整句翻译"},
        {"word_translations_json": json.dumps({"rules": "用户修正的词义", "apply": ""})},
        {"word_tips_json": json.dumps({"rules": "用户新助记"})},
        {"context_before": ["New context."]},
    ):
        try:
            reconcile._focus_jobs(originals, originals, [{**row, **changes}], approvals)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe concurrent edit accepted: {changes}")
    corrupted = copy.deepcopy(event)
    corrupted["focus_rebase"]["current_snapshot_sha256"] = "changed"
    try:
        reconcile._validate_rebase_provenance(original, corrupted)
    except ValueError:
        pass
    else:
        raise AssertionError("altered focus-rebase snapshot was accepted")
    with tempfile.TemporaryDirectory() as temp_dir:
        directory = Path(temp_dir)
        baseline_path = directory / "baseline.jsonl"
        focus_path = directory / "focus.jsonl"
        ledger = directory / "reviews.jsonl"
        baseline_path.write_text(json.dumps(original) + "\n", encoding="utf-8")
        focus_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        ledger.write_text(json.dumps({"report": focus_path.name, "accepted_ids": [1]}) + "\n", encoding="utf-8")
        exported = finalize_translation_evaluation._accepted_candidates([baseline_path, focus_path], ledger)
        assert exported[1]["words"] == ["rules", "apply"]


def check_sentence_integrity() -> None:
    with get_connection() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT id, text, word_translations_json, word_tips_json, word_play_counts_json "
                "FROM english_sentences WHERE COALESCE(deleted_at, '') = ''"
            ).fetchall()
        ]
        conn.execute("SELECT COUNT(*) FROM english_review_rounds").fetchone()
        conn.execute("SELECT COUNT(*) FROM english_review_round_items").fetchone()
    identities = [repository.sentence_identity_key(row["text"]) for row in rows]
    assert len(identities) == len(set(identities)), "duplicate active English sentence identity"
    for row in rows:
        translations = _decode_json(row.get("word_translations_json"), {})
        tips = _decode_json(row.get("word_tips_json"), {})
        counts = _decode_json(row.get("word_play_counts_json"), {})
        translation_keys = {
            repository._normalize_focus_word(key)
            for key in translations
        }
        marked_keys = {
            repository._normalize_focus_word(surface)
            for surface in repository._marked_word_surfaces(row["text"])
        }
        assert translation_keys == marked_keys, row["id"]
        assert all(repository._normalize_focus_word(key) in translation_keys for key in tips), row["id"]
        assert all(repository._normalize_focus_word(key) in translation_keys for key in counts), row["id"]
    summary = repository.stats(user_id=1)
    lightweight_summary = repository.stats(user_id=1, include_word_network=False)
    assert "word_network" in summary, summary
    assert "word_network" not in lightweight_summary, lightweight_summary
    assert lightweight_summary["today"] == summary["today"], lightweight_summary
    today = summary["today"]
    assert "reviewed_sentences" in today, today
    assert int(today["reviewed_sentences"]) <= int(today["sentence_completions"]), today


def check_audio_assets() -> None:
    with get_connection() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM english_sentences
                WHERE COALESCE(deleted_at, '') = ''
                  AND audio_status = 'ready'
                """
            ).fetchall()
        ]
    for row in rows:
        audio_path = str(row["audio_path"] or "").strip()
        assert audio_path, dict(row)
        assert str(row.get("audio_provider") or "").strip(), row["id"]
        assert str(row.get("audio_voice") or "").strip(), row["id"]
        assert str(row.get("audio_hash") or "").strip(), row["id"]
        local_path = repository.ENGLISH_AUDIO_DIR / Path(audio_path).name
        assert local_path.is_file() and local_path.stat().st_size > 0, {
            "sentence_id": int(row["id"]),
            "path": audio_path,
        }


def check_kokoro_voice_catalog() -> None:
    catalog = repository.sentence_audio_voice_catalog()
    kokoro_voices = [item for item in catalog if item["provider"] == "kokoro"]
    assert len(kokoro_voices) == 28, len(kokoro_voices)
    assert len({item["voice"] for item in kokoro_voices}) == 28
    assert all(item["available"] for item in kokoro_voices), [
        item["voice"] for item in kokoro_voices if not item["available"]
    ]
    assert audio_generation._kokoro_language_code("af_heart") == "a"
    assert audio_generation._kokoro_language_code("bf_emma") == "b"


def check_kokoro_sentence_loudness_normalization() -> None:
    try:
        import numpy as np
        import soundfile  # noqa: F401 - availability gate for optional Kokoro checks.
    except ImportError:
        # Kokoro is optional; an Edge-only installation has no waveform to normalize.
        return

    from app.english.audio_generation import (
        DEFAULT_KOKORO_SAMPLE_RATE,
        KOKORO_TARGET_LOUDNESS_LUFS,
        KOKORO_TARGET_TRUE_PEAK_DBFS,
        _write_kokoro_audio,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        output_path = root / "normalized.wav"
        seconds = 5
        timeline = np.arange(DEFAULT_KOKORO_SAMPLE_RATE * seconds) / DEFAULT_KOKORO_SAMPLE_RATE
        # A quiet body plus an isolated high peak reproduces the shape that
        # fooled the old peak-only normalization.
        samples = (0.025 * np.sin(2 * np.pi * 220 * timeline)).astype(np.float32)
        samples[DEFAULT_KOKORO_SAMPLE_RATE] = 0.9
        _write_kokoro_audio(samples, output_path)

        measured = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(output_path),
                "-af",
                "loudnorm=I=-16:TP=-1:LRA=7:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        report_start = measured.stderr.rfind("{")
        report_end = measured.stderr.rfind("}") + 1
        assert report_start >= 0 and report_end > report_start, measured.stderr
        report = json.loads(measured.stderr[report_start:report_end])
        integrated_lufs = float(report["input_i"])
        true_peak_dbfs = float(report["input_tp"])
        assert abs(integrated_lufs - KOKORO_TARGET_LOUDNESS_LUFS) <= 2.0, report
        assert true_peak_dbfs <= KOKORO_TARGET_TRUE_PEAK_DBFS + 0.1, report


def check_dedicated_ai_configuration() -> None:
    names = (
        "STUDY_ENGLISH_AI_BASE_URL",
        "STUDY_ENGLISH_AI_API_KEY",
        "STUDY_ENGLISH_AI_MODEL",
        "STUDY_ENGLISH_AI_TEMPERATURE",
        "STUDY_ENGLISH_AI_MAX_TOKENS",
        "STUDY_ENGLISH_AI_TIMEOUT_SECONDS",
    )
    original = {name: os.environ.get(name) for name in names}
    try:
        os.environ["STUDY_ENGLISH_AI_BASE_URL"] = "https://ai.example/v1"
        os.environ["STUDY_ENGLISH_AI_API_KEY"] = "test-key"
        os.environ["STUDY_ENGLISH_AI_MODEL"] = "provider/deepseek-v4-pro"
        os.environ["STUDY_ENGLISH_AI_MAX_TOKENS"] = "1200"
        options = translator._english_ai_options()
        assert options["base_url"] == "https://ai.example/v1", options
        assert options["api_key"] == "test-key", options
        assert options["model"] == "provider/deepseek-v4-pro", options
        assert "max_tokens" not in options, options

        # Generic subject variables must never become an English fallback.
        os.environ["STUDY_AI_MODEL"] = "wrong-subject-model"
        assert translator._english_ai_options()["model"] == "provider/deepseek-v4-pro"
        os.environ["STUDY_ENGLISH_AI_TEMPERATURE"] = "not-a-number"
        try:
            translator._english_ai_options()
        except translator.AIProviderError as exc:
            assert "温度参数" in exc.user_message, exc.user_message
        else:
            raise AssertionError("invalid English AI temperature must be controlled")
    finally:
        os.environ.pop("STUDY_AI_MODEL", None)
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_translation_requires_dedicated_ai_configuration() -> None:
    names = (
        "STUDY_ENGLISH_AI_BASE_URL",
        "STUDY_ENGLISH_AI_API_KEY",
        "STUDY_ENGLISH_AI_MODEL",
    )
    original = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        assert translator.translation_configured() is False
        try:
            translator._english_ai_options()
        except translator.AIProviderError as exc:
            assert "英语翻译 AI 服务未完整配置" in exc.user_message, exc.user_message
        else:
            raise AssertionError("translation must not fall back to a generic AI gateway")
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_library_metadata() -> None:
    assert repository._stored_sentence_audio_identity(
        {
            "audio_path": "sentence_724_kokoro_af_heart.mp3",
            "audio_provider": "",
            "audio_voice": "",
        }
    ) == ("kokoro", "af_heart")
    assert repository._stored_sentence_audio_identity(
        {
            "audio_path": "sentence_724_kokoro_af_heart_deadbeefcafebabe.wav",
            "audio_provider": "",
            "audio_voice": "",
        }
    ) == ("kokoro", "af_heart")
    assert repository._stored_sentence_audio_identity(
        {
            "audio_path": "sentence_724_kokoro_af_heart.wav",
            "audio_provider": "edge",
            "audio_voice": "custom-voice",
        }
    ) == ("edge", "custom-voice")

    rows = [
        {
            "id": 1,
            "text": "A **shared** word appears here.",
            "word_translations_json": '{"shared":"句中：共同的"}',
            "word_play_counts_json": "{}",
            "review_count": 0,
        },
        {
            "id": 2,
            "text": "This is another **shared** example.",
            "word_translations_json": '{"shared":"句中：共同的"}',
            "word_play_counts_json": "{}",
            "review_count": 0,
        },
    ]
    metrics = sentence_word_network_metrics(rows)
    assert metrics[1]["linked_words"][0]["linked_sentences"] == 2, metrics
    assert metrics[2]["linked_words"][0]["key"] == "shared", metrics


def check_split_translation_pipeline() -> None:
    sentence = "People [人们] often complain that **plastics** are too **durable**."
    context_before = ["Earlier researchers discussed **plastic** waste. [仅作背景]"]
    context_after = ["The next sentence changes to recycling policy."]
    responses = [
        {"sentence_translation": "人们抱怨塑料太耐用。"},
        {"sentence_translation": "人们常常抱怨塑料过于耐用。"},
        {
            "words": [
                {"word": "plastics", "base_translation": "塑料", "context_translation": "塑料", "english_definition": "artificial materials that can be shaped when soft", "source_quote": "plastics", "translation_quote": "塑料", "tip": ""},
                {"word": "durable", "base_translation": "耐用的", "context_translation": "难以降解的", "english_definition": "able to last a long time without breaking down", "source_quote": "too durable", "translation_quote": "过于耐用", "tip": ""},
            ],
        },
        {
            "sentence_segments": ["People often complain that plastics are too durable."],
            "translation_segments": ["人们常常抱怨塑料过于耐用。"],
        },
    ]
    calls: list[list[dict]] = []
    original_chat = translator._chat_completion
    original_options = translator._english_ai_options
    fake_options = {
        "base_url": "https://ai.example/v1",
        "api_key": "test-key",
        "model": "test-model",
    }

    def fake_chat(messages, **_kwargs):
        calls.append(messages)
        return json.dumps(responses[len(calls) - 1], ensure_ascii=False)

    translator._chat_completion = fake_chat
    translator._english_ai_options = lambda: dict(fake_options)
    try:
        result = translator.translate_text(
            sentence,
            words=["plastics", "durable"],
            context_before=context_before,
            context_after=context_after,
        )
    finally:
        translator._chat_completion = original_chat
        translator._english_ai_options = original_options
    assert len(calls) == 4, len(calls)
    assert result["sentence_translation"] == "人们常常抱怨塑料过于耐用。", result
    assert result["word_translations"]["durable"] == "本义：耐用的；句中：难以降解的；英文：able to last a long time without breaking down", result
    first_prompt = calls[0][-1]["content"]
    assert "People often complain that plastics are too durable." in first_prompt, first_prompt
    assert "[人们]" not in first_prompt and "**plastics**" not in first_prompt, first_prompt
    assert "Earlier researchers discussed plastic waste." in first_prompt, first_prompt
    assert "[仅作背景]" not in first_prompt, first_prompt
    assert "<target_sentence>People often complain" in first_prompt, first_prompt
    assert "相邻项可能来自另一道题或另一篇文章" in first_prompt, first_prompt
    assert "Earlier researchers discussed plastic waste." in calls[1][-1]["content"], calls[1]
    assert "Earlier researchers discussed plastic waste." in calls[2][-1]["content"], calls[2]
    assert "neurology 是“神经学”" in calls[2][-1]["content"], calls[2]
    assert "<approved_translation>人们常常抱怨塑料过于耐用。</approved_translation>" in calls[2][-1]["content"], calls[2]
    assert "Earlier researchers discussed plastic waste." not in calls[3][-1]["content"], calls[3]

    hyphen_marker_result = {
        "sentence_translation": "一种不置可否的凝视成了常态。",
        "sentence_segments": ["A non-committal blank stare became the norm."],
        "translation_segments": ["一种不置可否的凝视成了常态。"],
        "word_translations": {},
        "word_tips": {},
    }
    hyphen_issues = translator.translation_result_issues(
        hyphen_marker_result,
        [],
        source_text="A non-**committal** blank stare became the norm.",
    )
    assert "source_segment_coverage_mismatch" not in hyphen_issues, hyphen_issues

    # Compact cuts must retain opening punctuation, and a cut immediately
    # before a verb complement must be rejected rather than displayed as a
    # misleading ``results / in fines`` pair.
    compact = translator._compact_segment_payload(
        '"pathological gambling" involves risks.',
        {"cut_after": [2, 4], "translation_segments": ["“病理性赌博”", "涉及风险。"]},
    )
    assert compact and compact["sentence_segments"][0].startswith('"pathological'), compact
    aligned_attribution = translator._translation_aligned_for_final_attribution(
        "This may backfire, said Minson.",
        "明森说，这可能会适得其反。",
    )
    assert aligned_attribution == "这可能会适得其反，明森说。", aligned_attribution
    aligned_according = translator._translation_aligned_for_final_attribution(
        "Eye contact increased avoidance, according to Finnish researchers.",
        "据芬兰研究人员，眼神接触增强了回避反应。",
    )
    assert aligned_according == "眼神接触增强了回避反应，芬兰研究人员称。", aligned_according
    incomplete_cut_issues = translator.translation_result_issues(
        {
            "sentence_translation": "估计结果会导致罚款。",
            "sentence_segments": ["The plan results", "in fines."],
            "translation_segments": ["该计划的结果", "会导致罚款。"],
            "word_translations": {},
            "word_tips": {},
        },
        [],
        source_text="The plan results in fines.",
    )
    assert any(item.startswith("incomplete_sentence_segment_suffix:") for item in incomplete_cut_issues), incomplete_cut_issues

    # A complete noun ending in 为 must not be mistaken for the bare
    # preposition 为.
    complete_word_issues = translator.translation_result_issues(
        {
            "sentence_translation": "这是一种行为。",
            "sentence_segments": ["This is a behavior."],
            "translation_segments": ["这是一种行为。"],
            "word_translations": {},
            "word_tips": {},
        },
        [],
        source_text="This is a behavior.",
    )
    assert not any(item.startswith("bad_translation_segment_suffix:") for item in complete_word_issues), complete_word_issues

    fallback_responses = [
        {"sentence_translation": "人们常常抱怨塑料过于耐用。"},
        {"sentence_translation": "人们常常抱怨塑料过于耐用。"},
        responses[2],
        {"sentence_segments": [], "translation_segments": []},
        {"sentence_segments": [], "translation_segments": []},
        {"sentence_segments": [], "translation_segments": []},
        {"sentence_segments": [], "translation_segments": []},
    ]
    fallback_calls = 0

    def fallback_chat(_messages, **_kwargs):
        nonlocal fallback_calls
        response = fallback_responses[fallback_calls]
        fallback_calls += 1
        return json.dumps(response, ensure_ascii=False)

    translator._chat_completion = fallback_chat
    translator._english_ai_options = lambda: dict(fake_options)
    try:
        fallback_result = translator.translate_text(sentence, words=["plastics", "durable"])
    finally:
        translator._chat_completion = original_chat
        translator._english_ai_options = original_options
    assert fallback_calls == 7, fallback_calls
    assert fallback_result["sentence_segments"] == ["People often complain that plastics are too durable."], fallback_result
    assert fallback_result["translation_segments"] == ["人们常常抱怨塑料过于耐用。"], fallback_result

    failed_calls = 0

    def failing_chat(_messages, **_kwargs):
        nonlocal failed_calls
        failed_calls += 1
        raise translator.AIProviderError("AI 服务网络请求失败", "AI provider HTTP 500")

    translator._chat_completion = failing_chat
    translator._english_ai_options = lambda: dict(fake_options)
    try:
        try:
            translator.translate_text(sentence, words=["plastics", "durable"])
        except translator.AIProviderError:
            pass
        else:
            raise AssertionError("provider failure was unexpectedly accepted")
    finally:
        translator._chat_completion = original_chat
        translator._english_ai_options = original_options
    assert failed_calls == 3, failed_calls

    word_only_calls = 0

    def word_only_chat(_messages, **_kwargs):
        nonlocal word_only_calls
        word_only_calls += 1
        return json.dumps(
            {
                "words": [
                    {
                        "word": "durable",
                        "base_translation": "耐用的",
                        "context_translation": "难以降解的",
                        "english_definition": "able to last a long time without breaking down",
                        "source_quote": "too durable",
                        "tip": "durable = dur + able",
                    }
                ]
            },
            ensure_ascii=False,
        )

    translator._chat_completion = word_only_chat
    translator._english_ai_options = lambda: dict(fake_options)
    try:
        word_only_result = translator.translate_words(sentence, words=["durable"])
    finally:
        translator._chat_completion = original_chat
        translator._english_ai_options = original_options
    assert word_only_calls == 1, word_only_calls
    assert word_only_result["word_translations"] == {
        "durable": "本义：耐用的；句中：难以降解的；英文：able to last a long time without breaking down"
    }, word_only_result
    assert "sentence_translation" not in word_only_result, word_only_result


def check_translation_request_policy_and_evidence() -> None:
    clock = [0.0]
    calls = []

    def sleep(seconds):
        clock[0] += seconds

    def completion(_messages, **_kwargs):
        calls.append(clock[0])
        if len(calls) == 1:
            raise translator.AIProviderError("限流", 'AI provider HTTP 429: {"data":{"retryAfterSeconds":44}}')
        return "ok"

    options = {"base_url": "https://rate-test.invalid/v1", "api_key": "private-test-key", "model": "test"}
    with patch.dict(os.environ, {"STUDY_ENGLISH_AI_REQUESTS_PER_MINUTE": "20", "STUDY_ENGLISH_AI_MAX_RETRIES": "2"}), patch.dict(
        translation_transport._gates, {}, clear=True
    ), patch.object(translation_transport.time, "monotonic", lambda: clock[0]), patch.object(translation_transport.time, "sleep", sleep):
        assert translation_transport.translation_completion([], options=options, completion=completion) == "ok"
        assert translation_transport.translation_completion([], options=options, completion=completion) == "ok"
        assert calls == [0.0, 60.25, 63.25], calls
        forbidden_calls = []

        def forbidden(_messages, **_kwargs):
            forbidden_calls.append(True)
            raise translator.AIProviderError("密钥无效", "AI provider HTTP 401: private-test-key")

        try:
            translation_transport.translation_completion([], options=options, completion=forbidden)
        except translator.AIProviderError as exc:
            assert "private-test-key" not in exc.diagnostic, exc.diagnostic
        else:
            raise AssertionError("authentication error was accepted")
        assert len(forbidden_calls) == 1, forbidden_calls

    candidate = {
        "word_translations": {"measure": "本义：措施；句中：措施"},
        "word_evidence_required": True,
        "items": [{"word": "measure", "source_quote": "a measure", "translation_quote": "一项措施"}],
    }
    assert not translator.word_translation_issues(candidate, ["measure"], source_text="Adopt a **measure**.", sentence_translation="通过一项措施。")
    candidate["items"][0]["translation_quote"] = "法案"
    assert any(issue.startswith("bad_word_evidence:measure:translation_quote") for issue in translator.word_translation_issues(
        candidate, ["measure"], source_text="Adopt a measure.", sentence_translation="通过一项措施。"
    ))
    candidate["items"][0]["source_quote"] = "a measurement"
    assert "bad_word_evidence:measure:source_quote" in translator.word_translation_issues(candidate, ["measure"], source_text="Adopt a measure.")
    assert translator.word_translation_issues({"word_translations": {"measure": "本义：；句中：措施"}}, ["measure"])
    assert translator._compose_word_translation({"base_translation": "本义：本义：措施", "context_translation": "句中：句中：措施"}) == "本义：措施；句中：措施"
    assert translator._compose_word_translation({"base_translation": "margin: 利润；利润", "context_translation": "利润率"}) == "本义：利润；句中：利润率"
    assert expand_unique_quote("不受……的影响", "仍然不受这个国家同化力量的影响。") == "不受这个国家同化力量的影响"
    assert expand_unique_quote("不受……影响", "不受风影响，也不受雨影响") == "不受……影响"
    assert expand_unique_quote("不受……影响", "没有相关内容") == "不受……影响"
    assert expand_unique_quote("……影响", "产生影响") == "……影响"
    phrase = {"items": [{"word": "slot", "translation": "本义：狭槽；句中：老虎机", "source_quote": "slot machine", "translation_quote": "老虎机"}], "word_translations": {}}
    ground_word_cards(phrase, "He lost money to one slot machine.", "他在一台老虎机上输钱。")
    assert phrase["word_translations"]["slot"] == "本义：狭槽；句中：用于 slot machine，整体意为老虎机", phrase
    neutral = {"items": [{"word": "suit", "translation": "本义：花色；句中：跟出同花色的牌"}], "word_translations": {}}
    ground_word_cards(neutral, "You must follow suit in this card game.", "你必须跟出同花色的牌。")
    assert "效仿" not in neutral["word_translations"]["suit"], neutral
    negative = {"items": [{"word": "Sustainable", "translation": "本义：可持续的；句中：难以为继"}], "word_translations": {}}
    ground_word_cards(negative, "Ever-rising fares aren't sustainable.", "不断上涨的票价难以为继。")
    assert negative["word_translations"]["Sustainable"] == "本义：可持续的；句中：可持续的（本句否定结构表示不可持续）", negative
    modifier = {"items": [{"word": "checked-baggage", "translation": "本义：托运行李；句中：托运行李费"}], "word_translations": {}}
    ground_word_cards(modifier, "Avoid checked-baggage fees.", "避免托运行李费。")
    assert "句中：托运行李的（修饰 fees" in modifier["word_translations"]["checked-baggage"], modifier
    granted = {"items": [{"word": "granted", "translation": "本义：认为理所当然；句中：用于 take for granted，意为视为理所当然"}], "word_translations": {}}
    ground_word_cards(granted, "He takes his code for granted.", "他将准则视为理所当然。")
    assert granted["word_translations"]["granted"].startswith("本义：给予；承认；句中："), granted
    metaphor = {"items": [{"word": "police", "translation": "本义：警察；句中：监管机构"}], "word_translations": {}}
    ground_word_cards(metaphor, "The food police object.", "饮食卫士反对。")
    assert "比喻对他人饮食进行说教的人" in metaphor["word_translations"]["police"], metaphor
    candidate["items"][0] = {"word": "measure", "source_quote": "Adopt a measure", "translation_quote": "一项措施"}
    assert not translator.word_translation_issues(candidate, ["measure"], source_text="Adopt [采用] a **measure**.", sentence_translation="通过一项措施。")

    anchored = translator._anchored_segment_payload(
        "First we listen, then we act.",
        "先听，再行动。",
        {"source_breaks": ["we listen,"], "translation_breaks": ["先听，"]},
    )
    assert anchored == {"sentence_segments": ["First we listen,", "then we act."], "translation_segments": ["先听，", "再行动。"]}, anchored
    assert translator._anchored_segment_payload("We act.", "我们行动。", {"source_breaks": [], "translation_breaks": []}) == {
        "sentence_segments": ["We act."], "translation_segments": ["我们行动。"]
    }
    assert translator._segments_from_anchors("We act, then we act again.", ["act"]) is None
    assert translator._segments_from_anchors("We act.", ["We act."]) is None
    assert translator._segments_from_anchors("We act.", ["We work"]) is None
    assert translator._anchored_segment_payload("First we listen, then we act.", "先听，再行动。", {
        "source_breaks": ["we listen,"], "translation_breaks": ["先行动，"]
    }) is None
    for auxiliary in ("should", "must", "do", "could"):
        issues = translator.translation_result_issues({
            "sentence_translation": "他们应当认真评估这件事。",
            "sentence_segments": [f"They {auxiliary}", "evaluate the matter carefully."],
            "translation_segments": ["他们应当", "认真评估这件事。"],
            "word_translations": {},
        }, [], source_text=f"They {auxiliary} evaluate the matter carefully.")
        assert any("auxiliary" in issue for issue in issues), issues
    with patch.object(translator, "translation_completion", side_effect=AssertionError("Reordered conditions must stay together")):
        conditional = translator.segment_translation(
            "It succeeds only if it maintains its image or grows over time.",
            "它只有在维护形象或持续发展时才会成功。",
        )
    assert len(conditional["sentence_segments"]) == len(conditional["translation_segments"]) == 1, conditional
    assert translator.translation_result_issues({
        "sentence_translation": "一些人担心，住在美国的移民仍不受影响。",
        "sentence_segments": ["Some fear that immigrants living within the United States", "remain immune."],
        "translation_segments": ["一些人担心，住在美国的移民", "仍不受影响。"],
        "word_translations": {},
    }, [], source_text="Some fear that immigrants living within the United States remain immune.")
    for source, target, marker in (
        ("The bill is doing the rounds.", "法案正在流传审议。", "doing_the_rounds"),
        ("She is ready for the move.", "她已经做好心理和实际准备。", "ready_for"),
        ("He could not confide them to his wife.", "他不愿向妻子吐露这些事。", "could_not_confide"),
        ("They frankly dislike the actors.", "他们表示不喜欢演员。", "frankly_attitude"),
        ("They face a cascade of different taxes.", "他们面临接连不同税种。", "cascade"),
        ("It can be less of a setback.", "它不太会成为挫折。", "degree_changed_to_probability"),
        ("The mystery is that this should come as a surprise to any boss.", "令人费解的是这会让任何老板都惊讶。", "any_under_modal"),
        ("It is a painful reminder.", "它痛苦地提醒着人们。", "painful_reminder"),
        ("The occupation of what was once a sovereign nation.", "他们曾为主权国家如今却被占领。", "sovereign_nation"),
    ):
        issues = translator.translation_result_issues({
            "sentence_translation": target, "sentence_segments": [source], "translation_segments": [target], "word_translations": {},
        }, [], source_text=source)
        assert any(issue.startswith(f"literal_translation:{marker}") for issue in issues), issues


def check_independent_structure_review() -> None:
    source = "They have viewed its presence as an insult and a painful reminder of the past."
    assert "view" in translator._structure_review_hint(source)
    assert "emergence" in translator._structure_review_hint(
        "The rise of art tracks the emergence of media, and with it, a commercial culture."
    )
    assert not translator._structure_review_hint("The new rules apply.")
    audit = {}
    approved = "他们将它的存在视为一种侮辱，也视为对往事的沉痛提醒。"
    with patch.object(translator, "_json_from_chat", return_value={"structure": "两个补语共用一个对象", "sentence_translation": approved}) as completion:
        actual = translator._review_sentence_only(source, "不应作为重译依据的草稿", audit=audit, context_before=["A telescope stands there."])
    prompt = json.dumps(completion.call_args.args[0], ensure_ascii=False)
    assert actual == approved
    assert "不应作为重译依据的草稿" not in prompt
    assert "A telescope stands there." in prompt
    assert audit["review_strategy"] == "independent_source_structure"
    with patch.object(translator, "_json_from_chat", return_value={"sentence_translation": ""}):
        try:
            translator._review_sentence_only(source, approved)
        except translator.AIProviderError:
            pass
        else:
            raise AssertionError("An empty structural review was accepted")
    audit = {}
    grounded = translator.ground_sentence_terms(
        "A vocal group of Hawaiians viewed their presence as disrespect for sacred land.",
        "一个立场坚定的夏威夷人群体将他们的存在视为对圣地的不敬。",
        context_before=["The telescopes were built on the mountain."],
        audit=audit,
    )
    assert grounded == "一个积极发声的夏威夷人群体将这些望远镜的存在视为对圣地的不敬。", grounded
    assert len(audit["term_repairs"]) == 2, audit
    assert translator.ground_sentence_terms(
        "Hawaiians viewed their presence as disrespect for sacred land and a reminder of what was once a sovereign nation.",
        "他们将（望远镜在山上的）存在视为对圣地的不敬，以及对一个曾经主权国家被占领的提醒。",
        context_before=["The telescopes were built on the mountain."],
    ) == "他们将这些望远镜的存在视为对圣地的不敬，以及对一个曾经的主权国家被占领的提醒。"
    assert translator.ground_sentence_terms("They noticed their presence.", "他们注意到他们的存在。") == "他们注意到他们的存在。"
    assert translator.ground_sentence_terms("A firm and vocal group objected.", "一个立场坚定且敢于发声的群体表示反对。") == "一个立场坚定且敢于发声的群体表示反对。"
    with patch.object(translator, "translation_completion", side_effect=AssertionError("Complex shared complements must remain aligned")):
        result = translator.segment_translation(source, approved)
    assert result["sentence_segments"] == [source]
    assert result["translation_segments"] == [approved]


def check_focused_word_card_repairs() -> None:
    approved_translation = "新规则适用。"
    original = {
        "items": [
            {"word": "rules", "translation": "本义：规则；句中：规则；英文：instructions about what people may do", "source_quote": "rules", "translation_quote": "规则"},
            {"word": "apply", "translation": "本义：适用；句中：适用；英文：be relevant to a situation", "source_quote": "apply", "translation_quote": "执行"},
        ],
        "word_translations": {"rules": "本义：规则；句中：规则；英文：instructions about what people may do", "apply": "本义：适用；句中：适用；英文：be relevant to a situation"},
        "word_tips": {"apply": "旧提示"},
        "word_evidence_required": True,
    }
    repairs = [
        {
            "items": [{"word": "apply", "translation": "本义：适用；句中：适用；英文：be relevant to a situation", "source_quote": "apply", "translation_quote": quote}],
            "word_translations": {"apply": "本义：适用；句中：适用；英文：be relevant to a situation"},
            "word_tips": {},
            "word_evidence_required": True,
        }
        for quote in ("生效", "适用")
    ]
    preserved_card = dict(original["items"][0])
    with patch.object(translator, "_translate_words_only", side_effect=[original, *repairs]) as generate:
        result = translator._translate_verified_words("New rules apply.", ["rules", "apply"], sentence_translation=approved_translation, feedback="原始词卡审阅要求")
    assert [call.args[1] for call in generate.call_args_list] == [["rules", "apply"], ["apply"], ["apply"]]
    assert all(call.kwargs["sentence_translation"] == approved_translation for call in generate.call_args_list)
    assert all("原始词卡审阅要求" in call.kwargs.get("feedback", "") for call in generate.call_args_list)
    assert result["items"][0] == preserved_card
    assert [item["word"] for item in result["items"]] == ["rules", "apply"]
    assert result["items"][1]["translation_quote"] == "适用"
    assert not result["word_tips"]
    with patch.object(translator, "_translate_words_only", side_effect=lambda *_args, **_kwargs: json.loads(json.dumps(repairs[0]))) as generate:
        try:
            translator._translate_verified_words("New rules apply.", ["apply"], sentence_translation=approved_translation)
        except translator.TranslationQualityError as exc:
            assert "bad_word_evidence:apply" in exc.diagnostic
            assert exc.candidate["sentence_translation"] == approved_translation
        else:
            raise AssertionError("Repeated ungrounded word cards were accepted")
    assert generate.call_count == 3


def check_english_word_definitions() -> None:
    chinese = "本义：平易近人的；句中：平易近人"
    meaning = chinese + "；英文：friendly and easy to talk to"
    payload = {"words": [
        {"word": "approachable", "base_translation": "平易近人的", "context_translation": "平易近人", "english_definition": "英文：friendly and\neasy to talk to", "source_quote": "approachable", "translation_quote": "平易近人"},
        {"word": "stylish", "base_translation": "时尚的", "context_translation": "时尚的", "source_quote": "stylish", "translation_quote": "时尚"},
    ]}
    repaired = {"words": [{**payload["words"][1], "english_definition": "fashionable and attractive in appearance"}]}
    with patch.object(translator, "_json_from_chat", side_effect=[payload, repaired]) as generate:
        result = translator.translate_words("She is approachable and stylish.", words=["approachable", "stylish"], sentence_translation="她平易近人又时尚。")
    assert generate.call_count == 2
    assert "单词列表：stylish" in generate.call_args.args[0][-1]["content"]
    assert set(result) == {"items", "word_translations", "word_tips"}, result
    assert result["word_translations"]["approachable"] == meaning
    assert result["items"][0]["translation"] == meaning
    assert set(result["items"][0]) == {"word", "translation", "source_quote", "translation_quote"}
    assert not translator.word_translation_issues(result, ["approachable", "stylish"], require_english_definition=True)

    legacy = {"word_translations": {"approachable": chinese}}
    assert not translator.word_translation_issues(legacy, ["approachable"])
    assert translator.word_translation_issues(legacy, ["approachable"], require_english_definition=True)[0].startswith("missing_word_english_definition:")
    for invalid in ("", "friendly", "approachable", "friendly and 平易近人", "friendly；英文：easy to talk to"):
        candidate = {"word_translations": {"approachable": chinese + "；英文：" + invalid}}
        assert any(issue.startswith("bad_word_english_definition:") for issue in translator.word_translation_issues(candidate, ["approachable"])), invalid
    assert translator.word_translation_issues({"word_translations": {"approachable": "本义：平易近人的；句中：；英文：friendly and easy to talk to"}}, ["approachable"])[0].startswith("bad_word_translation_format:")

    for word, text, target, original, expected, english in (
        ("slot", "He uses a slot machine.", "他使用一台老虎机。", "本义：狭槽；句中：老虎机", "用于 slot machine，整体意为老虎机", "part of slot machine, a machine used for gambling"),
        ("rests", "Good governance rests on an understanding of human worth.", "良好的治理建立在对人的价值的认识之上。", "本义：休息；句中：依赖于", "用于 rest on，表示以……为基础", "used with on to mean being based on something"),
        ("individual", "the worth of each individual", "每个人的价值", "本义：个人；句中：每个人", "个人（each 表示“每个”）", "a single person"),
    ):
        phrase = {"items": [{"word": word, "translation": original + "；英文：" + english}], "word_translations": {}}
        ground_word_cards(phrase, text, target)
        assert phrase["word_translations"][word].endswith("；句中：" + expected + "；英文：" + english), phrase

    from app.english.api import EnglishSentencePayload

    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            old_payload = EnglishSentencePayload(text="She is **approachable**.", word_translations={"approachable": chinese}, sentence_translation="她平易近人。")
            created = repository.create_sentence(**old_payload.model_dump())
            assert created["translation_pending"] is False
            new_payload = old_payload.model_copy(update={"word_translations": {"approachable": meaning}})
            updated = repository.update_sentence(sentence_id=created["id"], **new_payload.model_dump())
            assert set(updated) == set(created)
            assert updated["word_translations"] == {"approachable": meaning}
            assert updated["sentence_translation"] == created["sentence_translation"]
            assert updated["translation_pending"] is False
    finally:
        platform_db.DB_PATH = original_path


def check_legacy_english_definition_backfill() -> None:
    backfill = backfill_english_definitions
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            chinese = "本义：先前的；以往的；句中：此前的"
            created = repository.create_sentence(
                text="**Previous** studies were useful.",
                word_translations={"Previous": chinese},
                sentence_translation="此前的研究很有用。",
                sentence_segments=["Previous studies were useful."],
                translation_segments=["此前的研究很有用。"],
            )
            identifier = created["id"]
            rows = backfill._load_rows({identifier})
            card = {"word": "Previous", "source_quote": "Previous studies",
                    "english_definition": "existing or happening before this time"}
            payload = {"sentences": [{"id": identifier, "words": [card]}]}
            validated = backfill._validate_batch(rows, payload)
            punctuated = {"id": 999, "text": "They prefer **bone-showing.**", "words": {"bone-showing.": "显露骨骼的"}}
            punctuated_card = {"word": "bone-showing.", "source_quote": "bone-showing",
                               "english_definition": "so thin that bones are visible"}
            assert backfill._validate_batch([punctuated], {
                "sentences": [{"id": 999, "words": [punctuated_card]}]
            })[999][0]["word"] == "bone-showing."
            for invalid in (
                {"sentences": []},
                {"sentences": [{"id": identifier, "words": [card, card]}]},
                {"sentences": [{"id": identifier, "words": [{**card, "source_quote": "Previous research"}]}]},
                {"sentences": [{"id": identifier, "words": [{**card, "english_definition": "earlier"}]}]},
                {"sentences": [{"id": identifier, "words": [{**card, "english_definition": "existing 在之前"}]}]},
            ):
                try:
                    backfill._validate_batch(rows, invalid)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid backfill candidate was accepted")

            # A study event occurring during generation must survive the append.
            with get_connection() as conn:
                conn.execute(
                    "UPDATE english_sentences SET word_play_total = 7, word_play_counts_json = ? WHERE id = ?",
                    (json.dumps({"Previous": 7}), identifier),
                )
                before = dict(conn.execute("SELECT * FROM english_sentences WHERE id = ?", (identifier,)).fetchone())
            assert backfill._apply_row(rows[0], validated[identifier])
            with get_connection() as conn:
                after = dict(conn.execute("SELECT * FROM english_sentences WHERE id = ?", (identifier,)).fetchone())
            assert all(after[key] == before[key] for key in before if key not in {"word_translations_json", "updated_at"})
            assert json.loads(after["word_translations_json"]) == {
                "Previous": chinese + "；英文：" + card["english_definition"]
            }
            assert not backfill._apply_row(rows[0], validated[identifier]), "replaying an old result must be harmless"
            assert backfill._load_rows({identifier}) == []

            # Concurrent edits to Chinese or the source invalidate a generated result.
            for column, value in (("text", "**Previous** findings were useful."),
                                  ("sentence_translation", "用户自己修改的整句译文。"),
                                  ("word_translations_json", json.dumps({"Previous": "用户自己修改的词义"}))):
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE english_sentences SET text = ?, sentence_translation = ?, word_translations_json = ? WHERE id = ?",
                        (rows[0]["text"], rows[0]["sentence_translation"], rows[0]["word_translations_json"], identifier),
                    )
                    conn.execute(f"UPDATE english_sentences SET {column} = ? WHERE id = ?", (value, identifier))
                assert not backfill._apply_row(rows[0], validated[identifier])
                with get_connection() as conn:
                    untouched = dict(conn.execute("SELECT * FROM english_sentences WHERE id = ?", (identifier,)).fetchone())
                assert untouched[column] == value
                assert "；英文：" not in untouched["word_translations_json"]
    finally:
        platform_db.DB_PATH = original_path


def check_edit_translation_invalidation() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            created = repository.create_sentence(
                text="The **old** sentence is here.",
                word_translations={"old": "本义：旧的；句中：旧的"},
                sentence_translation="旧句子在这里。",
                sentence_segments=["The old sentence is here."],
                translation_segments=["旧句子在这里。"],
            )
            updated = repository.update_sentence(
                sentence_id=int(created["id"]),
                text="The **new** sentence is here.",
                word_translations=created["word_translations"],
                sentence_translation=created["sentence_translation"],
                sentence_segments=created["sentence_segments"],
                translation_segments=created["translation_segments"],
            )
            assert updated and updated["translation_pending"] is True, updated
            assert updated["sentence_translation"] == "", updated
            assert updated["word_translations"] == {"new": ""}, updated
            result = {
                "sentence_translation": "新句子在这里。",
                "sentence_segments": ["The new sentence is here."],
                "translation_segments": ["新句子在这里。"],
                "word_translations": {"new": "本义：新的；句中：新的", "old": "不应写回"},
                "word_tips": {},
            }
            assert not translation_generation._apply_translation_if_still_missing(
                int(created["id"]),
                result,
                expected_text="stale source",
            )
            assert translation_generation._apply_translation_if_still_missing(
                int(created["id"]),
                result,
                expected_text="The **new** sentence is here.",
            )
            refreshed = repository.get_sentence(int(created["id"]))
            assert refreshed and refreshed["word_translations"] == {
                "new": "本义：新的；句中：新的"
            }, refreshed
            following_one = repository.create_sentence(text="The first following sentence.")
            following_two = repository.create_sentence(text="The second following sentence.")
            repository.create_sentence(text="The third following sentence is outside the window.")
            before, after = translation_generation.translation_context_for_sentence(
                int(following_one["id"]),
                expected_text="The first following sentence.",
            )
            assert before == ["The **new** sentence is here."], before
            assert after == [
                "The second following sentence.",
                "The third following sentence is outside the window.",
            ], after
            stale_before, stale_after = translation_generation.translation_context_for_sentence(
                int(following_two["id"]),
                expected_text="A stale edited source.",
            )
            assert stale_before == [] and stale_after == [], (stale_before, stale_after)
    finally:
        platform_db.DB_PATH = original_path


def check_incremental_focus_word_translation() -> None:
    original_path = platform_db.DB_PATH
    original_configured = translation_generation.translation_configured
    original_translate_text = translation_generation.translate_text
    original_translate_words = translation_generation.translate_words
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            created = repository.create_sentence(
                text="A **known** and new word.",
                word_translations={"known": "本义：知道；句中：已知的"},
                word_tips={"known": "know 的过去分词"},
                sentence_translation="一个已知词和一个新词。",
                sentence_segments=["A known and new word."],
                translation_segments=["一个已知词和一个新词。"],
            )
            updated = repository.update_sentence(
                sentence_id=int(created["id"]),
                text="A **known** and **new** word. [新增重点词]",
                word_translations={"known": "本义：知道；句中：已知的", "new": ""},
                word_tips={"known": "know 的过去分词"},
                sentence_translation=created["sentence_translation"],
                sentence_segments=created["sentence_segments"],
                translation_segments=created["translation_segments"],
            )
            assert updated and updated["translation_pending"] is True, updated
            assert updated["sentence_translation"] == "一个已知词和一个新词。", updated
            assert updated["sentence_segments"] == ["A known and new word."], updated
            assert repository.sentence_translation_source_key(updated["text"]) == (
                repository.sentence_translation_source_key(created["text"])
            )

            word_requests: list[tuple[str, list[str] | None, list[str] | None, list[str] | None]] = []

            def unexpected_full_translation(*_args, **_kwargs):
                raise AssertionError("incremental focus words must not retranslate the sentence")

            def fake_word_translation(text, *, words=None, sentence_translation="", context_before=None, context_after=None):
                assert sentence_translation == "一个已知词和一个新词。", sentence_translation
                word_requests.append((text, words, context_before, context_after))
                return {
                    "items": [],
                    "word_translations": {"new": "本义：新的；句中：新出现的"},
                    "word_tips": {"new": "常与名词连用"},
                }

            translation_generation.translation_configured = lambda: True
            translation_generation.translate_text = unexpected_full_translation
            translation_generation.translate_words = fake_word_translation
            translation_generation.translate_sentence_if_missing_best_effort(
                int(created["id"]),
                expected_text="A **known** and **new** word. [新增重点词]",
            )

            assert word_requests == [
                ("A **known** and **new** word. [新增重点词]", ["new"], [], [])
            ], word_requests
            refreshed = repository.get_sentence(int(created["id"]))
            assert refreshed and refreshed["sentence_translation"] == "一个已知词和一个新词。", refreshed
            assert refreshed["sentence_segments"] == ["A known and new word."], refreshed
            assert refreshed["translation_segments"] == ["一个已知词和一个新词。"], refreshed
            assert refreshed["word_translations"] == {
                "known": "本义：知道；句中：已知的",
                "new": "本义：新的；句中：新出现的",
            }, refreshed
            assert refreshed["word_tips"] == {
                "known": "know 的过去分词",
                "new": "常与名词连用",
            }, refreshed
    finally:
        translation_generation.translation_configured = original_configured
        translation_generation.translate_text = original_translate_text
        translation_generation.translate_words = original_translate_words
        platform_db.DB_PATH = original_path


def check_startup_translation_recovery_scans_only_pending_sentences() -> None:
    original_path = platform_db.DB_PATH
    original_configured = translation_generation.translation_configured
    original_translate_many = translation_generation.translate_sentences_if_missing_best_effort
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            pending = repository.create_sentence(text="A **pending** sentence needs translation.")
            complete = repository.create_sentence(
                text="A **complete** sentence already has translation.",
                word_translations={"complete": "本义：完整的；句中：完整的"},
                sentence_translation="一个完整的句子已经有翻译。",
                sentence_segments=["A complete sentence already has translation."],
                translation_segments=["一个完整的句子已经有翻译。"],
            )
            deleted = repository.create_sentence(text="A deleted sentence needs translation.")
            assert repository.delete_sentence(sentence_id=int(deleted["id"]))

            captured: list[tuple[list[int], dict[int, str]]] = []

            def fake_translate(sentence_ids, expected_texts=None):
                captured.append((list(sentence_ids), dict(expected_texts or {})))

            translation_generation.translation_configured = lambda: True
            translation_generation.translate_sentences_if_missing_best_effort = fake_translate
            translation_generation.resume_pending_translation_generation_best_effort()

            assert captured == [
                (
                    [int(pending["id"])],
                    {int(pending["id"]): "A **pending** sentence needs translation."},
                )
            ], captured
            assert int(complete["id"]) not in captured[0][0]
            assert int(deleted["id"]) not in captured[0][0]
    finally:
        translation_generation.translation_configured = original_configured
        translation_generation.translate_sentences_if_missing_best_effort = original_translate_many
        platform_db.DB_PATH = original_path


def check_audio_voice_settings() -> None:
    original_path = platform_db.DB_PATH
    env_names = (
        "STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER",
        "STUDY_ENGLISH_EDGE_VOICE",
        "STUDY_ENGLISH_KOKORO_VOICE",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    try:
        os.environ["STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER"] = "edge"
        os.environ["STUDY_ENGLISH_EDGE_VOICE"] = "en-US-JennyNeural"
        os.environ["STUDY_ENGLISH_KOKORO_VOICE"] = "af_heart"
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()

            first = repository.create_sentence(text="The first voice setting example is ready.")
            assert first["audio_uses_global"] is True, first
            assert (first["audio_effective_provider"], first["audio_effective_voice"]) == (
                "edge",
                "en-US-JennyNeural",
            ), first

            settings = repository.set_global_sentence_audio_settings(provider="kokoro", voice="af_heart")
            assert settings["global"]["source"] == "database", settings
            second = repository.create_sentence(text="The second voice setting example is ready.")
            assert (second["audio_effective_provider"], second["audio_effective_voice"]) == (
                "kokoro",
                "af_heart",
            ), second

            overridden = repository.set_sentence_audio_override(
                sentence_id=int(first["id"]),
                provider="edge",
                voice="en-US-GuyNeural",
            )
            assert overridden and overridden["audio_uses_global"] is False, overridden
            assert overridden["audio_effective_voice"] == "en-US-GuyNeural", overridden

            repository.set_global_sentence_audio_settings(provider="edge", voice="en-US-AriaNeural")
            refreshed_override = repository.get_sentence(int(first["id"]))
            refreshed_global = repository.get_sentence(int(second["id"]))
            assert refreshed_override and refreshed_override["audio_effective_voice"] == "en-US-GuyNeural"
            assert refreshed_global and refreshed_global["audio_effective_voice"] == "en-US-AriaNeural"

            queued = repository.queue_global_sentence_audio_regeneration()
            assert queued["sentence_ids"] == [int(second["id"])], queued
            inherited = repository.set_sentence_audio_override(
                sentence_id=int(first["id"]),
                use_global=True,
            )
            assert inherited and inherited["audio_uses_global"] is True, inherited
            assert inherited["audio_effective_voice"] == "en-US-AriaNeural", inherited

            try:
                repository.validate_sentence_audio_identity("edge", "unsupported-voice")
            except ValueError:
                pass
            else:
                raise AssertionError("unsupported voice was accepted")
    finally:
        platform_db.DB_PATH = original_path
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_legacy_audio_metadata_reconciliation() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    env_names = ("STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER", "STUDY_ENGLISH_EDGE_VOICE")
    original_env = {name: os.environ.get(name) for name in env_names}
    try:
        os.environ["STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER"] = "edge"
        os.environ["STUDY_ENGLISH_EDGE_VOICE"] = "en-US-JennyNeural"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            repository.ENGLISH_AUDIO_DIR.mkdir(parents=True)
            initialize_database()
            initialize_english_schema()

            legacy = repository.create_sentence(text="A legacy sentence audio file remains usable.")
            stale = repository.create_sentence(text="A stale sentence audio file must be regenerated.")
            legacy_path = repository.ENGLISH_AUDIO_DIR / (
                f"sentence_{legacy['id']}_edge_en-US-JennyNeural.mp3"
            )
            stale_path = repository.ENGLISH_AUDIO_DIR / (
                f"sentence_{stale['id']}_edge_en-US-JennyNeural.mp3"
            )
            legacy_path.write_bytes(b"legacy-audio")
            stale_path.write_bytes(b"stale-audio")
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_path = ?, audio_provider = '', audio_voice = '',
                        audio_hash = '', audio_status = 'ready'
                    WHERE id = ?
                    """,
                    (legacy_path.name, int(legacy["id"])),
                )
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_path = ?, audio_provider = 'edge', audio_voice = 'en-US-JennyNeural',
                        audio_hash = 'stale-hash', audio_status = 'ready'
                    WHERE id = ?
                    """,
                    (stale_path.name, int(stale["id"])),
                )

            result = repository.reconcile_sentence_audio_metadata()
            assert result["backfilled"] == 1, result
            assert result["queued"] == 1, result
            refreshed_legacy = repository.get_sentence(int(legacy["id"]))
            refreshed_stale = repository.get_sentence(int(stale["id"]))
            assert refreshed_legacy and refreshed_legacy["audio_available"] is True, refreshed_legacy
            with get_connection() as conn:
                legacy_hash = conn.execute(
                    "SELECT audio_hash FROM english_sentences WHERE id = ?",
                    (int(legacy["id"]),),
                ).fetchone()["audio_hash"]
            assert legacy_hash == repository.sentence_audio_hash(
                legacy["text"], provider="edge", voice="en-US-JennyNeural"
            )
            assert refreshed_stale and refreshed_stale["audio_status"] == "pending", refreshed_stale
            assert refreshed_stale["audio_available"] is False, refreshed_stale
    finally:
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_focus_map_pruning_and_reconciliation() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            created = repository.create_sentence(
                text="A **focus** word remains here.",
                word_translations={"focus": "重点"},
            )
            sentence_id = int(created["id"])
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET word_translations_json = ?, word_tips_json = ?,
                        word_play_counts_json = ?, word_play_total = 7
                    WHERE id = ?
                    """,
                    (
                        json.dumps({"focus": "重点", "stale": "过期"}, ensure_ascii=False),
                        json.dumps({"focus": "提示", "stale": "过期提示"}, ensure_ascii=False),
                        json.dumps({"focus": 2, "stale": 5}, ensure_ascii=False),
                        sentence_id,
                    ),
                )
            assert repository.reconcile_sentence_focus_state() == 1
            repaired = repository.get_sentence(sentence_id)
            assert repaired and repaired["word_translations"] == {"focus": "重点"}, repaired
            assert repaired["word_tips"] == {"focus": "提示"}, repaired
            assert repaired["word_play_counts"] == {"focus": 2}, repaired
            assert repaired["word_play_total"] == 7, repaired
            assert repaired["focus_word_play_total"] == 2, repaired

            unmarked = repository.update_sentence(
                sentence_id=sentence_id,
                text="A focus word remains here.",
                word_translations=repaired["word_translations"],
                word_tips=repaired["word_tips"],
            )
            assert unmarked and unmarked["word_translations"] == {}, unmarked
            assert unmarked["word_tips"] == {}, unmarked
            assert unmarked["word_play_counts"] == {}, unmarked
            assert unmarked["word_play_total"] == 7, unmarked
            assert unmarked["focus_word_play_total"] == 0, unmarked
    finally:
        platform_db.DB_PATH = original_path


def check_deleted_sentence_lifetime_stats() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )
            created = repository.create_sentence(text="A reviewed sentence may later be deleted.")
            sentence_id = int(created["id"])
            repository.review_sentence(
                user_id=1,
                sentence_id=sentence_id,
                event_type="sentence_play",
                complete_round_item=False,
            )
            assert repository.delete_sentence(sentence_id=sentence_id)
            summary = repository.stats(user_id=1)
            heatmap = repository.review_heatmap(user_id=1, days=7)
            assert summary["sentence_reviews"] == 1, summary
            assert heatmap["tracked_sentence_reviews"] == 1, heatmap
            assert heatmap["lifetime_sentence_reviews"] == 1, heatmap
            assert heatmap["legacy_sentence_reviews"] == 0, heatmap
    finally:
        platform_db.DB_PATH = original_path


def check_audio_play_does_not_complete_review_item() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            created = repository.create_sentence(text="Listening alone must not complete this sentence.")
            sentence_id = int(created["id"])
            _mark_sentence_audio_ready(sentence_id)
            repository.list_sentences(user_id=1, sort="smart", page=1, page_size=20, resume=True)

            played = repository.review_sentence(
                user_id=1,
                sentence_id=sentence_id,
                event_type="sentence_play",
                complete_round_item=True,
            )
            assert played and played["review_count"] == 1, played
            assert played["review_round_item_completed"] is False, played
            with get_connection() as conn:
                round_item = conn.execute(
                    "SELECT completed_at FROM english_review_round_items WHERE sentence_id = ?",
                    (sentence_id,),
                ).fetchone()
            assert round_item and str(round_item["completed_at"] or "") == "", round_item

            reviewed = repository.review_sentence(
                user_id=1,
                sentence_id=sentence_id,
                event_type="sentence_review",
            )
            assert reviewed and reviewed["review_count"] == 1, reviewed
            assert reviewed["completion_count"] == 1, reviewed
            assert reviewed["review_round_item_completed"] is True, reviewed
    finally:
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


def check_sentence_write_boundaries() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            try:
                repository.create_sentence(text="   ")
            except ValueError:
                pass
            else:
                raise AssertionError("blank sentence must be rejected")

            first = repository.create_sentence(
                text="A **focus** word starts the review round.",
                word_translations={"focus": "重点"},
            )
            repository.list_sentences(user_id=1, sort="smart", page=1, page_size=20, resume=True)
            second = repository.create_sentence(text="A later sentence is not yet in that frozen round.")
            reviewed = repository.review_sentence(user_id=1, sentence_id=int(second["id"]))
            assert reviewed and reviewed["review_round_item_completed"] is False, reviewed

            try:
                repository.record_word_play(user_id=1, sentence_id=int(first["id"]), word="other")
            except ValueError:
                pass
            else:
                raise AssertionError("non-focus word play must be rejected")

            assert repository.delete_sentence(sentence_id=int(second["id"]))
            assert repository.update_sentence(
                sentence_id=int(second["id"]),
                text="Deleted content must stay deleted.",
            ) is None
    finally:
        platform_db.DB_PATH = original_path


def check_review_queue_includes_audio_optional_sentences_and_freezes_membership() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            pending = repository.create_sentence(text="A pending sentence must wait outside review.")
            failed = repository.create_sentence(text="A failed sentence must also wait outside review.")
            missing = repository.create_sentence(text="A missing sentence must stay outside review.")
            with get_connection() as conn:
                conn.execute(
                    "UPDATE english_sentences SET audio_status = 'failed' WHERE id = ?",
                    (int(failed["id"]),),
                )
                conn.execute(
                    "UPDATE english_sentences SET audio_status = 'missing' WHERE id = ?",
                    (int(missing["id"]),),
                )

            first_load = repository.list_sentences(
                user_id=1,
                sort="smart",
                page=1,
                page_size=20,
                resume=True,
            )
            round_id = int(first_load["review_round"]["id"])
            assert {int(item["id"]) for item in first_load["items"]} == {
                int(pending["id"]),
                int(failed["id"]),
                int(missing["id"]),
            }, first_load
            assert first_load["total"] == 3, first_load
            assert first_load["review_round"]["available"] == 3, first_load
            with get_connection() as conn:
                item_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM english_review_round_items WHERE round_id = ?",
                    (round_id,),
                ).fetchone()["count"]
            assert int(item_count) == 3, item_count

            later = repository.create_sentence(text="A new sentence waits for the next review cycle.")
            frozen_load = repository.list_sentences(
                user_id=1,
                sort="smart",
                page=1,
                page_size=20,
                resume=True,
            )
            assert frozen_load["review_round"]["id"] == round_id, frozen_load
            assert frozen_load["total"] == 3, frozen_load
            assert all(int(item["id"]) != int(later["id"]) for item in frozen_load["items"]), frozen_load
    finally:
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


def check_exposure_formula_and_double_peak_repeats() -> None:
    linked_rows = [
        {
            "id": 1,
            "text": "**Echo** returns, and echo remains.",
            "word_translations_json": json.dumps({"Echo": "回声"}),
            "word_play_counts_json": json.dumps({"Echo": 3}),
            "review_count": 0,
            "word_play_total": 3,
            "completion_count": 1,
        },
        {
            "id": 2,
            "text": "An echo fades.",
            "word_translations_json": "{}",
            "word_play_counts_json": "{}",
            "review_count": 0,
            "word_play_total": 0,
            "completion_count": 1,
        },
    ]
    linked = sentence_exposure_metrics(linked_rows)
    assert linked[1]["word_exposure"] == linked[2]["word_exposure"] * 2, linked

    peak_rows = [
        {
            "id": index + 1,
            "text": f"Plain sentence {index}.",
            "word_translations_json": "{}",
            "word_play_counts_json": "{}",
            "review_count": index,
            "word_play_total": 0,
            "completion_count": 1,
        }
        for index in range(5)
    ]
    peak = sentence_exposure_metrics(peak_rows)
    assert [peak[index]["repeat_count"] for index in range(1, 6)] == [1, 2, 1, 2, 1], peak
    ranked = [(row, {"score": 0}) for row in peak_rows]
    schedule = build_review_schedule(ranked)
    counts = {
        sentence_id: sum(1 for item in schedule if int(item["sentence_id"]) == sentence_id)
        for sentence_id in range(1, 6)
    }
    assert [counts[index] for index in range(1, 6)] == [1, 2, 1, 2, 1], counts
    positions = [
        index
        for index, item in enumerate(schedule)
        if int(item["sentence_id"]) == 2
    ]
    assert len(positions) == 2 and positions == sorted(positions), positions


def check_repeated_items_complete_independently_and_wait_until_next_boundary() -> None:
    original_path = platform_db.DB_PATH
    original_now = review_rounds._utc_now
    clock = [datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)]
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            review_rounds._utc_now = lambda: clock[0]
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )
            sentences = [repository.create_sentence(text=f"Review schedule sentence {index}.") for index in range(5)]
            with get_connection() as conn:
                # These sentences existed before the fixed 08:00 boundary;
                # they belong to the first cycle's frozen snapshot.
                conn.execute(
                    "UPDATE english_sentences SET created_at = '2026-08-20T23:00:00+00:00'"
                )
                for index, sentence in enumerate(sentences):
                    conn.execute(
                        "UPDATE english_sentences SET review_count = ?, completion_count = 1 WHERE id = ?",
                        (index, int(sentence["id"])),
                    )

            first = repository.list_sentences(user_id=1, sort="smart", page=1, page_size=200, resume=True)
            round_id = int(first["review_round"]["id"])
            assert first["review_round"]["total"] == 7, first["review_round"]
            repeated = next(item for item in first["items"] if int(item["review_repeat_total"]) == 2)
            same_sentence_items = [
                item for item in first["items"] if int(item["id"]) == int(repeated["id"])
            ]
            assert len(same_sentence_items) == 2, same_sentence_items

            completed = repository.review_sentence(
                user_id=1,
                sentence_id=int(repeated["id"]),
                round_item_id=int(same_sentence_items[0]["review_round_item_id"]),
            )
            assert completed and completed["review_round_item_completed"] is True, completed
            assert completed["review_count"] == int(repeated["review_count"]), completed
            assert completed["completion_count"] == 2, completed
            with get_connection() as conn:
                remaining_same = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM english_review_round_items
                    WHERE round_id = ? AND sentence_id = ? AND COALESCE(completed_at, '') = ''
                    """,
                    (round_id, int(repeated["id"])),
                ).fetchone()["count"]
            assert int(remaining_same) == 1, remaining_same

            with get_connection() as conn:
                remaining = conn.execute(
                    """
                    SELECT id, sentence_id
                    FROM english_review_round_items
                    WHERE round_id = ? AND COALESCE(completed_at, '') = ''
                    ORDER BY position
                    """,
                    (round_id,),
                ).fetchall()
            for item in remaining:
                repository.review_sentence(
                    user_id=1,
                    sentence_id=int(item["sentence_id"]),
                    round_item_id=int(item["id"]),
                )

            waiting = repository.list_sentences(user_id=1, sort="smart", page=1, page_size=200, resume=True)
            assert int(waiting["review_round"]["id"]) == round_id, waiting["review_round"]
            assert waiting["review_round"]["is_completed"] is True, waiting["review_round"]
            assert waiting["review_round"]["next_round_at"] == "2026-08-22T00:00:00+00:00", waiting

            clock[0] += timedelta(hours=14)
            next_round = repository.list_sentences(user_id=1, sort="smart", page=1, page_size=200, resume=True)
            assert int(next_round["review_round"]["id"]) != round_id, next_round["review_round"]
            next_round_id = int(next_round["review_round"]["id"])
            stale_item = next_round["items"][0]
            clock[0] += timedelta(days=7)
            expired = repository.review_sentence(
                user_id=1,
                sentence_id=int(stale_item["id"]),
                round_item_id=int(stale_item["review_round_item_id"]),
            )
            assert expired and expired["review_round_expired"] is True, expired
            refreshed = repository.list_sentences(user_id=1, sort="smart", page=1, page_size=200, resume=True)
            assert int(refreshed["review_round"]["id"]) != next_round_id, refreshed["review_round"]
    finally:
        review_rounds._utc_now = original_now
        platform_db.DB_PATH = original_path


def check_review_rounds_use_fixed_boundaries_and_catch_up_without_request() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    original_now = review_rounds._utc_now
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            first = repository.create_sentence(text="Fixed boundary sentence.")
            with get_connection() as conn:
                conn.execute("UPDATE english_sentences SET created_at = '2026-08-20T00:00:00+00:00'")
            first_time = datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc)
            created = repository.advance_due_review_rounds(now=first_time)
            assert created and created[0]["created"] is True, created
            with get_connection() as conn:
                round_row = conn.execute(
                    "SELECT * FROM english_review_rounds WHERE status = 'active'"
                ).fetchone()
            assert round_row["started_at"] == "2026-08-21T00:00:00+00:00", round_row
            assert round_row["expires_at"] == "2026-08-22T00:00:00+00:00", round_row

            # No request is needed at the boundary: the scheduler entry point
            # catches up and creates the next fixed cycle.
            next_cycle = repository.advance_due_review_rounds(
                now=datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc)
            )
            assert next_cycle and next_cycle[0]["round_id"] != int(round_row["id"]), next_cycle
            with get_connection() as conn:
                rounds = conn.execute(
                    "SELECT * FROM english_review_rounds ORDER BY id"
                ).fetchall()
            assert rounds[-1]["started_at"] == "2026-08-22T00:00:00+00:00", rounds[-1]
            assert rounds[-1]["expires_at"] == "2026-08-23T00:00:00+00:00", rounds[-1]

            # A sentence added after the fixed boundary is deferred to the
            # following cycle.
            later = repository.create_sentence(text="Added after boundary.")
            with get_connection() as conn:
                conn.execute(
                    "UPDATE english_sentences SET created_at = '2026-08-22T10:00:00+00:00' WHERE id = ?",
                    (int(later["id"]),),
                )
            following = repository.advance_due_review_rounds(
                now=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
            )
            assert following and following[0]["created"] is True, following
            with get_connection() as conn:
                latest_id = int(conn.execute("SELECT MAX(id) FROM english_review_rounds").fetchone()[0])
                included = conn.execute(
                    "SELECT 1 FROM english_review_round_items WHERE round_id = ? AND sentence_id = ?",
                    (latest_id, int(later["id"])),
                ).fetchone()
            assert included is not None, (latest_id, later)
    finally:
        review_rounds._utc_now = original_now
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


def check_review_round_test_expiry_override() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    env_names = (review_rounds.TEST_ROUND_ID_ENV, review_rounds.TEST_EXPIRES_AT_ENV)
    original_env = {name: os.environ.get(name) for name in env_names}
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            sentence = repository.create_sentence(text="Test expiry override sentence.")
            with get_connection() as conn:
                conn.execute(
                    "UPDATE english_sentences SET created_at = '2026-08-20T00:00:00+00:00' WHERE id = ?",
                    (int(sentence["id"]),),
                )
            created = repository.advance_due_review_rounds(
                now=datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
            )
            round_id = int(created[0]["round_id"])
            target = datetime(2026, 8, 22, 21, 45, tzinfo=timezone.utc)
            os.environ[review_rounds.TEST_ROUND_ID_ENV] = str(round_id)
            os.environ[review_rounds.TEST_EXPIRES_AT_ENV] = target.isoformat()

            rotated = repository.advance_due_review_rounds(now=target)
            assert rotated and rotated[0]["created"] is True, rotated
            assert int(rotated[0]["round_id"]) != round_id, rotated
            with get_connection() as conn:
                rounds = conn.execute(
                    "SELECT * FROM english_review_rounds ORDER BY id"
                ).fetchall()
            assert rounds[0]["status"] == "expired", rounds[0]
            assert rounds[0]["expires_at"] == target.isoformat(), rounds[0]
            assert rounds[1]["status"] == "active", rounds[1]
            assert rounds[1]["started_at"] == target.isoformat(), rounds[1]
            assert rounds[1]["expires_at"] == (target + timedelta(days=1)).isoformat(), rounds[1]

            unchanged = repository.advance_due_review_rounds(now=target + timedelta(minutes=1))
            assert unchanged and unchanged[0]["created"] is False, unchanged
            with get_connection() as conn:
                active = conn.execute(
                    "SELECT * FROM english_review_rounds WHERE status = 'active'"
                ).fetchone()
            assert active["expires_at"] == (target + timedelta(days=1)).isoformat(), active
    finally:
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


def check_sqlite_review_concurrency_and_stale_audio() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            repository.ENGLISH_AUDIO_DIR.mkdir(parents=True)
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            created = repository.create_sentence(
                text="A **focus** word appears in this sentence.",
                word_translations={"focus": "重点"},
            )
            sentence_id = int(created["id"])
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(
                    pool.map(
                        lambda _: repository.record_word_play(
                            user_id=1,
                            sentence_id=sentence_id,
                            word="focus",
                        ),
                        range(20),
                    )
                )
            assert all(results), results
            refreshed = repository.get_sentence(sentence_id)
            assert refreshed and refreshed["word_play_counts"]["focus"] == 20, refreshed
            assert refreshed["word_play_total"] == 20, refreshed
            with get_connection() as conn:
                event_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM english_review_events WHERE event_type = 'word_play'"
                ).fetchone()["count"]
            assert int(event_count) == 20, event_count

            provider = str(refreshed["audio_effective_provider"])
            voice = str(refreshed["audio_effective_voice"])
            audio_path = repository.ENGLISH_AUDIO_DIR / "sentence-current.mp3"
            audio_path.write_bytes(b"current-audio")
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_path = ?, audio_provider = ?, audio_voice = ?, audio_hash = ?, audio_status = 'ready'
                    WHERE id = ?
                    """,
                    (
                        audio_path.name,
                        provider,
                        voice,
                        repository.sentence_audio_hash(created["text"], provider=provider, voice=voice),
                        sentence_id,
                    ),
                )
            ready = repository.get_sentence(sentence_id)
            assert ready and ready["audio_available"] is True, ready
            changed = repository.update_sentence(
                sentence_id=sentence_id,
                text="A changed **focus** word appears in this sentence.",
                word_translations=ready["word_translations"],
                word_tips=ready["word_tips"],
            )
            assert changed and changed["audio_status"] == "pending", changed
            assert changed["audio_needs_regeneration"] is True, changed
            assert changed["audio_available"] is False and changed["audio_url"] == "", changed
            assert repository.audio_file_for_sentence(sentence_id) is None
    finally:
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


def check_today_passage_keeps_completed_items() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )
            first_completed = repository.create_passage(
                user_id=1,
                title="First completed today",
                exam_type="english1",
                passage_type="reading_a",
                body_text="The first completed passage.",
            )
            second_completed = repository.create_passage(
                user_id=1,
                title="Second completed today",
                exam_type="english1",
                passage_type="reading_a",
                body_text="The second completed passage.",
            )
            repository.create_passage(
                user_id=1,
                title="Still new",
                exam_type="english2",
                passage_type="reading_a",
                body_text="A new passage.",
            )
            repository.complete_passage(passage_id=int(first_completed["id"]), user_id=1)
            repository.complete_passage(passage_id=int(second_completed["id"]), user_id=1)
            result = repository.list_passages(user_id=1)
            today_ids = [int(item["id"]) for item in result["today_items"]]
            assert today_ids == [int(first_completed["id"]), int(second_completed["id"])], result
    finally:
        platform_db.DB_PATH = original_path


CHECKS = (
    check_sentence_integrity,
    check_audio_assets,
    check_kokoro_voice_catalog,
    check_kokoro_sentence_loudness_normalization,
    check_dedicated_ai_configuration,
    check_translation_requires_dedicated_ai_configuration,
    check_library_metadata,
    check_split_translation_pipeline,
    check_translation_request_policy_and_evidence,
    check_evaluation_review_feedback,
    check_fact_clause_segmentation_is_advisory,
    check_pipeline_review_feedback_propagation,
    check_translation_prompt_scope_safeguards,
    check_translation_repair_feedback_history,
    check_translation_audit_repairs,
    check_translation_focus_reconciliation,
    check_independent_structure_review,
    check_focused_word_card_repairs,
    check_english_word_definitions,
    check_legacy_english_definition_backfill,
    check_edit_translation_invalidation,
    check_incremental_focus_word_translation,
    check_startup_translation_recovery_scans_only_pending_sentences,
    check_audio_voice_settings,
    check_legacy_audio_metadata_reconciliation,
    check_focus_map_pruning_and_reconciliation,
    check_deleted_sentence_lifetime_stats,
    check_audio_play_does_not_complete_review_item,
    check_sentence_write_boundaries,
    check_review_queue_includes_audio_optional_sentences_and_freezes_membership,
    check_exposure_formula_and_double_peak_repeats,
    check_repeated_items_complete_independently_and_wait_until_next_boundary,
    check_review_rounds_use_fixed_boundaries_and_catch_up_without_request,
    check_review_round_test_expiry_override,
    check_review_round_length_preserves_progress_without_daily_limits,
    check_review_round_catch_up_uses_each_snapshot_length,
    check_review_round_deadline_is_frozen_and_early_completion_still_works,
    check_sqlite_review_concurrency_and_stale_audio,
    check_today_passage_keeps_completed_items,
) + REGRESSION_CHECKS


def run_checks() -> None:
    initialize_database()
    initialize_english_schema()
    for check in CHECKS:
        check()
        print(f"OK english.{check.__name__}")


def main() -> int:
    run_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

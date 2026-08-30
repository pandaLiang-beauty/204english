from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter

from ..platform.auth import get_current_user
from ..platform.ai_transport import AIProviderError, http_status_for_ai_error
from ..platform.rate_limit import resolve_annotations
from ..platform.security import client_ip
from ..platform.security import verify_write_origin
from . import repository
from .audio_generation import (
    generate_sentence_audio_for_sentence_ids_best_effort,
    generate_voice_preview,
    generate_word_audio_for_sentence_ids_best_effort,
    voice_preview_file,
)
from .translation_generation import translate_sentences_if_missing_best_effort
from .translator import translate_text, translation_configured


router = APIRouter(prefix="/api/english", tags=["english"])
limiter = Limiter(key_func=client_ip)
logger = logging.getLogger(__name__)


class EnglishSentencePayload(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    word_translations: dict[str, str] = Field(default_factory=dict)
    word_tips: dict[str, str] = Field(default_factory=dict)
    sentence_translation: str = Field(default="", max_length=12000)
    sentence_segments: list[str] = Field(default_factory=list)
    translation_segments: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("sentence text is required")
        return value


class EnglishSentenceBulkPayload(BaseModel):
    items: list[EnglishSentencePayload] = Field(min_length=1, max_length=2000)


class EnglishReviewPayload(BaseModel):
    event_type: str = "sentence_review"
    complete_round_item: bool = True
    round_item_id: int | None = Field(default=None, ge=1)


class EnglishFocusWordPayload(BaseModel):
    word: str = Field(min_length=1, max_length=255)
    action: str = "toggle"


class EnglishTranslatePayload(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    words: list[str] | None = None


class EnglishAudioSelectionPayload(BaseModel):
    provider: str = Field(default="", max_length=40)
    voice: str = Field(default="", max_length=120)
    use_global: bool = False


class EnglishAudioPreviewPayload(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    voice: str = Field(min_length=1, max_length=120)


class EnglishPassagePayload(BaseModel):
    title: str = Field(default="", max_length=500)
    source_label: str = Field(default="", max_length=500)
    source_url: str = Field(default="", max_length=2000)
    year: int | None = None
    exam_type: str = Field(default="", max_length=80)
    passage_type: str = Field(default="custom", max_length=80)
    body_text: str = Field(min_length=1, max_length=120000)
    status: str = "new"


class EnglishPassageSyncPayload(BaseModel):
    candidate_indexes: list[int] = Field(default_factory=list)


@router.get("/stats")
def read_english_stats(
    include_word_network: bool = True,
    user: dict = Depends(get_current_user),
) -> dict:
    return repository.stats(
        user_id=int(user["id"]),
        include_word_network=include_word_network,
    )


@router.get("/heatmap")
def read_english_heatmap(
    days: int = Query(default=119, ge=7, le=370),
    user: dict = Depends(get_current_user),
) -> dict:
    return repository.review_heatmap(user_id=int(user["id"]), days=days)


@router.get("/audio/settings")
def read_english_audio_settings(user: dict = Depends(get_current_user)) -> dict:
    _ = user
    return repository.audio_settings_overview()


@router.put("/audio/settings")
def update_english_audio_settings(
    payload: EnglishAudioSelectionPayload,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = user, csrf
    try:
        return repository.set_global_sentence_audio_settings(
            provider=payload.provider,
            voice=payload.voice,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/audio/settings/apply")
def apply_english_audio_settings(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = user, csrf
    result = repository.queue_global_sentence_audio_regeneration()
    sentence_ids = result.pop("sentence_ids")
    if sentence_ids:
        background_tasks.add_task(generate_sentence_audio_for_sentence_ids_best_effort, sentence_ids)
    return result


@router.post("/audio/previews")
@limiter.limit("15/minute")
@resolve_annotations
def create_english_audio_preview(
    request: Request,
    payload: EnglishAudioPreviewPayload,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = request, user, csrf
    try:
        provider, voice = repository.validate_sentence_audio_identity(payload.provider, payload.voice)
        path = generate_voice_preview(provider=provider, voice=voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - TTS errors are logged without exposing internals.
        logger.warning("english voice preview failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=503, detail="音色试听生成失败，请稍后重试") from exc
    return {
        "provider": provider,
        "voice": voice,
        "audio_url": f"/api/english/audio/previews/{provider}/{voice}?v={int(path.stat().st_mtime)}",
        "cached": True,
    }


@router.get("/audio/previews/{provider}/{voice}")
def read_english_audio_preview(
    provider: str,
    voice: str,
    user: dict = Depends(get_current_user),
) -> FileResponse:
    _ = user
    try:
        path = voice_preview_file(provider=provider, voice=voice)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="试听音频不存在") from exc
    if path is None:
        raise HTTPException(status_code=404, detail="试听音频不存在")
    media_type = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/sentences")
def read_english_sentences(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=40, ge=1, le=200),
    search: str = "",
    q: str = "",
    sort: str = "smart",
    include_deleted: bool = False,
    resume: bool = False,
    round_queue: bool = False,
    user: dict = Depends(get_current_user),
) -> dict:
    return repository.list_sentences(
        user_id=int(user["id"]) if round_queue else None,
        search=search or q,
        sort=sort,
        page=page,
        page_size=page_size,
        include_deleted=include_deleted,
        resume=resume,
    )


@router.get("/flow/queue")
def read_english_flow_queue(
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
) -> dict:
    return {
        "supported": True,
        "stats": repository.stats(user_id=int(user["id"])),
        **repository.list_sentences(user_id=int(user["id"]), sort="smart", page=1, page_size=limit, resume=True),
    }


@router.post("/translate")
@limiter.limit("10/minute")
@resolve_annotations
def translate_english_text(
    request: Request,
    payload: EnglishTranslatePayload,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = request, user, csrf
    if not translation_configured():
        raise HTTPException(status_code=400, detail="English translation AI provider is not configured")
    try:
        return translate_text(payload.text, words=payload.words)
    except AIProviderError as exc:
        logger.warning("english translation request failed: %s", exc.diagnostic)
        raise HTTPException(status_code=http_status_for_ai_error(exc), detail=exc.user_message) from exc


@router.get("/passages")
def read_english_passages(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str = "",
    passage_type: str = "",
    exam_type: str = "",
    year: int | None = Query(default=None, ge=1900, le=2200),
    search: str = "",
    include_deleted: bool = False,
    user: dict = Depends(get_current_user),
) -> dict:
    return repository.list_passages(
        user_id=int(user["id"]),
        status=status,
        passage_type=passage_type,
        exam_type=exam_type,
        year=year,
        search=search,
        page=page,
        page_size=page_size,
        include_deleted=include_deleted,
    )


@router.get("/passages/today")
def read_english_today_passage(user: dict = Depends(get_current_user)) -> dict:
    return {"item": repository.today_passage(user_id=int(user["id"]))}


@router.post("/passages")
def create_english_passage(
    payload: EnglishPassagePayload,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = csrf
    try:
        return repository.create_passage(
            user_id=int(user["id"]),
            title=payload.title,
            source_label=payload.source_label,
            source_url=payload.source_url,
            year=payload.year,
            exam_type=payload.exam_type,
            passage_type=payload.passage_type,
            body_text=payload.body_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/passages/{passage_id}")
def read_english_passage(passage_id: int, user: dict = Depends(get_current_user)) -> dict:
    passage = repository.get_passage(passage_id, user_id=int(user["id"]))
    if not passage:
        raise HTTPException(status_code=404, detail="阅读文章不存在")
    return passage


@router.put("/passages/{passage_id}")
def update_english_passage(
    passage_id: int,
    payload: EnglishPassagePayload,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = csrf
    try:
        passage = repository.update_passage(
            passage_id=passage_id,
            user_id=int(user["id"]),
            title=payload.title,
            source_label=payload.source_label,
            source_url=payload.source_url,
            year=payload.year,
            exam_type=payload.exam_type,
            passage_type=payload.passage_type,
            body_text=payload.body_text,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not passage:
        raise HTTPException(status_code=404, detail="阅读文章不存在")
    return passage


@router.delete("/passages/{passage_id}")
def delete_english_passage(
    passage_id: int,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = csrf
    if not repository.delete_passage(passage_id=passage_id, user_id=int(user["id"])):
        raise HTTPException(status_code=404, detail="阅读文章不存在")
    return {"ok": True}


@router.post("/passages/{passage_id}/sync-sentences")
def sync_english_passage_sentences(
    passage_id: int,
    background_tasks: BackgroundTasks,
    payload: EnglishPassageSyncPayload | None = None,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = csrf
    try:
        result = repository.sync_passage_sentences(
            passage_id=passage_id,
            user_id=int(user["id"]),
            candidate_indexes=payload.candidate_indexes if payload else [],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="阅读文章不存在")
    sentence_ids = [int(item.get("id")) for item in result.get("sentences") or [] if item.get("id")]
    if sentence_ids:
        expected_texts = {
            int(item["id"]): str(item.get("text") or "")
            for item in result.get("sentences") or []
            if item.get("id")
        }
        background_tasks.add_task(translate_sentences_if_missing_best_effort, sentence_ids, expected_texts)
        background_tasks.add_task(generate_word_audio_for_sentence_ids_best_effort, sentence_ids)
        sentence_audio_ids = [
            int(item["id"])
            for item in result.get("sentences") or []
            if item.get("id") and item.get("audio_needs_regeneration")
        ]
        if sentence_audio_ids:
            background_tasks.add_task(generate_sentence_audio_for_sentence_ids_best_effort, sentence_audio_ids)
    return result


@router.post("/passages/{passage_id}/complete")
def complete_english_passage(
    passage_id: int,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = csrf
    passage = repository.complete_passage(passage_id=passage_id, user_id=int(user["id"]))
    if not passage:
        raise HTTPException(status_code=404, detail="阅读文章不存在")
    return passage


@router.get("/sentences/{sentence_id}")
def read_english_sentence(sentence_id: int, user: dict = Depends(get_current_user)) -> dict:
    _ = user
    sentence = repository.get_sentence(sentence_id)
    if not sentence:
        raise HTTPException(status_code=404, detail="句子不存在")
    return sentence


@router.post("/sentences")
def create_english_sentence(
    payload: EnglishSentencePayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = user, csrf
    try:
        sentence = repository.create_sentence(
            text=payload.text,
            word_translations=payload.word_translations,
            word_tips=payload.word_tips,
            sentence_translation=payload.sentence_translation,
            sentence_segments=payload.sentence_segments,
            translation_segments=payload.translation_segments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if sentence.get("id"):
        sentence_id = int(sentence["id"])
        background_tasks.add_task(
            translate_sentences_if_missing_best_effort,
            [sentence_id],
            {sentence_id: str(sentence.get("text") or "")},
        )
    if sentence.get("id") and sentence.get("word_translations"):
        background_tasks.add_task(generate_word_audio_for_sentence_ids_best_effort, [int(sentence["id"])])
    if sentence.get("id") and sentence.get("audio_needs_regeneration"):
        background_tasks.add_task(generate_sentence_audio_for_sentence_ids_best_effort, [int(sentence["id"])])
    return sentence


@router.post("/sentences/bulk")
def create_english_sentences_bulk(
    payload: EnglishSentenceBulkPayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = user, csrf
    try:
        result = repository.create_sentences_bulk([item.model_dump() for item in payload.items])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sentence_ids = [int(item["id"]) for item in result["items"] if item.get("id")]
    if sentence_ids:
        expected_texts = {
            int(item["id"]): str(item.get("text") or "")
            for item in result["items"]
            if item.get("id")
        }
        background_tasks.add_task(translate_sentences_if_missing_best_effort, sentence_ids, expected_texts)
        background_tasks.add_task(generate_word_audio_for_sentence_ids_best_effort, sentence_ids)
        sentence_audio_ids = [
            int(item["id"])
            for item in result["items"]
            if item.get("id") and item.get("audio_needs_regeneration")
        ]
        if sentence_audio_ids:
            background_tasks.add_task(generate_sentence_audio_for_sentence_ids_best_effort, sentence_audio_ids)
    return result


@router.put("/sentences/{sentence_id}")
def update_english_sentence(
    sentence_id: int,
    payload: EnglishSentencePayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = user, csrf
    try:
        sentence = repository.update_sentence(
            sentence_id=sentence_id,
            text=payload.text,
            word_translations=payload.word_translations,
            word_tips=payload.word_tips,
            sentence_translation=payload.sentence_translation,
            sentence_segments=payload.sentence_segments,
            translation_segments=payload.translation_segments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not sentence:
        raise HTTPException(status_code=404, detail="句子不存在")
    if sentence.get("id"):
        updated_sentence_id = int(sentence["id"])
        if sentence.get("audio_needs_regeneration"):
            background_tasks.add_task(generate_sentence_audio_for_sentence_ids_best_effort, [updated_sentence_id])
        if sentence.get("word_translations"):
            background_tasks.add_task(generate_word_audio_for_sentence_ids_best_effort, [updated_sentence_id])
        background_tasks.add_task(
            translate_sentences_if_missing_best_effort,
            [updated_sentence_id],
            {updated_sentence_id: str(sentence.get("text") or "")},
        )
    return sentence


@router.put("/sentences/{sentence_id}/audio-settings")
def update_english_sentence_audio_settings(
    sentence_id: int,
    payload: EnglishAudioSelectionPayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = user, csrf
    try:
        sentence = repository.set_sentence_audio_override(
            sentence_id=sentence_id,
            provider=payload.provider,
            voice=payload.voice,
            use_global=payload.use_global,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not sentence:
        raise HTTPException(status_code=404, detail="句子不存在")
    if sentence.get("audio_needs_regeneration"):
        background_tasks.add_task(generate_sentence_audio_for_sentence_ids_best_effort, [sentence_id])
    return sentence


@router.delete("/sentences/{sentence_id}")
def delete_english_sentence(
    sentence_id: int,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = user, csrf
    if not repository.delete_sentence(sentence_id=sentence_id):
        raise HTTPException(status_code=404, detail="句子不存在")
    return {"ok": True}


@router.post("/sentences/{sentence_id}/review")
def review_english_sentence(
    sentence_id: int,
    payload: EnglishReviewPayload | None = None,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = csrf
    sentence = repository.review_sentence(
        user_id=int(user["id"]),
        sentence_id=sentence_id,
        event_type=(payload.event_type if payload else "sentence_review"),
        complete_round_item=(payload.complete_round_item if payload else True),
        round_item_id=(payload.round_item_id if payload else None),
    )
    if not sentence:
        raise HTTPException(status_code=404, detail="句子不存在")
    return sentence


@router.post("/sentences/{sentence_id}/words/{word}/play")
def record_english_word_play(
    sentence_id: int,
    word: str,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = csrf
    try:
        sentence = repository.record_word_play(user_id=int(user["id"]), sentence_id=sentence_id, word=word)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not sentence:
        raise HTTPException(status_code=404, detail="句子不存在")
    return sentence


@router.post("/sentences/{sentence_id}/focus-word")
def toggle_english_focus_word(
    sentence_id: int,
    payload: EnglishFocusWordPayload,
    user: dict = Depends(get_current_user),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    _ = csrf
    try:
        sentence = repository.toggle_focus_word(
            user_id=int(user["id"]),
            sentence_id=sentence_id,
            word=payload.word,
            action=payload.action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not sentence:
        raise HTTPException(status_code=404, detail="句子不存在")
    return sentence


@router.get("/audio/{sentence_id}")
def read_english_audio(sentence_id: int, user: dict = Depends(get_current_user)) -> FileResponse:
    _ = user
    path = repository.audio_file_for_sentence(sentence_id)
    if path is None:
        raise HTTPException(status_code=404, detail="音频不存在")
    media_type = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/pronunciations/{sentence_id}/{filename}")
def read_english_pronunciation(
    sentence_id: int,
    filename: str,
    user: dict = Depends(get_current_user),
) -> FileResponse:
    _ = user
    path = repository.pronunciation_file(sentence_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="单词音频不存在")
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)

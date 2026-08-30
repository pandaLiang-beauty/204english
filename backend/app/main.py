from __future__ import annotations

import os
import threading
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .english.api import router as english_router
from .english.audio_generation import resume_pending_audio_generation_best_effort
from .english import repository
from .english.repository import reconcile_sentence_audio_metadata, reconcile_sentence_focus_state
from .english.schema import initialize_schema as initialize_english_schema
from .english.translation_generation import resume_pending_translation_generation_best_effort
from .platform.api import router as platform_router
from .platform.auth import ensure_default_user, purge_expired_sessions
from .platform.db import initialize_database
from .platform.security import client_ip


def _cors_origins() -> list[str]:
    port = os.getenv("STUDY_FRONTEND_PORT", "5103")
    configured = {
        value.strip().rstrip("/")
        for value in os.getenv("STUDY_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    public_origin = os.getenv("STUDY_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if public_origin:
        configured.add(public_origin)
    return sorted({f"http://127.0.0.1:{port}", f"http://localhost:{port}", *configured})


limiter = Limiter(key_func=client_ip)
app = FastAPI(title="English Review", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(platform_router)
app.include_router(english_router)

logger = logging.getLogger(__name__)
_review_round_stop = threading.Event()


def _review_round_scheduler() -> None:
    """Keep fixed Beijing-08:00 review schedules advancing without page traffic."""
    while not _review_round_stop.wait(15):
        try:
            repository.advance_due_review_rounds()
        except Exception:  # noqa: BLE001 - scheduler must not take down the API
            logger.exception("English review round scheduler failed")

@app.on_event("startup")
def startup() -> None:
    initialize_database()
    initialize_english_schema()
    reconcile_sentence_focus_state()
    reconcile_sentence_audio_metadata()
    ensure_default_user()
    purge_expired_sessions()
    _review_round_stop.clear()
    try:
        repository.advance_due_review_rounds()
    except Exception:  # noqa: BLE001 - startup recovery should not block the API
        logger.exception("Initial English review round scheduling failed")
    threading.Thread(
        target=_review_round_scheduler,
        name="english-review-round-scheduler",
        daemon=True,
    ).start()
    threading.Thread(
        target=resume_pending_audio_generation_best_effort,
        name="english-audio-resume",
        daemon=True,
    ).start()
    threading.Thread(
        target=resume_pending_translation_generation_best_effort,
        name="english-translation-resume",
        daemon=True,
    ).start()


@app.on_event("shutdown")
def shutdown() -> None:
    _review_round_stop.set()

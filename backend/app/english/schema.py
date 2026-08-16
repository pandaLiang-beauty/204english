from __future__ import annotations

from ..platform.db import _ensure_column, get_connection


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS english_sentences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    word_translations_json TEXT NOT NULL DEFAULT '{}',
    word_tips_json TEXT NOT NULL DEFAULT '{}',
    word_play_counts_json TEXT NOT NULL DEFAULT '{}',
    audio_path TEXT NOT NULL DEFAULT '',
    audio_provider TEXT NOT NULL DEFAULT '',
    audio_voice TEXT NOT NULL DEFAULT '',
    audio_provider_override TEXT NOT NULL DEFAULT '',
    audio_voice_override TEXT NOT NULL DEFAULT '',
    audio_hash TEXT NOT NULL DEFAULT '',
    audio_status TEXT NOT NULL DEFAULT 'missing',
    audio_error TEXT NOT NULL DEFAULT '',
    audio_generated_at TEXT NOT NULL DEFAULT '',
    review_count INTEGER NOT NULL DEFAULT 0,
    word_play_total INTEGER NOT NULL DEFAULT 0,
    sentence_translation TEXT NOT NULL DEFAULT '',
    sentence_segments_json TEXT NOT NULL DEFAULT '[]',
    translation_segments_json TEXT NOT NULL DEFAULT '[]',
    deleted_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS english_audio_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sentence_provider TEXT NOT NULL,
    sentence_voice TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS english_passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    source_label TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    year INTEGER,
    exam_type TEXT NOT NULL DEFAULT '',
    passage_type TEXT NOT NULL DEFAULT 'reading_a',
    body_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    intensive_json TEXT NOT NULL DEFAULT '{}',
    selected_sentence_ids_json TEXT NOT NULL DEFAULT '[]',
    completed_at TEXT NOT NULL DEFAULT '',
    deleted_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS english_review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sentence_id INTEGER REFERENCES english_sentences(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    word TEXT NOT NULL DEFAULT '',
    client TEXT NOT NULL DEFAULT 'web',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS english_review_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    end_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS english_review_round_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL REFERENCES english_review_rounds(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sentence_id INTEGER NOT NULL REFERENCES english_sentences(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(round_id, sentence_id),
    UNIQUE(round_id, position)
);

CREATE INDEX IF NOT EXISTS idx_english_sentences_deleted ON english_sentences(deleted_at);
CREATE INDEX IF NOT EXISTS idx_english_sentences_review ON english_sentences(review_count, word_play_total, id);
CREATE INDEX IF NOT EXISTS idx_english_passages_user_status ON english_passages(user_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_english_passages_user_deleted ON english_passages(user_id, deleted_at, id);
CREATE INDEX IF NOT EXISTS idx_english_passages_user_type ON english_passages(user_id, passage_type, year);
CREATE INDEX IF NOT EXISTS idx_english_events_user_created ON english_review_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_english_events_sentence ON english_review_events(sentence_id, event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_english_rounds_user_status ON english_review_rounds(user_id, status, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_english_rounds_one_active ON english_review_rounds(user_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_english_round_items_queue ON english_review_round_items(round_id, position);
CREATE INDEX IF NOT EXISTS idx_english_round_items_completed ON english_review_round_items(round_id, completed_at);
"""


def _ensure_passage_columns(conn) -> None:
    _ensure_column(conn, "english_passages", "passage_type", "passage_type TEXT NOT NULL DEFAULT 'reading_a'")
    conn.execute(
        """
        UPDATE english_passages
        SET passage_type = 'reading_a'
        WHERE COALESCE(passage_type, '') = ''
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_english_passages_user_type
        ON english_passages(user_id, passage_type, year)
        """
    )


def _ensure_sentence_audio_columns(conn) -> None:
    _ensure_column(conn, "english_sentences", "audio_provider", "audio_provider TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "english_sentences", "audio_voice", "audio_voice TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        conn,
        "english_sentences",
        "audio_provider_override",
        "audio_provider_override TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(
        conn,
        "english_sentences",
        "audio_voice_override",
        "audio_voice_override TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(conn, "english_sentences", "audio_hash", "audio_hash TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "english_sentences", "audio_status", "audio_status TEXT NOT NULL DEFAULT 'missing'")
    _ensure_column(conn, "english_sentences", "audio_error", "audio_error TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "english_sentences", "audio_generated_at", "audio_generated_at TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        UPDATE english_sentences
        SET audio_status = CASE
                WHEN COALESCE(audio_path, '') <> '' THEN 'ready'
                ELSE 'missing'
            END
        WHERE COALESCE(audio_status, '') = ''
           OR (COALESCE(audio_path, '') <> '' AND audio_status = 'missing')
        """
    )


def _ensure_sentence_translation_columns(conn) -> None:
    _ensure_column(conn, "english_sentences", "sentence_segments_json", "sentence_segments_json TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "english_sentences", "translation_segments_json", "translation_segments_json TEXT NOT NULL DEFAULT '[]'")


def initialize_schema() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_sentence_audio_columns(conn)
        _ensure_sentence_translation_columns(conn)
        _ensure_passage_columns(conn)

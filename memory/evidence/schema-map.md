---
memory_level: 3
scope: evidence.schema
load_policy: generated-on-demand
generated: true
generator: backend/scripts/generate_memory_evidence.py
sources:
  - backend/app/platform/db.py
  - backend/app/english/schema.py
---

# Schema Evidence

> Generated from the SQLite base schemas.

| Owner | Table | Columns | Indexes |
| --- | --- | --- | --- |
| platform | `users` | `id`, `username`, `password_hash`, `display_name`, `created_at` | - |
| platform | `sessions` | `id`, `user_id`, `created_at`, `expires_at` | `idx_sessions_user`, `idx_sessions_expires` |
| english | `english_sentences` | `id`, `text`, `word_translations_json`, `word_tips_json`, `word_play_counts_json`, `audio_path`, `audio_provider`, `audio_voice`, `audio_provider_override`, `audio_voice_override`, `audio_hash`, `audio_status`, `audio_error`, `audio_generated_at`, `review_count`, `word_play_total`, `sentence_translation`, `sentence_segments_json`, `translation_segments_json`, `deleted_at`, `created_at`, `updated_at` | `idx_english_sentences_deleted`, `idx_english_sentences_review` |
| english | `english_audio_settings` | `id`, `sentence_provider`, `sentence_voice`, `updated_at` | - |
| english | `english_passages` | `id`, `user_id`, `title`, `source_label`, `source_url`, `year`, `exam_type`, `passage_type`, `body_text`, `status`, `intensive_json`, `selected_sentence_ids_json`, `completed_at`, `deleted_at`, `created_at`, `updated_at` | `idx_english_passages_user_status`, `idx_english_passages_user_deleted`, `idx_english_passages_user_type` |
| english | `english_review_events` | `id`, `user_id`, `sentence_id`, `event_type`, `word`, `client`, `metadata_json`, `created_at` | `idx_english_events_user_created`, `idx_english_events_sentence` |
| english | `english_review_rounds` | `id`, `user_id`, `status`, `started_at`, `expires_at`, `ended_at`, `end_reason`, `created_at`, `updated_at` | `idx_english_rounds_user_status`, `idx_english_rounds_one_active` |
| english | `english_review_round_items` | `id`, `round_id`, `user_id`, `sentence_id`, `position`, `completed_at`, `created_at`, `updated_at` | `idx_english_round_items_queue`, `idx_english_round_items_completed` |

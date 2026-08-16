---
memory_level: 3
scope: evidence.api-routes
load_policy: generated-on-demand
generated: true
generator: backend/scripts/generate_memory_evidence.py
sources:
  - backend/app/platform/api.py
  - backend/app/english/api.py
  - backend/app/main.py
  - frontend/src/english/navigation.js
  - frontend/src/router.js
---

# API And Route Evidence

> Generated file. Run `cd backend && python3 scripts/generate_memory_evidence.py` after route changes.

## Backend HTTP Routes

`Auth` means the handler depends on `get_current_user`. `Origin` means it depends on `verify_write_origin`.

| Method | Path | Handler | Auth | Origin | Rate limit | Source |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/api/auth/login` | `login` | no | yes | no | `backend/app/platform/api.py` |
| POST | `/api/auth/logout` | `logout` | no | yes | no | `backend/app/platform/api.py` |
| GET | `/api/auth/me` | `me` | yes | no | no | `backend/app/platform/api.py` |
| POST | `/api/english/audio/previews` | `create_english_audio_preview` | yes | yes | yes | `backend/app/english/api.py` |
| GET | `/api/english/audio/previews/{provider}/{voice}` | `read_english_audio_preview` | yes | no | no | `backend/app/english/api.py` |
| GET | `/api/english/audio/settings` | `read_english_audio_settings` | yes | no | no | `backend/app/english/api.py` |
| PUT | `/api/english/audio/settings` | `update_english_audio_settings` | yes | yes | no | `backend/app/english/api.py` |
| POST | `/api/english/audio/settings/apply` | `apply_english_audio_settings` | yes | yes | no | `backend/app/english/api.py` |
| GET | `/api/english/audio/{sentence_id}` | `read_english_audio` | yes | no | no | `backend/app/english/api.py` |
| GET | `/api/english/flow/queue` | `read_english_flow_queue` | yes | no | no | `backend/app/english/api.py` |
| GET | `/api/english/heatmap` | `read_english_heatmap` | yes | no | no | `backend/app/english/api.py` |
| GET | `/api/english/passages` | `read_english_passages` | yes | no | no | `backend/app/english/api.py` |
| POST | `/api/english/passages` | `create_english_passage` | yes | yes | no | `backend/app/english/api.py` |
| GET | `/api/english/passages/today` | `read_english_today_passage` | yes | no | no | `backend/app/english/api.py` |
| DELETE | `/api/english/passages/{passage_id}` | `delete_english_passage` | yes | yes | no | `backend/app/english/api.py` |
| GET | `/api/english/passages/{passage_id}` | `read_english_passage` | yes | no | no | `backend/app/english/api.py` |
| PUT | `/api/english/passages/{passage_id}` | `update_english_passage` | yes | yes | no | `backend/app/english/api.py` |
| POST | `/api/english/passages/{passage_id}/complete` | `complete_english_passage` | yes | yes | no | `backend/app/english/api.py` |
| POST | `/api/english/passages/{passage_id}/sync-sentences` | `sync_english_passage_sentences` | yes | yes | no | `backend/app/english/api.py` |
| GET | `/api/english/pronunciations/{sentence_id}/{filename}` | `read_english_pronunciation` | yes | no | no | `backend/app/english/api.py` |
| GET | `/api/english/sentences` | `read_english_sentences` | yes | no | no | `backend/app/english/api.py` |
| POST | `/api/english/sentences` | `create_english_sentence` | yes | yes | no | `backend/app/english/api.py` |
| POST | `/api/english/sentences/bulk` | `create_english_sentences_bulk` | yes | yes | no | `backend/app/english/api.py` |
| DELETE | `/api/english/sentences/{sentence_id}` | `delete_english_sentence` | yes | yes | no | `backend/app/english/api.py` |
| GET | `/api/english/sentences/{sentence_id}` | `read_english_sentence` | yes | no | no | `backend/app/english/api.py` |
| PUT | `/api/english/sentences/{sentence_id}` | `update_english_sentence` | yes | yes | no | `backend/app/english/api.py` |
| PUT | `/api/english/sentences/{sentence_id}/audio-settings` | `update_english_sentence_audio_settings` | yes | yes | no | `backend/app/english/api.py` |
| POST | `/api/english/sentences/{sentence_id}/focus-word` | `toggle_english_focus_word` | yes | yes | no | `backend/app/english/api.py` |
| POST | `/api/english/sentences/{sentence_id}/review` | `review_english_sentence` | yes | yes | no | `backend/app/english/api.py` |
| POST | `/api/english/sentences/{sentence_id}/words/{word}/play` | `record_english_word_play` | yes | yes | no | `backend/app/english/api.py` |
| GET | `/api/english/stats` | `read_english_stats` | yes | no | no | `backend/app/english/api.py` |
| POST | `/api/english/translate` | `translate_english_text` | yes | yes | yes | `backend/app/english/api.py` |
| GET | `/api/health` | `health` | no | no | no | `backend/app/platform/api.py` |

## Frontend Routes

| Path | View state |
| --- | --- |
| `/english` | `review` |
| `/english/review` | `review` |
| `/english/library` | `library` |
| `/english/passages` | `passages` |
| `/english/create` | `create` |
| `/english/stats` | `stats` |

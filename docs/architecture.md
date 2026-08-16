# Architecture

```text
App.vue                         # session gate
└── StudyApp.vue                # route coordination and pending-save flush
    ├── english/EnglishTopNav.vue
    └── english/EnglishFlow.vue

backend/app/main.py
├── backend/app/platform        # local infrastructure only
└── backend/app/english         # all English business behavior
```

The product is one English review application for one owner. There is no generic study Shell, system registry, subject switcher, activity timer, question schema, or PostgreSQL adapter.

The dependency direction is `english -> platform`. Platform must not import English business code. The frontend follows the same ownership rule: `frontend/src/english` owns navigation, pages, state, audio, passages, and sentence interactions.

SQLite is the only database. `english_review_events` is the ongoing behavioral fact source; sentence aggregate counters retain the historical baseline that predates event tracking. Review rounds freeze queue order, while unused due-card scheduling is intentionally absent.

`backend/scripts/check_module_boundaries.py` rejects sibling systems, foreign imports and endpoints, external symlinks, missing write-origin protection, and absolute dependencies on another project root.

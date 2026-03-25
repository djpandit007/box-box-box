# box-box-box

**F1 Live Race Summariser** — Follow any F1 race without watching it.

A Python application that polls the [OpenF1 API](https://openf1.org) during **live races**, collects structured event data and team radio transcriptions, and every 60 seconds generates an LLM-powered narrative summary. Like having a commentator in your ear.

> **Scope**: This app targets the **current/latest live race only** (`session_key=latest`). Historical race replay is not currently supported but may be explored in the future.

## How It Works

OpenF1 has no live commentary text feed. Instead, we **synthesize narrative** from structured data:

1. **Poll** race control messages, positions, pit stops, overtakes, intervals, laps, weather, and team radio every 10 seconds
2. **Transcribe** team radio MP3 clips via Groq Whisper
3. **Summarise** all events from the last 60 seconds into a natural-language race update via LLM (OpenRouter + PydanticAI), using Jinja2-rendered XML-tagged prompts
4. **Deliver** summaries in real-time via WebSocket, with optional TTS audio

## Tech Stack

| Component      | Technology                                                                              |
| -------------- | --------------------------------------------------------------------------------------- |
| Language       | Python 3.12+                                                                            |
| Data Source    | [OpenF1 API](https://openf1.org)                                                        |
| Database       | PostgreSQL 16 + pgvector                                                                |
| LLM            | [OpenRouter](https://openrouter.ai) via [PydanticAI](https://ai.pydantic.dev)           |
| Text-to-Speech | [ElevenLabs](https://elevenlabs.io) (English dialogue) |
| Frontend       | [htmx](https://htmx.org) + [Alpine.js](https://alpinejs.dev) + Jinja2 templates         |
| Visualisations | [Pyodide](https://pyodide.org) (Python in WebAssembly) for client-side charts           |
| Secrets        | [dotenvx](https://dotenvx.com)                                                          |
| Web Framework  | [FastAPI](https://fastapi.tiangolo.com) (REST API + WebSocket + htmx HTML fragments)    |

## Project Structure

```
box-box-box/
├── .env                            # Encrypted secrets (committed)
├── .env.keys                       # Decryption keys (NEVER commit)
├── .github/workflows/ci.yml        # CI: lint, type check, test
├── pyproject.toml
├── docker-compose.yml              # Postgres + pgvector
├── alembic.ini
├── alembic/                        # Database migrations
├── src/boxboxbox/
│   ├── config.py                   # Settings via pydantic-settings
│   ├── models.py                   # SQLAlchemy + pgvector models
│   ├── db.py                       # Async engine & session factory
│   ├── ingestion/
│   │   ├── client.py               # OpenF1 API client (rate-limited)
│   │   ├── poller.py               # Priority-based polling orchestrator
│   │   ├── endpoints.py            # Endpoint configs & priorities
│   │   └── schemas.py              # Pydantic models for API responses
│   ├── summariser/
│   │   ├── prompt.py               # Jinja2 prompt builder (DB queries + rendering)
│   │   ├── agent.py                # PydanticAI agent config (summary + digest)
│   │   ├── embeddings.py           # OpenRouter embedding client
│   │   ├── loop.py                 # 60-second summarisation loop
│   │   ├── digest.py               # Post-race digest generator
│   │   └── templates/
│   │       ├── summary_prompt.xml.jinja2   # XML-tagged prompt template
│   │       └── digest_prompt.xml.jinja2    # Post-race digest prompt template
│   ├── audio/
│   │   ├── tts.py                  # TTS dispatcher (parse dialogue, route to backend, save file)
│   │   └── elevenlabs.py           # ElevenLabs Text to Dialogue API client
│   ├── delivery/                   # Phase 4 (not yet implemented)
│   └── main.py                     # asyncio entrypoint (poller + summariser)
├── tests/
│   ├── fixtures/ci/                # Trimmed API fixtures (committed)
│   ├── fixtures/{session_key}/     # Full API snapshots (gitignored)
│   ├── test_client.py              # API client & fixture parsing tests
│   ├── test_poller.py              # Polling orchestrator tests
│   ├── test_schemas.py             # Pydantic schema validation tests
│   ├── test_prompt.py              # Prompt builder tests
│   ├── test_summariser.py          # Summarisation loop tests
│   └── test_digest.py              # Post-race digest tests
└── scripts/
    ├── snapshot_session.py         # Download session data for offline testing
    ├── init-db.sh                  # Docker entrypoint: create test DB
    └── pre-commit                  # Git pre-commit hook (ruff + ty)
```

## Build Phases

### Phase 1: Foundation — Project Setup + Data Ingestion

- [x] Project scaffolding (`pyproject.toml`, `config.py`, `docker-compose.yml`)
- [x] Database schema & Alembic migrations
- [x] OpenF1 API client with rate limiting and retry logic
- [x] Priority-based polling orchestrator
- [x] Pydantic response schemas for all OpenF1 endpoints
- [x] Test fixtures from historical session data
- [x] CI pipeline (GitHub Actions: ruff, ty, pytest)
- [x] Pre-commit hook (ruff + ty)

### Phase 2: Summarisation Engine (MVP)

- [x] Jinja2-templated prompt builder (events grouped by type via XML tags, previous summary for continuity)
- [x] 60-second summarisation loop via PydanticAI + OpenRouter
- [x] pgvector embeddings for semantic search
- [x] Post-race digest — final LLM call with all summaries as context to generate a shareable race report

> **After Phase 2, we have a working product**: run the app, it polls OpenF1, and every 60s prints a narrative race summary.

### Phase 3: Audio Pipeline

> **Note**: OpenF1 does not expose team radio MP3 streams. Radio download, transcription, and mood
> tagging are deferred until the API makes them available. Phase 3 focuses on TTS delivery of the
> post-race digest.

- [x] Text-to-speech for post-race digest via ElevenLabs Text to Dialogue API (English — two-commentator exchange with emotional delivery)

### Phase 4: Derived Intelligence + Delivery

- [ ] WebSocket server pushing pre-rendered HTML fragments (htmx `hx-swap-oob`)
- [ ] REST API endpoints returning Jinja2 partials (sessions, summaries, semantic search, standings)
- [ ] Battle detector — flag when two drivers' interval drops below ~1.5s and holds; resolve via `/overtakes`
- [ ] Weather alerts — monitor `/weather` rainfall transitions (0→1) and trigger push notifications
- [ ] Gap delta computation — track interval changes over time (closing/opening) for leaderboard enrichment

### Phase 5: Frontend (htmx + Alpine.js + Pyodide)

- [ ] htmx WebSocket integration — server pushes HTML fragments for timeline, leaderboard, and race control updates
- [ ] Jinja2 template partials — reusable components for summary card, leaderboard row, radio clip card
- [ ] Live leaderboard with gap deltas and sparkline trend charts (Pyodide/WASM on `<canvas>`)
- [ ] Tyre strategy view — horizontal bars per driver showing compound + tyre age
- [ ] Race control ticker — SSE-driven scrollable `/race_control` message feed
- [ ] Team radio player — Alpine.js for audio controls, transcript expand/collapse, mood tags
- [ ] Battle highlights in the narrative timeline
- [ ] Driver focus mode (Alpine.js) — filter summaries, radio, and gap charts to a selected driver
- [ ] Lazy-loading historical summaries via htmx (`hx-trigger="revealed"`)
- [ ] Weather radar — ambient dry/damp/wet indicator

## Features

### Core — the reason you open the app

- **Race narrative timeline** — LLM-generated summaries every 60 seconds, weaving race events into a commentator-style narrative with continuity between updates
- **Audio commentary** — TTS conversion of each summary so you can listen instead of read

### Essential context — always visible alongside summaries

- **Live leaderboard** (`/position` + `/intervals`) — real-time driver positions with gap deltas showing whether intervals are closing or opening. A gap of 1.2s that was 3.4s two minutes ago tells you there's a battle brewing — the static number alone doesn't.
- **Tyre strategy view** (`/stints` + `/pit`) — horizontal bars per driver showing compound and tyre age (like F1 TV graphics). At a glance: who's on ancient hards and about to pit, completely changing the context of the narrative.
- **Race control feed** (`/race_control`) — raw messages in a scrollable ticker. Flags, penalties, track limits, DRS zones. The "breaking news" channel alongside the summarised narrative.

### Rich features — what makes this better than a text thread

- **Team radio player** (`/team_radio` + STT) — card per clip with driver avatar (from `/drivers` `headshot_url`), transcript text, and a play button for the original MP3. LLM-tagged by mood/category (frustrated, celebratory, strategic, funny). Team radio is the most shared content from any race.
- **Battle detector** (`/intervals` + `/overtakes`) — when two drivers' interval drops below ~1.5s and holds, flag it as an active battle with special visual treatment and more frequent summary triggers. `/overtakes` confirms resolution. This answers: "should I go watch this live right now?"
- **Gap trend charts** (`/intervals` over time) — sparklines next to each driver in the leaderboard. A converging line tells you a story at a glance that no text can match. Computed client-side in Pyodide/WASM — just array math on cached interval data.
- **Weather radar** (`/weather`) — ambient indicator (dry/damp/wet) updated every minute. Rain is F1's single biggest drama catalyst. Push notification when rainfall transitions from 0 to 1.

### Engagement — what makes someone open this again next race

- **Driver focus mode** — pick "your" driver and filter everything: summaries mentioning that driver, radio from that team only, gap chart relative to their position. Personalisation turns a tool into *your* tool.
- **Post-race digest** — after the session ends, one final LLM call with all summaries as context generates a 2-3 paragraph race report. Stored, shareable — the thing someone sends to their WhatsApp group.

## Polling Strategy

Stays within the free tier limit of 30 req/min:

| Priority        | Endpoints                                 | Frequency | Requests/min |
| --------------- | ----------------------------------------- | --------- | ------------ |
| P1 (critical)   | `race_control`, `pit`, `overtakes`        | Every 10s | 18           |
| P2 (important)  | `position`, `intervals`                   | Every 30s | 4            |
| P3 (background) | `laps`, `weather`, `stints`, `team_radio` | Every 60s | 4            |
| **Total**       |                                           |           | **~26**      |

## Quick Start

```bash
# Install dotenvx
curl -sfS https://dotenvx.sh/install.sh | sh

# Set secrets (first time only)
dotenvx set OPENROUTER_API_KEY "your-key"

# Start Postgres
docker compose up -d

# Install dependencies
uv sync

# Run migrations
dotenvx run -- uv run alembic upgrade head

# Start the summariser (live race)
dotenvx run -- uv run python -m boxboxbox
```

## Secret Management

We use [dotenvx](https://dotenvx.com) for encrypted environment variables.
Secrets are encrypted at rest — only `.env.keys` (gitignored) holds decryption keys.

### Initial setup

```bash
# Install dotenvx
curl -sfS https://dotenvx.sh/install.sh | sh

# Set your secrets (encrypts automatically)
dotenvx set OPENROUTER_API_KEY "sk-or-..."
dotenvx set GROQ_API_KEY "gsk_..."
dotenvx set DEEPGRAM_API_KEY "..."
```

This creates:

- `.env` — encrypted values (safe to commit)
- `.env.keys` — decryption keys (**never commit this**)

### Required variables

| Variable                       | Description                                                       |
| ------------------------------ | ----------------------------------------------------------------- |
| `OPENROUTER_API_KEY`           | LLM API key via OpenRouter                                        |
| `OPENF1_BASE_URL`              | OpenF1 API base (default: `https://api.openf1.org/v1`)            |
| `POLL_INTERVAL_SECONDS`        | Polling frequency (default: `10`)                                 |
| `SUMMARY_INTERVAL_SECONDS`     | Summary generation interval (default: `60`)                       |
| `TTS_LANGUAGE`                 | TTS language (default: `en`)                                      |
| `AUDIO_DIR`                    | Directory for generated audio files (default: `data/audio`)       |
| `ELEVENLABS_API_KEY`           | ElevenLabs API key (English TTS)                                  |
| `ELEVENLABS_LEAD_VOICE_ID`     | ElevenLabs voice ID for the Lead commentator                      |
| `ELEVENLABS_ANALYST_VOICE_ID`  | ElevenLabs voice ID for the Analyst commentator                   |

## Development

### Install dev dependencies

```bash
uv sync --dev
```

### Run tests

```bash
uv run pytest
```

To regenerate full test fixtures from the latest OpenF1 session:

```bash
uv run python scripts/snapshot_session.py
```

### Linting & formatting

```bash
uv run ruff check .          # lint
uv run ruff format --check .  # format check
uv run ruff format .          # auto-format
```

### Type checking

This project uses [ty](https://docs.astral.sh/ty/) for static type checking:

```bash
uvx ty check
```

### Pre-commit hook

Install the pre-commit hook to run ruff and ty before each commit:

```bash
ln -sf ../../scripts/pre-commit .git/hooks/pre-commit
```

## Future Ideas

- Historical race replay (reprocess past sessions from OpenF1 archive)
- Multi-session support (qualifying, sprint races)
- Mobile push notifications

## License

MIT

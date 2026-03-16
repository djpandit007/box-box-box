# box-box-box

**F1 Live Race Summariser** — Follow any F1 race without watching it.

A Python application that polls the [OpenF1 API](https://openf1.org) during **live races**, collects structured event data and team radio transcriptions, and every 60 seconds generates an LLM-powered narrative summary. Like having a commentator in your ear.

> **Scope**: This app targets the **current/latest live race only** (`session_key=latest`). Historical race replay is not currently supported but may be explored in the future.

## How It Works

OpenF1 has no live commentary text feed. Instead, we **synthesize narrative** from structured data:

1. **Poll** race control messages, positions, pit stops, overtakes, intervals, laps, weather, and team radio every 10 seconds
2. **Transcribe** team radio MP3 clips via Groq Whisper
3. **Summarise** all events from the last 60 seconds into a natural-language race update via LLM (OpenRouter + PydanticAI)
4. **Deliver** summaries in real-time via WebSocket, with optional TTS audio

## Tech Stack

| Component      | Technology                                                                    |
| -------------- | ----------------------------------------------------------------------------- |
| Language       | Python 3.12+                                                                  |
| Data Source    | [OpenF1 API](https://openf1.org)                                              |
| Database       | PostgreSQL 16 + pgvector                                                      |
| LLM            | [OpenRouter](https://openrouter.ai) via [PydanticAI](https://ai.pydantic.dev) |
| Speech-to-Text | Groq Whisper                                                                  |
| Text-to-Speech | Deepgram Aura                                                                 |
| Frontend       | Pyodide (Python in WebAssembly)                                               |
| Secrets        | [dotenvx](https://dotenvx.com)                                                |
| Web Framework  | [FastAPI](https://fastapi.tiangolo.com) (REST API + WebSocket)                |

## Project Structure

```
box-box-box/
├── .env                            # Encrypted secrets (committed)
├── .env.keys                       # Decryption keys (NEVER commit)
├── .dockerignore                   # Excludes .env.keys
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
│   │   └── endpoints.py            # Endpoint configs & parsers
│   ├── audio/
│   │   ├── downloader.py           # Team radio MP3 downloader
│   │   └── transcriber.py          # Groq Whisper STT
│   ├── summariser/
│   │   ├── prompt_builder.py       # XML-tagged prompt construction
│   │   ├── engine.py               # 60-second summarisation loop
│   │   └── embeddings.py           # pgvector semantic search
│   ├── delivery/
│   │   ├── websocket.py            # WebSocket server
│   │   └── tts.py                  # Deepgram TTS
│   ├── frontend/                   # Pyodide WASM assets
│   └── main.py                     # asyncio entrypoint
├── tests/
│   └── fixtures/                   # Saved API responses for offline testing
└── scripts/
    └── snapshot_session.py         # Download session data for offline testing
```

## Build Phases

### Phase 1: Foundation — Project Setup + Data Ingestion

- [x] Project scaffolding (`pyproject.toml`, `config.py`, `docker-compose.yml`)
- [x] Database schema & Alembic migrations
- [x] OpenF1 API client with rate limiting (30 req/min budget)
- [x] Priority-based polling orchestrator
- [x] Test fixtures from historical session data

### Phase 2: Summarisation Engine (MVP)

- [ ] XML-tagged prompt builder (events grouped by type, previous summary for continuity)
- [ ] 60-second summarisation loop via PydanticAI + OpenRouter
- [ ] pgvector embeddings for semantic search
- [ ] Post-race digest — final LLM call with all summaries as context to generate a shareable race report

> **After Phase 2, we have a working product**: run the app, it polls OpenF1, and every 60s prints a narrative race summary.

### Phase 3: Audio Pipeline

- [ ] Team radio MP3 download + Groq Whisper transcription
- [ ] Team radio mood tagging — LLM classification per clip (frustrated, celebratory, strategic, funny)
- [ ] Text-to-speech output via Deepgram Aura

### Phase 4: Derived Intelligence + Delivery

- [ ] WebSocket server for real-time push
- [ ] REST API endpoints (sessions, summaries, semantic search, standings)
- [ ] Battle detector — flag when two drivers' interval drops below ~1.5s and holds; resolve via `/overtakes`
- [ ] Weather alerts — monitor `/weather` rainfall transitions (0→1) and trigger push notifications
- [ ] Gap delta computation — track interval changes over time (closing/opening) for leaderboard enrichment

### Phase 5: Frontend (Pyodide/WASM)

- [ ] Live leaderboard with gap deltas and sparkline trend charts (computed client-side)
- [ ] Tyre strategy view — horizontal bars per driver showing compound + tyre age
- [ ] Race control ticker — scrollable raw `/race_control` message feed
- [ ] Team radio player — driver avatar, transcript, play button, mood tags
- [ ] Battle highlights in the narrative timeline
- [ ] Driver focus mode — filter summaries, radio, and gap charts to a selected driver
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

| Variable                   | Description                                            |
| -------------------------- | ------------------------------------------------------ |
| `OPENROUTER_API_KEY`       | LLM API key via OpenRouter                             |
| `GROQ_API_KEY`             | Groq Whisper for team radio transcription              |
| `DEEPGRAM_API_KEY`         | Deepgram Aura for TTS                                  |
| `OPENF1_BASE_URL`          | OpenF1 API base (default: `https://api.openf1.org/v1`) |
| `POLL_INTERVAL_SECONDS`    | Polling frequency (default: `10`)                      |
| `SUMMARY_INTERVAL_SECONDS` | Summary generation interval (default: `60`)            |

## Development

### Pre-commit hook

Install the pre-commit hook to run linting, formatting, and type checks before each commit:

```bash
ln -sf ../../scripts/pre-commit .git/hooks/pre-commit
```

The hook runs ruff (lint + format) on staged Python files and ty (type check) on the full project.

### Type checking

This project uses [ty](https://docs.astral.sh/ty/) for static type checking:

```bash
uvx ty check
```

## Future Ideas

- Historical race replay (reprocess past sessions from OpenF1 archive)
- Multi-session support (qualifying, sprint races)
- Mobile push notifications

## License

MIT

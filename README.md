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

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Data Source | [OpenF1 API](https://openf1.org) |
| Database | PostgreSQL 16 + pgvector |
| LLM | [OpenRouter](https://openrouter.ai) via [PydanticAI](https://ai.pydantic.dev) |
| Speech-to-Text | Groq Whisper |
| Text-to-Speech | Deepgram Aura |
| Frontend | Pyodide (Python in WebAssembly) |
| Secrets | [dotenvx](https://dotenvx.com) |
| Orchestration | asyncio (Temporal migration path available) |

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
- [ ] Project scaffolding (`pyproject.toml`, `config.py`, `docker-compose.yml`)
- [ ] Database schema & Alembic migrations
- [ ] OpenF1 API client with rate limiting (30 req/min budget)
- [ ] Priority-based polling orchestrator
- [ ] Test fixtures from historical session data

### Phase 2: Summarisation Engine (MVP)
- [ ] XML-tagged prompt builder (events grouped by type, previous summary for continuity)
- [ ] 60-second summarisation loop via PydanticAI + OpenRouter
- [ ] pgvector embeddings for semantic search

> **After Phase 2, we have a working product**: run the app, it polls OpenF1, and every 60s prints a narrative race summary.

### Phase 3: Audio Pipeline
- [ ] Team radio MP3 download + Groq Whisper transcription
- [ ] Text-to-speech output via Deepgram Aura

### Phase 4: Delivery Layer
- [ ] WebSocket server for real-time push
- [ ] REST API endpoints (sessions, summaries, semantic search, standings)

### Phase 5: Frontend
- [ ] Pyodide/WASM dashboard with live summary feed
- [ ] Standings table, radio transcript feed, semantic search

## Polling Strategy

Stays within the free tier limit of 30 req/min:

| Priority | Endpoints | Frequency | Requests/min |
|----------|-----------|-----------|-------------|
| P1 (critical) | `race_control`, `pit`, `overtakes` | Every 10s | 18 |
| P2 (important) | `position`, `intervals` | Every 30s | 4 |
| P3 (background) | `laps`, `weather`, `stints`, `team_radio` | Every 60s | 4 |
| **Total** | | | **~26** |

## Quick Start

```bash
# Install dotenvx
curl -sfS https://dotenvx.sh/install.sh | sh

# Set secrets (first time only)
dotenvx set DATABASE_URL "postgresql+asyncpg://boxboxbox:boxboxbox@localhost:5432/boxboxbox"
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
dotenvx set DATABASE_URL "postgresql+asyncpg://user:pass@localhost:5432/boxboxbox"
dotenvx set OPENROUTER_API_KEY "sk-or-..."
dotenvx set GROQ_API_KEY "gsk_..."
dotenvx set DEEPGRAM_API_KEY "..."
```

This creates:
- `.env` — encrypted values (safe to commit)
- `.env.keys` — decryption keys (**never commit this**)

### Required variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Postgres connection string (asyncpg) |
| `OPENROUTER_API_KEY` | LLM API key via OpenRouter |
| `GROQ_API_KEY` | Groq Whisper for team radio transcription |
| `DEEPGRAM_API_KEY` | Deepgram Aura for TTS |
| `OPENF1_BASE_URL` | OpenF1 API base (default: `https://api.openf1.org/v1`) |
| `POLL_INTERVAL_SECONDS` | Polling frequency (default: `10`) |
| `SUMMARY_INTERVAL_SECONDS` | Summary generation interval (default: `60`) |

## Future Ideas

- Historical race replay (reprocess past sessions from OpenF1 archive)
- Multi-session support (qualifying, sprint races)
- Mobile push notifications

## License

MIT

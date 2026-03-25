from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Postgres (used by docker-compose and SQLAlchemy)
    POSTGRES_DB: str = "boxboxbox"
    POSTGRES_USER: str = "boxboxbox"
    POSTGRES_PASSWORD: str = "boxboxbox"
    DATABASE_URL: str = ""  # built from above if not set explicitly

    # API keys
    OPENROUTER_API_KEY: str
    GROQ_API_KEY: str

    # Audio / TTS (Phase 3)
    TTS_LANGUAGE: str = "en"  # "en" | "hi" | "mr"
    AUDIO_DIR: str = "data/audio"
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_LEAD_VOICE_ID: str = ""
    ELEVENLABS_ANALYST_VOICE_ID: str = ""
    SARVAM_API_KEY: str = ""
    SARVAM_VOICE: str = "anushka"  # bulbul:v2 default; for bulbul:v3 use "shubh"
    SARVAM_MODEL: str = "bulbul:v2"

    # App config
    OPENF1_BASE_URL: str = "https://api.openf1.org/v1"
    POLL_INTERVAL_SECONDS: int = 10
    SUMMARY_INTERVAL_SECONDS: int = 60

    # Summariser config
    SUMMARISER_MODEL: str = "groq:moonshotai/kimi-k2-instruct-0905"
    DIGEST_MODEL: str = "groq:moonshotai/kimi-k2-instruct-0905"
    EMBEDDING_MODEL: str = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
    SESSION_END_GRACE_SECONDS: int = 300

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def build_database_url(self):
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@localhost:5432/{self.POSTGRES_DB}"
            )
        return self


settings = Settings()  # ty: ignore[missing-argument]

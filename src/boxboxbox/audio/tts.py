from __future__ import annotations

import logging
import pathlib
import re

from boxboxbox.audio.elevenlabs import elevenlabs_tts
from boxboxbox.config import settings

logger = logging.getLogger(__name__)


def parse_dialogue_lines(text: str) -> list[tuple[str, str]]:
    """
    Parse canonical digest dialogue format into (speaker, text) pairs.

    Input:  "Lead: [excited] What a race!\nAnalyst: [analytical] The strategy was key."
    Output: [("Lead", "[excited] What a race!"), ("Analyst", "[analytical] The strategy was key.")]
    """
    lines = []
    for raw in text.strip().splitlines():
        raw = raw.strip()
        if raw.startswith("Lead: "):
            lines.append(("Lead", raw[len("Lead: ") :]))
        elif raw.startswith("Analyst: "):
            lines.append(("Analyst", raw[len("Analyst: ") :]))
        elif raw.startswith("Historian: "):
            lines.append(("Historian", raw[len("Historian: ") :]))
    return lines


def strip_emotion_tags(text: str) -> str:
    """Remove ElevenLabs v3 emotional delivery tags, e.g. [excited], [analytical]."""
    return re.sub(r"\[.*?\]", "", text).strip()


async def generate_audio(summary_text: str, session_key: int, session_type: str = "Race") -> str | None:
    """
    Generate TTS audio for a post-race digest and save it locally.

    Uses ElevenLabs Text to Dialogue API for English.
    Returns the local file path, or None if API keys are not configured.
    """
    audio_dir = settings.AUDIO_DIR

    lines = parse_dialogue_lines(summary_text)
    if not lines:
        logger.warning("No dialogue lines found in digest — skipping audio generation")
        return None

    pathlib.Path(audio_dir).mkdir(parents=True, exist_ok=True)

    api_key = settings.ELEVENLABS_API_KEY
    lead_voice_id = settings.ELEVENLABS_LEAD_VOICE_ID
    analyst_voice_id = settings.ELEVENLABS_ANALYST_VOICE_ID
    historian_voice_id = settings.ELEVENLABS_HISTORIAN_VOICE_ID

    if not api_key:
        logger.warning("ELEVENLABS_API_KEY not set — skipping audio generation")
        return None

    logger.info("Generating ElevenLabs dialogue audio for session %s", session_key)
    audio_bytes = await elevenlabs_tts(lines, api_key, lead_voice_id, analyst_voice_id, historian_voice_id)
    slug = session_type.lower().replace(" ", "_")
    file_path = pathlib.Path(audio_dir) / f"digest_{session_key}_{slug}.mp3"

    file_path.write_bytes(audio_bytes)
    logger.info("Audio saved to %s", file_path)
    return str(file_path)

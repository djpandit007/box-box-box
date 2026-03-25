from __future__ import annotations

import logging
import pathlib
import re

from boxboxbox.audio.elevenlabs import elevenlabs_tts
from boxboxbox.audio.sarvam import sarvam_translate, sarvam_tts
from boxboxbox.config import settings

logger = logging.getLogger(__name__)

_LANG_TO_SARVAM = {"hi": "hi-IN", "mr": "mr-IN"}


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
    return lines


def strip_emotion_tags(text: str) -> str:
    """Remove ElevenLabs v3 emotional delivery tags, e.g. [excited], [analytical]."""
    return re.sub(r"\[.*?\]", "", text).strip()


async def generate_audio(summary_text: str, session_key: int) -> str | None:
    """
    Generate TTS audio for a post-race digest and save it locally.

    Routes to ElevenLabs (English) or Sarvam AI (Hindi/Marathi) based on TTS_LANGUAGE env var.
    Returns the local file path, or None if API keys are not configured.
    """
    language = settings.TTS_LANGUAGE
    audio_dir = settings.AUDIO_DIR

    lines = parse_dialogue_lines(summary_text)
    if not lines:
        logger.warning("No dialogue lines found in digest — skipping audio generation")
        return None

    pathlib.Path(audio_dir).mkdir(parents=True, exist_ok=True)

    if language == "en":
        api_key = settings.ELEVENLABS_API_KEY
        lead_voice_id = settings.ELEVENLABS_LEAD_VOICE_ID
        analyst_voice_id = settings.ELEVENLABS_ANALYST_VOICE_ID

        if not api_key:
            logger.warning("ELEVENLABS_API_KEY not set — skipping audio generation")
            return None

        logger.info("Generating ElevenLabs dialogue audio for session %s", session_key)
        audio_bytes = await elevenlabs_tts(lines, api_key, lead_voice_id, analyst_voice_id)
        file_path = pathlib.Path(audio_dir) / f"digest_{session_key}.mp3"
    else:
        sarvam_key = settings.SARVAM_API_KEY
        sarvam_voice = settings.SARVAM_VOICE
        sarvam_model = settings.SARVAM_MODEL
        lang_code = _LANG_TO_SARVAM.get(language, "hi-IN")

        if not sarvam_key:
            logger.warning("SARVAM_API_KEY not set — skipping audio generation")
            return None

        plain_text = " ".join(strip_emotion_tags(line_text) for _, line_text in lines)

        logger.info("Translating digest to %s for session %s", lang_code, session_key)
        translated = await sarvam_translate(plain_text, lang_code, sarvam_key)

        logger.info("Generating Sarvam TTS audio for session %s", session_key)
        audio_bytes = await sarvam_tts(translated, lang_code, sarvam_voice, sarvam_model, sarvam_key)
        file_path = pathlib.Path(audio_dir) / f"digest_{session_key}.wav"

    file_path.write_bytes(audio_bytes)
    logger.info("Audio saved to %s", file_path)
    return str(file_path)

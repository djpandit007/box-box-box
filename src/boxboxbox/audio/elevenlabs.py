from __future__ import annotations

from elevenlabs import DialogueInput
from elevenlabs.client import AsyncElevenLabs


async def elevenlabs_tts(
    lines: list[tuple[str, str]],
    api_key: str,
    lead_voice_id: str,
    analyst_voice_id: str,
) -> bytes:
    """
    Call the ElevenLabs Text to Dialogue API.

    lines: list of (speaker, text) where speaker is "Lead" or "Analyst".
    text already contains ElevenLabs v3 emotional delivery tags, e.g. "[excited] What a race!".
    Returns raw MP3 bytes.
    """
    voice_map = {"Lead": lead_voice_id, "Analyst": analyst_voice_id}
    inputs = [DialogueInput(text=text, voice_id=voice_map[speaker]) for speaker, text in lines]

    client = AsyncElevenLabs(api_key=api_key)
    return await client.text_to_dialogue.convert(inputs=inputs)

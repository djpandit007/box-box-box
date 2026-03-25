from __future__ import annotations

import asyncio
import base64

from sarvamai import SarvamAI


def _translate_sync(text: str, target_lang: str, api_key: str) -> str:
    client = SarvamAI(api_subscription_key=api_key)
    response = client.text.translate(
        input=text,
        source_language_code="en-IN",
        target_language_code=target_lang,
    )
    return response.translated_text


def _tts_sync(text: str, lang: str, voice: str, model: str, api_key: str) -> bytes:
    client = SarvamAI(api_subscription_key=api_key)
    response = client.text_to_speech.convert(
        text=text,
        target_language_code=lang,
        speaker=voice,
        model=model,
    )
    return base64.b64decode(response.audios[0])


async def sarvam_translate(text: str, target_lang: str, api_key: str) -> str:
    """Translate text from English to target_lang using Sarvam AI."""
    return await asyncio.to_thread(_translate_sync, text, target_lang, api_key)


async def sarvam_tts(text: str, lang: str, voice: str, model: str, api_key: str) -> bytes:
    """Convert text to speech using Sarvam AI. Returns raw WAV bytes."""
    return await asyncio.to_thread(_tts_sync, text, lang, voice, model, api_key)

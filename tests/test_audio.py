from __future__ import annotations

import os
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from boxboxbox.audio.tts import generate_audio, parse_dialogue_lines, strip_emotion_tags

_DIALOGUE = (
    "Lead: [dramatic] Verstappen controls from the front.\n"
    "Analyst: [analytical] The undercut on lap 32 was decisive.\n"
    "Lead: [excited] Hamilton storms back from ninth to second!\n"
    "Analyst: [reflective] The championship stays very much alive."
)


class TestParseDialogueLines:
    def test_parses_lead_and_analyst(self):
        lines = parse_dialogue_lines(_DIALOGUE)
        assert len(lines) == 4
        assert lines[0] == ("Lead", "[dramatic] Verstappen controls from the front.")
        assert lines[1] == ("Analyst", "[analytical] The undercut on lap 32 was decisive.")
        assert lines[2] == ("Lead", "[excited] Hamilton storms back from ninth to second!")
        assert lines[3] == ("Analyst", "[reflective] The championship stays very much alive.")

    def test_skips_empty_lines(self):
        text = "Lead: [excited] First.\n\nAnalyst: [analytical] Second."
        lines = parse_dialogue_lines(text)
        assert len(lines) == 2

    def test_skips_unrecognised_prefixes(self):
        text = "Host: Something\nLead: [warmly] Valid line."
        lines = parse_dialogue_lines(text)
        assert len(lines) == 1
        assert lines[0][0] == "Lead"

    def test_empty_text_returns_empty_list(self):
        assert parse_dialogue_lines("") == []


class TestStripEmotionTags:
    def test_strips_single_tag(self):
        assert strip_emotion_tags("[excited] What a race!") == "What a race!"

    def test_strips_tag_with_spaces(self):
        assert strip_emotion_tags("[analytical] The strategy was key.") == "The strategy was key."

    def test_no_tag_unchanged(self):
        assert strip_emotion_tags("Plain text.") == "Plain text."

    def test_strips_multiple_tags(self):
        result = strip_emotion_tags("[sighing] Well, [laughing] that happened.")
        assert "[sighing]" not in result
        assert "[laughing]" not in result


class TestGenerateAudio:
    @pytest.mark.asyncio
    async def test_skipped_when_no_api_keys(self, tmp_path):
        fake_settings = SimpleNamespace(
            TTS_LANGUAGE="en",
            ELEVENLABS_API_KEY="",
            ELEVENLABS_LEAD_VOICE_ID="",
            ELEVENLABS_ANALYST_VOICE_ID="",
            SARVAM_API_KEY="",
            AUDIO_DIR=str(tmp_path),
        )
        with patch("boxboxbox.audio.tts.settings", fake_settings):
            result = await generate_audio(_DIALOGUE, 12345)
        assert result is None

    @pytest.mark.asyncio
    async def test_english_calls_elevenlabs(self, tmp_path):
        fake_settings = SimpleNamespace(
            TTS_LANGUAGE="en",
            ELEVENLABS_API_KEY="test-key",
            ELEVENLABS_LEAD_VOICE_ID="lead-id",
            ELEVENLABS_ANALYST_VOICE_ID="analyst-id",
            AUDIO_DIR=str(tmp_path),
        )
        fake_audio = b"fake-mp3-bytes"
        with patch("boxboxbox.audio.tts.settings", fake_settings):
            with patch("boxboxbox.audio.tts.elevenlabs_tts", new=AsyncMock(return_value=fake_audio)) as mock_tts:
                result = await generate_audio(_DIALOGUE, 99)

        mock_tts.assert_awaited_once()
        call_kwargs = mock_tts.call_args
        lines_arg = call_kwargs.args[0]
        assert lines_arg[0] == ("Lead", "[dramatic] Verstappen controls from the front.")
        assert call_kwargs.args[1] == "test-key"
        assert call_kwargs.args[2] == "lead-id"
        assert call_kwargs.args[3] == "analyst-id"
        assert result is not None
        assert result == str(tmp_path / "digest_99.mp3")
        assert pathlib.Path(result).read_bytes() == fake_audio

    @pytest.mark.asyncio
    async def test_hindi_calls_sarvam(self, tmp_path):
        fake_settings = SimpleNamespace(
            TTS_LANGUAGE="hi",
            SARVAM_API_KEY="sarvam-key",
            SARVAM_VOICE="anushka",
            SARVAM_MODEL="bulbul:v2",
            ELEVENLABS_API_KEY="",
            AUDIO_DIR=str(tmp_path),
        )
        translated = "हिंदी में अनुवाद।"
        fake_audio = b"fake-wav-bytes"
        with patch("boxboxbox.audio.tts.settings", fake_settings):
            with patch(
                "boxboxbox.audio.tts.sarvam_translate", new=AsyncMock(return_value=translated)
            ) as mock_translate:
                with patch("boxboxbox.audio.tts.sarvam_tts", new=AsyncMock(return_value=fake_audio)) as mock_tts:
                    result = await generate_audio(_DIALOGUE, 42)

        mock_translate.assert_awaited_once()
        translate_args = mock_translate.call_args.args
        assert translate_args[1] == "hi-IN"
        assert "[dramatic]" not in translate_args[0]  # emotion tags stripped

        mock_tts.assert_awaited_once()
        tts_args = mock_tts.call_args.args
        assert tts_args[0] == translated
        assert tts_args[1] == "hi-IN"
        assert result == str(tmp_path / "digest_42.wav")

    @pytest.mark.asyncio
    async def test_marathi_calls_sarvam(self, tmp_path):
        fake_settings = SimpleNamespace(
            TTS_LANGUAGE="mr",
            SARVAM_API_KEY="sarvam-key",
            SARVAM_VOICE="anushka",
            SARVAM_MODEL="bulbul:v2",
            ELEVENLABS_API_KEY="",
            AUDIO_DIR=str(tmp_path),
        )
        with patch("boxboxbox.audio.tts.settings", fake_settings):
            with patch("boxboxbox.audio.tts.sarvam_translate", new=AsyncMock(return_value="मराठी")) as mock_translate:
                with patch("boxboxbox.audio.tts.sarvam_tts", new=AsyncMock(return_value=b"wav")) as _:
                    await generate_audio(_DIALOGUE, 7)

        assert mock_translate.call_args.args[1] == "mr-IN"

    @pytest.mark.asyncio
    async def test_sarvam_strips_emotion_tags_before_translate(self, tmp_path):
        fake_settings = SimpleNamespace(
            TTS_LANGUAGE="hi",
            SARVAM_API_KEY="key",
            SARVAM_VOICE="anushka",
            SARVAM_MODEL="bulbul:v2",
            ELEVENLABS_API_KEY="",
            AUDIO_DIR=str(tmp_path),
        )
        with patch("boxboxbox.audio.tts.settings", fake_settings):
            with patch("boxboxbox.audio.tts.sarvam_translate", new=AsyncMock(return_value="text")) as mock_translate:
                with patch("boxboxbox.audio.tts.sarvam_tts", new=AsyncMock(return_value=b"wav")):
                    await generate_audio(_DIALOGUE, 1)

        plain_text_arg = mock_translate.call_args.args[0]
        assert "[dramatic]" not in plain_text_arg
        assert "[analytical]" not in plain_text_arg
        assert "[excited]" not in plain_text_arg
        assert "[reflective]" not in plain_text_arg

    @pytest.mark.asyncio
    async def test_audio_url_updated_in_db(self, tmp_path):
        fake_settings = SimpleNamespace(
            TTS_LANGUAGE="en",
            ELEVENLABS_API_KEY="key",
            ELEVENLABS_LEAD_VOICE_ID="l",
            ELEVENLABS_ANALYST_VOICE_ID="a",
            AUDIO_DIR=str(tmp_path),
        )
        with patch("boxboxbox.audio.tts.settings", fake_settings):
            with patch("boxboxbox.audio.tts.elevenlabs_tts", new=AsyncMock(return_value=b"mp3")):
                result = await generate_audio(_DIALOGUE, 55)
        assert result is not None
        assert "digest_55.mp3" in result

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_dialogue(self, tmp_path):
        env = {"ELEVENLABS_API_KEY": "key", "AUDIO_DIR": str(tmp_path)}
        with patch.dict(os.environ, env, clear=False):
            result = await generate_audio("No valid lines here.", 1)
        assert result is None

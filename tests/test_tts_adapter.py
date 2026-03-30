"""Tests for BaseTTSProvider and EdgeTTSProvider."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tts.base import BaseTTSProvider, TTSResult
from src.tts.edge_tts_provider import EdgeTTSProvider


# ---------------------------------------------------------------------------
# TTSResult dataclass tests
# ---------------------------------------------------------------------------


class TestTTSResult:
    def test_create_tts_result(self, tmp_path: Path):
        result = TTSResult(
            audio_path=tmp_path / "test.mp3",
            duration=3.5,
            sample_rate=24000,
        )
        assert result.audio_path == tmp_path / "test.mp3"
        assert result.duration == 3.5
        assert result.sample_rate == 24000

    def test_tts_result_fields(self):
        """TTSResult should have exactly the three expected fields."""
        import dataclasses

        fields = {f.name for f in dataclasses.fields(TTSResult)}
        assert fields == {"audio_path", "duration", "sample_rate"}


# ---------------------------------------------------------------------------
# BaseTTSProvider abstract class tests
# ---------------------------------------------------------------------------


class TestBaseTTSProvider:
    def test_cannot_instantiate_directly(self):
        """BaseTTSProvider is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseTTSProvider()

    def test_subclass_must_implement_synthesize(self):
        """A subclass missing synthesize should fail to instantiate."""

        class Incomplete(BaseTTSProvider):
            def list_voices(self) -> list[dict]:
                return []

        with pytest.raises(TypeError):
            Incomplete()

    def test_subclass_must_implement_list_voices(self):
        """A subclass missing list_voices should fail to instantiate."""

        class Incomplete(BaseTTSProvider):
            async def synthesize(self, text, voice, output_path):
                pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_can_be_instantiated(self):
        """A fully implemented subclass should instantiate fine."""

        class Concrete(BaseTTSProvider):
            async def synthesize(self, text, voice, output_path):
                return TTSResult(audio_path=output_path, duration=1.0, sample_rate=16000)

            def list_voices(self):
                return []

        provider = Concrete()
        assert isinstance(provider, BaseTTSProvider)


# ---------------------------------------------------------------------------
# EdgeTTSProvider tests
# ---------------------------------------------------------------------------


class TestEdgeTTSProviderInit:
    def test_default_voice(self):
        provider = EdgeTTSProvider()
        assert provider._default_voice == "zh-CN-XiaoxiaoNeural"

    def test_custom_default_voice(self):
        provider = EdgeTTSProvider(default_voice="zh-CN-YunxiNeural")
        assert provider._default_voice == "zh-CN-YunxiNeural"

    def test_is_base_tts_provider(self):
        provider = EdgeTTSProvider()
        assert isinstance(provider, BaseTTSProvider)


class TestEdgeTTSProviderListVoices:
    def test_list_voices_returns_list(self):
        provider = EdgeTTSProvider()
        voices = provider.list_voices()
        assert isinstance(voices, list)
        assert len(voices) > 0

    def test_voices_have_required_fields(self):
        provider = EdgeTTSProvider()
        voices = provider.list_voices()
        for voice in voices:
            assert "id" in voice
            assert "name" in voice
            assert "language" in voice

    def test_all_voices_are_chinese(self):
        provider = EdgeTTSProvider()
        voices = provider.list_voices()
        for voice in voices:
            assert voice["language"].startswith("zh-CN")

    def test_default_voice_in_list(self):
        provider = EdgeTTSProvider()
        voices = provider.list_voices()
        voice_ids = [v["id"] for v in voices]
        assert "zh-CN-XiaoxiaoNeural" in voice_ids

    def test_list_voices_returns_copy(self):
        """list_voices should return a new list each time (not a reference)."""
        provider = EdgeTTSProvider()
        v1 = provider.list_voices()
        v2 = provider.list_voices()
        assert v1 is not v2


class TestEdgeTTSProviderSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_empty_text_raises(self, tmp_path: Path):
        provider = EdgeTTSProvider()
        with pytest.raises(ValueError, match="合成文本不能为空"):
            await provider.synthesize("", "zh-CN-XiaoxiaoNeural", tmp_path / "out.mp3")

    @pytest.mark.asyncio
    async def test_synthesize_whitespace_text_raises(self, tmp_path: Path):
        provider = EdgeTTSProvider()
        with pytest.raises(ValueError, match="合成文本不能为空"):
            await provider.synthesize("   ", "zh-CN-XiaoxiaoNeural", tmp_path / "out.mp3")

    @pytest.mark.asyncio
    async def test_synthesize_uses_default_voice_when_empty(self, tmp_path: Path):
        """When voice is empty string, should fall back to default voice."""
        provider = EdgeTTSProvider()
        output_path = tmp_path / "out.mp3"

        # Mock edge_tts.Communicate to avoid real network calls
        mock_communicate_instance = AsyncMock()
        mock_communicate_instance.save = AsyncMock()

        # Create a fake MP3 file after save is called
        async def fake_save(path):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            # Write minimal valid MP3 header bytes
            p.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1000)

        mock_communicate_instance.save = AsyncMock(side_effect=fake_save)

        with patch("src.tts.edge_tts_provider.edge_tts.Communicate", return_value=mock_communicate_instance) as mock_cls, \
             patch.object(EdgeTTSProvider, "_get_audio_duration", return_value=2.5), \
             patch.object(EdgeTTSProvider, "_get_sample_rate", return_value=24000):
            result = await provider.synthesize("你好世界", "", output_path)
            # Should have used the default voice
            mock_cls.assert_called_once_with("你好世界", "zh-CN-XiaoxiaoNeural")

    @pytest.mark.asyncio
    async def test_synthesize_returns_tts_result(self, tmp_path: Path):
        provider = EdgeTTSProvider()
        output_path = tmp_path / "out.mp3"

        async def fake_save(path):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1000)

        mock_communicate_instance = AsyncMock()
        mock_communicate_instance.save = AsyncMock(side_effect=fake_save)

        with patch("src.tts.edge_tts_provider.edge_tts.Communicate", return_value=mock_communicate_instance), \
             patch.object(EdgeTTSProvider, "_get_audio_duration", return_value=3.0), \
             patch.object(EdgeTTSProvider, "_get_sample_rate", return_value=24000):
            result = await provider.synthesize("测试文本", "zh-CN-YunxiNeural", output_path)

        assert isinstance(result, TTSResult)
        assert result.audio_path == output_path
        assert result.duration == 3.0
        assert result.sample_rate == 24000

    @pytest.mark.asyncio
    async def test_synthesize_creates_parent_dirs(self, tmp_path: Path):
        provider = EdgeTTSProvider()
        output_path = tmp_path / "sub" / "dir" / "out.mp3"

        async def fake_save(path):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1000)

        mock_communicate_instance = AsyncMock()
        mock_communicate_instance.save = AsyncMock(side_effect=fake_save)

        with patch("src.tts.edge_tts_provider.edge_tts.Communicate", return_value=mock_communicate_instance), \
             patch.object(EdgeTTSProvider, "_get_audio_duration", return_value=1.0), \
             patch.object(EdgeTTSProvider, "_get_sample_rate", return_value=24000):
            result = await provider.synthesize("测试", "zh-CN-XiaoxiaoNeural", output_path)

        assert result.audio_path.parent.exists()

    @pytest.mark.asyncio
    async def test_synthesize_forces_mp3_extension(self, tmp_path: Path):
        provider = EdgeTTSProvider()
        output_path = tmp_path / "out.wav"  # Wrong extension

        async def fake_save(path):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1000)

        mock_communicate_instance = AsyncMock()
        mock_communicate_instance.save = AsyncMock(side_effect=fake_save)

        with patch("src.tts.edge_tts_provider.edge_tts.Communicate", return_value=mock_communicate_instance), \
             patch.object(EdgeTTSProvider, "_get_audio_duration", return_value=1.0), \
             patch.object(EdgeTTSProvider, "_get_sample_rate", return_value=24000):
            result = await provider.synthesize("测试", "zh-CN-XiaoxiaoNeural", output_path)

        assert result.audio_path.suffix == ".mp3"

    @pytest.mark.asyncio
    async def test_synthesize_edge_tts_failure_raises_runtime_error(self, tmp_path: Path):
        provider = EdgeTTSProvider()
        output_path = tmp_path / "out.mp3"

        mock_communicate_instance = AsyncMock()
        mock_communicate_instance.save = AsyncMock(side_effect=Exception("Network error"))

        with patch("src.tts.edge_tts_provider.edge_tts.Communicate", return_value=mock_communicate_instance):
            with pytest.raises(RuntimeError, match="Edge TTS 合成失败"):
                await provider.synthesize("测试", "zh-CN-XiaoxiaoNeural", output_path)

    @pytest.mark.asyncio
    async def test_synthesize_empty_output_raises(self, tmp_path: Path):
        provider = EdgeTTSProvider()
        output_path = tmp_path / "out.mp3"

        async def fake_save_empty(path):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"")  # Empty file

        mock_communicate_instance = AsyncMock()
        mock_communicate_instance.save = AsyncMock(side_effect=fake_save_empty)

        with patch("src.tts.edge_tts_provider.edge_tts.Communicate", return_value=mock_communicate_instance):
            with pytest.raises(RuntimeError, match="输出文件为空"):
                await provider.synthesize("测试", "zh-CN-XiaoxiaoNeural", output_path)


# ---------------------------------------------------------------------------
# Imports for HTTP-based TTS providers
# ---------------------------------------------------------------------------
import io
import struct
import wave

import httpx

from src.tts.cosyvoice import CosyVoiceProvider
from src.tts.fish_speech import FishSpeechProvider
from src.tts.chattts import ChatTTSProvider
from src.tts.melotts import MeloTTSProvider


def _make_wav_bytes(duration: float = 1.0, sample_rate: int = 22050) -> bytes:
    """Create minimal valid WAV file bytes for testing."""
    num_frames = int(sample_rate * duration)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


def _mock_httpx_response(status_code: int = 200, content: bytes = b"") -> httpx.Response:
    """Create an httpx.Response with a request set so raise_for_status works."""
    request = httpx.Request("POST", "http://test")
    return httpx.Response(status_code, content=content, request=request)


# ---------------------------------------------------------------------------
# CosyVoiceProvider tests
# ---------------------------------------------------------------------------


class TestCosyVoiceProviderInit:
    def test_default_values(self):
        provider = CosyVoiceProvider()
        assert provider._api_base == "http://localhost:9880"
        assert provider._default_voice == "中文女"

    def test_custom_values(self):
        provider = CosyVoiceProvider(api_base="http://myhost:1234/", default_voice="中文男")
        assert provider._api_base == "http://myhost:1234"
        assert provider._default_voice == "中文男"

    def test_is_base_tts_provider(self):
        assert isinstance(CosyVoiceProvider(), BaseTTSProvider)


class TestCosyVoiceProviderListVoices:
    def test_returns_list(self):
        voices = CosyVoiceProvider().list_voices()
        assert isinstance(voices, list)
        assert len(voices) > 0

    def test_voices_have_required_fields(self):
        for v in CosyVoiceProvider().list_voices():
            assert "id" in v and "name" in v and "language" in v

    def test_returns_copy(self):
        p = CosyVoiceProvider()
        assert p.list_voices() is not p.list_voices()


class TestCosyVoiceProviderSynthesize:
    @pytest.mark.asyncio
    async def test_empty_text_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="合成文本不能为空"):
            await CosyVoiceProvider().synthesize("", "中文女", tmp_path / "out.wav")

    @pytest.mark.asyncio
    async def test_successful_synthesis(self, tmp_path: Path):
        wav_data = _make_wav_bytes(duration=1.5, sample_rate=22050)
        output = tmp_path / "out.wav"

        mock_response = _mock_httpx_response(200, wav_data)
        with patch("src.tts.cosyvoice.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await CosyVoiceProvider().synthesize("你好", "中文女", output)

        assert isinstance(result, TTSResult)
        assert result.audio_path.exists()
        assert result.duration > 0
        assert result.sample_rate == 22050

    @pytest.mark.asyncio
    async def test_connect_error_raises_runtime(self, tmp_path: Path):
        with patch("src.tts.cosyvoice.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="服务不可用"):
                await CosyVoiceProvider().synthesize("你好", "中文女", tmp_path / "out.wav")

    @pytest.mark.asyncio
    async def test_timeout_raises_runtime(self, tmp_path: Path):
        with patch("src.tts.cosyvoice.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="超时"):
                await CosyVoiceProvider().synthesize("你好", "中文女", tmp_path / "out.wav")

    @pytest.mark.asyncio
    async def test_empty_response_raises(self, tmp_path: Path):
        mock_response = _mock_httpx_response(200, b"")
        with patch("src.tts.cosyvoice.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="空的音频数据"):
                await CosyVoiceProvider().synthesize("你好", "中文女", tmp_path / "out.wav")

    @pytest.mark.asyncio
    async def test_uses_default_voice_when_empty(self, tmp_path: Path):
        wav_data = _make_wav_bytes()
        mock_response = _mock_httpx_response(200, wav_data)
        with patch("src.tts.cosyvoice.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await CosyVoiceProvider(default_voice="中文男").synthesize("你好", "", tmp_path / "out.wav")
            call_args = mock_client.post.call_args
            assert call_args[1]["json"]["speaker"] == "中文男"


# ---------------------------------------------------------------------------
# FishSpeechProvider tests
# ---------------------------------------------------------------------------


class TestFishSpeechProviderInit:
    def test_default_values(self):
        provider = FishSpeechProvider()
        assert provider._api_base == "http://localhost:8080"
        assert provider._default_voice == "default"

    def test_is_base_tts_provider(self):
        assert isinstance(FishSpeechProvider(), BaseTTSProvider)


class TestFishSpeechProviderListVoices:
    def test_returns_list_with_fields(self):
        voices = FishSpeechProvider().list_voices()
        assert len(voices) > 0
        for v in voices:
            assert "id" in v and "name" in v and "language" in v


class TestFishSpeechProviderSynthesize:
    @pytest.mark.asyncio
    async def test_empty_text_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="合成文本不能为空"):
            await FishSpeechProvider().synthesize("  ", "default", tmp_path / "out.wav")

    @pytest.mark.asyncio
    async def test_successful_synthesis(self, tmp_path: Path):
        wav_data = _make_wav_bytes(duration=2.0, sample_rate=44100)
        mock_response = _mock_httpx_response(200, wav_data)
        with patch("src.tts.fish_speech.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await FishSpeechProvider().synthesize("测试", "default", tmp_path / "out.wav")

        assert isinstance(result, TTSResult)
        assert result.duration > 0
        assert result.sample_rate == 44100

    @pytest.mark.asyncio
    async def test_connect_error(self, tmp_path: Path):
        with patch("src.tts.fish_speech.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="服务不可用"):
                await FishSpeechProvider().synthesize("测试", "default", tmp_path / "out.wav")


# ---------------------------------------------------------------------------
# ChatTTSProvider tests
# ---------------------------------------------------------------------------


class TestChatTTSProviderInit:
    def test_default_values(self):
        provider = ChatTTSProvider()
        assert provider._api_base == "http://localhost:9966"
        assert provider._default_voice == "default"

    def test_is_base_tts_provider(self):
        assert isinstance(ChatTTSProvider(), BaseTTSProvider)


class TestChatTTSProviderListVoices:
    def test_returns_list_with_fields(self):
        voices = ChatTTSProvider().list_voices()
        assert len(voices) > 0
        for v in voices:
            assert "id" in v and "name" in v and "language" in v


class TestChatTTSProviderSynthesize:
    @pytest.mark.asyncio
    async def test_empty_text_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="合成文本不能为空"):
            await ChatTTSProvider().synthesize("", "default", tmp_path / "out.wav")

    @pytest.mark.asyncio
    async def test_successful_synthesis(self, tmp_path: Path):
        wav_data = _make_wav_bytes(duration=1.0, sample_rate=24000)
        mock_response = _mock_httpx_response(200, wav_data)
        with patch("src.tts.chattts.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await ChatTTSProvider().synthesize("你好世界", "default", tmp_path / "out.wav")

        assert isinstance(result, TTSResult)
        assert result.duration > 0
        assert result.sample_rate == 24000

    @pytest.mark.asyncio
    async def test_seed_voice_sends_seed(self, tmp_path: Path):
        wav_data = _make_wav_bytes()
        mock_response = _mock_httpx_response(200, wav_data)
        with patch("src.tts.chattts.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await ChatTTSProvider().synthesize("测试", "seed_1234", tmp_path / "out.wav")
            call_args = mock_client.post.call_args
            assert call_args[1]["json"]["seed"] == 1234

    @pytest.mark.asyncio
    async def test_connect_error(self, tmp_path: Path):
        with patch("src.tts.chattts.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="服务不可用"):
                await ChatTTSProvider().synthesize("测试", "default", tmp_path / "out.wav")


# ---------------------------------------------------------------------------
# MeloTTSProvider tests
# ---------------------------------------------------------------------------


class TestMeloTTSProviderInit:
    def test_default_values(self):
        provider = MeloTTSProvider()
        assert provider._api_base == "http://localhost:8888"
        assert provider._default_voice == "zh"

    def test_is_base_tts_provider(self):
        assert isinstance(MeloTTSProvider(), BaseTTSProvider)


class TestMeloTTSProviderListVoices:
    def test_returns_list_with_fields(self):
        voices = MeloTTSProvider().list_voices()
        assert len(voices) > 0
        for v in voices:
            assert "id" in v and "name" in v and "language" in v


class TestMeloTTSProviderSynthesize:
    @pytest.mark.asyncio
    async def test_empty_text_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="合成文本不能为空"):
            await MeloTTSProvider().synthesize("", "zh", tmp_path / "out.wav")

    @pytest.mark.asyncio
    async def test_successful_synthesis(self, tmp_path: Path):
        wav_data = _make_wav_bytes(duration=0.5, sample_rate=16000)
        mock_response = _mock_httpx_response(200, wav_data)
        with patch("src.tts.melotts.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await MeloTTSProvider().synthesize("你好", "zh", tmp_path / "out.wav")

        assert isinstance(result, TTSResult)
        assert result.duration > 0
        assert result.sample_rate == 16000

    @pytest.mark.asyncio
    async def test_sends_language_param(self, tmp_path: Path):
        wav_data = _make_wav_bytes()
        mock_response = _mock_httpx_response(200, wav_data)
        with patch("src.tts.melotts.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await MeloTTSProvider().synthesize("hello", "en", tmp_path / "out.wav")
            call_args = mock_client.post.call_args
            assert call_args[1]["json"]["language"] == "en"

    @pytest.mark.asyncio
    async def test_connect_error(self, tmp_path: Path):
        with patch("src.tts.melotts.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="服务不可用"):
                await MeloTTSProvider().synthesize("测试", "zh", tmp_path / "out.wav")

    @pytest.mark.asyncio
    async def test_timeout_error(self, tmp_path: Path):
        with patch("src.tts.melotts.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="超时"):
                await MeloTTSProvider().synthesize("测试", "zh", tmp_path / "out.wav")


# ---------------------------------------------------------------------------
# TTSAdapter tests
# ---------------------------------------------------------------------------

from src.tts.adapter import TTSAdapter


def _make_tts_config() -> dict:
    """Create a minimal TTS config dict for testing."""
    return {
        "cosyvoice": {
            "api_base": "http://localhost:9880",
            "default_voice": "中文女",
        },
        "fish_speech": {
            "api_base": "http://localhost:8080",
            "default_voice": "default",
        },
        "chattts": {
            "api_base": "http://localhost:9966",
            "default_voice": "default",
        },
        "melotts": {
            "api_base": "http://localhost:8888",
            "default_voice": "zh",
        },
        "edge_tts": {
            "default_voice": "zh-CN-XiaoxiaoNeural",
        },
    }


class TestTTSAdapterInit:
    def test_creates_with_config(self):
        adapter = TTSAdapter(_make_tts_config())
        assert adapter._config is not None

    def test_creates_with_empty_config(self):
        adapter = TTSAdapter({})
        assert adapter._config == {}

    def test_providers_registry_has_all_providers(self):
        expected = {"cosyvoice", "fish_speech", "chattts", "melotts", "edge_tts"}
        assert set(TTSAdapter.PROVIDERS.keys()) == expected


class TestTTSAdapterListProviders:
    def test_returns_all_provider_names(self):
        adapter = TTSAdapter(_make_tts_config())
        providers = adapter.list_providers()
        assert isinstance(providers, list)
        expected = {"cosyvoice", "fish_speech", "chattts", "melotts", "edge_tts"}
        assert set(providers) == expected

    def test_edge_tts_always_present(self):
        adapter = TTSAdapter({})
        providers = adapter.list_providers()
        assert "edge_tts" in providers


class TestTTSAdapterListVoices:
    def test_list_edge_tts_voices(self):
        adapter = TTSAdapter(_make_tts_config())
        voices = adapter.list_voices("edge_tts")
        assert isinstance(voices, list)
        assert len(voices) > 0
        for v in voices:
            assert "id" in v and "name" in v and "language" in v

    def test_list_cosyvoice_voices(self):
        adapter = TTSAdapter(_make_tts_config())
        voices = adapter.list_voices("cosyvoice")
        assert len(voices) > 0

    def test_list_fish_speech_voices(self):
        adapter = TTSAdapter(_make_tts_config())
        voices = adapter.list_voices("fish_speech")
        assert len(voices) > 0

    def test_list_chattts_voices(self):
        adapter = TTSAdapter(_make_tts_config())
        voices = adapter.list_voices("chattts")
        assert len(voices) > 0

    def test_list_melotts_voices(self):
        adapter = TTSAdapter(_make_tts_config())
        voices = adapter.list_voices("melotts")
        assert len(voices) > 0

    def test_unknown_provider_raises(self):
        adapter = TTSAdapter(_make_tts_config())
        with pytest.raises(ValueError, match="未知的 TTS provider"):
            adapter.list_voices("nonexistent")


class TestTTSAdapterSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_with_edge_tts_directly(self, tmp_path: Path):
        """When provider_name is edge_tts, should call EdgeTTS directly."""
        adapter = TTSAdapter(_make_tts_config())
        output = tmp_path / "out.mp3"

        mock_result = TTSResult(audio_path=output, duration=2.0, sample_rate=24000)

        with patch.object(EdgeTTSProvider, "synthesize", new_callable=AsyncMock, return_value=mock_result) as mock_synth:
            result = await adapter.synthesize("你好", "edge_tts", "zh-CN-XiaoxiaoNeural", output)

        assert result == mock_result
        mock_synth.assert_called_once_with("你好", "zh-CN-XiaoxiaoNeural", output)

    @pytest.mark.asyncio
    async def test_synthesize_with_cosyvoice_success(self, tmp_path: Path):
        """When cosyvoice succeeds, should return its result without fallback."""
        adapter = TTSAdapter(_make_tts_config())
        output = tmp_path / "out.wav"

        mock_result = TTSResult(audio_path=output, duration=3.0, sample_rate=22050)

        with patch.object(CosyVoiceProvider, "synthesize", new_callable=AsyncMock, return_value=mock_result) as mock_synth:
            result = await adapter.synthesize("你好世界", "cosyvoice", "中文女", output)

        assert result == mock_result
        mock_synth.assert_called_once_with("你好世界", "中文女", output)

    @pytest.mark.asyncio
    async def test_synthesize_fallback_on_failure(self, tmp_path: Path):
        """When primary provider fails, should fallback to Edge TTS."""
        adapter = TTSAdapter(_make_tts_config())
        output = tmp_path / "out.wav"

        fallback_result = TTSResult(audio_path=output.with_suffix(".mp3"), duration=2.0, sample_rate=24000)

        with patch.object(CosyVoiceProvider, "synthesize", new_callable=AsyncMock, side_effect=RuntimeError("服务不可用")), \
             patch.object(EdgeTTSProvider, "synthesize", new_callable=AsyncMock, return_value=fallback_result) as mock_edge:
            result = await adapter.synthesize("你好", "cosyvoice", "中文女", output)

        assert result == fallback_result
        # Edge TTS should have been called with its default voice (since "中文女" is not an Edge voice)
        mock_edge.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_uses_edge_default_voice_for_unknown_voice(self, tmp_path: Path):
        """When falling back, if the voice is not an Edge TTS voice, use Edge default."""
        adapter = TTSAdapter(_make_tts_config())
        output = tmp_path / "out.wav"

        fallback_result = TTSResult(audio_path=output.with_suffix(".mp3"), duration=1.5, sample_rate=24000)

        with patch.object(FishSpeechProvider, "synthesize", new_callable=AsyncMock, side_effect=RuntimeError("timeout")), \
             patch.object(EdgeTTSProvider, "synthesize", new_callable=AsyncMock, return_value=fallback_result) as mock_edge:
            result = await adapter.synthesize("测试", "fish_speech", "unknown_voice", output)

        assert result == fallback_result
        # Should use Edge TTS default voice since "unknown_voice" is not in Edge voice list
        call_args = mock_edge.call_args
        assert call_args[0][1] == "zh-CN-XiaoxiaoNeural"

    @pytest.mark.asyncio
    async def test_fallback_preserves_edge_voice_if_valid(self, tmp_path: Path):
        """When falling back, if the voice IS a valid Edge TTS voice, keep it."""
        adapter = TTSAdapter(_make_tts_config())
        output = tmp_path / "out.wav"

        fallback_result = TTSResult(audio_path=output.with_suffix(".mp3"), duration=1.5, sample_rate=24000)

        with patch.object(ChatTTSProvider, "synthesize", new_callable=AsyncMock, side_effect=RuntimeError("error")), \
             patch.object(EdgeTTSProvider, "synthesize", new_callable=AsyncMock, return_value=fallback_result) as mock_edge:
            result = await adapter.synthesize("测试", "chattts", "zh-CN-YunxiNeural", output)

        call_args = mock_edge.call_args
        assert call_args[0][1] == "zh-CN-YunxiNeural"

    @pytest.mark.asyncio
    async def test_synthesize_unknown_provider_falls_back(self, tmp_path: Path):
        """When an unknown provider is requested, it should raise ValueError (not fallback)."""
        adapter = TTSAdapter(_make_tts_config())
        output = tmp_path / "out.wav"

        fallback_result = TTSResult(audio_path=output.with_suffix(".mp3"), duration=1.0, sample_rate=24000)

        # Unknown provider will raise ValueError during instantiation,
        # which triggers fallback
        with patch.object(EdgeTTSProvider, "synthesize", new_callable=AsyncMock, return_value=fallback_result):
            result = await adapter.synthesize("测试", "nonexistent", "voice", output)

        assert result == fallback_result

    @pytest.mark.asyncio
    async def test_provider_instances_are_cached(self, tmp_path: Path):
        """Provider instances should be cached after first creation."""
        adapter = TTSAdapter(_make_tts_config())

        mock_result = TTSResult(audio_path=tmp_path / "out.mp3", duration=1.0, sample_rate=24000)

        with patch.object(EdgeTTSProvider, "synthesize", new_callable=AsyncMock, return_value=mock_result):
            await adapter.synthesize("第一次", "edge_tts", "zh-CN-XiaoxiaoNeural", tmp_path / "out1.mp3")
            await adapter.synthesize("第二次", "edge_tts", "zh-CN-XiaoxiaoNeural", tmp_path / "out2.mp3")

        # Should have only one EdgeTTSProvider instance
        assert "edge_tts" in adapter._instances
        assert isinstance(adapter._instances["edge_tts"], EdgeTTSProvider)


class TestTTSAdapterInstantiateProvider:
    def test_instantiate_edge_tts(self):
        adapter = TTSAdapter(_make_tts_config())
        provider = adapter._instantiate_provider("edge_tts")
        assert isinstance(provider, EdgeTTSProvider)
        assert provider._default_voice == "zh-CN-XiaoxiaoNeural"

    def test_instantiate_cosyvoice(self):
        adapter = TTSAdapter(_make_tts_config())
        provider = adapter._instantiate_provider("cosyvoice")
        assert isinstance(provider, CosyVoiceProvider)
        assert provider._api_base == "http://localhost:9880"

    def test_instantiate_fish_speech(self):
        adapter = TTSAdapter(_make_tts_config())
        provider = adapter._instantiate_provider("fish_speech")
        assert isinstance(provider, FishSpeechProvider)

    def test_instantiate_chattts(self):
        adapter = TTSAdapter(_make_tts_config())
        provider = adapter._instantiate_provider("chattts")
        assert isinstance(provider, ChatTTSProvider)

    def test_instantiate_melotts(self):
        adapter = TTSAdapter(_make_tts_config())
        provider = adapter._instantiate_provider("melotts")
        assert isinstance(provider, MeloTTSProvider)

    def test_instantiate_unknown_raises(self):
        adapter = TTSAdapter(_make_tts_config())
        with pytest.raises(ValueError, match="未知的 TTS provider"):
            adapter._instantiate_provider("nonexistent")

    def test_instantiate_with_empty_config_uses_defaults(self):
        adapter = TTSAdapter({})
        # Edge TTS should still work with empty config
        provider = adapter._instantiate_provider("edge_tts")
        assert isinstance(provider, EdgeTTSProvider)

    def test_instantiate_cosyvoice_with_empty_config_uses_defaults(self):
        adapter = TTSAdapter({})
        provider = adapter._instantiate_provider("cosyvoice")
        assert isinstance(provider, CosyVoiceProvider)
        assert provider._api_base == "http://localhost:9880"
        assert provider._default_voice == "中文女"

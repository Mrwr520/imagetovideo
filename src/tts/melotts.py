"""MeloTTSProvider：通过 HTTP API 调用 MeloTTS 服务。"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import httpx

from src.tts.base import BaseTTSProvider, TTSResult


class MeloTTSProvider(BaseTTSProvider):
    """MeloTTS Provider，通过 HTTP API 调用。

    默认 API 地址: http://localhost:8888
    """

    DEFAULT_VOICES: list[dict] = [
        {"id": "zh", "name": "中文", "language": "zh-CN"},
        {"id": "en", "name": "英文", "language": "en"},
        {"id": "es", "name": "西班牙语", "language": "es"},
        {"id": "fr", "name": "法语", "language": "fr"},
        {"id": "ja", "name": "日语", "language": "ja"},
        {"id": "ko", "name": "韩语", "language": "ko"},
    ]

    def __init__(self, api_base: str = "http://localhost:8888", default_voice: str = "zh"):
        """初始化 MeloTTSProvider。

        Args:
            api_base: MeloTTS 服务 API 地址。
            default_voice: 默认音色/语言。
        """
        self._api_base = api_base.rstrip("/")
        self._default_voice = default_voice

    async def synthesize(self, text: str, voice: str, output_path: Path, **kwargs) -> TTSResult:
        """通过 MeloTTS HTTP API 合成语音。

        Args:
            text: 待合成的文本。
            voice: 音色/语言标识符。
            output_path: 输出音频文件路径。

        Returns:
            TTSResult 包含音频路径、时长和采样率。

        Raises:
            ValueError: 文本为空时抛出。
            RuntimeError: 服务不可用或合成失败时抛出。
        """
        if not text or not text.strip():
            raise ValueError("合成文本不能为空")

        voice = voice or self._default_voice
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.suffix.lower() != ".wav":
            output_path = output_path.with_suffix(".wav")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._api_base}/api/tts",
                    json={
                        "text": text,
                        "language": voice,
                    },
                )
                response.raise_for_status()
        except httpx.ConnectError as e:
            raise RuntimeError(f"MeloTTS 服务不可用 ({self._api_base}): {e}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError(f"MeloTTS 请求超时: {e}") from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"MeloTTS 合成失败 (HTTP {e.response.status_code}): {e}") from e

        audio_data = response.content
        if not audio_data:
            raise RuntimeError("MeloTTS 返回了空的音频数据")

        output_path.write_bytes(audio_data)

        duration = self._get_wav_duration(output_path)
        sample_rate = self._get_wav_sample_rate(output_path)

        return TTSResult(audio_path=output_path, duration=duration, sample_rate=sample_rate)

    def list_voices(self) -> list[dict]:
        """返回 MeloTTS 可用音色列表。"""
        return list(self.DEFAULT_VOICES)

    @staticmethod
    def _get_wav_duration(audio_path: Path) -> float:
        """获取 WAV 文件时长。"""
        with wave.open(str(audio_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / float(rate)

    @staticmethod
    def _get_wav_sample_rate(audio_path: Path) -> int:
        """获取 WAV 文件采样率。"""
        with wave.open(str(audio_path), "rb") as wf:
            return wf.getframerate()

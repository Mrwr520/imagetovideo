"""EdgeTTSProvider：使用 edge-tts 库的兜底 TTS 方案。"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import edge_tts
from mutagen.mp3 import MP3

from src.tts.base import BaseTTSProvider, TTSResult


class EdgeTTSProvider(BaseTTSProvider):
    """Edge TTS Provider，作为兜底方案。

    使用微软 Edge TTS 服务，通过 edge-tts 库调用。
    默认输出 MP3 格式。
    """

    # 预定义的中文音色列表
    CHINESE_VOICES: list[dict] = [
        {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓（女）", "language": "zh-CN"},
        {"id": "zh-CN-YunxiNeural", "name": "云希（男）", "language": "zh-CN"},
        {"id": "zh-CN-YunjianNeural", "name": "云健（男）", "language": "zh-CN"},
        {"id": "zh-CN-XiaoyiNeural", "name": "晓伊（女）", "language": "zh-CN"},
        {"id": "zh-CN-YunyangNeural", "name": "云扬（男）", "language": "zh-CN"},
        {"id": "zh-CN-XiaochenNeural", "name": "晓辰（女）", "language": "zh-CN"},
        {"id": "zh-CN-XiaohanNeural", "name": "晓涵（女）", "language": "zh-CN"},
        {"id": "zh-CN-XiaomengNeural", "name": "晓梦（女）", "language": "zh-CN"},
        {"id": "zh-CN-XiaomoNeural", "name": "晓墨（女）", "language": "zh-CN"},
        {"id": "zh-CN-XiaoruiNeural", "name": "晓睿（女）", "language": "zh-CN"},
        {"id": "zh-CN-XiaoshuangNeural", "name": "晓双（女/童声）", "language": "zh-CN"},
        {"id": "zh-CN-XiaoxuanNeural", "name": "晓萱（女）", "language": "zh-CN"},
        {"id": "zh-CN-XiaoyanNeural", "name": "晓颜（女）", "language": "zh-CN"},
        {"id": "zh-CN-XiaozhenNeural", "name": "晓甄（女）", "language": "zh-CN"},
        {"id": "zh-CN-YunfengNeural", "name": "云枫（男）", "language": "zh-CN"},
        {"id": "zh-CN-YunhaoNeural", "name": "云皓（男）", "language": "zh-CN"},
        {"id": "zh-CN-YunxiaNeural", "name": "云夏（男/童声）", "language": "zh-CN"},
        {"id": "zh-CN-YunzeNeural", "name": "云泽（男）", "language": "zh-CN"},
    ]

    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

    def __init__(self, default_voice: str | None = None):
        """初始化 EdgeTTSProvider。

        Args:
            default_voice: 默认音色 ID，为 None 时使用 zh-CN-XiaoxiaoNeural。
        """
        self._default_voice = default_voice or self.DEFAULT_VOICE

    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
        """使用 Edge TTS 将文本合成为 MP3 音频文件。

        Args:
            text: 待合成的文本。
            voice: 音色标识符（如 zh-CN-XiaoxiaoNeural）。
            output_path: 输出音频文件路径。

        Returns:
            TTSResult 包含音频路径、时长和采样率。

        Raises:
            ValueError: 文本为空时抛出。
            RuntimeError: 合成失败时抛出。
        """
        if not text or not text.strip():
            raise ValueError("合成文本不能为空")

        voice = voice or self._default_voice

        # 确保输出目录存在
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 确保输出文件为 .mp3 扩展名
        if output_path.suffix.lower() != ".mp3":
            output_path = output_path.with_suffix(".mp3")

        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))
        except Exception as e:
            raise RuntimeError(f"Edge TTS 合成失败: {e}") from e

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Edge TTS 合成失败：输出文件为空")

        duration = self._get_audio_duration(output_path)
        # Edge TTS 默认输出 24kHz MP3
        sample_rate = self._get_sample_rate(output_path)

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            sample_rate=sample_rate,
        )

    def list_voices(self) -> list[dict]:
        """返回预定义的中文音色列表。

        Returns:
            音色列表，每项包含 id, name, language 字段。
        """
        return list(self.CHINESE_VOICES)

    @staticmethod
    def _get_audio_duration(audio_path: Path) -> float:
        """获取音频文件时长。

        Args:
            audio_path: 音频文件路径。

        Returns:
            音频时长（秒）。
        """
        suffix = audio_path.suffix.lower()
        if suffix == ".mp3":
            audio = MP3(str(audio_path))
            return audio.info.length
        elif suffix == ".wav":
            with wave.open(str(audio_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / float(rate)
        else:
            raise ValueError(f"不支持的音频格式: {suffix}")

    @staticmethod
    def _get_sample_rate(audio_path: Path) -> int:
        """获取音频文件采样率。

        Args:
            audio_path: 音频文件路径。

        Returns:
            采样率（Hz）。
        """
        suffix = audio_path.suffix.lower()
        if suffix == ".mp3":
            audio = MP3(str(audio_path))
            return audio.info.sample_rate
        elif suffix == ".wav":
            with wave.open(str(audio_path), "rb") as wf:
                return wf.getframerate()
        else:
            raise ValueError(f"不支持的音频格式: {suffix}")

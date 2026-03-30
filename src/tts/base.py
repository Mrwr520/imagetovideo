"""BaseTTSProvider 抽象基类和 TTSResult 数据类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TTSResult:
    """语音合成结果。"""

    audio_path: Path
    duration: float  # 音频时长（秒）
    sample_rate: int


class BaseTTSProvider(ABC):
    """所有 TTS Provider 的抽象基类。"""

    @abstractmethod
    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
        """将文本合成为音频文件。

        Args:
            text: 待合成的文本。
            voice: 音色标识符。
            output_path: 输出音频文件路径。

        Returns:
            TTSResult 包含音频路径、时长和采样率。
        """
        ...

    @abstractmethod
    def list_voices(self) -> list[dict]:
        """返回可用音色列表。

        Returns:
            音色列表，每项包含 id, name, language 字段。
        """
        ...

"""BaseLLMProvider：大模型适配器抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseLLMProvider(ABC):
    """所有 LLM Provider 的抽象基类。"""

    @abstractmethod
    async def generate_narration(self, images: list[Path], prompt: str) -> str:
        """根据图片列表和提示词生成解说词文本。

        Args:
            images: 图片文件路径列表。
            prompt: 提示词文本。

        Returns:
            生成的解说词文本。
        """
        ...

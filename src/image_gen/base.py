"""BaseImageProvider 抽象基类和 ImageGenResult 数据类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImageGenResult:
    """出图结果。"""

    image_path: Path  # 生成图片的文件路径
    prompt: str  # 实际使用的提示词
    seed: int | None = None  # 随机种子（可复现）
    metadata: dict = field(default_factory=dict)  # 额外元数据（模型名、耗时等）


class BaseImageProvider(ABC):
    """所有出图 Provider 的抽象基类。"""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        style: str = "",
        ref_images: list[Path] | None = None,
        negative_prompt: str = "",
        width: int = 720,
        height: int = 1280,
        seed: int | None = None,
        output_path: Path | None = None,
    ) -> ImageGenResult:
        """根据提示词生成图片。

        Args:
            prompt: 正向提示词。
            style: 画风/风格标签（如 "anime", "realistic"）。
            ref_images: 角色参考图路径列表（用于角色一致性）。
            negative_prompt: 负面提示词。
            width: 图片宽度（像素）。
            height: 图片高度（像素）。
            seed: 随机种子，None 表示随机。
            output_path: 输出文件路径，None 则由 provider 自动生成。

        Returns:
            ImageGenResult 包含图片路径、提示词、种子和元数据。
        """
        ...

    @abstractmethod
    def list_styles(self) -> list[dict]:
        """返回该 provider 支持的风格列表。

        Returns:
            风格列表，每项包含 id, name, description 字段。
        """
        ...

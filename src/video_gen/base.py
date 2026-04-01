"""BaseVideoGenProvider 抽象基类和 VideoGenResult 数据类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VideoGenResult:
    """视频生成结果。"""

    video_path: Path  # 生成视频的文件路径
    duration: float = 0.0  # 视频时长（秒）
    width: int = 0  # 视频宽度
    height: int = 0  # 视频高度
    fps: float = 0.0  # 帧率
    seed: int | None = None  # 随机种子（可复现）
    metadata: dict = field(default_factory=dict)  # 额外元数据


class BaseVideoGenProvider(ABC):
    """所有视频生成 Provider 的抽象基类。"""

    @abstractmethod
    async def generate(
        self,
        image_path: Path,
        *,
        prompt: str = "",
        negative_prompt: str = "",
        duration: float = 4.0,
        width: int = 720,
        height: int = 1280,
        fps: float = 24.0,
        seed: int | None = None,
        output_path: Path | None = None,
    ) -> VideoGenResult:
        """根据图片生成视频（I2V）。

        Args:
            image_path: 输入图片路径。
            prompt: 运动/动作提示词。
            negative_prompt: 负面提示词。
            duration: 视频时长（秒）。
            width: 视频宽度（像素）。
            height: 视频高度（像素）。
            fps: 帧率。
            seed: 随机种子，None 表示随机。
            output_path: 输出文件路径，None 则由 provider 自动生成。

        Returns:
            VideoGenResult 包含视频路径、时长、分辨率等信息。
        """
        ...

    @abstractmethod
    def list_models(self) -> list[dict]:
        """返回该 provider 支持的模型列表。

        Returns:
            模型列表，每项包含 id, name, description 字段。
        """
        ...

    @abstractmethod
    def get_vram_requirement(self) -> int:
        """返回该 provider 的显存需求（MB）。

        Returns:
            显存需求（MB），0 表示不需要本地 GPU。
        """
        ...

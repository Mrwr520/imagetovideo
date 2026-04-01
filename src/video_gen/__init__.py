"""视频生成模块：图生视频 Provider 抽象层。"""

from src.video_gen.base import BaseVideoGenProvider, VideoGenResult
from src.video_gen.adapter import VideoGenAdapter

__all__ = ["BaseVideoGenProvider", "VideoGenResult", "VideoGenAdapter"]

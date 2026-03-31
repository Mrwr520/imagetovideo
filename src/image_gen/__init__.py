"""AI 出图模块。"""

from src.image_gen.adapter import ImageGenAdapter, register_provider
from src.image_gen.base import BaseImageProvider, ImageGenResult

# 导入 provider 模块以触发自注册
import src.image_gen.wanx as _wanx  # noqa: F401
import src.image_gen.comfyui as _comfyui  # noqa: F401

__all__ = [
    "BaseImageProvider",
    "ImageGenAdapter",
    "ImageGenResult",
    "register_provider",
]

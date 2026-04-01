"""VideoGenAdapter：视频生成适配器，支持多 provider 切换。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Type

from src.video_gen.base import BaseVideoGenProvider, VideoGenResult

logger = logging.getLogger(__name__)

# Provider name -> Provider class
_PROVIDER_REGISTRY: dict[str, Type[BaseVideoGenProvider]] = {}

# 默认 provider 名称
_DEFAULT_PROVIDER = "wan2gp"


def register_provider(name: str, cls: Type[BaseVideoGenProvider]) -> None:
    """注册一个视频生成 provider。

    供各 provider 模块在导入时调用，实现自注册。

    Args:
        name: provider 名称（如 "wan2gp", "kling"）。
        cls: provider 类。
    """
    _PROVIDER_REGISTRY[name] = cls


class VideoGenAdapter:
    """视频生成适配器，支持多 provider 切换和回退。

    Config 结构示例（config.toml 的 [video_gen] 部分）::

        [video_gen]
        default_provider = "wan2gp"

        [video_gen.wan2gp]
        model_path = "./models/wan2.1"
        vram_limit = 8192

        [video_gen.kling]
        api_key = ""
        api_base = "https://api.kling.ai"
    """

    PROVIDERS = _PROVIDER_REGISTRY

    def __init__(self, config: dict) -> None:
        """初始化 VideoGenAdapter。

        Args:
            config: config.toml 中 ``[video_gen]`` 部分的字典。
        """
        self._config = config
        self._default_provider = config.get("default_provider", _DEFAULT_PROVIDER)
        self._instances: dict[str, BaseVideoGenProvider] = {}

    def _get_provider_config(self, name: str) -> dict:
        """获取指定 provider 的配置子字典。"""
        return self._config.get(name, {})

    def _instantiate_provider(self, name: str) -> BaseVideoGenProvider:
        """根据名称和配置实例化一个视频生成 provider。"""
        if name not in self.PROVIDERS:
            raise ValueError(
                f"未知的视频生成 provider: {name}，"
                f"已注册: {list(self.PROVIDERS.keys())}"
            )

        cls = self.PROVIDERS[name]
        cfg = self._get_provider_config(name)
        return cls(config=cfg)

    def _get_or_create_provider(self, name: str) -> BaseVideoGenProvider:
        """获取缓存的 provider 实例，不存在则创建。"""
        if name not in self._instances:
            self._instances[name] = self._instantiate_provider(name)
        return self._instances[name]

    async def generate(
        self,
        image_path: Path,
        *,
        provider_name: str | None = None,
        prompt: str = "",
        negative_prompt: str = "",
        duration: float = 4.0,
        width: int = 720,
        height: int = 1280,
        fps: float = 24.0,
        seed: int | None = None,
        output_path: Path | None = None,
    ) -> VideoGenResult:
        """生成视频，失败时尝试回退到其他可用 provider。

        Args:
            image_path: 输入图片路径。
            provider_name: 要使用的 provider 名称，None 则使用默认。
            prompt: 运动/动作提示词。
            negative_prompt: 负面提示词。
            duration: 视频时长（秒）。
            width: 视频宽度。
            height: 视频高度。
            fps: 帧率。
            seed: 随机种子。
            output_path: 输出文件路径。

        Returns:
            VideoGenResult 包含视频路径等信息。

        Raises:
            RuntimeError: 所有 provider 均失败时抛出。
        """
        name = provider_name or self._default_provider

        try:
            provider = self._get_or_create_provider(name)
            return await provider.generate(
                image_path,
                prompt=prompt,
                negative_prompt=negative_prompt,
                duration=duration,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
                output_path=output_path,
            )
        except Exception as exc:
            logger.warning(
                "视频生成 provider '%s' 失败: %s，尝试回退...",
                name,
                exc,
            )

        # 回退：尝试其他已注册的 provider
        for fallback_name in self.PROVIDERS:
            if fallback_name == name:
                continue
            try:
                logger.info("尝试回退到视频生成 provider: %s", fallback_name)
                provider = self._get_or_create_provider(fallback_name)
                return await provider.generate(
                    image_path,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    duration=duration,
                    width=width,
                    height=height,
                    fps=fps,
                    seed=seed,
                    output_path=output_path,
                )
            except Exception as fallback_exc:
                logger.warning(
                    "回退 provider '%s' 也失败: %s",
                    fallback_name,
                    fallback_exc,
                )

        raise RuntimeError(
            f"所有视频生成 provider 均失败，已尝试: {name} + "
            f"{[n for n in self.PROVIDERS if n != name]}"
        )

    def list_providers(self) -> list[str]:
        """返回所有已注册的视频生成 provider 名称列表。"""
        return list(self.PROVIDERS.keys())

    def list_models(self, provider_name: str | None = None) -> list[dict]:
        """返回指定 provider 支持的模型列表。"""
        name = provider_name or self._default_provider
        provider = self._get_or_create_provider(name)
        return provider.list_models()

    def get_vram_requirement(self, provider_name: str | None = None) -> int:
        """返回指定 provider 的显存需求（MB）。"""
        name = provider_name or self._default_provider
        provider = self._get_or_create_provider(name)
        return provider.get_vram_requirement()

    @property
    def default_provider(self) -> str:
        """当前默认 provider 名称。"""
        return self._default_provider

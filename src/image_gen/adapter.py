"""ImageGenAdapter：出图适配器，支持多 provider 切换和回退。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Type

from src.image_gen.base import BaseImageProvider, ImageGenResult

logger = logging.getLogger(__name__)

# Provider name -> Provider class
_PROVIDER_REGISTRY: dict[str, Type[BaseImageProvider]] = {}

# 默认 provider 名称（config 中未指定时使用）
_DEFAULT_PROVIDER = "wanx"


def register_provider(name: str, cls: Type[BaseImageProvider]) -> None:
    """注册一个出图 provider。

    供各 provider 模块在导入时调用，实现自注册。

    Args:
        name: provider 名称（如 "wanx", "comfyui"）。
        cls: provider 类。
    """
    _PROVIDER_REGISTRY[name] = cls


class ImageGenAdapter:
    """出图适配器，支持多 provider 切换和回退。

    Config 结构示例（config.toml 的 [image_gen] 部分）::

        [image_gen]
        default_provider = "wanx"

        [image_gen.wanx]
        api_key = ""
        model = "wanx-v1"
        default_style = "anime"

        [image_gen.comfyui]
        api_base = "http://localhost:8188"
        workflow = "default_workflow.json"
    """

    PROVIDERS = _PROVIDER_REGISTRY

    def __init__(self, config: dict) -> None:
        """初始化 ImageGenAdapter。

        Args:
            config: config.toml 中 ``[image_gen]`` 部分的字典。
                    每个 key 对应一个 provider 名称，value 是该 provider 的配置。
        """
        self._config = config
        self._default_provider = config.get("default_provider", _DEFAULT_PROVIDER)
        # 缓存已实例化的 provider
        self._instances: dict[str, BaseImageProvider] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_provider_config(self, name: str) -> dict:
        """获取指定 provider 的配置子字典。"""
        return self._config.get(name, {})

    def _instantiate_provider(self, name: str) -> BaseImageProvider:
        """根据名称和配置实例化一个出图 provider。

        Raises:
            ValueError: provider 名称未注册时抛出。
        """
        if name not in self.PROVIDERS:
            raise ValueError(
                f"未知的出图 provider: {name}，"
                f"已注册: {list(self.PROVIDERS.keys())}"
            )

        cls = self.PROVIDERS[name]
        cfg = self._get_provider_config(name)
        return cls(config=cfg)

    def _get_or_create_provider(self, name: str) -> BaseImageProvider:
        """获取缓存的 provider 实例，不存在则创建。"""
        if name not in self._instances:
            self._instances[name] = self._instantiate_provider(name)
        return self._instances[name]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        provider_name: str | None = None,
        style: str = "",
        ref_images: list[Path] | None = None,
        negative_prompt: str = "",
        width: int = 720,
        height: int = 1280,
        seed: int | None = None,
        output_path: Path | None = None,
    ) -> ImageGenResult:
        """生成图片，失败时尝试回退到其他可用 provider。

        Args:
            prompt: 正向提示词。
            provider_name: 要使用的 provider 名称，None 则使用默认。
            style: 画风/风格标签。
            ref_images: 角色参考图路径列表。
            negative_prompt: 负面提示词。
            width: 图片宽度。
            height: 图片高度。
            seed: 随机种子。
            output_path: 输出文件路径。

        Returns:
            ImageGenResult 包含图片路径、提示词、种子和元数据。

        Raises:
            RuntimeError: 所有 provider 均失败时抛出。
        """
        name = provider_name or self._default_provider

        # 尝试使用指定 provider
        try:
            provider = self._get_or_create_provider(name)
            return await provider.generate(
                prompt,
                style=style,
                ref_images=ref_images,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                seed=seed,
                output_path=output_path,
            )
        except Exception as exc:
            logger.warning(
                "出图 provider '%s' 失败: %s，尝试回退...",
                name,
                exc,
            )

        # 回退：尝试其他已注册的 provider
        for fallback_name in self.PROVIDERS:
            if fallback_name == name:
                continue
            try:
                logger.info("尝试回退到出图 provider: %s", fallback_name)
                provider = self._get_or_create_provider(fallback_name)
                return await provider.generate(
                    prompt,
                    style=style,
                    ref_images=ref_images,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
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
            f"所有出图 provider 均失败，已尝试: {name} + "
            f"{[n for n in self.PROVIDERS if n != name]}"
        )

    def list_providers(self) -> list[str]:
        """返回所有已注册的出图 provider 名称列表。"""
        return list(self.PROVIDERS.keys())

    def list_styles(self, provider_name: str | None = None) -> list[dict]:
        """返回指定 provider 支持的风格列表。

        Args:
            provider_name: provider 名称，None 则使用默认。

        Returns:
            风格列表，每项包含 id, name, description 字段。
        """
        name = provider_name or self._default_provider
        provider = self._get_or_create_provider(name)
        return provider.list_styles()

    @property
    def default_provider(self) -> str:
        """当前默认 provider 名称。"""
        return self._default_provider

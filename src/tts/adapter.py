"""TTSAdapter：TTS 适配器，支持自动回退到 Edge TTS。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Type

from src.tts.base import BaseTTSProvider, TTSResult
from src.tts.chattts import ChatTTSProvider
from src.tts.cosyvoice import CosyVoiceProvider
from src.tts.edge_tts_provider import EdgeTTSProvider
from src.tts.fish_speech import FishSpeechProvider
from src.tts.melotts import MeloTTSProvider

logger = logging.getLogger(__name__)

# Provider name -> (Provider class, config keys used for instantiation)
_PROVIDER_REGISTRY: dict[str, Type[BaseTTSProvider]] = {
    "cosyvoice": CosyVoiceProvider,
    "fish_speech": FishSpeechProvider,
    "chattts": ChatTTSProvider,
    "melotts": MeloTTSProvider,
    "edge_tts": EdgeTTSProvider,
}

# Edge TTS is the fallback provider name
_FALLBACK_PROVIDER = "edge_tts"


class TTSAdapter:
    """TTS 适配器，支持自动回退到 Edge TTS，支持动态选择音色。

    Config 结构示例（config.toml 的 [tts] 部分）::

        [tts.cosyvoice]
        api_base = "http://localhost:9880"
        default_voice = "中文女"

        [tts.edge_tts]
        default_voice = "zh-CN-XiaoxiaoNeural"
    """

    PROVIDERS = _PROVIDER_REGISTRY

    def __init__(self, config: dict) -> None:
        """初始化 TTSAdapter。

        Args:
            config: config.toml 中 ``[tts]`` 部分的字典。
                    每个 key 对应一个 provider 名称，value 是该 provider 的配置。
        """
        self._config = config
        # 缓存已实例化的 provider
        self._instances: dict[str, BaseTTSProvider] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_provider_config(self, name: str) -> dict:
        """获取指定 provider 的配置子字典。"""
        return self._config.get(name, {})

    def _instantiate_provider(self, name: str) -> BaseTTSProvider:
        """根据名称和配置实例化一个 TTS provider。

        Raises:
            ValueError: provider 名称未注册时抛出。
        """
        if name not in self.PROVIDERS:
            raise ValueError(f"未知的 TTS provider: {name}")

        cls = self.PROVIDERS[name]
        cfg = self._get_provider_config(name)

        # 根据不同 provider 构造参数
        if name == "edge_tts":
            return cls(default_voice=cfg.get("default_voice"))
        elif name == "cosyvoice":
            return cls(
                api_base=cfg.get("api_base", "http://localhost:9880"),
                default_voice=cfg.get("default_voice", "中文女"),
            )
        elif name == "fish_speech":
            return cls(
                api_base=cfg.get("api_base", "http://localhost:8080"),
                default_voice=cfg.get("default_voice", "default"),
            )
        elif name == "chattts":
            return cls(
                api_base=cfg.get("api_base", "http://localhost:9966"),
                default_voice=cfg.get("default_voice", "default"),
            )
        elif name == "melotts":
            return cls(
                api_base=cfg.get("api_base", "http://localhost:8888"),
                default_voice=cfg.get("default_voice", "zh"),
            )
        else:
            # Fallback: try no-arg construction
            return cls()

    def _get_or_create_provider(self, name: str) -> BaseTTSProvider:
        """获取缓存的 provider 实例，不存在则创建。"""
        if name not in self._instances:
            self._instances[name] = self._instantiate_provider(name)
        return self._instances[name]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        provider_name: str,
        voice: str,
        output_path: Path,
    ) -> TTSResult:
        """合成语音，失败时自动回退到 Edge TTS。

        Args:
            text: 待合成的文本。
            provider_name: 要使用的 TTS provider 名称。
            voice: 音色标识符。
            output_path: 输出音频文件路径。

        Returns:
            TTSResult 包含音频路径、时长和采样率。
            如果发生了回退，result 中的 audio_path 可能与请求的 output_path 不同
            （Edge TTS 会强制 .mp3 扩展名）。
        """
        # 尝试使用指定 provider
        if provider_name != _FALLBACK_PROVIDER:
            try:
                provider = self._get_or_create_provider(provider_name)
                return await provider.synthesize(text, voice, output_path)
            except Exception as exc:
                logger.warning(
                    "TTS provider '%s' 合成失败，正在回退到 Edge TTS: %s",
                    provider_name,
                    exc,
                )
                # 回退到 Edge TTS
                return await self._fallback_synthesize(text, voice, output_path)
        else:
            # 直接使用 Edge TTS
            provider = self._get_or_create_provider(_FALLBACK_PROVIDER)
            return await provider.synthesize(text, voice, output_path)

    async def _fallback_synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
    ) -> TTSResult:
        """使用 Edge TTS 作为兜底方案合成语音。

        如果 voice 不是 Edge TTS 支持的音色，则使用 Edge TTS 的默认音色。
        """
        edge_provider = self._get_or_create_provider(_FALLBACK_PROVIDER)

        # 检查 voice 是否为 Edge TTS 支持的音色
        edge_voice_ids = {v["id"] for v in edge_provider.list_voices()}
        if voice not in edge_voice_ids:
            # 使用 Edge TTS 默认音色
            voice = edge_provider._default_voice

        return await edge_provider.synthesize(text, voice, output_path)

    def list_providers(self) -> list[str]:
        """返回所有已注册的 TTS provider 名称列表。

        edge_tts 始终包含在列表中。

        Returns:
            provider 名称列表。
        """
        return list(self.PROVIDERS.keys())

    def list_voices(self, provider_name: str) -> list[dict]:
        """返回指定 provider 的可用音色列表。

        Args:
            provider_name: TTS provider 名称。

        Returns:
            音色列表，每项包含 id, name, language 字段。

        Raises:
            ValueError: provider 名称未注册时抛出。
        """
        provider = self._get_or_create_provider(provider_name)
        return provider.list_voices()

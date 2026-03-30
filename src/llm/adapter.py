"""LLMAdapter：LLM 适配器，根据配置选择 Provider，支持动态选择模型名称。

根据 config.toml 中 [llm.*] 配置段，注册所有 Provider 并提供统一的
获取 Provider、列出模型、列出已配置 Provider 和渲染提示词模板的接口。
"""

from __future__ import annotations

from .base import BaseLLMProvider
from .openai_compat import OpenAICompatibleProvider
from .prompt_builder import PromptBuilder
from .wenxin import WenxinProvider
from src.narration_mode import NarrationMode

# 默认提示词模板
_DEFAULT_PROMPT_TEMPLATE = (
    "我是一个内容创作者，我需要你帮我写解说词，我会用这些解说词直接去生成配音视频。\n"
    "所以你只需要给我纯解说词文本，不要给我任何推荐、建议、解释或额外内容。\n"
    "\n"
    "我给你{image_count}张图片，请根据每张图片上的文字内容，以我本人的口吻（第一人称'我'）写解说词。\n"
    "总时长约{duration}秒，风格{style}，语气{tone}。\n"
    "\n"
    "按以下JSON格式填写value，不要修改key：\n"
    "{json_template}\n"
)


class LLMAdapter:
    """LLM 适配器，根据配置选择 Provider，支持动态选择模型名称。"""

    DEFAULT_MODELS: dict[str, list[str]] = {
        "qwen": ["qwen-vl-max", "qwen-vl-plus", "qwen-vl-max-latest"],
        "deepseek": ["deepseek-chat", "deepseek-reasoner"],
        "glm": ["glm-4v", "glm-4v-plus", "glm-4v-flash"],
        "wenxin": ["ernie-bot-4", "ernie-bot-turbo", "ernie-4.0-8k"],
        "openai_compatible": [],
    }

    PROVIDERS: dict[str, object] = {
        "qwen": lambda cfg, model: OpenAICompatibleProvider(
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=cfg["api_key"],
            model=model,
        ),
        "deepseek": lambda cfg, model: OpenAICompatibleProvider(
            api_base="https://api.deepseek.com/v1",
            api_key=cfg["api_key"],
            model=model,
        ),
        "glm": lambda cfg, model: OpenAICompatibleProvider(
            api_base="https://open.bigmodel.cn/api/paas/v4",
            api_key=cfg["api_key"],
            model=model,
        ),
        "wenxin": lambda cfg, model: WenxinProvider(
            api_key=cfg["api_key"],
            secret_key=cfg["secret_key"],
            model=model,
        ),
        "openai_compatible": lambda cfg, model: OpenAICompatibleProvider(
            api_base=cfg["api_base"],
            api_key=cfg["api_key"],
            model=model,
        ),
    }

    def __init__(self, config: dict) -> None:
        """初始化 LLM 适配器。

        Args:
            config: config.toml 中 ``[llm]`` 部分的配置字典，
                    键为 provider 名称，值为该 provider 的配置。
        """
        self._config = config

    def get_provider(self, name: str, model: str | None = None) -> BaseLLMProvider:
        """获取指定 provider 实例。

        Args:
            name: provider 名称（如 "qwen"、"deepseek" 等）。
            model: 模型名称，为 None 时使用配置中的 default_model。

        Returns:
            对应的 BaseLLMProvider 实例。

        Raises:
            ValueError: provider 名称未注册或未配置。
        """
        if name not in self.PROVIDERS:
            raise ValueError(f"未知的 LLM provider: {name}")

        provider_cfg = self._config.get(name)
        if provider_cfg is None:
            raise ValueError(f"LLM provider '{name}' 未在配置中找到")

        if model is None:
            model = provider_cfg.get("default_model", "")

        factory = self.PROVIDERS[name]
        return factory(provider_cfg, model)  # type: ignore[operator]

    def list_models(self, provider_name: str) -> list[str]:
        """返回指定 provider 支持的模型列表。

        合并 DEFAULT_MODELS 中的默认列表和配置文件中的自定义列表，
        去重并保持顺序。

        Args:
            provider_name: provider 名称。

        Returns:
            模型名称列表。

        Raises:
            ValueError: provider 名称未注册。
        """
        if provider_name not in self.PROVIDERS:
            raise ValueError(f"未知的 LLM provider: {provider_name}")

        defaults = list(self.DEFAULT_MODELS.get(provider_name, []))
        provider_cfg = self._config.get(provider_name, {})
        custom = provider_cfg.get("models", [])

        # 合并去重，保持顺序
        seen: set[str] = set()
        merged: list[str] = []
        for m in defaults + custom:
            if m not in seen:
                seen.add(m)
                merged.append(m)
        return merged

    def list_providers(self) -> list[str]:
        """返回所有已配置（api_key 非空）的 provider 名称列表。

        Returns:
            已配置的 provider 名称列表。
        """
        result: list[str] = []
        for name in self.PROVIDERS:
            provider_cfg = self._config.get(name, {})
            if provider_cfg.get("api_key"):
                result.append(name)
        return result

    def render_prompt(
        self,
        style: str = "专业自信",
        duration: int | str = 60,
        tone: str = "沉稳可靠、有说服力",
        image_count: int = 1,
        mode: NarrationMode = NarrationMode.DESCRIBE_IMAGES,
        search_context: str = "",
    ) -> str:
        """渲染提示词模板。

        委托给 PromptBuilder 构建提示词。支持通过 mode 和 search_context
        参数选择不同的解说模式。原有参数保持向后兼容。

        Args:
            style: 解说风格，默认"专业自信"。
            duration: 目标时长（秒），默认 60。
            tone: 解说语气，默认"沉稳可靠、有说服力"。
            image_count: 图片数量，默认 1。
            mode: 解说模式，默认 DESCRIBE_IMAGES（按图说话）。
            search_context: 网络搜索上下文，仅在 NEWS_COMMENTARY 模式下使用。
        """
        builder = PromptBuilder()
        return builder.build(
            mode=mode,
            image_count=image_count,
            duration=int(duration),
            search_context=search_context,
            style=style,
            tone=tone,
        )

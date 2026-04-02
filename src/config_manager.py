"""配置管理器：加载、保存和校验TOML格式的配置文件。"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w


# 默认配置模板
DEFAULT_CONFIG: dict = {
    "general": {
        "output_dir": "./output",
        "temp_dir": "./temp",
        "default_aspect_ratio": "9:16",
        "default_narration_mode": "describe_images",
        "default_duration": 60,
    },
    "search": {
        "engine": "duckduckgo",
        "timeout": 10.0,
        "max_results": 10,
    },
    "llm": {
        "qwen": {
            "api_key": "",
            "default_model": "qwen-vl-max",
            "models": ["qwen-vl-max", "qwen-vl-plus", "qwen-vl-max-latest"],
        },
        "deepseek": {
            "api_key": "",
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-reasoner"],
        },
        "glm": {
            "api_key": "",
            "default_model": "glm-4v",
            "models": ["glm-4v", "glm-4v-plus", "glm-4v-flash"],
        },
        "wenxin": {
            "api_key": "",
            "secret_key": "",
            "default_model": "ernie-bot-4",
            "models": ["ernie-bot-4", "ernie-bot-turbo", "ernie-4.0-8k"],
        },
        "openai_compatible": {
            "api_base": "",
            "api_key": "",
            "default_model": "",
            "models": [],
        },
        "prompt_template": {
            "default": (
                "我是一个内容创作者，我需要你帮我写解说词，我会用这些解说词直接去生成配音视频。\n"
                "所以你只需要给我纯解说词文本，不要给我任何推荐、建议、解释或额外内容。\n"
                "\n"
                "我给你{image_count}张图片，请根据每张图片上的文字内容，以我本人的口吻（第一人称'我'）写解说词。\n"
                "总时长约{duration}秒，风格{style}，语气{tone}。\n"
                "\n"
                "按以下JSON格式填写value，不要修改key：\n"
                "{json_template}\n"
            ),
        },
    },
    "tts": {
        "volcano": {
            "appid": "",
            "access_token": "",
            "resource_id": "seed-tts-2.0",
            "default_voice": "zh_female_shuangkuaisisi_uranus_bigtts",
            "default_speed_ratio": 1.2,
        },
        "cosyvoice": {
            "api_base": "http://localhost:9880",
            "default_voice": "中文女",
        },
        "fish_speech": {
            "api_base": "http://localhost:8080",
            "default_voice": "default",
        },
        "chattts": {
            "api_base": "http://localhost:9966",
        },
        "melotts": {
            "api_base": "http://localhost:8888",
        },
        "edge_tts": {
            "default_voice": "zh-CN-XiaoxiaoNeural",
        },
    },
    "video": {
        "default_bitrate": "4M",
        "default_fps": 30,
        "codec": "libx264",
        "bgm_volume": 0.25,
        "fade_duration": 0.5,
    },
    "subtitle": {
        "font_family": "Microsoft YaHei",
        "font_size": 36,
        "color": "#FFFFFF",
        "outline_color": "#000000",
        "outline_width": 2,
        "max_chars_per_line": 15,
    },
}

# 必要字段定义：使用点分路径表示嵌套字段
REQUIRED_FIELDS: list[str] = [
    "general.output_dir",
    "general.temp_dir",
    "general.default_aspect_ratio",
    "video.default_bitrate",
    "video.default_fps",
    "video.codec",
    "video.bgm_volume",
    "video.fade_duration",
    "subtitle.font_family",
    "subtitle.font_size",
    "subtitle.color",
    "subtitle.outline_color",
    "subtitle.outline_width",
    "subtitle.max_chars_per_line",
    "tts.edge_tts.default_voice",
]


def _get_nested(data: dict, dotted_key: str) -> object:
    """沿点分路径取值，找不到时抛出 KeyError。"""
    current = data
    for part in dotted_key.split("."):
        current = current[part]
    return current


class ConfigManager:
    """TOML 配置文件管理器。"""

    DEFAULT_CONFIG_PATH = Path("config.toml")

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.DEFAULT_CONFIG_PATH

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """加载TOML配置文件。文件不存在时自动生成默认模板并返回默认配置。"""
        if not self.path.exists():
            self.save(DEFAULT_CONFIG)
            return self._deep_copy(DEFAULT_CONFIG)

        with open(self.path, "rb") as f:
            return tomllib.load(f)

    def save(self, config: dict) -> None:
        """将配置字典写入TOML文件。自动创建父目录。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "wb") as f:
            tomli_w.dump(config, f)

    def validate(self, config: dict) -> list[str]:
        """校验配置完整性，返回缺失字段的点分路径列表。"""
        missing: list[str] = []
        for field in REQUIRED_FIELDS:
            try:
                _get_nested(config, field)
            except (KeyError, TypeError):
                missing.append(field)
        return missing

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _deep_copy(d: dict) -> dict:
        """简单的字典深拷贝（仅处理 dict / list / 基本类型）。"""
        import copy
        return copy.deepcopy(d)

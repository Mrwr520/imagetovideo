"""TTS 语音合成模块。"""

from src.tts.adapter import TTSAdapter
from src.tts.base import BaseTTSProvider, TTSResult
from src.tts.chattts import ChatTTSProvider
from src.tts.cosyvoice import CosyVoiceProvider
from src.tts.edge_tts_provider import EdgeTTSProvider
from src.tts.fish_speech import FishSpeechProvider
from src.tts.melotts import MeloTTSProvider

__all__ = [
    "BaseTTSProvider",
    "TTSAdapter",
    "TTSResult",
    "ChatTTSProvider",
    "CosyVoiceProvider",
    "EdgeTTSProvider",
    "FishSpeechProvider",
    "MeloTTSProvider",
]

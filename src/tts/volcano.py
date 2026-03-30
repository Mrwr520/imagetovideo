"""VolcanoTTSProvider：火山引擎（字节跳动）大模型语音合成。

API 文档：https://www.volcengine.com/docs/6561/1257584
使用 HTTP 非流式接口 https://openspeech.bytedance.com/api/v1/tts
支持字级别时间戳，可用于精确字幕同步。
"""

from __future__ import annotations

import base64
import json
import uuid
import wave
from pathlib import Path

import httpx

from src.tts.base import BaseTTSProvider, TTSResult


class VolcanoTTSProvider(BaseTTSProvider):
    """火山引擎 TTS Provider。

    需要在火山引擎控制台申请 appid 和 access_token。
    """

    API_URL = "https://openspeech.bytedance.com/api/v1/tts"

    # 常用中文音色
    CHINESE_VOICES: list[dict] = [
        {"id": "zh_female_shuangkuaisisi_moon_bigtts", "name": "爽快思思（女）"},
        {"id": "zh_male_jnjbyl_moon_bigtts", "name": "江南才子（男）"},
        {"id": "zh_female_wanwanxiaohe_moon_bigtts", "name": "弯弯小何（女）"},
        {"id": "zh_male_M392_conversation_wvae_bigtts", "name": "阳光男声（男）"},
        {"id": "zh_female_lhchenyixuan_moon_bigtts", "name": "甜美女声（女）"},
        {"id": "zh_male_chunhou_moon_bigtts", "name": "醇厚男声（男）"},
        {"id": "zh_female_maomao_moon_bigtts", "name": "毛毛（女）"},
        {"id": "zh_male_rap_moon_bigtts", "name": "说唱歌手（男）"},
    ]

    DEFAULT_VOICE = "zh_female_shuangkuaisisi_moon_bigtts"

    def __init__(
        self,
        appid: str = "",
        access_token: str = "",
        cluster: str = "volcano_tts",
        default_voice: str | None = None,
    ):
        self._appid = appid
        self._access_token = access_token
        self._cluster = cluster
        self._default_voice = default_voice or self.DEFAULT_VOICE

    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
        """调用火山引擎 TTS 合成语音，同时获取字级别时间戳。"""
        if not text or not text.strip():
            raise ValueError("合成文本不能为空")
        if not self._appid or not self._access_token:
            raise RuntimeError("火山引擎 TTS 未配置 appid 或 access_token")

        voice = voice or self._default_voice
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() != ".mp3":
            output_path = output_path.with_suffix(".mp3")

        # 文本超过300字符时分段合成
        max_chars = 300
        if len(text) > max_chars:
            return await self._synthesize_long_text(text, voice, output_path, max_chars)

        return await self._synthesize_single(text, voice, output_path)

    async def _synthesize_single(
        self, text: str, voice: str, output_path: Path
    ) -> TTSResult:
        """单次合成（文本 <= 300 字符）。"""
        reqid = str(uuid.uuid4())

        payload = {
            "app": {
                "appid": self._appid,
                "token": "fake_token",
                "cluster": self._cluster,
            },
            "user": {"uid": "narrator_app"},
            "audio": {
                "voice_type": voice,
                "encoding": "mp3",
                "speed_ratio": 1.0,
            },
            "request": {
                "reqid": reqid,
                "text": text,
                "operation": "query",
                "with_timestamp": 1,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer;{self._access_token}",
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(self.API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                result = resp.json()
        except httpx.ConnectError as e:
            raise RuntimeError(f"火山引擎 TTS 连接失败: {e}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError(f"火山引擎 TTS 请求超时: {e}") from e

        code = result.get("code", -1)
        if code != 3000:
            msg = result.get("message", "未知错误")
            raise RuntimeError(f"火山引擎 TTS 错误 (code={code}): {msg}")

        # 解码音频
        audio_b64 = result.get("data", "")
        if not audio_b64:
            raise RuntimeError("火山引擎 TTS 返回空音频数据")

        audio_bytes = base64.b64decode(audio_b64)
        output_path.write_bytes(audio_bytes)

        # 解析时长
        addition = result.get("addition", {})
        duration_ms = float(addition.get("duration", 0))
        duration = duration_ms / 1000.0

        # 解析字级别时间戳
        word_timings = self._parse_timestamps(result)

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            sample_rate=24000,
            word_timings=word_timings if word_timings else None,
        )

    async def _synthesize_long_text(
        self, text: str, voice: str, output_path: Path, max_chars: int
    ) -> TTSResult:
        """长文本分段合成后拼接。"""
        import re
        import tempfile

        # 按标点分段，每段不超过 max_chars
        punct = r'[，。！？；：、,.!?;:]'
        sentences = re.split(f'({punct})', text)
        chunks: list[str] = []
        current = ""
        for part in sentences:
            if len(current) + len(part) > max_chars and current:
                chunks.append(current)
                current = part
            else:
                current += part
        if current:
            chunks.append(current)

        all_audio = bytearray()
        all_timings: list[tuple[float, float, str]] = []
        total_offset = 0.0

        for i, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk:
                continue
            tmp_path = Path(tempfile.mktemp(suffix=".mp3"))
            result = await self._synthesize_single(chunk, voice, tmp_path)

            all_audio.extend(tmp_path.read_bytes())

            # 偏移时间戳
            if result.word_timings:
                for offset, dur, word in result.word_timings:
                    all_timings.append((offset + total_offset, dur, word))

            total_offset += result.duration
            tmp_path.unlink(missing_ok=True)

        output_path.write_bytes(bytes(all_audio))

        return TTSResult(
            audio_path=output_path,
            duration=total_offset,
            sample_rate=24000,
            word_timings=all_timings if all_timings else None,
        )

    @staticmethod
    def _parse_timestamps(result: dict) -> list[tuple[float, float, str]]:
        """从火山引擎返回结果中解析字级别时间戳。

        时间戳在 addition.frontend 字段中，是一个 JSON 字符串，结构为：
        {"words": [{"word": "你", "start_time": 105, "end_time": 235, "confidence": 0.95}, ...]}
        时间单位为毫秒。
        """
        timings = []
        addition = result.get("addition", {})

        frontend_raw = addition.get("frontend", "")
        if not frontend_raw:
            return []

        try:
            frontend = json.loads(frontend_raw) if isinstance(frontend_raw, str) else frontend_raw
        except json.JSONDecodeError:
            return []

        words = frontend.get("words", [])
        for item in words:
            word = item.get("word", "")
            start_ms = float(item.get("start_time", 0))
            end_ms = float(item.get("end_time", 0))
            if word and end_ms > start_ms:
                offset_sec = start_ms / 1000.0
                dur_sec = (end_ms - start_ms) / 1000.0
                timings.append((offset_sec, dur_sec, word))

        return timings

    def list_voices(self) -> list[dict]:
        """返回预定义的中文音色列表。"""
        return list(self.CHINESE_VOICES)

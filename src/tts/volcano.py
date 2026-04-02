"""VolcanoTTSProvider: 火山引擎豆包语音合成 V3 接入。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import tempfile
import uuid
from pathlib import Path
from typing import AsyncIterator

import httpx
from mutagen.mp3 import MP3
import requests

from src.tts.base import BaseTTSProvider, TTSResult

logger = logging.getLogger(__name__)


class VolcanoTTSProvider(BaseTTSProvider):
    """火山引擎 TTS Provider，使用豆包语音 V3 单向流式接口。"""

    API_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
    DEFAULT_RESOURCE_ID = "seed-tts-2.0"
    DEFAULT_SATURN_MODEL = "seed-tts-2.0-expressive"
    MAX_TEXT_CHARS = 300

    # 豆包语音合成 2.0 音色列表
    CHINESE_VOICES: list[dict] = [
        {"id": "zh_female_vv_uranus_bigtts", "name": "Vivi 2.0（女·通用·多情感）"},
        {"id": "zh_female_xiaohe_uranus_bigtts", "name": "小何 2.0（女·通用）"},
        {"id": "zh_male_m191_uranus_bigtts", "name": "云舟 2.0（男·通用）"},
        {"id": "zh_male_taocheng_uranus_bigtts", "name": "小天 2.0（男·通用）"},
        {"id": "zh_male_liufei_uranus_bigtts", "name": "刘飞 2.0（男·通用）"},
        {"id": "zh_male_sophie_uranus_bigtts", "name": "魅力苏菲 2.0（男·通用）"},
        {"id": "zh_female_qingxinnvsheng_uranus_bigtts", "name": "清新女声 2.0（女·通用）"},
        {"id": "zh_female_tianmeixiaoyuan_uranus_bigtts", "name": "甜美小源 2.0（女·通用）"},
        {"id": "zh_female_tianmeitaozi_uranus_bigtts", "name": "甜美桃子 2.0（女·通用）"},
        {"id": "zh_female_shuangkuaisisi_uranus_bigtts", "name": "爽快思思 2.0（女·通用）"},
        {"id": "zh_female_linjianvhai_uranus_bigtts", "name": "邻家女孩 2.0（女·通用）"},
        {"id": "zh_female_meilinvyou_uranus_bigtts", "name": "魅力女友 2.0（女·通用）"},
        {"id": "zh_female_cancan_uranus_bigtts", "name": "知性灿灿 2.0（女·角色扮演）"},
        {"id": "zh_female_sajiaoxuemei_uranus_bigtts", "name": "撒娇学妹 2.0（女·角色扮演）"},
        {"id": "zh_male_shaonianzixin_uranus_bigtts", "name": "少年梓辛 2.0（男·角色扮演）"},
        {"id": "saturn_zh_female_keainvsheng_tob", "name": "可爱女生（女·角色扮演）"},
        {"id": "saturn_zh_female_tiaopigongzhu_tob", "name": "调皮公主（女·角色扮演）"},
        {"id": "saturn_zh_male_shuanglangshaonian_tob", "name": "爽朗少年（男·角色扮演）"},
        {"id": "saturn_zh_male_tiancaitongzhuo_tob", "name": "天才同桌（男·角色扮演）"},
        {"id": "saturn_zh_female_cancan_tob", "name": "知性灿灿（女·角色扮演COT）"},
        {"id": "zh_female_peiqi_uranus_bigtts", "name": "佩奇猪 2.0（女·视频配音）"},
        {"id": "zh_male_sunwukong_uranus_bigtts", "name": "猴哥 2.0（男·视频配音）"},
        {"id": "zh_male_dayi_uranus_bigtts", "name": "大壹 2.0（男·视频配音）"},
        {"id": "zh_female_mizai_uranus_bigtts", "name": "黑猫咪仔 2.0（女·视频配音）"},
        {"id": "zh_female_jitangnv_uranus_bigtts", "name": "鸡汤女 2.0（女·视频配音）"},
        {"id": "zh_female_liuchangnv_uranus_bigtts", "name": "流畅女声 2.0（女·视频配音）"},
        {"id": "zh_male_ruyayichen_uranus_bigtts", "name": "儒雅逸辰 2.0（男·视频配音）"},
        {"id": "zh_female_yingyujiaoxue_uranus_bigtts", "name": "Tina老师 2.0（女·教育）"},
        {"id": "zh_female_kefunvsheng_uranus_bigtts", "name": "暖阳女声 2.0（女·客服）"},
        {"id": "zh_female_xiaoxue_uranus_bigtts", "name": "儿童绘本 2.0（女·有声阅读）"},
        {"id": "en_male_tim_uranus_bigtts", "name": "Tim 蒂姆 2.0（男·美式英语）"},
        {"id": "en_female_dacey_uranus_bigtts", "name": "Dacey 黛西 2.0（女·美式英语）"},
        {"id": "en_female_stokie_uranus_bigtts", "name": "Stokie 斯托克斯 2.0（女·美式英语）"},
    ]

    DEFAULT_VOICE = "zh_female_shuangkuaisisi_uranus_bigtts"

    def __init__(
        self,
        appid: str = "",
        access_token: str = "",
        cluster: str = "volcano_tts",
        resource_id: str | None = None,
        model: str | None = None,
        default_voice: str | None = None,
        default_speed_ratio: float = 1.2,
    ):
        self._appid = appid.strip()
        self._access_token = access_token.strip()
        self._cluster = cluster.strip()
        self._resource_id = self._resolve_resource_id(resource_id, self._cluster)
        self._model = model.strip() if model else None
        self._default_voice = default_voice or self.DEFAULT_VOICE
        self._default_speed_ratio = float(default_speed_ratio)

    async def synthesize(self, text: str, voice: str, output_path: Path, **kwargs) -> TTSResult:
        """调用火山引擎 TTS 合成语音，并提取字幕时间戳。"""
        if not text or not text.strip():
            raise ValueError("合成文本不能为空")
        if not self._appid or not self._access_token:
            raise RuntimeError("火山引擎 TTS 未配置 appid 或 access_token")

        voice = voice or self._default_voice
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() != ".mp3":
            output_path = output_path.with_suffix(".mp3")

        request_options = {
            "emotion": kwargs.get("emotion", ""),
            "emotion_scale": self._normalize_emotion_scale(kwargs.get("emotion_scale", 4)),
            "speech_rate": self._speed_ratio_to_speech_rate(
                kwargs.get("speed_ratio", self._default_speed_ratio)
            ),
            "context_texts": kwargs.get("context_texts") or [],
            "enable_native_subtitle": True,
        }

        if len(text) > self.MAX_TEXT_CHARS:
            return await self._synthesize_long_text(
                text,
                voice,
                output_path,
                self.MAX_TEXT_CHARS,
                request_options,
            )

        return await self._synthesize_single(text, voice, output_path, request_options)

    async def _synthesize_single(
        self,
        text: str,
        voice: str,
        output_path: Path,
        request_options: dict,
    ) -> TTSResult:
        try:
            return await self._stream_synthesize(text, voice, output_path, request_options)
        except Exception as exc:
            if not request_options.get("enable_native_subtitle", False):
                raise

            logger.warning("Volcano 2.0 原生字幕时间戳失败，回退到估算时间戳: %s", exc)
            fallback_options = dict(request_options)
            fallback_options["enable_native_subtitle"] = False
            result = await self._stream_synthesize(text, voice, output_path, fallback_options)
            result.word_timings = self._estimate_word_timings(text, result.duration)
            return result

    async def _stream_synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        request_options: dict,
    ) -> TTSResult:
        return await asyncio.to_thread(
            self._stream_synthesize_sync,
            text,
            voice,
            output_path,
            request_options,
        )

    def _stream_synthesize_sync(
        self,
        text: str,
        voice: str,
        output_path: Path,
        request_options: dict,
    ) -> TTSResult:
        payload = self._build_payload(text, voice, request_options)
        headers = self._build_headers()
        audio_bytes = bytearray()
        word_timings: list[tuple[float, float, str]] = []

        response = None
        try:
            with requests.Session() as session:
                response = session.post(
                    self.API_URL,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=(20, 180),
                )
                response.raise_for_status()
                logid = response.headers.get("X-Tt-Logid")
                for event_name, raw_payload in self._iter_sse_messages_sync(response):
                    self._consume_stream_payload(
                        raw_payload,
                        audio_bytes,
                        word_timings,
                        event_name=event_name,
                        logid=logid,
                    )
        except requests.exceptions.ConnectTimeout as exc:
            raise RuntimeError(f"火山引擎 TTS 连接超时: {exc}") from exc
        except requests.exceptions.ReadTimeout as exc:
            raise RuntimeError(f"火山引擎 TTS 请求超时: {exc}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"火山引擎 TTS 连接失败: {exc}") from exc
        except requests.HTTPError as exc:
            raise RuntimeError(f"火山引擎 TTS HTTP 错误: {exc}") from exc
        finally:
            if response is not None:
                response.close()

        if not audio_bytes:
            raise RuntimeError("火山引擎 TTS 未返回音频数据")

        output_path.write_bytes(bytes(audio_bytes))
        duration = self._get_audio_duration(output_path)
        sample_rate = self._get_sample_rate(output_path)
        word_timings.sort(key=lambda item: item[0])

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            sample_rate=sample_rate,
            word_timings=word_timings if word_timings else None,
        )

    async def _synthesize_long_text(
        self,
        text: str,
        voice: str,
        output_path: Path,
        max_chars: int,
        request_options: dict,
    ) -> TTSResult:
        chunks = self._split_text(text, max_chars)
        if not chunks:
            raise RuntimeError("火山引擎 TTS 没有可合成的文本分段")

        all_audio = bytearray()
        all_timings: list[tuple[float, float, str]] = []
        total_duration = 0.0
        sample_rate = 24000

        for chunk in chunks:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                tmp_path = Path(tmp_file.name)

            result = await self._synthesize_single(chunk, voice, tmp_path, request_options)
            all_audio.extend(tmp_path.read_bytes())

            if result.word_timings:
                for offset, duration, word in result.word_timings:
                    all_timings.append((offset + total_duration, duration, word))

            total_duration += result.duration
            sample_rate = result.sample_rate
            tmp_path.unlink(missing_ok=True)

        output_path.write_bytes(bytes(all_audio))
        return TTSResult(
            audio_path=output_path,
            duration=total_duration,
            sample_rate=sample_rate,
            word_timings=all_timings if all_timings else None,
        )

    def _build_payload(self, text: str, voice: str, request_options: dict) -> dict:
        audio_params: dict[str, object] = {
            "format": "mp3",
            "sample_rate": 24000,
            "speech_rate": request_options["speech_rate"],
        }

        if request_options.get("enable_native_subtitle", False):
            audio_params["enable_subtitle"] = True
        else:
            audio_params["enable_timestamp"] = True

        emotion = request_options.get("emotion", "")
        if emotion:
            audio_params["emotion"] = emotion
            audio_params["emotion_scale"] = request_options["emotion_scale"]

        additions = {
            "explicit_language": self._guess_language(voice),
            "disable_markdown_filter": True,
        }

        context_texts = request_options.get("context_texts") or []
        if context_texts:
            additions["context_texts"] = context_texts
        if not request_options.get("enable_native_subtitle", False):
            additions["enable_timestamp"] = True

        req_params: dict[str, object] = {
            "text": text,
            "speaker": voice,
            "audio_params": audio_params,
            "additions": json.dumps(additions, ensure_ascii=False),
        }

        model = self._resolve_model(voice)
        if model:
            req_params["model"] = model

        return {
            "user": {"uid": "narrator_app"},
            "req_params": req_params,
        }

    def _build_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "X-Api-App-Id": self._appid,
            "X-Api-Access-Key": self._access_token,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

    def _consume_stream_payload(
        self,
        raw_payload: str,
        audio_bytes: bytearray,
        word_timings: list[tuple[float, float, str]],
        *,
        event_name: str | None = None,
        logid: str | None = None,
    ) -> None:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"火山引擎 TTS 返回了无法解析的响应: {raw_payload}") from exc

        code = payload.get("code")
        message = payload.get("message", "未知错误")

        if code not in (0, 20000000):
            event_hint = f", event={event_name}" if event_name else ""
            logid_hint = f", logid={logid}" if logid else ""
            raise RuntimeError(f"火山引擎 TTS 错误 (code={code}{event_hint}{logid_hint}): {message}")

        audio_chunk = payload.get("data")
        if audio_chunk:
            try:
                audio_bytes.extend(base64.b64decode(audio_chunk))
            except (ValueError, TypeError) as exc:
                raise RuntimeError(f"火山引擎 TTS 返回了无法解析的音频数据: {exc}") from exc

        for key in ("sentence", "subtitle"):
            section = payload.get(key)
            if isinstance(section, dict):
                word_timings.extend(self._parse_sentence_timings(section))

    @staticmethod
    async def _iter_sse_messages(
        response: httpx.Response,
    ) -> AsyncIterator[tuple[str | None, str]]:
        current_event: str | None = None
        data_lines: list[str] = []

        async for raw_line in response.aiter_lines():
            line = raw_line.strip()

            if not line:
                if data_lines:
                    yield current_event, "\n".join(data_lines)
                current_event = None
                data_lines = []
                continue

            if line.startswith("event:"):
                current_event = line[6:].strip()
                continue

            if line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if data_lines:
            yield current_event, "\n".join(data_lines)

    @staticmethod
    def _iter_sse_messages_sync(
        response: requests.Response,
    ) -> list[tuple[str | None, str]]:
        messages: list[tuple[str | None, str]] = []
        current_event: str | None = None
        data_lines: list[str] = []

        try:
            for raw_line in response.iter_lines():
                if raw_line is None:
                    continue
                line = raw_line.decode("utf-8").strip()

                if not line:
                    if data_lines:
                        messages.append((current_event, "\n".join(data_lines)))
                    current_event = None
                    data_lines = []
                    continue

                if line.startswith(":"):
                    continue

                if line.startswith("event:"):
                    current_event = line[6:].strip()
                    continue

                if line.startswith("data:"):
                    data_lines.append(line[5:].strip())
        except requests.exceptions.ChunkedEncodingError:
            # 火山 2.0 开启字幕时偶发提前断流；保留已收到的数据继续处理。
            pass

        if data_lines:
            messages.append((current_event, "\n".join(data_lines)))
        return messages

    @staticmethod
    def _parse_sentence_timings(sentence: dict) -> list[tuple[float, float, str]]:
        timings: list[tuple[float, float, str]] = []
        for item in sentence.get("words", []):
            word = str(item.get("word", "")).strip()
            if not word:
                continue

            try:
                start_time = float(item.get("startTime", 0))
                end_time = float(item.get("endTime", 0))
            except (TypeError, ValueError):
                continue

            if end_time <= start_time:
                continue

            timings.append((start_time, end_time - start_time, word))

        return timings

    @classmethod
    def _resolve_resource_id(cls, resource_id: str | None, cluster: str) -> str:
        if resource_id and resource_id.strip():
            return resource_id.strip()
        if cluster and cluster.strip() and cluster != "volcano_tts":
            return cluster.strip()
        return cls.DEFAULT_RESOURCE_ID

    def _resolve_model(self, voice: str) -> str | None:
        if self._model:
            return self._model
        if voice.startswith("saturn_"):
            return self.DEFAULT_SATURN_MODEL
        return None

    @staticmethod
    def _normalize_emotion_scale(value: object) -> int:
        try:
            scale = int(value)
        except (TypeError, ValueError):
            scale = 4
        return max(1, min(5, scale))

    @staticmethod
    def _speed_ratio_to_speech_rate(value: object) -> int:
        try:
            speed_ratio = float(value)
        except (TypeError, ValueError):
            speed_ratio = 1.0
        speed_ratio = max(0.5, min(2.0, speed_ratio))
        return max(-50, min(100, int(round((speed_ratio - 1.0) * 100))))

    @staticmethod
    def _split_text(text: str, max_chars: int) -> list[str]:
        sentences = re.split(r"([，。！？；：,.!?;:])", text)
        chunks: list[str] = []
        current = ""

        for part in sentences:
            if len(current) + len(part) > max_chars and current:
                chunks.append(current.strip())
                current = part
            else:
                current += part

        if current.strip():
            chunks.append(current.strip())

        return chunks

    @staticmethod
    def _get_audio_duration(audio_path: Path) -> float:
        return MP3(str(audio_path)).info.length

    @staticmethod
    def _get_sample_rate(audio_path: Path) -> int:
        return MP3(str(audio_path)).info.sample_rate

    @staticmethod
    def _guess_language(voice: str) -> str:
        return "en" if voice.startswith("en_") else "zh"

    @staticmethod
    def _estimate_word_timings(text: str, total_duration: float) -> list[tuple[float, float, str]]:
        units = [token for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|[^\s]", text) if token.strip()]
        if not units or total_duration <= 0:
            return []

        duration_per_unit = total_duration / len(units)
        timings: list[tuple[float, float, str]] = []
        offset = 0.0
        for unit in units:
            timings.append((offset, duration_per_unit, unit))
            offset += duration_per_unit
        return timings

    def list_voices(self) -> list[dict]:
        voices: list[dict] = []
        for voice in self.CHINESE_VOICES:
            language = "en-US" if voice["id"].startswith("en_") else "zh-CN"
            voices.append({**voice, "language": language})
        return voices

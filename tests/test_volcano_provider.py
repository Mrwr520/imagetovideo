from __future__ import annotations

import base64
import json

import pytest

from src.tts.volcano import VolcanoTTSProvider


def test_build_payload_uses_tts2_subtitle_flag() -> None:
    provider = VolcanoTTSProvider(
        appid="app",
        access_token="token",
        resource_id="seed-tts-2.0",
        default_voice="zh_female_shuangkuaisisi_uranus_bigtts",
    )

    payload = provider._build_payload(
        "hello",
        "zh_female_shuangkuaisisi_uranus_bigtts",
        {
            "emotion": "happy",
            "emotion_scale": 4,
            "speech_rate": 10,
            "context_texts": ["请更有活力一点"],
            "enable_native_subtitle": True,
        },
    )

    audio_params = payload["req_params"]["audio_params"]
    assert audio_params["format"] == "mp3"
    assert audio_params["sample_rate"] == 24000
    assert audio_params["speech_rate"] == 10
    assert audio_params["enable_subtitle"] is True
    assert audio_params["emotion"] == "happy"
    additions = json.loads(payload["req_params"]["additions"])
    assert additions["explicit_language"] == "zh"
    assert additions["disable_markdown_filter"] is True
    assert additions["context_texts"] == ["请更有活力一点"]


def test_build_payload_without_native_subtitle_omits_subtitle_flag() -> None:
    provider = VolcanoTTSProvider(
        appid="app",
        access_token="token",
        resource_id="seed-tts-2.0",
        default_voice="zh_female_shuangkuaisisi_uranus_bigtts",
    )

    payload = provider._build_payload(
        "hello",
        "zh_female_shuangkuaisisi_uranus_bigtts",
        {
            "emotion": "",
            "emotion_scale": 4,
            "speech_rate": 0,
            "context_texts": [],
            "enable_native_subtitle": False,
        },
    )

    audio_params = payload["req_params"]["audio_params"]
    assert "enable_subtitle" not in audio_params
    assert audio_params["enable_timestamp"] is True
    additions = json.loads(payload["req_params"]["additions"])
    assert additions["explicit_language"] == "zh"
    assert additions["enable_timestamp"] is True


def test_consume_stream_payload_collects_audio_and_timings() -> None:
    provider = VolcanoTTSProvider(appid="app", access_token="token")
    audio_bytes = bytearray()
    word_timings: list[tuple[float, float, str]] = []

    raw_payload = (
        '{"code":0,"message":"ok","data":"%s","sentence":{"text":"你好",'
        '"words":[{"word":"你","startTime":0.1,"endTime":0.2},'
        '{"word":"好","startTime":0.2,"endTime":0.35}]}}'
        % base64.b64encode(b"audio").decode("ascii")
    )

    provider._consume_stream_payload(raw_payload, audio_bytes, word_timings)

    assert bytes(audio_bytes) == b"audio"
    assert word_timings[0][0] == pytest.approx(0.1, rel=0, abs=1e-9)
    assert word_timings[0][1] == pytest.approx(0.1, rel=0, abs=1e-9)
    assert word_timings[0][2] == "你"
    assert word_timings[1][0] == pytest.approx(0.2, rel=0, abs=1e-9)
    assert word_timings[1][1] == pytest.approx(0.15, rel=0, abs=1e-9)
    assert word_timings[1][2] == "好"


def test_consume_stream_payload_raises_with_logid() -> None:
    provider = VolcanoTTSProvider(appid="app", access_token="token")

    with pytest.raises(RuntimeError, match="logid=test-logid"):
        provider._consume_stream_payload(
            '{"code":45000010,"message":"grant missing","data":null}',
            bytearray(),
            [],
            event_name="153",
            logid="test-logid",
        )


def test_estimate_word_timings() -> None:
    timings = VolcanoTTSProvider._estimate_word_timings("你好，OpenAI", 3.0)

    assert len(timings) >= 3
    assert timings[0][0] == pytest.approx(0.0, rel=0, abs=1e-9)
    assert sum(duration for _, duration, _ in timings) == pytest.approx(3.0, rel=0, abs=1e-9)


def test_speed_ratio_to_speech_rate_for_plus_point_two() -> None:
    assert VolcanoTTSProvider._speed_ratio_to_speech_rate(1.2) == 20

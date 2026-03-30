"""Unit tests for VideoComposer and VideoConfig."""

from __future__ import annotations

import struct
import tempfile
import wave
from pathlib import Path

import pytest

from src.video.composer import VideoComposer, VideoConfig, _RESOLUTION_MAP


# ---------------------------------------------------------------------------
# VideoConfig tests
# ---------------------------------------------------------------------------


class TestVideoConfig:
    """Tests for VideoConfig dataclass and factory method."""

    def test_default_values(self):
        cfg = VideoConfig()
        assert cfg.aspect_ratio == "9:16"
        assert cfg.width == 1080
        assert cfg.height == 1920
        assert cfg.fps == 30
        assert cfg.bitrate == "4M"
        assert cfg.codec == "libx264"

    def test_from_aspect_ratio_vertical(self):
        cfg = VideoConfig.from_aspect_ratio("9:16")
        assert cfg.width == 1080
        assert cfg.height == 1920
        assert cfg.aspect_ratio == "9:16"

    def test_from_aspect_ratio_horizontal(self):
        cfg = VideoConfig.from_aspect_ratio("16:9")
        assert cfg.width == 1920
        assert cfg.height == 1080
        assert cfg.aspect_ratio == "16:9"

    def test_from_aspect_ratio_with_overrides(self):
        cfg = VideoConfig.from_aspect_ratio("16:9", fps=60, bitrate="8M")
        assert cfg.fps == 60
        assert cfg.bitrate == "8M"
        assert cfg.width == 1920

    def test_from_aspect_ratio_invalid(self):
        with pytest.raises(ValueError, match="Unsupported aspect ratio"):
            VideoConfig.from_aspect_ratio("4:3")

    def test_resolution_map_completeness(self):
        assert "9:16" in _RESOLUTION_MAP
        assert "16:9" in _RESOLUTION_MAP


# ---------------------------------------------------------------------------
# calculate_image_durations tests
# ---------------------------------------------------------------------------


class TestCalculateImageDurations:
    """Tests for VideoComposer.calculate_image_durations."""

    def setup_method(self):
        self.composer = VideoComposer()

    def test_single_image(self):
        durations = self.composer.calculate_image_durations(1, 10.0)
        assert len(durations) == 1
        assert durations[0] == pytest.approx(10.0)

    def test_even_split(self):
        durations = self.composer.calculate_image_durations(4, 12.0)
        assert len(durations) == 4
        assert all(d == pytest.approx(3.0) for d in durations)
        assert sum(durations) == pytest.approx(12.0)

    def test_uneven_split_remainder_distributed(self):
        durations = self.composer.calculate_image_durations(3, 10.0)
        assert len(durations) == 3
        assert all(d > 0 for d in durations)
        assert sum(durations) == pytest.approx(10.0)

    def test_many_images_short_duration(self):
        durations = self.composer.calculate_image_durations(100, 5.0)
        assert len(durations) == 100
        assert all(d > 0 for d in durations)
        assert sum(durations) == pytest.approx(5.0)

    def test_all_durations_positive(self):
        durations = self.composer.calculate_image_durations(7, 1.0)
        assert all(d > 0 for d in durations)

    def test_invalid_image_count(self):
        with pytest.raises(ValueError):
            self.composer.calculate_image_durations(0, 10.0)
        with pytest.raises(ValueError):
            self.composer.calculate_image_durations(-1, 10.0)

    def test_invalid_duration(self):
        with pytest.raises(ValueError):
            self.composer.calculate_image_durations(5, 0.0)
        with pytest.raises(ValueError):
            self.composer.calculate_image_durations(5, -1.0)


# ---------------------------------------------------------------------------
# mix_audio tests
# ---------------------------------------------------------------------------


def _create_wav(path: Path, duration_seconds: float, sample_rate: int = 44100):
    """Create a minimal WAV file with silence for the given duration."""
    n_frames = int(sample_rate * duration_seconds)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Write silence (zeros)
        wf.writeframes(b"\x00\x00" * n_frames)


class TestMixAudio:
    """Tests for VideoComposer.mix_audio."""

    def setup_method(self):
        self.composer = VideoComposer()

    def test_no_bgm_returns_narration_path(self, tmp_path):
        narration = tmp_path / "narration.wav"
        _create_wav(narration, 5.0)
        result = self.composer.mix_audio(narration, None, 5.0)
        assert result == narration

    def test_bgm_volume_clamped_low(self, tmp_path):
        """Volume below 0.20 should be clamped to 0.20."""
        narration = tmp_path / "narration.wav"
        bgm = tmp_path / "bgm.wav"
        _create_wav(narration, 3.0)
        _create_wav(bgm, 3.0)
        # Should not raise; volume is clamped internally
        result = self.composer.mix_audio(narration, bgm, 3.0, bgm_volume=0.10)
        assert Path(result).exists()

    def test_bgm_volume_clamped_high(self, tmp_path):
        """Volume above 0.30 should be clamped to 0.30."""
        narration = tmp_path / "narration.wav"
        bgm = tmp_path / "bgm.wav"
        _create_wav(narration, 3.0)
        _create_wav(bgm, 3.0)
        result = self.composer.mix_audio(narration, bgm, 3.0, bgm_volume=0.50)
        assert Path(result).exists()

    def test_bgm_shorter_than_video_loops(self, tmp_path):
        """BGM shorter than video should be looped to match video duration."""
        narration = tmp_path / "narration.wav"
        bgm = tmp_path / "bgm.wav"
        _create_wav(narration, 10.0)
        _create_wav(bgm, 3.0)  # shorter than video
        result = self.composer.mix_audio(narration, bgm, 10.0, bgm_volume=0.25)
        assert Path(result).exists()

    def test_bgm_longer_than_video_trimmed(self, tmp_path):
        """BGM longer than video should be trimmed with fade-out."""
        narration = tmp_path / "narration.wav"
        bgm = tmp_path / "bgm.wav"
        _create_wav(narration, 5.0)
        _create_wav(bgm, 15.0)  # longer than video
        result = self.composer.mix_audio(narration, bgm, 5.0, bgm_volume=0.25)
        assert Path(result).exists()

    def test_bgm_equal_duration(self, tmp_path):
        """BGM same length as video should work without looping or trimming."""
        narration = tmp_path / "narration.wav"
        bgm = tmp_path / "bgm.wav"
        _create_wav(narration, 5.0)
        _create_wav(bgm, 5.0)
        result = self.composer.mix_audio(narration, bgm, 5.0, bgm_volume=0.25)
        assert Path(result).exists()

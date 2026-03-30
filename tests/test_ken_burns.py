"""Tests for the Ken Burns effect module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.video.ken_burns import (
    KenBurnsParams,
    _apply_zoom_pan_frame,
    _prepare_image,
    create_ken_burns_clip,
)


# ---------------------------------------------------------------------------
# KenBurnsParams
# ---------------------------------------------------------------------------

class TestKenBurnsParams:
    def test_defaults(self):
        p = KenBurnsParams()
        assert p.zoom_range == (1.0, 1.3)
        assert p.pan_speed == 0.02
        assert p.fade_duration == 0.5

    def test_custom_values(self):
        p = KenBurnsParams(zoom_range=(1.0, 2.0), pan_speed=0.05, fade_duration=1.0)
        assert p.zoom_range == (1.0, 2.0)
        assert p.pan_speed == 0.05
        assert p.fade_duration == 1.0


# ---------------------------------------------------------------------------
# _prepare_image
# ---------------------------------------------------------------------------

class TestPrepareImage:
    def test_pil_image_input(self):
        img = Image.new("RGB", (800, 600), color=(100, 150, 200))
        arr = _prepare_image(img, 1080, 1920)
        assert arr.shape == (int(1920 * 1.4), int(1080 * 1.4), 3)
        assert arr.dtype == np.uint8

    def test_file_path_input(self):
        img = Image.new("RGB", (640, 480), color=(50, 50, 50))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f.name)
            arr = _prepare_image(Path(f.name), 1080, 1920)
        assert arr.shape == (int(1920 * 1.4), int(1080 * 1.4), 3)

    def test_string_path_input(self):
        img = Image.new("RGB", (640, 480), color=(50, 50, 50))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img.save(f.name)
            arr = _prepare_image(f.name, 1080, 1920)
        assert arr.shape == (int(1920 * 1.4), int(1080 * 1.4), 3)

    def test_rgba_image_converted_to_rgb(self):
        img = Image.new("RGBA", (800, 600), color=(100, 150, 200, 128))
        arr = _prepare_image(img, 1080, 1920)
        assert arr.shape[2] == 3  # RGB, not RGBA

    def test_landscape_target(self):
        img = Image.new("RGB", (800, 600))
        arr = _prepare_image(img, 1920, 1080)
        assert arr.shape == (int(1080 * 1.4), int(1920 * 1.4), 3)


# ---------------------------------------------------------------------------
# _apply_zoom_pan_frame
# ---------------------------------------------------------------------------

class TestApplyZoomPanFrame:
    @pytest.fixture()
    def source_array(self):
        """A prepared image array (padded size for 1080x1920 target)."""
        img = Image.new("RGB", (800, 600), color=(200, 100, 50))
        return _prepare_image(img, 1080, 1920)

    def test_output_shape(self, source_array):
        frame = _apply_zoom_pan_frame(
            source_array, t=0.0, duration=3.0,
            target_width=1080, target_height=1920,
            params=KenBurnsParams(),
        )
        assert frame.shape == (1920, 1080, 3)

    def test_frame_at_end(self, source_array):
        frame = _apply_zoom_pan_frame(
            source_array, t=3.0, duration=3.0,
            target_width=1080, target_height=1920,
            params=KenBurnsParams(),
        )
        assert frame.shape == (1920, 1080, 3)

    def test_frame_at_midpoint(self, source_array):
        frame = _apply_zoom_pan_frame(
            source_array, t=1.5, duration=3.0,
            target_width=1080, target_height=1920,
            params=KenBurnsParams(),
        )
        assert frame.shape == (1920, 1080, 3)

    def test_zero_duration_no_crash(self, source_array):
        frame = _apply_zoom_pan_frame(
            source_array, t=0.0, duration=0.0,
            target_width=1080, target_height=1920,
            params=KenBurnsParams(),
        )
        assert frame.shape == (1920, 1080, 3)

    def test_different_zoom_produces_different_frames(self):
        # Use a gradient image so zoom actually changes pixel content
        arr = np.zeros((400, 300, 3), dtype=np.uint8)
        for i in range(400):
            arr[i, :, :] = i % 256
        img = Image.fromarray(arr)
        src = _prepare_image(img, 1080, 1920)

        params = KenBurnsParams(zoom_range=(1.0, 2.0), pan_speed=0.0)
        frame_start = _apply_zoom_pan_frame(
            src, t=0.0, duration=3.0,
            target_width=1080, target_height=1920, params=params,
        )
        frame_end = _apply_zoom_pan_frame(
            src, t=3.0, duration=3.0,
            target_width=1080, target_height=1920, params=params,
        )
        # Frames should differ due to zoom change on non-uniform image
        assert not np.array_equal(frame_start, frame_end)


# ---------------------------------------------------------------------------
# create_ken_burns_clip
# ---------------------------------------------------------------------------

class TestCreateKenBurnsClip:
    def test_clip_properties(self):
        img = Image.new("RGB", (800, 600), color=(0, 128, 255))
        clip = create_ken_burns_clip(img, 1080, 1920, duration=2.0, fps=15)
        assert clip.duration == 2.0
        assert clip.fps == 15
        assert clip.w == 1080
        assert clip.h == 1920
        clip.close()

    def test_landscape_clip(self):
        img = Image.new("RGB", (800, 600))
        clip = create_ken_burns_clip(img, 1920, 1080, duration=3.0, fps=24)
        assert clip.w == 1920
        assert clip.h == 1080
        frame = clip.get_frame(0.0)
        assert frame.shape == (1080, 1920, 3)
        clip.close()

    def test_default_params_when_none(self):
        img = Image.new("RGB", (400, 300))
        clip = create_ken_burns_clip(img, 1080, 1920, duration=1.0)
        assert clip.duration == 1.0
        assert clip.fps == 30  # default fps
        clip.close()

    def test_custom_params(self):
        img = Image.new("RGB", (400, 300))
        params = KenBurnsParams(zoom_range=(1.0, 1.5), pan_speed=0.05, fade_duration=0.2)
        clip = create_ken_burns_clip(img, 1080, 1920, duration=2.0, params=params)
        assert clip.duration == 2.0
        clip.close()

    def test_fade_clamped_to_half_duration(self):
        """When fade_duration > duration/2, it should be clamped."""
        img = Image.new("RGB", (400, 300))
        params = KenBurnsParams(fade_duration=5.0)
        clip = create_ken_burns_clip(img, 1080, 1920, duration=1.0, params=params)
        # Should not crash; fade is clamped to 0.5s
        frame = clip.get_frame(0.0)
        assert frame.shape == (1920, 1080, 3)
        clip.close()

    def test_from_file_path(self):
        img = Image.new("RGB", (640, 480), color=(255, 0, 0))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f.name)
            clip = create_ken_burns_clip(Path(f.name), 1080, 1920, duration=1.0, fps=10)
        assert clip.duration == 1.0
        frame = clip.get_frame(0.5)
        assert frame.shape == (1920, 1080, 3)
        clip.close()

    def test_frames_are_valid_rgb(self):
        img = Image.new("RGB", (400, 300), color=(128, 64, 32))
        clip = create_ken_burns_clip(img, 1080, 1920, duration=1.0, fps=10)
        for t in [0.0, 0.5, 0.99]:
            frame = clip.get_frame(t)
            # FadeIn/FadeOut may produce float64 frames; convert for validation
            if frame.dtype != np.uint8:
                assert frame.min() >= 0.0
                assert frame.max() <= 255.0
            else:
                assert frame.min() >= 0
                assert frame.max() <= 255
        clip.close()

"""Tests for app.py UI layout logic.

These tests focus on the testable non-rendering logic:
- _save_config: TOML parsing, validation, persistence
- Session state initialization
- Image list mutation helpers
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# We need streamlit importable for app.py to load
import streamlit


# ---------------------------------------------------------------------------
# _save_config tests
# ---------------------------------------------------------------------------

class TestSaveConfig:
    """Test _save_config parsing and validation."""

    @patch("app.st")
    @patch("app.ConfigManager")
    def test_invalid_toml_shows_error(self, MockCM, mock_st):
        """Invalid TOML text should trigger st.error."""
        from app import _save_config

        cm = MagicMock()
        _save_config(cm, "this is [[[invalid toml")

        mock_st.error.assert_called_once()
        assert "TOML" in mock_st.error.call_args[0][0]
        cm.save.assert_not_called()

    @patch("app.st")
    @patch("app.ConfigManager")
    def test_valid_toml_saves(self, MockCM, mock_st):
        """Valid TOML should be parsed, validated, and saved."""
        from app import _save_config

        mock_st.session_state = {}
        cm = MagicMock()
        cm.validate.return_value = []

        toml_text = '[general]\noutput_dir = "./output"\n'
        _save_config(cm, toml_text)

        mock_st.error.assert_not_called()
        cm.save.assert_called_once()
        cm.validate.assert_called_once()
        mock_st.success.assert_called_once()
        assert "config" in mock_st.session_state

    @patch("app.st")
    @patch("app.ConfigManager")
    def test_missing_fields_shows_warning(self, MockCM, mock_st):
        """If validate returns missing fields, a warning should be shown but save still proceeds."""
        from app import _save_config

        mock_st.session_state = {}
        cm = MagicMock()
        cm.validate.return_value = ["general.temp_dir", "video.codec"]

        toml_text = '[general]\noutput_dir = "./output"\n'
        _save_config(cm, toml_text)

        mock_st.warning.assert_called_once()
        warning_msg = mock_st.warning.call_args[0][0]
        assert "general.temp_dir" in warning_msg
        assert "video.codec" in warning_msg
        # Should still save even with warnings
        cm.save.assert_called_once()


# ---------------------------------------------------------------------------
# Image list reorder / delete logic tests
# ---------------------------------------------------------------------------

class TestImageListMutations:
    """Test the image list swap and delete logic directly."""

    def test_swap_images(self):
        """Swapping two adjacent images should exchange their positions."""
        images = [
            {"name": "a.jpg", "data": b"a"},
            {"name": "b.jpg", "data": b"b"},
            {"name": "c.jpg", "data": b"c"},
        ]
        # Simulate swap_pair = (0, 1)
        i, j = 0, 1
        images[i], images[j] = images[j], images[i]

        assert images[0]["name"] == "b.jpg"
        assert images[1]["name"] == "a.jpg"
        assert images[2]["name"] == "c.jpg"

    def test_delete_image(self):
        """Deleting an image should remove it and preserve order of remaining."""
        images = [
            {"name": "a.jpg", "data": b"a"},
            {"name": "b.jpg", "data": b"b"},
            {"name": "c.jpg", "data": b"c"},
        ]
        images.pop(1)

        assert len(images) == 2
        assert images[0]["name"] == "a.jpg"
        assert images[1]["name"] == "c.jpg"

    def test_swap_last_to_first(self):
        """Swapping last element up should work correctly."""
        images = [
            {"name": "a.jpg", "data": b"a"},
            {"name": "b.jpg", "data": b"b"},
        ]
        i, j = 1, 0
        images[i], images[j] = images[j], images[i]

        assert images[0]["name"] == "b.jpg"
        assert images[1]["name"] == "a.jpg"

    def test_delete_only_image(self):
        """Deleting the only image should result in empty list."""
        images = [{"name": "a.jpg", "data": b"a"}]
        images.pop(0)
        assert images == []

    def test_merge_avoids_duplicates(self):
        """Merging uploaded files should skip files with existing names."""
        existing = [{"name": "a.jpg", "data": b"a"}]
        existing_names = {img["name"] for img in existing}

        new_files = [
            MagicMock(name="a.jpg"),  # duplicate
            MagicMock(name="b.jpg"),  # new
        ]
        # Fix: MagicMock's name attribute is special
        new_files[0].name = "a.jpg"
        new_files[0].getvalue.return_value = b"a_new"
        new_files[1].name = "b.jpg"
        new_files[1].getvalue.return_value = b"b"

        for uf in new_files:
            if uf.name not in existing_names:
                existing.append({"name": uf.name, "data": uf.getvalue()})
                existing_names.add(uf.name)

        assert len(existing) == 2
        assert existing[0]["name"] == "a.jpg"
        assert existing[0]["data"] == b"a"  # original kept
        assert existing[1]["name"] == "b.jpg"


# ---------------------------------------------------------------------------
# Pipeline helper tests
# ---------------------------------------------------------------------------

class TestSaveImagesToTemp:
    """Test _save_images_to_temp helper."""

    def test_saves_images_to_disk(self, tmp_path):
        """Images should be written to temp files with correct content."""
        from app import _save_images_to_temp

        images = [
            {"name": "photo1.jpg", "data": b"\xff\xd8\xff\xe0"},
            {"name": "photo2.png", "data": b"\x89PNG"},
        ]
        paths = _save_images_to_temp(images)

        assert len(paths) == 2
        assert paths[0].name == "photo1.jpg"
        assert paths[1].name == "photo2.png"
        assert paths[0].read_bytes() == b"\xff\xd8\xff\xe0"
        assert paths[1].read_bytes() == b"\x89PNG"

    def test_empty_list_returns_empty(self):
        """Empty image list should return empty path list."""
        from app import _save_images_to_temp

        paths = _save_images_to_temp([])
        assert paths == []


class TestRunAsync:
    """Test _run_async helper."""

    def test_runs_coroutine(self):
        """Should successfully run an async coroutine."""
        import asyncio
        from app import _run_async

        async def add(a, b):
            return a + b

        result = _run_async(add(2, 3))
        assert result == 5

    def test_handles_exception(self):
        """Should propagate exceptions from coroutines."""
        from app import _run_async

        async def fail():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            _run_async(fail())


# ---------------------------------------------------------------------------
# Session state initialization tests
# ---------------------------------------------------------------------------

class TestInitSessionState:
    """Test that _init_session_state sets up all pipeline-related keys."""

    @patch("app.st")
    @patch("app.ConfigManager")
    def test_pipeline_state_initialized(self, MockCM, mock_st):
        """All pipeline-related session state keys should be initialized."""
        mock_st.session_state = {}
        cm_instance = MagicMock()
        cm_instance.load.return_value = {"general": {}}
        MockCM.return_value = cm_instance

        from app import _init_session_state
        _init_session_state()

        assert "pipeline_step" in mock_st.session_state
        assert mock_st.session_state["pipeline_step"] == 1
        assert "narration" in mock_st.session_state
        assert mock_st.session_state["narration"] == ""
        assert "audio_path" in mock_st.session_state
        assert mock_st.session_state["audio_path"] is None
        assert "audio_duration" in mock_st.session_state
        assert mock_st.session_state["audio_duration"] == 0.0
        assert "video_path" in mock_st.session_state
        assert mock_st.session_state["video_path"] is None

    @patch("app.st")
    @patch("app.ConfigManager")
    def test_batch_state_initialized(self, MockCM, mock_st):
        """Batch mode session state keys should be initialized."""
        mock_st.session_state = {}
        cm_instance = MagicMock()
        cm_instance.load.return_value = {"general": {}}
        MockCM.return_value = cm_instance

        from app import _init_session_state
        _init_session_state()

        assert "batch_mode" in mock_st.session_state
        assert mock_st.session_state["batch_mode"] is False
        assert "batch_groups" in mock_st.session_state
        assert mock_st.session_state["batch_groups"] == []
        assert "batch_results" in mock_st.session_state
        assert mock_st.session_state["batch_results"] == []

    @patch("app.st")
    @patch("app.ConfigManager")
    def test_does_not_overwrite_existing(self, MockCM, mock_st):
        """Existing session state values should not be overwritten."""
        mock_st.session_state = {
            "pipeline_step": 3,
            "narration": "existing narration",
            "uploaded_images": [{"name": "x.jpg", "data": b"x"}],
            "config": {"general": {}},
            "config_toml_text": "",
            "audio_path": "/tmp/audio.mp3",
            "audio_duration": 10.5,
            "video_path": "/tmp/video.mp4",
            "batch_mode": True,
            "batch_groups": [{"name": "g1", "images": []}],
            "batch_results": [],
        }
        cm_instance = MagicMock()
        MockCM.return_value = cm_instance

        from app import _init_session_state
        _init_session_state()

        assert mock_st.session_state["pipeline_step"] == 3
        assert mock_st.session_state["narration"] == "existing narration"
        assert mock_st.session_state["audio_path"] == "/tmp/audio.mp3"
        assert mock_st.session_state["batch_mode"] is True

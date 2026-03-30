"""ConfigManager 单元测试。"""

from pathlib import Path

import pytest

from src.config_manager import ConfigManager, DEFAULT_CONFIG, REQUIRED_FIELDS


class TestConfigManagerLoad:
    """load() 方法测试。"""

    def test_load_creates_default_when_file_missing(self, tmp_path: Path):
        """文件不存在时应自动生成默认配置文件并返回默认配置。"""
        cfg_path = tmp_path / "config.toml"
        mgr = ConfigManager(path=cfg_path)

        result = mgr.load()

        assert cfg_path.exists()
        assert result == DEFAULT_CONFIG

    def test_load_reads_existing_file(self, tmp_path: Path):
        """已有配置文件时应正确读取。"""
        cfg_path = tmp_path / "config.toml"
        mgr = ConfigManager(path=cfg_path)

        mgr.save(DEFAULT_CONFIG)
        result = mgr.load()

        assert result["general"]["output_dir"] == "./output"
        assert result["video"]["default_fps"] == 30

    def test_load_preserves_custom_values(self, tmp_path: Path):
        """自定义值应在 save→load 后保留。"""
        cfg_path = tmp_path / "config.toml"
        mgr = ConfigManager(path=cfg_path)

        custom = {"general": {"output_dir": "/custom/path", "temp_dir": "./tmp", "default_aspect_ratio": "16:9"}}
        mgr.save(custom)
        result = mgr.load()

        assert result["general"]["output_dir"] == "/custom/path"
        assert result["general"]["default_aspect_ratio"] == "16:9"


class TestConfigManagerSave:
    """save() 方法测试。"""

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        """save() 应自动创建不存在的父目录。"""
        cfg_path = tmp_path / "nested" / "dir" / "config.toml"
        mgr = ConfigManager(path=cfg_path)

        mgr.save(DEFAULT_CONFIG)

        assert cfg_path.exists()

    def test_save_overwrites_existing(self, tmp_path: Path):
        """save() 应覆盖已有文件。"""
        cfg_path = tmp_path / "config.toml"
        mgr = ConfigManager(path=cfg_path)

        mgr.save({"general": {"output_dir": "./v1"}})
        mgr.save({"general": {"output_dir": "./v2"}})
        result = mgr.load()

        assert result["general"]["output_dir"] == "./v2"


class TestConfigManagerValidate:
    """validate() 方法测试。"""

    def test_validate_default_config_has_no_missing(self):
        """默认配置应通过校验，无缺失字段。"""
        mgr = ConfigManager()
        missing = mgr.validate(DEFAULT_CONFIG)
        assert missing == []

    def test_validate_empty_config_reports_all_required(self):
        """空配置应报告所有必要字段缺失。"""
        mgr = ConfigManager()
        missing = mgr.validate({})
        assert set(missing) == set(REQUIRED_FIELDS)

    def test_validate_partial_config_reports_missing(self):
        """部分配置应只报告缺失的字段。"""
        mgr = ConfigManager()
        partial = {
            "general": {
                "output_dir": "./output",
                "temp_dir": "./temp",
                "default_aspect_ratio": "9:16",
            },
        }
        missing = mgr.validate(partial)

        # general 字段不应出现在缺失列表中
        for field in missing:
            assert not field.startswith("general.")

        # video、subtitle、tts.edge_tts 字段应在缺失列表中
        assert "video.default_fps" in missing
        assert "subtitle.font_size" in missing
        assert "tts.edge_tts.default_voice" in missing

    def test_validate_missing_single_field(self):
        """移除单个字段后应只报告该字段缺失。"""
        import copy
        mgr = ConfigManager()
        config = copy.deepcopy(DEFAULT_CONFIG)
        del config["video"]["codec"]

        missing = mgr.validate(config)
        assert missing == ["video.codec"]


class TestConfigManagerDefaultPath:
    """默认路径测试。"""

    def test_default_path(self):
        mgr = ConfigManager()
        assert mgr.path == Path("config.toml")

    def test_custom_path(self, tmp_path: Path):
        custom = tmp_path / "my_config.toml"
        mgr = ConfigManager(path=custom)
        assert mgr.path == custom

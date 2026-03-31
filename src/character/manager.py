"""角色管理器：CRUD 操作，本地 JSON 存储。"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from src.character.models import Character

logger = logging.getLogger(__name__)

CHARACTERS_DIR = Path("characters")
CONFIG_FILENAME = "config.json"


class CharacterManager:
    """管理本地角色库。

    存储结构：
      characters/
        角色名/
          config.json
          ref_1.png
          ref_2.png
          ref_3.png
          lora.safetensors  (可选，预留)
    """

    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or CHARACTERS_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def list_characters(self) -> list[Character]:
        """列出所有角色。"""
        characters = []
        for d in sorted(self._base_dir.iterdir()):
            if d.is_dir() and (d / CONFIG_FILENAME).exists():
                try:
                    char = self._load(d)
                    characters.append(char)
                except Exception:
                    logger.warning("加载角色失败: %s", d.name, exc_info=True)
        return characters

    def get_character(self, name: str) -> Character | None:
        """按名字获取角色。"""
        char_dir = self._base_dir / name
        if not (char_dir / CONFIG_FILENAME).exists():
            return None
        return self._load(char_dir)

    def save_character(
        self, char: Character, ref_image_data: list[tuple[str, bytes]] | None = None
    ) -> Path:
        """保存角色（新建或更新）。

        Args:
            char: 角色数据。
            ref_image_data: 参考图列表 [(filename, bytes), ...]
        """
        char_dir = self._base_dir / char.name
        char_dir.mkdir(parents=True, exist_ok=True)

        # 保存参考图
        if ref_image_data:
            ref_names = []
            for filename, data in ref_image_data:
                img_path = char_dir / filename
                img_path.write_bytes(data)
                ref_names.append(filename)
            char.ref_images = ref_names

        # 保存配置
        config_path = char_dir / CONFIG_FILENAME
        config_path.write_text(
            json.dumps(char.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return char_dir

    def delete_character(self, name: str) -> bool:
        """删除角色及其所有文件。"""
        char_dir = self._base_dir / name
        if char_dir.exists():
            shutil.rmtree(char_dir)
            return True
        return False

    def get_ref_image_paths(self, name: str) -> list[Path]:
        """获取角色参考图的完整路径。"""
        char = self.get_character(name)
        if not char:
            return []
        char_dir = self._base_dir / name
        return [char_dir / img for img in char.ref_images if (char_dir / img).exists()]

    def _load(self, char_dir: Path) -> Character:
        config_path = char_dir / CONFIG_FILENAME
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return Character.from_dict(data)

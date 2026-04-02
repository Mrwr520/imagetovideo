from __future__ import annotations

from src.character.manager import CharacterManager
from src.tts.volcano import VolcanoTTSProvider


def test_builtin_characters_use_supported_volcano_2_voices() -> None:
    manager = CharacterManager()
    supported_voice_ids = {voice["id"] for voice in VolcanoTTSProvider().list_voices()}

    invalid_voices = {
        character.name: character.voice_type
        for character in manager.list_characters()
        if character.voice_type and character.voice_type not in supported_voice_ids
    }

    assert invalid_voices == {}

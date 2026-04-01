"""多角色对话 TTS 模块。

根据剧本的 character 和 emotion 字段自动切换音色和情感参数。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.character.models import Character
from src.script.models import Scene, Script
from src.tts.adapter import TTSAdapter

logger = logging.getLogger(__name__)


@dataclass
class CharacterVoiceMapping:
    """角色音色映射。"""
    
    character_name: str
    voice_type: str
    emotion_default: str = "neutral"
    
    # 情感 → TTS 参数映射
    emotion_params: dict = field(default_factory=dict)


@dataclass
class SceneAudioResult:
    """场景音频结果。"""
    
    scene_index: int
    audio_path: Path | None = None
    character: str = ""
    emotion: str = ""
    duration: float = 0.0
    word_timings: list | None = None
    error: str = ""


@dataclass
class MultiCharacterTTSResult:
    """多角色 TTS 结果。"""
    
    scene_results: list[SceneAudioResult] = field(default_factory=list)
    total_duration: float = 0.0
    merged_audio_path: Path | None = None
    
    @property
    def success_count(self) -> int:
        return sum(1 for r in self.scene_results if r.audio_path)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.scene_results if r.error)


# 情感 → TTS 参数映射（火山引擎）
_EMOTION_PARAMS = {
    "neutral": {"emotion": "neutral", "speed_ratio": 1.0},
    "happy": {"emotion": "happy", "speed_ratio": 1.05},
    "sad": {"emotion": "sad", "speed_ratio": 0.95},
    "angry": {"emotion": "angry", "speed_ratio": 1.1},
    "tender": {"emotion": "tender", "speed_ratio": 0.95},
    "excited": {"emotion": "happy", "speed_ratio": 1.15},
    "fearful": {"emotion": "sad", "speed_ratio": 1.0},
    "surprised": {"emotion": "happy", "speed_ratio": 1.1},
}


class MultiCharacterTTS:
    """多角色 TTS 合成器。"""
    
    def __init__(
        self,
        tts_adapter: TTSAdapter,
        default_provider: str = "volcano",
    ) -> None:
        """初始化多角色 TTS。
        
        Args:
            tts_adapter: TTSAdapter 实例。
            default_provider: 默认 TTS provider。
        """
        self._tts_adapter = tts_adapter
        self._default_provider = default_provider
        self._voice_mappings: dict[str, CharacterVoiceMapping] = {}
    
    def register_character(
        self,
        character: Character,
        emotion_params: dict | None = None,
    ) -> None:
        """注册角色音色映射。
        
        Args:
            character: 角色对象。
            emotion_params: 自定义情感参数映射。
        """
        mapping = CharacterVoiceMapping(
            character_name=character.name,
            voice_type=character.voice_type,
            emotion_default=character.emotion_default,
            emotion_params=emotion_params or _EMOTION_PARAMS.copy(),
        )
        self._voice_mappings[character.name] = mapping
        logger.info("已注册角色音色: %s -> %s", character.name, character.voice_type)
    
    def register_characters(self, characters: list[Character]) -> None:
        """批量注册角色。"""
        for char in characters:
            self.register_character(char)
    
    def _get_voice_for_character(self, character_name: str) -> str:
        """获取角色对应的音色。"""
        if character_name in self._voice_mappings:
            return self._voice_mappings[character_name].voice_type
        
        # 默认音色
        logger.warning("未找到角色 '%s' 的音色映射，使用默认音色", character_name)
        return ""
    
    def _get_emotion_params(self, character_name: str, emotion: str) -> dict:
        """获取情感参数。"""
        if character_name in self._voice_mappings:
            mapping = self._voice_mappings[character_name]
            if emotion in mapping.emotion_params:
                return mapping.emotion_params[emotion]
            if mapping.emotion_default in mapping.emotion_params:
                return mapping.emotion_params[mapping.emotion_default]
        
        # 默认参数
        return _EMOTION_PARAMS.get(emotion, _EMOTION_PARAMS["neutral"])
    
    async def synthesize_scene(
        self,
        scene: Scene,
        scene_index: int,
        output_path: Path,
        provider: str | None = None,
    ) -> SceneAudioResult:
        """合成单个场景的语音。
        
        Args:
            scene: 场景对象。
            scene_index: 场景索引。
            output_path: 输出路径。
            provider: TTS provider，None 则使用默认。
            
        Returns:
            场景音频结果。
        """
        result = SceneAudioResult(
            scene_index=scene_index,
            character=scene.character,
            emotion=scene.emotion,
        )
        
        if not scene.narration or not scene.narration.strip():
            result.error = "旁白文本为空"
            return result
        
        try:
            # 获取角色音色
            voice = self._get_voice_for_character(scene.character)
            
            # 获取情感参数
            emotion_params = self._get_emotion_params(scene.character, scene.emotion)
            
            # 合成语音
            provider_name = provider or self._default_provider
            
            tts_result = await self._tts_adapter.synthesize(
                scene.narration,
                provider_name,
                voice,
                output_path,
                **emotion_params,
            )
            
            result.audio_path = tts_result.audio_path
            result.duration = tts_result.duration
            result.word_timings = tts_result.word_timings
            
            logger.info(
                "场景 %d 语音合成完成: %s (%s) %.1fs",
                scene_index,
                scene.character,
                scene.emotion,
                result.duration,
            )
            
        except Exception as e:
            result.error = str(e)
            logger.error("场景 %d 语音合成失败: %s", scene_index, e)
        
        return result


    async def synthesize_script(
        self,
        script: Script,
        output_dir: Path | str,
        provider: str | None = None,
        merge: bool = True,
    ) -> MultiCharacterTTSResult:
        """合成整个剧本的语音。
        
        Args:
            script: 剧本对象。
            output_dir: 输出目录。
            provider: TTS provider。
            merge: 是否合并为单个音频文件。
            
        Returns:
            多角色 TTS 结果。
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        result = MultiCharacterTTSResult()
        
        # 逐场景合成
        for i, scene in enumerate(script.scenes):
            scene_output = output_dir / f"scene_{i:03d}.mp3"
            scene_result = await self.synthesize_scene(
                scene, i, scene_output, provider
            )
            result.scene_results.append(scene_result)
            result.total_duration += scene_result.duration
        
        # 合并音频
        if merge and result.success_count > 0:
            try:
                merged_path = output_dir / "merged.mp3"
                audio_paths = [
                    r.audio_path for r in result.scene_results
                    if r.audio_path and r.audio_path.exists()
                ]
                
                if audio_paths:
                    self._merge_audio_files(audio_paths, merged_path)
                    result.merged_audio_path = merged_path
                    
            except Exception as e:
                logger.warning("音频合并失败: %s", e)
        
        return result
    
    def _merge_audio_files(self, audio_paths: list[Path], output_path: Path) -> None:
        """合并多个音频文件。"""
        import subprocess
        import tempfile
        
        # 创建 concat 文件列表
        temp_dir = Path(tempfile.mkdtemp(prefix="tts_merge_"))
        list_file = temp_dir / "list.txt"
        
        with open(list_file, "w", encoding="utf-8") as f:
            for p in audio_paths:
                f.write(f"file '{p.absolute()}'\n")
        
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output_path),
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"音频合并失败: {result.stderr}")


def get_character_subtitle_style(character_name: str, characters: list[Character]) -> dict:
    """获取角色的字幕样式。
    
    Args:
        character_name: 角色名。
        characters: 角色列表。
        
    Returns:
        字幕样式字典，包含 color, outline_color 等。
    """
    # 预定义颜色列表
    colors = [
        {"color": "#FFFFFF", "outline_color": "#000000"},  # 白色（旁白）
        {"color": "#FFD700", "outline_color": "#8B4513"},  # 金色
        {"color": "#87CEEB", "outline_color": "#00008B"},  # 天蓝色
        {"color": "#98FB98", "outline_color": "#006400"},  # 浅绿色
        {"color": "#FFB6C1", "outline_color": "#8B0000"},  # 浅粉色
        {"color": "#DDA0DD", "outline_color": "#4B0082"},  # 梅红色
    ]
    
    # 查找角色索引
    for i, char in enumerate(characters):
        if char.name == character_name:
            return colors[i % len(colors)]
    
    # 默认样式
    return colors[0]


def generate_multi_character_subtitles(
    script: Script,
    tts_result: MultiCharacterTTSResult,
    characters: list[Character],
    output_path: Path,
) -> Path:
    """生成多角色字幕文件（ASS 格式）。
    
    Args:
        script: 剧本对象。
        tts_result: TTS 结果。
        characters: 角色列表。
        output_path: 输出路径。
        
    Returns:
        字幕文件路径。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # ASS 文件头
    ass_header = """[Script Info]
Title: Multi-Character Subtitles
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""
    
    # 为每个角色创建样式
    styles = []
    for i, char in enumerate(characters):
        style = get_character_subtitle_style(char.name, characters)
        # 转换颜色格式（ASS 使用 &HAABBGGRR）
        primary = _hex_to_ass_color(style["color"])
        outline = _hex_to_ass_color(style["outline_color"])
        
        style_line = (
            f"Style: {char.name},Microsoft YaHei,18,{primary},&H000000FF,"
            f"{outline},&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1"
        )
        styles.append(style_line)
    
    # 默认样式
    styles.append(
        "Style: Default,Microsoft YaHei,18,&H00FFFFFF,&H000000FF,"
        "&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1"
    )
    
    # 生成事件
    events = ["[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    
    current_time = 0.0
    for scene_result in tts_result.scene_results:
        if not scene_result.audio_path:
            continue
        
        # 使用 word_timings 或估算时间
        if scene_result.word_timings:
            for timing in scene_result.word_timings:
                start = _format_ass_time(current_time + timing.get("start", 0))
                end = _format_ass_time(current_time + timing.get("end", 0))
                text = timing.get("word", "")
                style_name = scene_result.character or "Default"
                
                events.append(
                    f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}"
                )
        else:
            # 没有 word_timings，使用整段
            scene_idx = scene_result.scene_index
            if scene_idx < len(script.scenes):
                text = script.scenes[scene_idx].narration
                start = _format_ass_time(current_time)
                end = _format_ass_time(current_time + scene_result.duration)
                style_name = scene_result.character or "Default"
                
                events.append(
                    f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}"
                )
        
        current_time += scene_result.duration
    
    # 写入文件
    content = ass_header + "\n".join(styles) + "\n\n" + "\n".join(events)
    output_path.write_text(content, encoding="utf-8")
    
    return output_path


def _hex_to_ass_color(hex_color: str) -> str:
    """将 #RRGGBB 转换为 ASS 颜色格式 &HAABBGGRR。"""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"&H00{b:02X}{g:02X}{r:02X}"


def _format_ass_time(seconds: float) -> str:
    """格式化 ASS 时间戳。"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"

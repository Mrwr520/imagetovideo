"""FFmpeg xfade 转场封装。

支持多种转场效果，用于视频片段拼接。
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 支持的转场效果
TRANSITIONS = {
    "fade": "fade",
    "fadeblack": "fadeblack",
    "fadewhite": "fadewhite",
    "dissolve": "dissolve",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "wipeup": "wipeup",
    "wipedown": "wipedown",
    "slideleft": "slideleft",
    "slideright": "slideright",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "circlecrop": "circlecrop",
    "rectcrop": "rectcrop",
    "distance": "distance",
    "smoothleft": "smoothleft",
    "smoothright": "smoothright",
    "smoothup": "smoothup",
    "smoothdown": "smoothdown",
    "circleopen": "circleopen",
    "circleclose": "circleclose",
    "vertopen": "vertopen",
    "vertclose": "vertclose",
    "horzopen": "horzopen",
    "horzclose": "horzclose",
    "diagtl": "diagtl",
    "diagtr": "diagtr",
    "diagbl": "diagbl",
    "diagbr": "diagbr",
    "hlslice": "hlslice",
    "hrslice": "hrslice",
    "vuslice": "vuslice",
    "vdslice": "vdslice",
}


def get_video_duration(video_path: Path) -> float:
    """获取视频时长（秒）。"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr}")
    return float(result.stdout.strip())


def apply_xfade(
    video1: Path,
    video2: Path,
    output: Path,
    *,
    transition: str = "fade",
    duration: float = 0.5,
    offset: float | None = None,
) -> Path:
    """对两个视频应用 xfade 转场。

    Args:
        video1: 第一个视频路径。
        video2: 第二个视频路径。
        output: 输出视频路径。
        transition: 转场效果名称。
        duration: 转场时长（秒）。
        offset: 转场开始时间，None 则自动计算（video1 时长 - duration）。

    Returns:
        输出视频路径。
    """
    video1 = Path(video1)
    video2 = Path(video2)
    output = Path(output)

    if transition not in TRANSITIONS:
        logger.warning("未知转场效果 '%s'，使用 fade", transition)
        transition = "fade"

    # 计算 offset
    if offset is None:
        v1_duration = get_video_duration(video1)
        offset = max(0, v1_duration - duration)

    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video1),
        "-i", str(video2),
        "-filter_complex",
        f"[0:v][1:v]xfade=transition={transition}:duration={duration}:offset={offset}[v]",
        "-map", "[v]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        str(output),
    ]

    logger.info("执行 xfade: %s -> %s", video1.name, video2.name)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"xfade 失败: {result.stderr}")

    return output


def concat_videos_with_xfade(
    videos: list[Path],
    output: Path,
    *,
    transition: str = "fade",
    duration: float = 0.5,
) -> Path:
    """使用 xfade 转场拼接多个视频。

    Args:
        videos: 视频路径列表。
        output: 输出视频路径。
        transition: 转场效果名称。
        duration: 转场时长（秒）。

    Returns:
        输出视频路径。
    """
    if not videos:
        raise ValueError("视频列表不能为空")

    if len(videos) == 1:
        # 单个视频直接复制
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(videos[0].read_bytes())
        return output

    # 逐个拼接
    temp_dir = Path(tempfile.mkdtemp(prefix="xfade_"))
    current = videos[0]

    for i, next_video in enumerate(videos[1:], 1):
        if i == len(videos) - 1:
            # 最后一次拼接，输出到目标路径
            temp_output = output
        else:
            temp_output = temp_dir / f"concat_{i}.mp4"

        current = apply_xfade(
            current,
            next_video,
            temp_output,
            transition=transition,
            duration=duration,
        )

    return output


def concat_videos_simple(videos: list[Path], output: Path) -> Path:
    """简单拼接视频（无转场）。

    Args:
        videos: 视频路径列表。
        output: 输出视频路径。

    Returns:
        输出视频路径。
    """
    if not videos:
        raise ValueError("视频列表不能为空")

    output.parent.mkdir(parents=True, exist_ok=True)

    # 创建 concat 文件列表
    temp_dir = Path(tempfile.mkdtemp(prefix="concat_"))
    list_file = temp_dir / "list.txt"

    with open(list_file, "w", encoding="utf-8") as f:
        for v in videos:
            f.write(f"file '{v.absolute()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"concat 失败: {result.stderr}")

    return output


def add_audio_to_video(
    video: Path,
    audio: Path,
    output: Path,
    *,
    audio_volume: float = 1.0,
) -> Path:
    """为视频添加音频轨道。

    Args:
        video: 视频路径。
        audio: 音频路径。
        output: 输出视频路径。
        audio_volume: 音频音量（0.0-1.0）。

    Returns:
        输出视频路径。
    """
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-filter_complex",
        f"[1:a]volume={audio_volume}[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(output),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"添加音频失败: {result.stderr}")

    return output


def mix_audio_tracks(
    video: Path,
    narration: Path,
    bgm: Path | None,
    output: Path,
    *,
    narration_volume: float = 1.0,
    bgm_volume: float = 0.25,
) -> Path:
    """混合配音和背景音乐。

    Args:
        video: 视频路径。
        narration: 配音音频路径。
        bgm: 背景音乐路径，None 则只添加配音。
        output: 输出视频路径。
        narration_volume: 配音音量。
        bgm_volume: 背景音乐音量。

    Returns:
        输出视频路径。
    """
    output.parent.mkdir(parents=True, exist_ok=True)

    if bgm is None:
        return add_audio_to_video(video, narration, output, audio_volume=narration_volume)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(narration),
        "-i", str(bgm),
        "-filter_complex",
        f"[1:a]volume={narration_volume}[narr];"
        f"[2:a]volume={bgm_volume}[bgm];"
        f"[narr][bgm]amix=inputs=2:duration=first[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(output),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"混音失败: {result.stderr}")

    return output

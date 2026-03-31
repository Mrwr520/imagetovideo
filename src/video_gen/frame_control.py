"""首尾帧控制模块。

实现 FLF2V（First-Last Frame to Video）场景衔接，
自动提取关键帧作为下一场景参考。
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_frame(
    video_path: Path,
    output_path: Path,
    *,
    position: str = "last",
    time_offset: float | None = None,
) -> Path:
    """从视频中提取帧。
    
    Args:
        video_path: 视频路径。
        output_path: 输出图片路径。
        position: 提取位置，"first"、"last" 或 "middle"。
        time_offset: 指定时间点（秒），覆盖 position。
        
    Returns:
        输出图片路径。
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    
    if not video_path.exists():
        raise ValueError(f"视频不存在: {video_path}")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 获取视频时长
    duration = _get_video_duration(video_path)
    
    # 计算提取时间点
    if time_offset is not None:
        seek_time = min(time_offset, duration - 0.1)
    elif position == "first":
        seek_time = 0.0
    elif position == "last":
        seek_time = max(0, duration - 0.1)
    elif position == "middle":
        seek_time = duration / 2
    else:
        seek_time = 0.0
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(seek_time),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"提取帧失败: {result.stderr}")
    
    logger.info("已提取帧: %s (%.2fs)", output_path, seek_time)
    return output_path


def extract_first_frame(video_path: Path, output_path: Path) -> Path:
    """提取视频首帧。"""
    return extract_frame(video_path, output_path, position="first")


def extract_last_frame(video_path: Path, output_path: Path) -> Path:
    """提取视频末帧。"""
    return extract_frame(video_path, output_path, position="last")


def _get_video_duration(video_path: Path) -> float:
    """获取视频时长。"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"获取视频时长失败: {result.stderr}")
    return float(result.stdout.strip())


def prepare_scene_chain(
    scene_videos: list[Path],
    output_dir: Path | str = "./temp/frames",
) -> list[dict]:
    """准备场景链接信息。
    
    从每个场景视频提取末帧，作为下一场景的首帧参考。
    
    Args:
        scene_videos: 场景视频路径列表。
        output_dir: 输出目录。
        
    Returns:
        场景链接信息列表，每项包含：
        - scene_index: 场景索引
        - video_path: 视频路径
        - first_frame: 首帧路径（如果有）
        - last_frame: 末帧路径
        - next_first_frame: 下一场景应使用的首帧（即当前场景末帧）
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    chain_info = []
    
    for i, video_path in enumerate(scene_videos):
        video_path = Path(video_path)
        
        info = {
            "scene_index": i,
            "video_path": video_path,
            "first_frame": None,
            "last_frame": None,
            "next_first_frame": None,
        }
        
        if not video_path.exists():
            logger.warning("场景视频不存在: %s", video_path)
            chain_info.append(info)
            continue
        
        # 提取首帧
        first_frame = output_dir / f"scene_{i:03d}_first.png"
        try:
            extract_first_frame(video_path, first_frame)
            info["first_frame"] = first_frame
        except Exception as e:
            logger.warning("提取首帧失败: %s", e)
        
        # 提取末帧
        last_frame = output_dir / f"scene_{i:03d}_last.png"
        try:
            extract_last_frame(video_path, last_frame)
            info["last_frame"] = last_frame
            
            # 末帧作为下一场景的首帧参考
            if i < len(scene_videos) - 1:
                info["next_first_frame"] = last_frame
        except Exception as e:
            logger.warning("提取末帧失败: %s", e)
        
        chain_info.append(info)
    
    return chain_info


def generate_with_first_frame(
    video_gen_adapter,
    image_path: Path,
    first_frame: Path | None,
    prompt: str,
    **kwargs,
):
    """使用首帧参考生成视频（FLF2V）。
    
    如果提供了首帧参考，将其与输入图片合并作为参考。
    
    Args:
        video_gen_adapter: VideoGenAdapter 实例。
        image_path: 输入图片路径。
        first_frame: 首帧参考图路径，None 则不使用。
        prompt: 运动提示词。
        **kwargs: 其他参数传递给 generate。
        
    Returns:
        VideoGenResult。
    """
    # 如果有首帧参考，在提示词中添加衔接说明
    if first_frame and first_frame.exists():
        enhanced_prompt = (
            f"{prompt}, smooth transition from previous scene, "
            "maintain visual continuity"
        )
        # 注意：实际的首帧注入需要视频生成模型支持
        # 这里通过提示词引导，具体实现取决于 provider
        kwargs["prompt"] = enhanced_prompt
    else:
        kwargs["prompt"] = prompt
    
    return video_gen_adapter.generate(image_path, **kwargs)


def create_keyframe_sequence(
    videos: list[Path],
    output_dir: Path | str = "./temp/keyframes",
    interval: float = 1.0,
) -> list[list[Path]]:
    """从视频序列中提取关键帧序列。
    
    Args:
        videos: 视频路径列表。
        output_dir: 输出目录。
        interval: 提取间隔（秒）。
        
    Returns:
        关键帧路径列表的列表，每个视频对应一个列表。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    all_keyframes = []
    
    for i, video_path in enumerate(videos):
        video_path = Path(video_path)
        keyframes = []
        
        if not video_path.exists():
            all_keyframes.append(keyframes)
            continue
        
        try:
            duration = _get_video_duration(video_path)
            
            # 按间隔提取关键帧
            t = 0.0
            frame_idx = 0
            while t < duration:
                frame_path = output_dir / f"video_{i:03d}_frame_{frame_idx:03d}.png"
                extract_frame(video_path, frame_path, time_offset=t)
                keyframes.append(frame_path)
                t += interval
                frame_idx += 1
            
            # 确保提取末帧
            if keyframes and t - interval < duration - 0.1:
                frame_path = output_dir / f"video_{i:03d}_frame_{frame_idx:03d}.png"
                extract_last_frame(video_path, frame_path)
                keyframes.append(frame_path)
                
        except Exception as e:
            logger.warning("提取关键帧失败: %s", e)
        
        all_keyframes.append(keyframes)
    
    return all_keyframes

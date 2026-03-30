"""视频合成器模块：将图片、音频、字幕、背景音乐合成为最终视频。

针对图片解说场景优化：静态图片展示 + 语音 + 字幕，无动画特效。
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    ImageClip,
    concatenate_videoclips,
)
from moviepy.audio.fx import AudioFadeOut, AudioLoop, MultiplyVolume
from PIL import Image

from src.subtitle.generator import SubtitleSegment, SubtitleStyle

logger = logging.getLogger(__name__)

# Resolution mapping for supported aspect ratios
_RESOLUTION_MAP: dict[str, tuple[int, int]] = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
}


@dataclass
class VideoConfig:
    """Video output configuration."""

    aspect_ratio: str = "9:16"
    width: int = 720
    height: int = 1280
    fps: int = 10
    bitrate: str = "2M"
    codec: str = "libx264"

    @classmethod
    def from_aspect_ratio(cls, aspect_ratio: str, **kwargs) -> VideoConfig:
        if aspect_ratio not in _RESOLUTION_MAP:
            raise ValueError(
                f"Unsupported aspect ratio '{aspect_ratio}'. "
                f"Supported: {list(_RESOLUTION_MAP.keys())}"
            )
        width, height = _RESOLUTION_MAP[aspect_ratio]
        return cls(
            aspect_ratio=aspect_ratio,
            width=width,
            height=height,
            **kwargs,
        )


def _fit_image(image_path: Path, target_width: int, target_height: int) -> str:
    """Resize image to fit entirely within target area, fill background with blurred version.

    Uses contain-fit: scales so the full image is visible,
    then fills the remaining area with a heavily blurred + darkened
    version of the image itself (no ugly black bars).
    """
    img = Image.open(image_path).convert("RGB")
    src_w, src_h = img.size

    # Create blurred background (cover-fit the blur layer)
    from PIL import ImageFilter
    bg_scale = max(target_width / src_w, target_height / src_h)
    bg_w = int(src_w * bg_scale)
    bg_h = int(src_h * bg_scale)
    bg = img.resize((bg_w, bg_h), Image.LANCZOS)
    bg_left = (bg_w - target_width) // 2
    bg_top = (bg_h - target_height) // 2
    bg = bg.crop((bg_left, bg_top, bg_left + target_width, bg_top + target_height))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=30))
    # Darken the blur layer so the main image stands out
    from PIL import ImageEnhance
    bg = ImageEnhance.Brightness(bg).enhance(0.4)

    # Contain-fit the main image
    fg_scale = min(target_width / src_w, target_height / src_h)
    fg_w = int(src_w * fg_scale)
    fg_h = int(src_h * fg_scale)
    fg = img.resize((fg_w, fg_h), Image.LANCZOS)

    # Center paste onto blurred background
    offset_x = (target_width - fg_w) // 2
    offset_y = (target_height - fg_h) // 2
    bg.paste(fg, (offset_x, offset_y))

    tmp = tempfile.mktemp(suffix=".jpg")
    bg.save(tmp, quality=95)
    return tmp


def _generate_srt(subtitles: list[SubtitleSegment], output_path: Path) -> Path:
    """Generate an SRT subtitle file from subtitle segments."""
    lines = []
    for seg in subtitles:
        start = _format_srt_time(seg.start_time)
        end = _format_srt_time(seg.end_time)
        lines.append(f"{seg.index + 1}")
        lines.append(f"{start} --> {end}")
        lines.append(seg.text)
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class VideoComposer:
    """Composes final video from images, audio, subtitles, and background music.

    Optimized for image-narration slideshows: static images, no animation.
    """

    def calculate_image_durations(
        self, image_count: int, total_duration: float
    ) -> list[float]:
        """Calculate display duration for each image, distributed evenly."""
        if image_count <= 0:
            raise ValueError("image_count must be positive")
        if total_duration <= 0:
            raise ValueError("total_duration must be positive")

        total_ms = round(total_duration * 1000)
        base_ms = total_ms // image_count
        remainder_ms = total_ms - base_ms * image_count

        durations_ms = [base_ms] * image_count
        for i in range(remainder_ms):
            durations_ms[i] += 1

        return [ms / 1000.0 for ms in durations_ms]

    def create_image_clips(
        self,
        images: list[Path],
        durations: list[float],
        video_config: VideoConfig,
    ) -> list:
        """Create static ImageClip for each image (no animation)."""
        clips = []
        for img_path, dur in zip(images, durations):
            fitted = _fit_image(img_path, video_config.width, video_config.height)
            clip = (
                ImageClip(fitted)
                .with_duration(dur)
                .with_fps(video_config.fps)
            )
            clips.append(clip)
        return clips

    def mix_audio(
        self,
        narration_path: Path,
        bgm_path: Path | None,
        video_duration: float,
        bgm_volume: float = 0.25,
    ) -> Path:
        """Mix narration audio with optional background music."""
        narration = AudioFileClip(str(narration_path))

        if bgm_path is None:
            narration.close()
            return narration_path

        bgm_volume = max(0.20, min(0.30, bgm_volume))
        bgm = AudioFileClip(str(bgm_path))

        if bgm.duration < video_duration:
            bgm = bgm.with_effects([AudioLoop(duration=video_duration)])
        elif bgm.duration > video_duration:
            bgm = bgm.with_duration(video_duration)
            fade_duration = min(2.0, video_duration)
            bgm = bgm.with_effects([AudioFadeOut(fade_duration)])

        bgm = bgm.with_effects([MultiplyVolume(bgm_volume)])

        mixed = CompositeAudioClip([narration, bgm])
        mixed = mixed.with_duration(video_duration)

        output_path = Path(tempfile.mktemp(suffix=".wav"))
        mixed.write_audiofile(str(output_path), fps=44100, logger=None)

        narration.close()
        bgm.close()
        mixed.close()

        return output_path

    def burn_subtitles_ffmpeg(
        self,
        video_path: Path,
        srt_path: Path,
        output_path: Path,
        style: SubtitleStyle,
    ) -> Path:
        """Use FFmpeg to burn subtitles into video.

        Uses the FFmpeg binary bundled with imageio_ffmpeg (same one MoviePy uses)
        to avoid requiring a system-wide FFmpeg installation.
        """
        import shutil
        from moviepy.config import FFMPEG_BINARY

        # Copy SRT next to video with simple name to avoid Windows path issues
        work_dir = video_path.parent
        local_srt = work_dir / "subs.srt"
        shutil.copy2(str(srt_path), str(local_srt))

        font_size = style.font_size
        sub_filter = (
            f"subtitles=subs.srt"
            f":force_style='FontSize={font_size},"
            f"FontName=Microsoft YaHei,"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"Outline={style.outline_width},"
            f"Alignment=2,"
            f"MarginV=40'"
        )

        cmd = [
            FFMPEG_BINARY, "-y",
            "-i", video_path.name,
            "-vf", sub_filter,
            "-c:a", "copy",
            "-c:v", "libx264",
            "-preset", "fast",
            output_path.name,
        ]

        logger.info("FFmpeg subtitle burn command: %s (cwd=%s)", " ".join(cmd), work_dir)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(work_dir),
        )

        # Clean up temp srt
        local_srt.unlink(missing_ok=True)

        if result.returncode != 0:
            logger.warning(
                "FFmpeg subtitle burn failed (rc=%d):\nstdout: %s\nstderr: %s",
                result.returncode, result.stdout, result.stderr,
            )
            return video_path

        return work_dir / output_path.name

    def compose(
        self,
        ctx,
        video_config: VideoConfig,
        ken_burns=None,  # kept for API compat, ignored
        subtitle_style: SubtitleStyle | None = None,
    ) -> Path:
        """Compose the final video from images, audio, subtitles, and BGM.

        Pipeline:
        1. Load narration audio to determine total duration.
        2. Calculate per-image display durations.
        3. Create static ImageClips for each image.
        4. Concatenate clips and attach audio.
        5. Write base video (no subtitles yet).
        6. Burn subtitles via FFmpeg (avoids memory issues).
        """
        if subtitle_style is None:
            subtitle_style = SubtitleStyle()

        # 1. Get total duration from audio
        narration = AudioFileClip(str(ctx.audio_path))
        total_duration = narration.duration
        narration.close()

        # 2. Calculate image durations
        durations = self.calculate_image_durations(
            len(ctx.images), total_duration
        )

        # 3. Create static image clips
        clips = self.create_image_clips(
            ctx.images, durations, video_config
        )

        # 4. Concatenate
        video = concatenate_videoclips(clips, method="chain")

        # 5. Mix audio and attach
        audio_path = self.mix_audio(
            ctx.audio_path, ctx.bgm_path, total_duration,
        )
        final_audio = AudioFileClip(str(audio_path))
        video = video.with_audio(final_audio)

        # Write base video (without subtitles)
        output_dir = Path(ctx.output_path).parent if ctx.output_path else Path("output")
        output_dir.mkdir(parents=True, exist_ok=True)

        base_file = output_dir / f"{ctx.task_id}_base.mp4"
        video.write_videofile(
            str(base_file),
            codec=video_config.codec,
            bitrate=video_config.bitrate,
            fps=video_config.fps,
            audio_codec="aac",
            logger=None,
        )

        # Clean up MoviePy resources
        for clip in clips:
            clip.close()
        video.close()
        final_audio.close()

        # 6. Burn subtitles via FFmpeg
        final_file = (
            Path(ctx.output_path)
            if ctx.output_path
            else output_dir / f"{ctx.task_id}.mp4"
        )

        if ctx.subtitle_data:
            subtitles = [
                SubtitleSegment(**s) if isinstance(s, dict) else s
                for s in ctx.subtitle_data
            ]
            srt_path = output_dir / f"{ctx.task_id}.srt"
            _generate_srt(subtitles, srt_path)
            result_path = self.burn_subtitles_ffmpeg(
                base_file, srt_path, final_file, subtitle_style,
            )
            # Clean up base file if subtitle burn succeeded
            if result_path != base_file and base_file.exists():
                base_file.unlink(missing_ok=True)
            return result_path
        else:
            # No subtitles, just rename base to final
            if base_file != final_file:
                base_file.rename(final_file)
            return final_file

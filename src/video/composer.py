"""视频合成器模块：将图片、音频、字幕、背景音乐合成为最终视频。

Supports 9:16 (vertical) and 16:9 (horizontal) aspect ratios,
Ken Burns animation, hardcoded subtitles, and BGM mixing.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    TextClip,
    concatenate_videoclips,
    vfx,
)
from moviepy.audio.fx import AudioFadeOut, AudioLoop, MultiplyVolume

from src.subtitle.generator import SubtitleSegment, SubtitleStyle
from src.video.ken_burns import KenBurnsParams, create_ken_burns_clip

logger = logging.getLogger(__name__)

# Resolution mapping for supported aspect ratios
_RESOLUTION_MAP: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


@dataclass
class VideoConfig:
    """Video output configuration.

    Attributes:
        aspect_ratio: "9:16" for vertical or "16:9" for horizontal.
        width: Output width in pixels.
        height: Output height in pixels.
        fps: Frames per second.
        bitrate: Target video bitrate (e.g. "4M").
        codec: Video codec name.
    """

    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    bitrate: str = "4M"
    codec: str = "libx264"

    @classmethod
    def from_aspect_ratio(cls, aspect_ratio: str, **kwargs) -> VideoConfig:
        """Create a VideoConfig from an aspect ratio string.

        Args:
            aspect_ratio: "9:16" or "16:9".
            **kwargs: Additional overrides for fps, bitrate, codec.

        Returns:
            A VideoConfig with the correct width/height for the ratio.

        Raises:
            ValueError: If aspect_ratio is not supported.
        """
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


class VideoComposer:
    """Composes final video from images, audio, subtitles, and background music."""

    def calculate_image_durations(
        self, image_count: int, total_duration: float
    ) -> list[float]:
        """Calculate display duration for each image, distributed evenly.

        The base duration is total_duration / image_count (truncated to 3 decimals).
        Any remainder is distributed one unit (0.001s) at a time to the first images,
        ensuring the sum equals total_duration exactly.

        Args:
            image_count: Number of images (must be > 0).
            total_duration: Total video duration in seconds (must be > 0).

        Returns:
            List of durations whose length == image_count, each > 0,
            and whose sum == total_duration.

        Raises:
            ValueError: If image_count <= 0 or total_duration <= 0.
        """
        if image_count <= 0:
            raise ValueError("image_count must be positive")
        if total_duration <= 0:
            raise ValueError("total_duration must be positive")

        # Work in integer milliseconds to avoid floating-point drift
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
        ken_burns: KenBurnsParams,
    ) -> list:
        """Create Ken Burns video clips for each image.

        Args:
            images: Ordered list of image file paths.
            durations: Display duration for each image (same length as images).
            video_config: Output video configuration.
            ken_burns: Ken Burns animation parameters.

        Returns:
            List of MoviePy VideoClip objects.
        """
        clips = []
        for img_path, dur in zip(images, durations):
            clip = create_ken_burns_clip(
                image=img_path,
                target_width=video_config.width,
                target_height=video_config.height,
                duration=dur,
                fps=video_config.fps,
                params=ken_burns,
            )
            clips.append(clip)
        return clips

    def add_subtitles(
        self,
        video_clip,
        subtitles: list[SubtitleSegment],
        style: SubtitleStyle,
    ):
        """Overlay hardcoded subtitles onto the video clip.

        Each subtitle segment is rendered as a TextClip positioned at the
        bottom of the frame, composited on top of the video.

        Args:
            video_clip: Base MoviePy video clip.
            subtitles: List of subtitle segments with timing info.
            style: Subtitle visual style configuration.

        Returns:
            A CompositeVideoClip with subtitles burned in.
        """
        if not subtitles:
            return video_clip

        subtitle_clips = []
        for seg in subtitles:
            duration = seg.end_time - seg.start_time
            if duration <= 0:
                continue
            try:
                txt_clip = (
                    TextClip(
                        text=seg.text,
                        font_size=style.font_size,
                        color=style.color,
                        font=style.font_family,
                        stroke_color=style.outline_color,
                        stroke_width=style.outline_width,
                        method="caption",
                        size=(video_clip.w * 0.9, None),
                    )
                    .with_start(seg.start_time)
                    .with_duration(duration)
                    .with_position(("center", 0.85), relative=True)
                )
                subtitle_clips.append(txt_clip)
            except Exception:
                logger.warning(
                    "Failed to create subtitle clip for segment %d: '%s'",
                    seg.index,
                    seg.text,
                    exc_info=True,
                )

        if not subtitle_clips:
            return video_clip

        return CompositeVideoClip([video_clip, *subtitle_clips])

    def mix_audio(
        self,
        narration_path: Path,
        bgm_path: Path | None,
        video_duration: float,
        bgm_volume: float = 0.25,
    ) -> Path:
        """Mix narration audio with optional background music.

        BGM handling:
        - bgm_volume is clamped to [0.20, 0.30].
        - If BGM is shorter than video, it loops until it covers the full duration.
        - If BGM is longer than video, it is trimmed and faded out over the last 2s.
        - The mixed result is written to a temporary WAV file.

        Args:
            narration_path: Path to the narration audio file.
            bgm_path: Path to background music file, or None to skip BGM.
            video_duration: Target duration in seconds.
            bgm_volume: Volume multiplier for BGM (clamped to 0.20–0.30).

        Returns:
            Path to the mixed audio file.
        """
        narration = AudioFileClip(str(narration_path))

        if bgm_path is None:
            return narration_path

        # Clamp BGM volume to 20%-30%
        bgm_volume = max(0.20, min(0.30, bgm_volume))

        bgm = AudioFileClip(str(bgm_path))

        # Handle BGM duration vs video duration
        if bgm.duration < video_duration:
            # Loop BGM to cover the full video duration
            bgm = bgm.with_effects([AudioLoop(duration=video_duration)])
        elif bgm.duration > video_duration:
            # Trim and fade out over the last 2 seconds
            bgm = bgm.with_duration(video_duration)
            fade_duration = min(2.0, video_duration)
            bgm = bgm.with_effects([AudioFadeOut(fade_duration)])

        # Apply volume reduction to BGM
        bgm = bgm.with_effects([MultiplyVolume(bgm_volume)])

        # Mix narration and BGM
        mixed = CompositeAudioClip([narration, bgm])
        mixed = mixed.with_duration(video_duration)

        # Write to temp file
        output_path = Path(tempfile.mktemp(suffix=".wav"))
        mixed.write_audiofile(
            str(output_path), fps=44100, logger=None
        )

        # Clean up clips
        narration.close()
        bgm.close()
        mixed.close()

        return output_path

    def compose(
        self,
        ctx,
        video_config: VideoConfig,
        ken_burns: KenBurnsParams,
        subtitle_style: SubtitleStyle,
    ) -> Path:
        """Compose the final video from images, audio, subtitles, and BGM.

        Pipeline:
        1. Load narration audio to determine total duration.
        2. Calculate per-image display durations.
        3. Create Ken Burns clips for each image.
        4. Concatenate image clips into a single video.
        5. Overlay subtitles.
        6. Mix narration with optional BGM.
        7. Attach audio and write H.264 MP4.

        Args:
            ctx: TaskContext with images, audio_path, subtitle_data, bgm_path, etc.
            video_config: Video output settings.
            ken_burns: Ken Burns animation parameters.
            subtitle_style: Subtitle rendering style.

        Returns:
            Path to the output MP4 file.
        """
        # 1. Load narration to get total duration
        narration = AudioFileClip(str(ctx.audio_path))
        total_duration = narration.duration
        narration.close()

        # 2. Calculate image durations
        durations = self.calculate_image_durations(
            len(ctx.images), total_duration
        )

        # 3. Create Ken Burns clips
        clips = self.create_image_clips(
            ctx.images, durations, video_config, ken_burns
        )

        # 4. Concatenate into a single video
        video = concatenate_videoclips(clips, method="compose")

        # 5. Add subtitles if available
        if ctx.subtitle_data:
            subtitles = [
                SubtitleSegment(**s) if isinstance(s, dict) else s
                for s in ctx.subtitle_data
            ]
            video = self.add_subtitles(video, subtitles, subtitle_style)

        # 6. Mix audio
        audio_path = self.mix_audio(
            ctx.audio_path,
            ctx.bgm_path,
            total_duration,
        )
        final_audio = AudioFileClip(str(audio_path))
        video = video.with_audio(final_audio)

        # 7. Write output
        output_dir = Path(ctx.output_path).parent if ctx.output_path else Path("output")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = (
            Path(ctx.output_path)
            if ctx.output_path
            else output_dir / f"{ctx.task_id}.mp4"
        )

        video.write_videofile(
            str(output_file),
            codec=video_config.codec,
            bitrate=video_config.bitrate,
            fps=video_config.fps,
            audio_codec="aac",
            logger=None,
        )

        # Clean up
        for clip in clips:
            clip.close()
        video.close()
        final_audio.close()

        return output_file

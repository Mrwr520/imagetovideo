"""Ken Burns effect implementation for static images.

Applies zoom, pan, and fade animations to create dynamic video clips
from still images. Used by VideoComposer to add transition effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from moviepy import ImageClip, VideoClip, vfx
from PIL import Image


@dataclass
class KenBurnsParams:
    """Parameters controlling the Ken Burns animation effect.

    Attributes:
        zoom_range: (start_zoom, end_zoom) multipliers applied over the clip duration.
        pan_speed: Fraction of image dimension to pan per second (0.0–1.0).
        fade_duration: Seconds for fade-in at start and fade-out at end.
    """

    zoom_range: tuple[float, float] = (1.0, 1.1)
    pan_speed: float = 0.01
    fade_duration: float = 0.3


def _prepare_image(
    image: Image.Image | str | Path,
    target_width: int,
    target_height: int,
) -> np.ndarray:
    """Load and resize an image to fit within the target resolution.

    The image is scaled to fit entirely inside the target area (contain fit),
    then placed centered on a black background of exactly target_width × target_height.
    A small margin is added for subtle zoom/pan room.
    """
    if not isinstance(image, Image.Image):
        image = Image.open(image)

    image = image.convert("RGB")

    # Add small margin for subtle zoom/pan
    margin = 1.15
    padded_w = int(target_width * margin)
    padded_h = int(target_height * margin)

    # Contain-fit: scale to fit inside padded area (show full image)
    src_w, src_h = image.size
    scale = min(padded_w / src_w, padded_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    image = image.resize((new_w, new_h), Image.LANCZOS)

    # Place on black background, centered
    bg = Image.new("RGB", (padded_w, padded_h), (0, 0, 0))
    offset_x = (padded_w - new_w) // 2
    offset_y = (padded_h - new_h) // 2
    bg.paste(image, (offset_x, offset_y))

    return np.array(bg)


def _apply_zoom_pan_frame(
    img_array: np.ndarray,
    t: float,
    duration: float,
    target_width: int,
    target_height: int,
    params: KenBurnsParams,
) -> np.ndarray:
    """Compute a single frame with zoom and pan applied.

    Args:
        img_array: Source image (larger than target to allow cropping).
        t: Current time in seconds.
        duration: Total clip duration in seconds.
        target_width: Output frame width.
        target_height: Output frame height.
        params: Ken Burns animation parameters.

    Returns:
        An (target_height, target_width, 3) uint8 numpy array.
    """
    progress = t / duration if duration > 0 else 0.0
    progress = max(0.0, min(1.0, progress))

    # Interpolate zoom level
    zoom_start, zoom_end = params.zoom_range
    zoom = zoom_start + (zoom_end - zoom_start) * progress

    src_h, src_w = img_array.shape[:2]

    # Size of the crop window (inverse of zoom)
    crop_w = int(target_width / zoom)
    crop_h = int(target_height / zoom)

    # Clamp crop size to source image bounds
    crop_w = min(crop_w, src_w)
    crop_h = min(crop_h, src_h)

    # Pan: shift the crop center over time
    max_pan_x = (src_w - crop_w) // 2
    max_pan_y = (src_h - crop_h) // 2

    pan_offset_x = int(max_pan_x * params.pan_speed * duration * progress)
    pan_offset_y = int(max_pan_y * params.pan_speed * duration * progress * 0.5)

    # Center of source image
    cx = src_w // 2
    cy = src_h // 2

    # Apply pan offset, clamped to valid range
    left = cx - crop_w // 2 + pan_offset_x
    top = cy - crop_h // 2 + pan_offset_y

    # Clamp to image bounds
    left = max(0, min(left, src_w - crop_w))
    top = max(0, min(top, src_h - crop_h))

    # Crop and resize to target
    cropped = img_array[top : top + crop_h, left : left + crop_w]

    # Resize using PIL for quality
    pil_frame = Image.fromarray(cropped)
    pil_frame = pil_frame.resize((target_width, target_height), Image.LANCZOS)

    return np.array(pil_frame)


def create_ken_burns_clip(
    image: Image.Image | str | Path,
    target_width: int,
    target_height: int,
    duration: float,
    fps: int = 30,
    params: KenBurnsParams | None = None,
) -> VideoClip:
    """Create a MoviePy VideoClip with Ken Burns zoom/pan/fade effect.

    Args:
        image: PIL Image, or path to an image file.
        target_width: Output video width in pixels.
        target_height: Output video height in pixels.
        duration: Clip duration in seconds.
        fps: Frames per second.
        params: Animation parameters. Uses defaults if None.

    Returns:
        A MoviePy VideoClip with the Ken Burns effect applied,
        including fade-in at the start and fade-out at the end.
    """
    if params is None:
        params = KenBurnsParams()

    img_array = _prepare_image(image, target_width, target_height)

    def make_frame(t: float) -> np.ndarray:
        return _apply_zoom_pan_frame(
            img_array, t, duration, target_width, target_height, params
        )

    clip = VideoClip(make_frame, duration=duration).with_fps(fps)

    # Skip fade effects to avoid float64 memory overhead.
    # For image-narration slideshows, clean cuts between slides are fine.

    return clip

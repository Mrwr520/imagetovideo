"""Wan2GP Provider：本地 Wan 2.1 图生视频。

通过命令行调用 Wan2GP 实现 I2V（图生视频），
支持 8GB 显存优化（低分辨率 + 分段生成）。
"""

from __future__ import annotations

import asyncio
import logging
import random
import subprocess
import tempfile
import time
from pathlib import Path

from src.video_gen.adapter import register_provider
from src.video_gen.base import BaseVideoGenProvider, VideoGenResult

logger = logging.getLogger(__name__)

# 默认配置
_DEFAULT_MODEL_PATH = "./models/wan2.1"
_DEFAULT_VRAM_LIMIT = 8192  # 8GB
_MAX_TIMEOUT = 600  # 10 分钟超时

# 支持的模型
_MODELS: list[dict] = [
    {
        "id": "wan2.1-1.3b",
        "name": "Wan 2.1 1.3B",
        "description": "轻量级模型，适合 8GB 显存",
        "vram": 6000,
    },
    {
        "id": "wan2.1-14b",
        "name": "Wan 2.1 14B",
        "description": "高质量模型，需要 24GB+ 显存",
        "vram": 24000,
    },
]

# 8GB 显存优化参数
_LOW_VRAM_SETTINGS = {
    "max_width": 480,
    "max_height": 854,
    "max_frames": 49,  # ~2秒 @ 24fps
    "enable_tiling": True,
    "enable_slicing": True,
}


class Wan2GPProvider(BaseVideoGenProvider):
    """Wan2GP 本地视频生成 Provider。

    通过命令行调用 Wan2GP 脚本实现 I2V。
    支持显存管理和分段生成。
    """

    def __init__(self, config: dict | None = None, **kwargs: object) -> None:
        cfg = config or {}
        cfg.update(kwargs)
        self._model_path: str = cfg.get("model_path", _DEFAULT_MODEL_PATH)
        self._vram_limit: int = int(cfg.get("vram_limit", _DEFAULT_VRAM_LIMIT))
        self._model: str = cfg.get("model", "wan2.1-1.3b")
        self._timeout: int = int(cfg.get("timeout", _MAX_TIMEOUT))
        self._wan2gp_path: str = cfg.get("wan2gp_path", "")
        self._python_path: str = cfg.get("python_path", "python")

    def _is_low_vram_mode(self) -> bool:
        """判断是否启用低显存模式。"""
        return self._vram_limit <= 8192

    def _adjust_resolution(self, width: int, height: int) -> tuple[int, int]:
        """根据显存限制调整分辨率。"""
        if not self._is_low_vram_mode():
            return width, height

        max_w = _LOW_VRAM_SETTINGS["max_width"]
        max_h = _LOW_VRAM_SETTINGS["max_height"]

        # 保持宽高比
        aspect = width / height
        if width > max_w:
            width = max_w
            height = int(width / aspect)
        if height > max_h:
            height = max_h
            width = int(height * aspect)

        # 确保是 8 的倍数
        width = (width // 8) * 8
        height = (height // 8) * 8

        return max(width, 64), max(height, 64)

    def _calculate_frames(self, duration: float, fps: float) -> int:
        """计算帧数，低显存模式下限制最大帧数。"""
        frames = int(duration * fps)

        if self._is_low_vram_mode():
            max_frames = _LOW_VRAM_SETTINGS["max_frames"]
            if frames > max_frames:
                logger.warning(
                    "低显存模式：帧数从 %d 限制到 %d",
                    frames,
                    max_frames,
                )
                frames = max_frames

        return frames

    def _build_command(
        self,
        image_path: Path,
        output_path: Path,
        *,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        frames: int,
        fps: float,
        seed: int,
    ) -> list[str]:
        """构建 Wan2GP 命令行参数。"""
        cmd = [
            self._python_path,
            "-m", "wan2gp.generate",
            "--image", str(image_path),
            "--output", str(output_path),
            "--model", self._model,
            "--width", str(width),
            "--height", str(height),
            "--frames", str(frames),
            "--fps", str(int(fps)),
            "--seed", str(seed),
        ]

        if prompt:
            cmd.extend(["--prompt", prompt])

        if negative_prompt:
            cmd.extend(["--negative-prompt", negative_prompt])

        # 低显存优化
        if self._is_low_vram_mode():
            if _LOW_VRAM_SETTINGS["enable_tiling"]:
                cmd.append("--enable-tiling")
            if _LOW_VRAM_SETTINGS["enable_slicing"]:
                cmd.append("--enable-slicing")

        if self._model_path:
            cmd.extend(["--model-path", self._model_path])

        return cmd

    async def _run_command(self, cmd: list[str]) -> tuple[int, str, str]:
        """异步运行命令并返回结果。"""
        logger.info("执行命令: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout,
            )
            return (
                process.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError(
                f"Wan2GP 执行超时（{self._timeout}秒）"
            )


    async def generate(
        self,
        image_path: Path,
        *,
        prompt: str = "",
        negative_prompt: str = "",
        duration: float = 4.0,
        width: int = 720,
        height: int = 1280,
        fps: float = 24.0,
        seed: int | None = None,
        output_path: Path | None = None,
    ) -> VideoGenResult:
        """根据图片生成视频。

        Args:
            image_path: 输入图片路径。
            prompt: 运动/动作提示词。
            negative_prompt: 负面提示词。
            duration: 视频时长（秒）。
            width: 视频宽度。
            height: 视频高度。
            fps: 帧率。
            seed: 随机种子。
            output_path: 输出文件路径。

        Returns:
            VideoGenResult 包含视频路径等信息。
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise ValueError(f"输入图片不存在: {image_path}")

        # 调整分辨率
        adj_width, adj_height = self._adjust_resolution(width, height)
        if adj_width != width or adj_height != height:
            logger.info(
                "分辨率已调整: %dx%d -> %dx%d",
                width, height, adj_width, adj_height,
            )

        # 计算帧数
        frames = self._calculate_frames(duration, fps)
        actual_duration = frames / fps

        # 生成种子
        actual_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

        # 确定输出路径
        if output_path is None:
            temp_dir = Path(tempfile.mkdtemp(prefix="wan2gp_"))
            output_path = temp_dir / f"video_{int(time.time() * 1000)}.mp4"
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        # 构建并执行命令
        cmd = self._build_command(
            image_path,
            output_path,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=adj_width,
            height=adj_height,
            frames=frames,
            fps=fps,
            seed=actual_seed,
        )

        returncode, stdout, stderr = await self._run_command(cmd)

        if returncode != 0:
            error_msg = stderr or stdout or "未知错误"
            raise RuntimeError(f"Wan2GP 执行失败: {error_msg}")

        if not output_path.exists():
            raise RuntimeError(
                f"Wan2GP 执行完成但输出文件不存在: {output_path}"
            )

        logger.info("视频生成成功: %s", output_path)

        return VideoGenResult(
            video_path=output_path,
            duration=actual_duration,
            width=adj_width,
            height=adj_height,
            fps=fps,
            seed=actual_seed,
            metadata={
                "provider": "wan2gp",
                "model": self._model,
                "frames": frames,
                "low_vram_mode": self._is_low_vram_mode(),
                "original_resolution": f"{width}x{height}",
            },
        )

    def list_models(self) -> list[dict]:
        """返回支持的模型列表。"""
        return list(_MODELS)

    def get_vram_requirement(self) -> int:
        """返回显存需求（MB）。"""
        for m in _MODELS:
            if m["id"] == self._model:
                return m["vram"]
        return 6000  # 默认返回 1.3B 模型的需求


# 自注册到 adapter
register_provider("wan2gp", Wan2GPProvider)

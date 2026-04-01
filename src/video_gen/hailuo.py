"""Hailuo Provider：海螺 API 图生视频（预留）。

通过 Hailuo API 实现高质量 I2V，使用异步提交 + 轮询模式。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
import time
from pathlib import Path

import httpx

from src.video_gen.adapter import register_provider
from src.video_gen.base import BaseVideoGenProvider, VideoGenResult

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 5.0
_MAX_POLL_TIME = 600.0

_MODELS: list[dict] = [
    {"id": "hailuo-v1", "name": "Hailuo V1", "description": "标准质量"},
    {"id": "hailuo-v1-hd", "name": "Hailuo V1 HD", "description": "高清质量"},
]


class HailuoProvider(BaseVideoGenProvider):
    """Hailuo 视频生成 Provider（预留）。

    当前版本为占位实现。
    """

    def __init__(self, config: dict | None = None, **kwargs: object) -> None:
        cfg = config or {}
        cfg.update(kwargs)
        self._api_key: str = cfg.get("api_key", "")
        self._api_base: str = cfg.get("api_base", "https://api.hailuo.ai")
        self._model: str = cfg.get("model", "hailuo-v1")
        self._timeout: float = float(cfg.get("timeout", _MAX_POLL_TIME))

    def _get_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    async def _submit_task(
        self,
        client: httpx.AsyncClient,
        image_path: Path,
        prompt: str,
        duration: float,
    ) -> str:
        """提交视频生成任务。"""
        image_data = image_path.read_bytes()
        image_b64 = base64.b64encode(image_data).decode("utf-8")

        body = {
            "model": self._model,
            "image": image_b64,
            "prompt": prompt,
            "duration": duration,
        }

        response = await client.post(
            f"{self._api_base}/v1/videos/generations",
            headers=self._get_headers(),
            json=body,
            timeout=30.0,
        )
        data = response.json()

        if "error" in data:
            raise RuntimeError(f"Hailuo API 错误: {data['error']}")

        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise RuntimeError(f"Hailuo 返回无效响应: {data}")

        return task_id

    async def _poll_task(self, client: httpx.AsyncClient, task_id: str) -> dict:
        """轮询任务状态。"""
        start_time = time.monotonic()

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > self._timeout:
                raise RuntimeError(f"Hailuo 任务超时: {task_id}")

            response = await client.get(
                f"{self._api_base}/v1/videos/generations/{task_id}",
                headers=self._get_headers(),
                timeout=30.0,
            )
            data = response.json()

            status = data.get("status", "")
            if status == "completed":
                return data
            if status == "failed":
                raise RuntimeError(f"Hailuo 任务失败: {data.get('error', '未知错误')}")

            await asyncio.sleep(_POLL_INTERVAL)

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
        """生成视频。"""
        if not self._api_key:
            raise ValueError(
                "Hailuo API 密钥未配置，请在 config.toml 的 "
                "[video_gen.hailuo] 中设置 api_key"
            )

        image_path = Path(image_path)
        if not image_path.exists():
            raise ValueError(f"输入图片不存在: {image_path}")

        if output_path is None:
            temp_dir = Path(tempfile.mkdtemp(prefix="hailuo_"))
            output_path = temp_dir / f"video_{int(time.time() * 1000)}.mp4"
        else:
            output_path = Path(output_path)

        async with httpx.AsyncClient() as client:
            task_id = await self._submit_task(client, image_path, prompt, duration)
            result = await self._poll_task(client, task_id)

            video_url = result.get("video_url")
            if video_url:
                response = await client.get(video_url, timeout=120.0)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(response.content)

        return VideoGenResult(
            video_path=output_path,
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            metadata={"provider": "hailuo", "model": self._model, "task_id": task_id},
        )

    def list_models(self) -> list[dict]:
        return list(_MODELS)

    def get_vram_requirement(self) -> int:
        return 0


register_provider("hailuo", HailuoProvider)

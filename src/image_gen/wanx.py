"""通义万相 WanxProvider：通过 DashScope HTTP API 生成图片。

支持文生图（text-to-image）和角色参考图（Phantom 多图参考）。
使用异步任务提交 + 轮询模式。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
import time
from pathlib import Path

import httpx

from src.image_gen.adapter import register_provider
from src.image_gen.base import BaseImageProvider, ImageGenResult

logger = logging.getLogger(__name__)

# DashScope API 端点（北京区域）
_API_BASE = "https://dashscope.aliyuncs.com/api/v1"
_SUBMIT_URL = f"{_API_BASE}/services/aigc/text2image/image-synthesis"
_TASK_URL = f"{_API_BASE}/tasks"

# 轮询配置
_POLL_INTERVAL = 5.0  # 秒
_MAX_POLL_TIME = 300.0  # 最大等待 5 分钟

# 支持的动漫/插画风格
_STYLES: list[dict] = [
    {"id": "anime", "name": "动漫风格", "description": "日系动漫画风，适合短剧场景"},
    {"id": "illustration", "name": "插画风格", "description": "精致插画风格，色彩丰富"},
    {"id": "watercolor", "name": "水彩风格", "description": "水彩画风，柔和淡雅"},
    {"id": "flat", "name": "扁平插画", "description": "扁平化设计风格，简洁明快"},
    {"id": "comic", "name": "漫画风格", "description": "漫画分镜风格，线条感强"},
    {"id": "realistic", "name": "写实风格", "description": "接近真实照片的画风"},
]

# 风格 → 提示词前缀映射
_STYLE_PROMPTS: dict[str, str] = {
    "anime": "anime style, Japanese animation, vibrant colors, ",
    "illustration": "digital illustration, detailed artwork, rich colors, ",
    "watercolor": "watercolor painting style, soft colors, artistic, ",
    "flat": "flat illustration style, minimalist, clean design, ",
    "comic": "comic book style, bold lines, dynamic composition, ",
    "realistic": "photorealistic, highly detailed, ",
}


class WanxProvider(BaseImageProvider):
    """通义万相出图 Provider，通过 DashScope HTTP API 调用。

    使用异步任务提交 + 轮询模式：
    1. POST 提交出图任务，获取 task_id
    2. GET 轮询任务状态，直到 SUCCEEDED 或 FAILED
    3. 下载生成的图片到本地

    支持角色参考图（ref_images）：将参考图编码为 base64 注入提示词，
    利用 Phantom 多图参考实现角色一致性。
    """

    def __init__(self, config: dict | None = None, **kwargs: object) -> None:
        """初始化 WanxProvider。

        Args:
            config: 配置字典，包含 api_key, model, default_style 等。
                    也可通过 kwargs 传入。
        """
        cfg = config or {}
        cfg.update(kwargs)
        self._api_key: str = cfg.get("api_key", "")
        self._model: str = cfg.get("model", "wanx2.0-t2i-turbo")
        self._default_style: str = cfg.get("default_style", "anime")
        self._api_base: str = cfg.get("api_base", _API_BASE)
        self._submit_url: str = f"{self._api_base}/services/aigc/text2image/image-synthesis"
        self._task_url: str = f"{self._api_base}/tasks"
        self._timeout: float = float(cfg.get("timeout", _MAX_POLL_TIME))
        self._poll_interval: float = float(cfg.get("poll_interval", _POLL_INTERVAL))

    def _get_headers(self) -> dict[str, str]:
        """构建请求头。"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-DashScope-Async": "enable",
        }

    def _build_prompt(self, prompt: str, style: str, ref_images: list[Path] | None) -> str:
        """构建最终提示词，注入风格前缀和角色参考描述。

        Args:
            prompt: 用户原始提示词。
            style: 风格标签。
            ref_images: 角色参考图路径列表。

        Returns:
            增强后的提示词。
        """
        parts: list[str] = []

        # 风格前缀
        style_key = style or self._default_style
        if style_key in _STYLE_PROMPTS:
            parts.append(_STYLE_PROMPTS[style_key])

        # 角色参考描述（提示模型保持角色一致性）
        if ref_images:
            parts.append(
                "maintain character consistency with reference images, "
                "same character appearance and features, "
            )

        parts.append(prompt)
        return "".join(parts)

    def _encode_ref_images(self, ref_images: list[Path]) -> list[str]:
        """将参考图编码为 base64 字符串。

        Args:
            ref_images: 参考图路径列表。

        Returns:
            base64 编码字符串列表。
        """
        encoded: list[str] = []
        for img_path in ref_images:
            path = Path(img_path)
            if not path.exists():
                logger.warning("参考图不存在，跳过: %s", path)
                continue
            data = path.read_bytes()
            encoded.append(base64.b64encode(data).decode("utf-8"))
        return encoded

    def _build_request_body(
        self,
        prompt: str,
        *,
        negative_prompt: str = "",
        width: int = 720,
        height: int = 1280,
        seed: int | None = None,
        ref_images: list[Path] | None = None,
    ) -> dict:
        """构建 DashScope API 请求体。

        Args:
            prompt: 增强后的提示词。
            negative_prompt: 负面提示词。
            width: 图片宽度。
            height: 图片高度。
            seed: 随机种子。
            ref_images: 角色参考图路径列表。

        Returns:
            请求体字典。
        """
        body: dict = {
            "model": self._model,
            "input": {
                "prompt": prompt,
            },
            "parameters": {
                "size": f"{width}*{height}",
                "n": 1,
            },
        }

        if negative_prompt:
            body["input"]["negative_prompt"] = negative_prompt

        if seed is not None:
            body["parameters"]["seed"] = seed

        # 角色参考图：编码为 base64 注入 ref_image 字段
        if ref_images:
            encoded = self._encode_ref_images(ref_images)
            if encoded:
                body["input"]["ref_image"] = encoded

        return body

    async def _submit_task(self, client: httpx.AsyncClient, body: dict) -> str:
        """提交出图任务，返回 task_id。

        Args:
            client: httpx 异步客户端。
            body: 请求体。

        Returns:
            任务 ID。

        Raises:
            PermissionError: API 密钥无效。
            RuntimeError: 提交失败。
        """
        try:
            response = await client.post(
                self._submit_url,
                headers=self._get_headers(),
                json=body,
                timeout=30.0,
            )
        except httpx.ConnectError as e:
            raise RuntimeError(f"DashScope 服务不可用: {e}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError(f"DashScope 请求超时: {e}") from e

        data = response.json()

        # 检查错误
        if "code" in data:
            code = data["code"]
            message = data.get("message", "")
            if code == "InvalidApiKey":
                raise PermissionError(f"API 密钥无效: {message}")
            raise RuntimeError(f"DashScope 提交失败 [{code}]: {message}")

        task_id = data.get("output", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"DashScope 返回无效响应，缺少 task_id: {data}")

        logger.info("出图任务已提交，task_id: %s", task_id)
        return task_id

    async def _poll_task(self, client: httpx.AsyncClient, task_id: str) -> dict:
        """轮询任务状态直到完成。

        Args:
            client: httpx 异步客户端。
            task_id: 任务 ID。

        Returns:
            任务结果字典。

        Raises:
            RuntimeError: 任务失败或超时。
        """
        url = f"{self._task_url}/{task_id}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }

        start_time = time.monotonic()

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > self._timeout:
                raise RuntimeError(
                    f"出图任务超时（{self._timeout}秒），task_id: {task_id}"
                )

            try:
                response = await client.get(url, headers=headers, timeout=30.0)
                data = response.json()
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("轮询请求失败，将重试: %s", e)
                await asyncio.sleep(self._poll_interval)
                continue

            output = data.get("output", {})
            status = output.get("task_status", "UNKNOWN")

            if status == "SUCCEEDED":
                logger.info("出图任务完成，task_id: %s", task_id)
                return data

            if status == "FAILED":
                code = output.get("code", "Unknown")
                message = output.get("message", "未知错误")
                raise RuntimeError(
                    f"出图任务失败 [{code}]: {message}，task_id: {task_id}"
                )

            if status in ("CANCELED", "UNKNOWN"):
                raise RuntimeError(
                    f"出图任务异常状态: {status}，task_id: {task_id}"
                )

            # PENDING 或 RUNNING，继续等待
            logger.debug(
                "出图任务状态: %s，已等待 %.1f 秒，task_id: %s",
                status,
                elapsed,
                task_id,
            )
            await asyncio.sleep(self._poll_interval)

    async def _download_image(
        self,
        client: httpx.AsyncClient,
        image_url: str,
        output_path: Path,
    ) -> Path:
        """下载生成的图片到本地。

        Args:
            client: httpx 异步客户端。
            image_url: 图片 URL。
            output_path: 输出文件路径。

        Returns:
            保存的文件路径。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        response = await client.get(image_url, timeout=60.0)
        response.raise_for_status()

        output_path.write_bytes(response.content)
        logger.info("图片已保存: %s", output_path)
        return output_path

    async def generate(
        self,
        prompt: str,
        *,
        style: str = "",
        ref_images: list[Path] | None = None,
        negative_prompt: str = "",
        width: int = 720,
        height: int = 1280,
        seed: int | None = None,
        output_path: Path | None = None,
    ) -> ImageGenResult:
        """根据提示词生成图片。

        完整流程：构建提示词 → 提交任务 → 轮询结果 → 下载图片。

        Args:
            prompt: 正向提示词。
            style: 画风/风格标签（如 "anime", "illustration"）。
            ref_images: 角色参考图路径列表（用于 Phantom 多图参考）。
            negative_prompt: 负面提示词。
            width: 图片宽度（像素）。
            height: 图片高度（像素）。
            seed: 随机种子，None 表示随机。
            output_path: 输出文件路径，None 则自动生成临时文件。

        Returns:
            ImageGenResult 包含图片路径、提示词、种子和元数据。

        Raises:
            ValueError: 提示词为空或 API 密钥未配置。
            PermissionError: API 密钥无效。
            RuntimeError: 出图失败。
        """
        if not prompt or not prompt.strip():
            raise ValueError("提示词不能为空")

        if not self._api_key:
            raise ValueError(
                "通义万相 API 密钥未配置，请在 config.toml 的 "
                "[image_gen.wanx] 中设置 api_key"
            )

        # 构建增强提示词
        final_prompt = self._build_prompt(prompt, style, ref_images)

        # 构建请求体
        body = self._build_request_body(
            final_prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=seed,
            ref_images=ref_images,
        )

        # 确定输出路径
        if output_path is None:
            temp_dir = Path(tempfile.gettempdir()) / "wanx_output"
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_path = temp_dir / f"wanx_{int(time.time() * 1000)}.png"
        else:
            output_path = Path(output_path)

        async with httpx.AsyncClient() as client:
            # 1. 提交任务
            task_id = await self._submit_task(client, body)

            # 2. 轮询结果
            result_data = await self._poll_task(client, task_id)

            # 3. 提取图片 URL 并下载
            output = result_data.get("output", {})
            results = output.get("results", [])

            image_url = None
            actual_prompt = final_prompt
            for r in results:
                if "url" in r:
                    image_url = r["url"]
                    actual_prompt = r.get("actual_prompt", final_prompt)
                    break

            if not image_url:
                raise RuntimeError(
                    f"出图任务成功但未返回图片 URL，task_id: {task_id}"
                )

            await self._download_image(client, image_url, output_path)

        # 提取种子信息（如果有）
        result_seed = seed  # DashScope 不一定返回种子

        return ImageGenResult(
            image_path=output_path,
            prompt=actual_prompt,
            seed=result_seed,
            metadata={
                "provider": "wanx",
                "model": self._model,
                "style": style or self._default_style,
                "task_id": task_id,
                "has_ref_images": bool(ref_images),
                "ref_image_count": len(ref_images) if ref_images else 0,
                "width": width,
                "height": height,
            },
        )

    def list_styles(self) -> list[dict]:
        """返回通义万相支持的风格列表。

        Returns:
            风格列表，每项包含 id, name, description 字段。
        """
        return list(_STYLES)


# 自注册到 adapter
register_provider("wanx", WanxProvider)

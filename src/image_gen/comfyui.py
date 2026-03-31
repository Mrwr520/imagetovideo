"""ComfyUI Provider：通过 ComfyUI HTTP API 生成图片。

支持 workflow JSON 模板加载、参数注入、异步轮询出图结果。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import tempfile
import time
import uuid
from pathlib import Path

import httpx

from src.image_gen.adapter import register_provider
from src.image_gen.base import BaseImageProvider, ImageGenResult

logger = logging.getLogger(__name__)

# 轮询配置
_POLL_INTERVAL = 1.0  # 秒
_MAX_POLL_TIME = 300.0  # 最大等待 5 分钟

# 默认 workflow 模板（简单文生图）
_DEFAULT_WORKFLOW = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "cfg": 7.5,
            "denoise": 1,
            "latent_image": ["5", 0],
            "model": ["4", 0],
            "negative": ["7", 0],
            "positive": ["6", 0],
            "sampler_name": "dpmpp_2m_sde",
            "scheduler": "karras",
            "seed": 0,
            "steps": 40,
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "Illustrious-XL-v0.1.safetensors"},
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"batch_size": 1, "height": 1216, "width": 832},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["4", 1], "text": ""},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["4", 1], "text": ""},
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
    },
}

# 支持的风格
_STYLES: list[dict] = [
    {"id": "anime", "name": "动漫风格", "description": "日系动漫画风"},
    {"id": "realistic", "name": "写实风格", "description": "接近真实照片"},
    {"id": "illustration", "name": "插画风格", "description": "精致插画风格"},
    {"id": "watercolor", "name": "水彩风格", "description": "水彩画风"},
]

# 风格 → 提示词前缀（Illustrious XL 用 Danbooru 标签，不需要自然语言前缀）
_STYLE_PROMPTS: dict[str, str] = {
    "anime": "",
    "realistic": "photorealistic, highly_detailed, 8k, ",
    "illustration": "digital_illustration, detailed_artwork, ",
    "watercolor": "watercolor_\\(medium\\), soft_colors, artistic, ",
}

# 风格 → 负面提示词
_STYLE_NEGATIVE: dict[str, str] = {
    "anime": "",
    "realistic": "cartoon, anime, drawing, ",
    "illustration": "photo, 3d, realistic, ",
    "watercolor": "photo, digital, sharp_lines, ",
}


class ComfyUIProvider(BaseImageProvider):
    """ComfyUI 出图 Provider，通过 HTTP API 调用本地 ComfyUI 服务。

    使用 workflow JSON 模板 + 参数注入 + 异步轮询模式。
    """

    def __init__(self, config: dict | None = None, **kwargs: object) -> None:
        cfg = config or {}
        cfg.update(kwargs)
        self._api_base: str = cfg.get("api_base", "http://localhost:8188")
        self._workflow_file: str = cfg.get("workflow", "")
        self._workflow_dir: Path = Path(cfg.get("workflow_dir", "workflows"))
        self._default_style: str = cfg.get("default_style", "anime")
        self._timeout: float = float(cfg.get("timeout", _MAX_POLL_TIME))
        self._poll_interval: float = float(cfg.get("poll_interval", _POLL_INTERVAL))
        self._checkpoint: str = cfg.get("checkpoint", "sd_xl_base_1.0.safetensors")

    def _get_prompt_url(self) -> str:
        return f"{self._api_base}/prompt"

    def _get_history_url(self, prompt_id: str) -> str:
        return f"{self._api_base}/history/{prompt_id}"

    def _get_view_url(self, filename: str, subfolder: str, folder_type: str) -> str:
        return f"{self._api_base}/view?filename={filename}&subfolder={subfolder}&type={folder_type}"

    def load_workflow(self, workflow_name: str | None = None) -> dict:
        """加载 workflow JSON 模板。

        Args:
            workflow_name: workflow 文件名，None 则使用配置或默认模板。

        Returns:
            workflow 字典。
        """
        name = workflow_name or self._workflow_file
        if not name:
            logger.info("使用内置默认 workflow 模板")
            return json.loads(json.dumps(_DEFAULT_WORKFLOW))

        path = self._workflow_dir / name
        if not path.exists():
            logger.warning("workflow 文件不存在: %s，使用默认模板", path)
            return json.loads(json.dumps(_DEFAULT_WORKFLOW))

        with open(path, encoding="utf-8") as f:
            workflow = json.load(f)
        logger.info("已加载 workflow: %s", path)
        return workflow


    def inject_params(
        self,
        workflow: dict,
        *,
        prompt: str = "",
        negative_prompt: str = "",
        width: int = 720,
        height: int = 1280,
        seed: int | None = None,
        style: str = "",
    ) -> dict:
        """向 workflow 模板注入参数。

        自动识别常见节点类型并注入对应参数：
        - KSampler: seed, steps
        - EmptyLatentImage: width, height
        - CLIPTextEncode: text (正向/负面提示词)
        - CheckpointLoaderSimple: ckpt_name

        Args:
            workflow: 原始 workflow 字典。
            prompt: 正向提示词。
            negative_prompt: 负面提示词。
            width: 图片宽度。
            height: 图片高度。
            seed: 随机种子，None 则随机生成。
            style: 风格标签。

        Returns:
            注入参数后的 workflow 字典。
        """
        wf = json.loads(json.dumps(workflow))  # 深拷贝

        # 生成种子
        actual_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

        # 构建最终提示词
        style_key = style or self._default_style
        style_prefix = _STYLE_PROMPTS.get(style_key, "")
        style_negative = _STYLE_NEGATIVE.get(style_key, "")

        # 清理提示词中的无用元数据
        import re
        cleaned_prompt = prompt
        cleaned_prompt = re.sub(r'\bstyle:\s*\w+,?\s*', '', cleaned_prompt)
        cleaned_prompt = re.sub(r'\bno specific appearance,?\s*', '', cleaned_prompt)
        cleaned_prompt = re.sub(r'\bnarrator,?\s*', '', cleaned_prompt, flags=re.IGNORECASE)
        cleaned_prompt = re.sub(r',\s*,', ',', cleaned_prompt)
        cleaned_prompt = cleaned_prompt.strip().strip(',').strip()

        final_prompt = style_prefix + cleaned_prompt + ", masterpiece, best quality, highres, very_aesthetic, absurdres"
        final_negative = style_negative + (negative_prompt or "low quality, blurry, bad anatomy, worst quality, lowres, text, watermark, extra_digits, fewer_digits, bad_hands")

        # 遍历节点注入参数
        positive_node_id = None
        negative_node_id = None

        for node_id, node in wf.items():
            class_type = node.get("class_type", "")
            inputs = node.get("inputs", {})

            if class_type == "KSampler":
                inputs["seed"] = actual_seed
                # 尝试识别正负提示词节点
                if "positive" in inputs and isinstance(inputs["positive"], list):
                    positive_node_id = inputs["positive"][0]
                if "negative" in inputs and isinstance(inputs["negative"], list):
                    negative_node_id = inputs["negative"][0]

            elif class_type == "EmptyLatentImage":
                inputs["width"] = width
                inputs["height"] = height

            elif class_type == "CheckpointLoaderSimple":
                if self._checkpoint:
                    inputs["ckpt_name"] = self._checkpoint
                    logger.info("注入 checkpoint: %s", self._checkpoint)

        # 注入提示词到对应节点
        if positive_node_id and positive_node_id in wf:
            wf[positive_node_id]["inputs"]["text"] = final_prompt
        if negative_node_id and negative_node_id in wf:
            wf[negative_node_id]["inputs"]["text"] = final_negative

        # 如果没找到通过 KSampler 引用的节点，尝试直接查找 CLIPTextEncode
        if not positive_node_id:
            for node_id, node in wf.items():
                if node.get("class_type") == "CLIPTextEncode":
                    inputs = node.get("inputs", {})
                    if "text" in inputs:
                        # 第一个设为正向，第二个设为负向
                        if not positive_node_id:
                            inputs["text"] = final_prompt
                            positive_node_id = node_id
                        elif not negative_node_id:
                            inputs["text"] = final_negative
                            negative_node_id = node_id

        return wf

    async def submit_workflow(self, workflow: dict) -> str:
        """提交 workflow 到 ComfyUI，返回 prompt_id。

        Args:
            workflow: 完整的 workflow 字典。

        Returns:
            ComfyUI 返回的 prompt_id。

        Raises:
            RuntimeError: 提交失败。
        """
        client_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": client_id}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self._get_prompt_url(),
                    json=payload,
                    timeout=30.0,
                )
                data = response.json()
            except httpx.ConnectError as e:
                raise RuntimeError(
                    f"无法连接 ComfyUI 服务 ({self._api_base})，请确保 ComfyUI 已启动: {e}"
                ) from e
            except httpx.TimeoutException as e:
                raise RuntimeError(f"ComfyUI 请求超时: {e}") from e
            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"ComfyUI 返回错误: {e.response.text}") from e

        prompt_id = data.get("prompt_id")
        if not prompt_id:
            # 检查各种错误格式
            error = data.get("error", {})
            node_errors = data.get("node_errors", {})
            error_type = error.get("type", "") if isinstance(error, dict) else str(error)
            
            details = []
            if error:
                details.append(f"error: {error}")
            if node_errors:
                details.append(f"node_errors: {node_errors}")
            
            raise RuntimeError(
                f"ComfyUI workflow 提交失败: {' | '.join(details) if details else data}"
            )

        logger.info("ComfyUI 任务已提交，prompt_id: %s", prompt_id)
        return prompt_id

    async def poll_result(self, prompt_id: str) -> dict:
        """轮询 ComfyUI 任务状态直到完成。

        Args:
            prompt_id: 任务 ID。

        Returns:
            任务结果字典，包含输出图片信息。

        Raises:
            RuntimeError: 任务失败或超时。
        """
        start_time = time.monotonic()

        async with httpx.AsyncClient() as client:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed > self._timeout:
                    raise RuntimeError(
                        f"ComfyUI 任务超时（{self._timeout}秒），prompt_id: {prompt_id}"
                    )

                try:
                    response = await client.get(
                        self._get_history_url(prompt_id),
                        timeout=30.0,
                    )
                    data = response.json()
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    logger.warning("轮询请求失败，将重试: %s", e)
                    await asyncio.sleep(self._poll_interval)
                    continue

                if prompt_id in data:
                    history = data[prompt_id]
                    status = history.get("status", {})

                    if status.get("completed"):
                        logger.info("ComfyUI 任务完成，prompt_id: %s", prompt_id)
                        return history

                    if status.get("status_str") == "error":
                        messages = status.get("messages", [])
                        error_msg = "; ".join(str(m) for m in messages) if messages else "未知错误"
                        raise RuntimeError(
                            f"ComfyUI 任务失败: {error_msg}，prompt_id: {prompt_id}"
                        )

                logger.debug(
                    "ComfyUI 任务进行中，已等待 %.1f 秒，prompt_id: %s",
                    elapsed,
                    prompt_id,
                )
                await asyncio.sleep(self._poll_interval)


    async def _download_image(
        self,
        filename: str,
        subfolder: str,
        output_path: Path,
    ) -> Path:
        """从 ComfyUI 下载生成的图片。

        Args:
            filename: 图片文件名。
            subfolder: 子文件夹。
            output_path: 输出文件路径。

        Returns:
            保存的文件路径。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        url = self._get_view_url(filename, subfolder, "output")

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=60.0)
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

        完整流程：加载 workflow → 注入参数 → 提交任务 → 轮询结果 → 下载图片。

        Args:
            prompt: 正向提示词。
            style: 画风/风格标签。
            ref_images: 角色参考图路径列表（当前版本暂不支持）。
            negative_prompt: 负面提示词。
            width: 图片宽度。
            height: 图片高度。
            seed: 随机种子，None 则随机。
            output_path: 输出文件路径，None 则自动生成。

        Returns:
            ImageGenResult 包含图片路径、提示词、种子和元数据。

        Raises:
            ValueError: 提示词为空。
            RuntimeError: 出图失败。
        """
        if not prompt or not prompt.strip():
            raise ValueError("提示词不能为空")

        if ref_images:
            logger.warning(
                "ComfyUI Provider 当前版本暂不支持角色参考图，将忽略 ref_images 参数"
            )

        # 1. 加载 workflow
        workflow = self.load_workflow()

        # 2. 注入参数
        actual_seed = seed if seed is not None else random.randint(0, 2**32 - 1)
        workflow = self.inject_params(
            workflow,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=actual_seed,
            style=style,
        )

        # 3. 提交任务
        prompt_id = await self.submit_workflow(workflow)

        # 4. 轮询结果
        history = await self.poll_result(prompt_id)

        # 5. 提取输出图片信息
        outputs = history.get("outputs", {})
        image_info = None

        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                image_info = images[0]
                break

        if not image_info:
            raise RuntimeError(
                f"ComfyUI 任务完成但未找到输出图片，prompt_id: {prompt_id}"
            )

        # 6. 下载图片
        if output_path is None:
            temp_dir = Path(tempfile.gettempdir()) / "comfyui_output"
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_path = temp_dir / f"comfyui_{int(time.time() * 1000)}.png"
        else:
            output_path = Path(output_path)

        await self._download_image(
            image_info["filename"],
            image_info.get("subfolder", ""),
            output_path,
        )

        # 构建最终提示词（用于返回）
        style_key = style or self._default_style
        style_prefix = _STYLE_PROMPTS.get(style_key, "")
        final_prompt = style_prefix + prompt

        return ImageGenResult(
            image_path=output_path,
            prompt=final_prompt,
            seed=actual_seed,
            metadata={
                "provider": "comfyui",
                "prompt_id": prompt_id,
                "style": style_key,
                "checkpoint": self._checkpoint,
                "width": width,
                "height": height,
                "workflow": self._workflow_file or "default",
            },
        )

    def list_styles(self) -> list[dict]:
        """返回 ComfyUI 支持的风格列表。"""
        return list(_STYLES)


# 自注册到 adapter
register_provider("comfyui", ComfyUIProvider)

"""出图 Pipeline：批量出图 + 单张重试 + 缓存。

负责将剧本中的 image_prompt 批量生成图片，支持：
- 角色参考图自动注入
- 单张重试
- 结果缓存（避免重复生成）
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.character.models import Character
from src.image_gen.adapter import ImageGenAdapter
from src.image_gen.base import ImageGenResult
from src.script.models import Script

logger = logging.getLogger(__name__)


@dataclass
class SceneImageResult:
    """单个场景的出图结果。"""
    scene_index: int
    image_path: Path | None = None
    prompt: str = ""
    success: bool = False
    error: str = ""
    from_cache: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class ImagePipelineResult:
    """批量出图结果。"""
    results: list[SceneImageResult] = field(default_factory=list)
    total: int = 0
    success_count: int = 0
    failed_count: int = 0
    cached_count: int = 0

    @property
    def all_success(self) -> bool:
        return self.failed_count == 0

    def get_image_paths(self) -> list[Path | None]:
        """返回所有场景的图片路径列表。"""
        return [r.image_path for r in self.results]


class ImageGenPipeline:
    """出图 Pipeline，批量生成剧本场景图片。"""

    def __init__(
        self,
        adapter: ImageGenAdapter,
        output_dir: Path | str = "./output/images",
        cache_dir: Path | str = "./cache/images",
    ) -> None:
        """初始化 Pipeline。

        Args:
            adapter: ImageGenAdapter 实例。
            output_dir: 输出图片目录。
            cache_dir: 缓存目录。
        """
        self._adapter = adapter
        self._output_dir = Path(output_dir)
        self._cache_dir = Path(cache_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _compute_cache_key(
        self,
        prompt: str,
        style: str,
        width: int,
        height: int,
        ref_image_paths: list[Path] | None,
    ) -> str:
        """计算缓存 key（基于提示词和参数的 hash）。"""
        data = {
            "prompt": prompt,
            "style": style,
            "width": width,
            "height": height,
            "ref_images": [str(p) for p in (ref_image_paths or [])],
        }
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径。"""
        return self._cache_dir / f"{cache_key}.png"

    def _get_cache_meta_path(self, cache_key: str) -> Path:
        """获取缓存元数据路径。"""
        return self._cache_dir / f"{cache_key}.json"

    def _check_cache(self, cache_key: str) -> tuple[bool, Path | None, dict]:
        """检查缓存是否存在。

        Returns:
            (是否命中, 图片路径, 元数据)
        """
        cache_path = self._get_cache_path(cache_key)
        meta_path = self._get_cache_meta_path(cache_key)

        if cache_path.exists() and meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                return True, cache_path, meta
            except Exception as e:
                logger.warning("读取缓存元数据失败: %s", e)

        return False, None, {}

    def _save_cache(
        self,
        cache_key: str,
        result: ImageGenResult,
    ) -> Path:
        """保存结果到缓存。"""
        cache_path = self._get_cache_path(cache_key)
        meta_path = self._get_cache_meta_path(cache_key)

        # 复制图片到缓存目录
        if result.image_path != cache_path:
            cache_path.write_bytes(result.image_path.read_bytes())

        # 保存元数据
        meta = {
            "prompt": result.prompt,
            "seed": result.seed,
            "metadata": result.metadata,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return cache_path


    def _get_character_ref_images(
        self,
        characters: list[Character],
        characters_dir: Path,
    ) -> list[Path]:
        """从角色列表中提取所有参考图路径。

        Args:
            characters: 角色列表。
            characters_dir: 角色数据根目录。

        Returns:
            参考图路径列表。
        """
        ref_images: list[Path] = []

        for char in characters:
            if not char.ref_images:
                continue

            char_dir = characters_dir / char.name
            for img_name in char.ref_images:
                img_path = char_dir / img_name
                if img_path.exists():
                    ref_images.append(img_path)
                else:
                    logger.warning(
                        "角色 %s 的参考图不存在: %s",
                        char.name,
                        img_path,
                    )

        return ref_images

    async def generate_single(
        self,
        prompt: str,
        scene_index: int,
        *,
        style: str = "anime",
        ref_images: list[Path] | None = None,
        negative_prompt: str = "",
        width: int = 720,
        height: int = 1280,
        use_cache: bool = True,
        provider_name: str | None = None,
    ) -> SceneImageResult:
        """生成单张场景图片。

        Args:
            prompt: 出图提示词。
            scene_index: 场景索引。
            style: 风格标签。
            ref_images: 角色参考图路径列表。
            negative_prompt: 负面提示词。
            width: 图片宽度。
            height: 图片高度。
            use_cache: 是否使用缓存。
            provider_name: 指定 provider。

        Returns:
            SceneImageResult 出图结果。
        """
        result = SceneImageResult(scene_index=scene_index, prompt=prompt)

        # 检查缓存
        cache_key = self._compute_cache_key(prompt, style, width, height, ref_images)
        if use_cache:
            hit, cached_path, meta = self._check_cache(cache_key)
            if hit and cached_path:
                logger.info("场景 %d 命中缓存: %s", scene_index, cache_key)
                result.image_path = cached_path
                result.success = True
                result.from_cache = True
                result.metadata = meta.get("metadata", {})
                return result

        # 生成图片
        try:
            output_path = self._output_dir / f"scene_{scene_index:03d}.png"
            gen_result = await self._adapter.generate(
                prompt,
                provider_name=provider_name,
                style=style,
                ref_images=ref_images,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                output_path=output_path,
            )

            result.image_path = gen_result.image_path
            result.success = True
            result.metadata = gen_result.metadata

            # 保存缓存
            if use_cache:
                self._save_cache(cache_key, gen_result)

            logger.info("场景 %d 出图成功: %s", scene_index, result.image_path)

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.error("场景 %d 出图失败: %s", scene_index, e)

        return result

    async def generate_for_script(
        self,
        script: Script,
        characters: list[Character] | None = None,
        characters_dir: Path | str = "./characters",
        *,
        style: str | None = None,
        negative_prompt: str = "",
        width: int = 720,
        height: int = 1280,
        use_cache: bool = True,
        provider_name: str | None = None,
    ) -> ImagePipelineResult:
        """为整个剧本批量生成图片。

        Args:
            script: 剧本对象。
            characters: 角色列表（用于提取参考图）。
            characters_dir: 角色数据根目录。
            style: 风格标签，None 则使用剧本的 style。
            negative_prompt: 负面提示词。
            width: 图片宽度。
            height: 图片高度。
            use_cache: 是否使用缓存。
            provider_name: 指定 provider。

        Returns:
            ImagePipelineResult 批量出图结果。
        """
        pipeline_result = ImagePipelineResult(total=len(script.scenes))

        # 提取角色参考图
        ref_images: list[Path] = []
        if characters:
            ref_images = self._get_character_ref_images(
                characters,
                Path(characters_dir),
            )
            if ref_images:
                logger.info("已加载 %d 张角色参考图", len(ref_images))

        # 确定风格
        actual_style = style or script.style or "anime"

        # 逐场景生成
        for i, scene in enumerate(script.scenes):
            prompt = scene.image_prompt or scene.image_desc
            if not prompt:
                logger.warning("场景 %d 没有出图提示词，跳过", i)
                result = SceneImageResult(
                    scene_index=i,
                    success=False,
                    error="没有出图提示词",
                )
                pipeline_result.results.append(result)
                pipeline_result.failed_count += 1
                continue

            result = await self.generate_single(
                prompt,
                i,
                style=actual_style,
                ref_images=ref_images if ref_images else None,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                use_cache=use_cache,
                provider_name=provider_name,
            )

            pipeline_result.results.append(result)
            if result.success:
                pipeline_result.success_count += 1
                if result.from_cache:
                    pipeline_result.cached_count += 1
            else:
                pipeline_result.failed_count += 1

        logger.info(
            "批量出图完成: 总计 %d，成功 %d，失败 %d，缓存命中 %d",
            pipeline_result.total,
            pipeline_result.success_count,
            pipeline_result.failed_count,
            pipeline_result.cached_count,
        )

        return pipeline_result

    async def retry_scene(
        self,
        scene_index: int,
        prompt: str,
        *,
        style: str = "anime",
        ref_images: list[Path] | None = None,
        negative_prompt: str = "",
        width: int = 720,
        height: int = 1280,
        provider_name: str | None = None,
    ) -> SceneImageResult:
        """重试单个场景的出图（不使用缓存）。

        Args:
            scene_index: 场景索引。
            prompt: 出图提示词。
            style: 风格标签。
            ref_images: 角色参考图路径列表。
            negative_prompt: 负面提示词。
            width: 图片宽度。
            height: 图片高度。
            provider_name: 指定 provider。

        Returns:
            SceneImageResult 出图结果。
        """
        logger.info("重试场景 %d 出图", scene_index)
        return await self.generate_single(
            prompt,
            scene_index,
            style=style,
            ref_images=ref_images,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            use_cache=False,  # 重试不使用缓存
            provider_name=provider_name,
        )

    def clear_cache(self) -> int:
        """清空缓存目录。

        Returns:
            删除的文件数量。
        """
        count = 0
        for f in self._cache_dir.iterdir():
            if f.is_file():
                f.unlink()
                count += 1
        logger.info("已清空缓存，删除 %d 个文件", count)
        return count

"""Pixabay 素材获取：图片 + BGM，免费 API。

API 文档：https://pixabay.com/api/docs/
图片搜索：https://pixabay.com/api/
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

IMAGE_API = "https://pixabay.com/api/"

# 情感 → BGM 搜索关键词映射
EMOTION_BGM_MAP = {
    "sad": "sad piano emotional",
    "happy": "happy upbeat cheerful",
    "angry": "epic dramatic intense",
    "tender": "gentle emotional soft",
    "surprise": "mysterious suspense",
    "fear": "dark tension horror",
    "neutral": "calm ambient background",
}


@dataclass
class ImageInfo:
    """Pixabay 图片信息。"""
    id: int
    page_url: str
    width: int
    height: int
    download_url: str  # 直接下载链接
    preview_url: str  # 预览图
    tags: str


class PixabayClient:
    """Pixabay API 客户端，获取动漫风格图片素材。"""

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def search_images(
        self,
        query: str,
        per_page: int = 5,
        image_type: str = "illustration",
    ) -> list[ImageInfo]:
        """搜索图片素材。

        Args:
            query: 搜索关键词（英文）
            per_page: 返回数量
            image_type: 图片类型 (all, photo, illustration, vector)
        """
        params = {
            "key": self._api_key,
            "q": query,
            "image_type": image_type,
            "per_page": per_page,
            "safesearch": "true",
            "order": "popular",
            "min_width": 640,
            "min_height": 480,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(IMAGE_API, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("Pixabay 图片搜索失败: %s", e)
            return []

        return self._parse_image_hits(data)

    def _parse_image_hits(self, data: dict) -> list[ImageInfo]:
        """解析图片搜索结果。"""
        results = []
        for hit in data.get("hits", []):
            # 优先用 largeImageURL（高清大图），回退到 webformatURL
            download_url = hit.get("largeImageURL", "")
            if not download_url:
                download_url = hit.get("webformatURL", "")
            if not download_url:
                continue

            results.append(ImageInfo(
                id=hit.get("id", 0),
                page_url=hit.get("pageURL", ""),
                width=hit.get("imageWidth", hit.get("webformatWidth", 0)),
                height=hit.get("imageHeight", hit.get("webformatHeight", 0)),
                download_url=download_url,
                preview_url=hit.get("previewURL", ""),
                tags=hit.get("tags", ""),
            ))

        return results

    async def search_images_fallback(
        self,
        query: str,
        per_page: int = 5,
    ) -> list[ImageInfo]:
        """搜索图片，多级回退确保有结果。

        1. 先搜 illustration 类型
        2. 没结果 → 搜 all 类型
        3. 还没结果 → 简化关键词只保留前 2 个词
        4. 还没结果 → 通用关键词 "anime illustration"
        """
        # 第一级：illustration
        results = await self.search_images(query, per_page, "illustration")
        if results:
            return results

        # 第二级：all 类型
        results = await self.search_images(query, per_page, "all")
        if results:
            return results

        # 第三级：简化关键词
        simplified = " ".join(query.split()[:2])
        if simplified != query:
            results = await self.search_images(simplified, per_page, "all")
            if results:
                return results

        # 第四级：通用关键词
        results = await self.search_images("anime illustration", per_page, "all")
        return results

    async def download_image(self, url: str, output_dir: Path, filename: str = "") -> Path:
        """下载图片文件到本地。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        if not filename:
            filename = f"pixabay_{hash(url) & 0xFFFFFFFF}.jpg"
        output_path = output_dir / filename

        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                output_path.write_bytes(resp.content)
        except Exception as e:
            raise RuntimeError(f"Pixabay 图片下载失败: {e}") from e

        return output_path

    async def search_and_download_images(
        self,
        keywords: list[str],
        output_dir: Path,
    ) -> list[Path]:
        """批量搜索并下载图片，每个关键词下载 1 张最佳匹配。

        Args:
            keywords: 每个场景的搜索关键词列表
            output_dir: 下载目录

        Returns:
            下载的图片文件路径列表（与 keywords 一一对应）
        """
        paths = []
        used_ids = set()

        for i, kw in enumerate(keywords):
            results = await self.search_images_fallback(kw, per_page=10)

            selected = None
            for r in results:
                if r.id not in used_ids:
                    selected = r
                    used_ids.add(r.id)
                    break

            if selected is None and results:
                selected = results[0]

            if selected:
                try:
                    path = await self.download_image(
                        selected.download_url, output_dir,
                        filename=f"scene_{i+1}.jpg",
                    )
                    paths.append(path)
                    logger.info("场景%d 图片下载: %s (%dx%d)", i+1, selected.tags, selected.width, selected.height)
                except Exception:
                    logger.warning("场景%d 图片下载失败", i+1, exc_info=True)
                    paths.append(None)
            else:
                logger.warning("场景%d 未找到匹配图片: %s", i+1, kw)
                paths.append(None)

        return paths


    async def search_bgm_audio(self, emotion: str = "neutral", output_dir: Path | None = None) -> Path | None:
        """搜索并下载 BGM 音频。

        Pixabay 图片 API 不直接提供音乐，但可以搜索音乐相关的内容。
        这里用一个简单的策略：从 Pixabay 的 music 页面下载。
        如果失败则返回 None，让用户手动上传。
        """
        # Pixabay 没有公开的音乐 API，返回 None 让用户手动上传
        # 未来可以接入 Freesound API 或其他音乐素材库
        return None

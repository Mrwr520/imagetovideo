"""Pipeline 模块 - 图片转短视频解说工具的核心流水线。"""

from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from src.narration_mode import NarrationMode

logger = logging.getLogger(__name__)

# 支持的图片文件扩展名（小写）
SUPPORTED_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".webp"}


def validate_single_image(file_path: Path) -> str | None:
    """校验单个图片文件的格式。

    Args:
        file_path: 图片文件路径。

    Returns:
        如果格式有效返回 None，否则返回错误提示字符串。
    """
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return (
            f"不支持的文件格式: '{file_path.name}' "
            f"(扩展名: {ext or '无'})。"
            f"仅支持 JPG、PNG、WEBP 格式。"
        )
    return None


def validate_image_files(
    file_paths: list[Path],
) -> tuple[list[Path], list[str]]:
    """批量校验图片文件格式。

    按输入顺序检查每个文件，有效文件保持原始顺序返回。

    Args:
        file_paths: 图片文件路径列表。

    Returns:
        (valid_files, errors) 元组：
        - valid_files: 格式有效的文件路径列表（保持输入顺序）
        - errors: 格式无效文件的错误提示列表
    """
    valid_files: list[Path] = []
    errors: list[str] = []

    for fp in file_paths:
        error = validate_single_image(fp)
        if error is None:
            valid_files.append(fp)
        else:
            errors.append(error)

    return valid_files, errors


# ---------------------------------------------------------------------------
# Task data models
# ---------------------------------------------------------------------------


class TaskStatus(Enum):
    """任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskContext:
    """单个视频生成任务的上下文。"""

    task_id: str
    images: list[Path]
    aspect_ratio: str  # "9:16" 或 "16:9"
    llm_provider: str
    llm_model: str
    tts_provider: str
    tts_voice: str
    bgm_path: Path | None = None
    narration: str = ""
    audio_path: Path | None = None
    subtitle_data: list[dict] | None = None
    output_path: Path | None = None
    narration_mode: NarrationMode = NarrationMode.DESCRIBE_IMAGES
    target_duration: int = 60
    search_results: list[dict] | None = None
    status: TaskStatus = TaskStatus.PENDING
    error: str = ""
    progress: float = 0.0


# ---------------------------------------------------------------------------
# PipelineManager
# ---------------------------------------------------------------------------


class PipelineManager:
    """编排完整的图片→视频流水线。

    流程：图片验证 → 解说词生成 → 语音合成 → 字幕生成 → 视频合成
    """

    # Progress milestones for each pipeline stage
    _PROGRESS_VALIDATE = 0.05
    _PROGRESS_NARRATION = 0.30
    _PROGRESS_TTS = 0.55
    _PROGRESS_SUBTITLE = 0.70
    _PROGRESS_VIDEO = 1.0

    def __init__(self, config: dict) -> None:
        """根据配置初始化各适配器。

        Args:
            config: 完整的配置字典（包含 llm, tts, video, subtitle 等段）。
        """
        from src.llm.adapter import LLMAdapter
        from src.subtitle.generator import SubtitleGenerator
        from src.tts.adapter import TTSAdapter
        from src.video.composer import VideoComposer, VideoConfig

        self._config = config
        self._llm = LLMAdapter(config.get("llm", {}))
        self._tts = TTSAdapter(config.get("tts", {}))
        self._subtitle = SubtitleGenerator()
        self._composer = VideoComposer()

    async def run(
        self,
        ctx: TaskContext,
        on_progress: Callable[[TaskContext], None] | None = None,
    ) -> TaskContext:
        """执行完整流水线。

        步骤：
        1. 验证图片
        2. 生成解说词（如果 narration 为空）
        3. 语音合成
        4. 字幕生成
        5. 视频合成

        Args:
            ctx: 任务上下文。
            on_progress: 可选的进度回调，每个阶段完成后调用。

        Returns:
            更新后的 TaskContext（status 为 COMPLETED 或 FAILED）。
        """
        from src.subtitle.generator import SubtitleGenerator
        from src.video.composer import VideoConfig

        ctx.status = TaskStatus.RUNNING
        ctx.progress = 0.0
        self._notify(ctx, on_progress)

        try:
            # 1. Validate images
            valid_files, errors = validate_image_files(ctx.images)
            if errors:
                raise ValueError(f"图片验证失败: {'; '.join(errors)}")
            if not valid_files:
                raise ValueError("没有有效的图片文件")
            ctx.images = valid_files
            ctx.progress = self._PROGRESS_VALIDATE
            self._notify(ctx, on_progress)

            # 2. Generate narration (skip if already provided)
            if not ctx.narration:
                from src.llm.keyword_extractor import KeywordExtractor
                from src.llm.prompt_builder import PromptBuilder
                from src.search.web_searcher import WebSearcher

                provider = self._llm.get_provider(ctx.llm_provider, ctx.llm_model)
                builder = PromptBuilder()

                if ctx.narration_mode == NarrationMode.NEWS_COMMENTARY:
                    # Keyword extraction (fall back to empty list on failure)
                    try:
                        extractor = KeywordExtractor(provider)
                        keywords = await extractor.extract(ctx.images)
                    except Exception:
                        logger.warning("关键词提取失败，回退到仅基于图片的解说", exc_info=True)
                        keywords = []

                    # Web search (fall back to empty results on failure)
                    search_context = ""
                    try:
                        search_cfg = self._config.get("search", {})
                        searcher = WebSearcher(
                            timeout=search_cfg.get("timeout", 10.0),
                            max_results=search_cfg.get("max_results", 10),
                        )
                        results = await searcher.search(keywords)
                        search_context = searcher.format_for_prompt(results)
                    except Exception:
                        logger.warning("网络搜索失败，回退到仅基于图片的解说", exc_info=True)
                        search_context = ""

                    prompt = builder.build(
                        mode=NarrationMode.NEWS_COMMENTARY,
                        search_context=search_context,
                        duration=ctx.target_duration,
                        image_count=len(ctx.images),
                    )
                else:
                    # DESCRIBE_IMAGES mode
                    prompt = builder.build(
                        mode=NarrationMode.DESCRIBE_IMAGES,
                        duration=ctx.target_duration,
                        image_count=len(ctx.images),
                    )

                ctx.narration = await provider.generate_narration(ctx.images, prompt)
            ctx.progress = self._PROGRESS_NARRATION
            self._notify(ctx, on_progress)

            # 3. TTS synthesis
            output_dir = Path(tempfile.mkdtemp(prefix="pipeline_"))
            audio_output = output_dir / f"{ctx.task_id}_narration.mp3"
            tts_result = await self._tts.synthesize(
                text=ctx.narration,
                provider_name=ctx.tts_provider,
                voice=ctx.tts_voice,
                output_path=audio_output,
            )
            ctx.audio_path = tts_result.audio_path
            ctx.progress = self._PROGRESS_TTS
            self._notify(ctx, on_progress)

            # 4. Generate subtitles
            segments = self._subtitle.generate(ctx.narration, tts_result.duration)
            ctx.subtitle_data = [
                {
                    "index": s.index,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "text": s.text,
                }
                for s in segments
            ]
            ctx.progress = self._PROGRESS_SUBTITLE
            self._notify(ctx, on_progress)

            # 5. Compose video
            video_config = VideoConfig.from_aspect_ratio(ctx.aspect_ratio)
            from src.subtitle.generator import SubtitleStyle

            subtitle_style = SubtitleStyle()

            output_path = self._composer.compose(
                ctx=ctx,
                video_config=video_config,
                subtitle_style=subtitle_style,
            )
            ctx.output_path = output_path
            ctx.status = TaskStatus.COMPLETED
            ctx.progress = self._PROGRESS_VIDEO
            self._notify(ctx, on_progress)

        except Exception as exc:
            logger.error("Pipeline task %s failed: %s", ctx.task_id, exc, exc_info=True)
            ctx.status = TaskStatus.FAILED
            ctx.error = str(exc)
            self._notify(ctx, on_progress)

        return ctx

    async def run_batch(
        self,
        tasks: list[TaskContext],
        on_progress: Callable[[TaskContext], None] | None = None,
    ) -> list[TaskContext]:
        """批量执行多个任务，单个失败不影响其他任务。

        按顺序执行每个任务。每个任务的异常被捕获并记录到
        该任务的 error 字段，不会中断后续任务。

        Args:
            tasks: 任务上下文列表。
            on_progress: 可选的进度回调，每个任务完成后调用。

        Returns:
            更新后的 TaskContext 列表（每个 status 为 COMPLETED 或 FAILED）。
        """
        results: list[TaskContext] = []
        for ctx in tasks:
            try:
                result = await self.run(ctx, on_progress=on_progress)
                results.append(result)
            except Exception as exc:
                # Defensive: run() should already catch exceptions,
                # but guard against unexpected errors.
                logger.error(
                    "Unexpected error in batch task %s: %s",
                    ctx.task_id,
                    exc,
                    exc_info=True,
                )
                ctx.status = TaskStatus.FAILED
                ctx.error = str(exc)
                results.append(ctx)
                if on_progress:
                    on_progress(ctx)
        return results

    @staticmethod
    def _notify(
        ctx: TaskContext,
        callback: Callable[[TaskContext], None] | None,
    ) -> None:
        """调用进度回调（如果提供）。"""
        if callback is not None:
            callback(ctx)

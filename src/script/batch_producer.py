"""批量生产模块。

支持一键生成多条剧本、批量出图、批量生成视频。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.character.models import Character
from src.script.models import Script

logger = logging.getLogger(__name__)


@dataclass
class BatchTask:
    """批量任务项。"""
    
    task_id: str
    domain: str
    topic: str
    characters: list[Character]
    status: str = "pending"  # pending, running, completed, failed
    script: Script | None = None
    images: list[Path] = field(default_factory=list)
    videos: list[Path] = field(default_factory=list)
    final_video: Path | None = None
    error: str = ""


@dataclass
class BatchProgress:
    """批量任务进度。"""
    
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_task_id: str = ""
    current_stage: str = ""  # script, image, video, compose
    stage_progress: float = 0.0
    
    @property
    def overall_progress(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.completed + self.failed) / self.total * 100


@dataclass
class BatchResult:
    """批量任务结果。"""
    
    tasks: list[BatchTask] = field(default_factory=list)
    total: int = 0
    success_count: int = 0
    failed_count: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.success_count / self.total * 100


class BatchProducer:
    """批量生产器。"""
    
    def __init__(
        self,
        llm_provider,
        image_gen_adapter=None,
        video_gen_adapter=None,
        output_dir: Path | str = "./output/batch",
    ) -> None:
        """初始化批量生产器。
        
        Args:
            llm_provider: LLM provider 实例。
            image_gen_adapter: ImageGenAdapter 实例。
            video_gen_adapter: VideoGenAdapter 实例。
            output_dir: 输出目录。
        """
        self._llm_provider = llm_provider
        self._image_gen_adapter = image_gen_adapter
        self._video_gen_adapter = video_gen_adapter
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        
        self._tasks: list[BatchTask] = []
        self._progress = BatchProgress()
        self._cancelled = False
    
    def add_task(
        self,
        task_id: str,
        domain: str,
        topic: str,
        characters: list[Character],
    ) -> BatchTask:
        """添加批量任务。
        
        Args:
            task_id: 任务 ID。
            domain: 领域。
            topic: 话题。
            characters: 角色列表。
            
        Returns:
            创建的任务。
        """
        task = BatchTask(
            task_id=task_id,
            domain=domain,
            topic=topic,
            characters=characters,
        )
        self._tasks.append(task)
        self._progress.total = len(self._tasks)
        return task
    
    def clear_tasks(self) -> None:
        """清空任务队列。"""
        self._tasks.clear()
        self._progress = BatchProgress()
    
    async def _generate_script(self, task: BatchTask) -> Script | None:
        """生成单个剧本。"""
        from src.script.pipeline import run_script_pipeline
        
        try:
            result = await run_script_pipeline(
                llm_provider=self._llm_provider,
                topic=task.topic,
                domain=task.domain,
                characters=task.characters,
                search_context="",
            )
            
            if result.success and result.script:
                return result.script
            else:
                task.error = "; ".join(result.errors) if result.errors else "剧本生成失败"
                return None
                
        except Exception as e:
            task.error = str(e)
            logger.error("剧本生成失败 [%s]: %s", task.task_id, e)
            return None
    
    async def _generate_images(self, task: BatchTask) -> list[Path]:
        """批量生成图片。"""
        if not self._image_gen_adapter or not task.script:
            return []
        
        images = []
        task_dir = self._output_dir / task.task_id / "images"
        task_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取角色参考图
        ref_images = []
        for char in task.characters:
            if char.ref_images:
                char_dir = Path("characters") / char.name
                for img_name in char.ref_images:
                    img_path = char_dir / img_name
                    if img_path.exists():
                        ref_images.append(img_path)
        
        for i, scene in enumerate(task.script.scenes):
            prompt = scene.image_prompt or scene.image_desc
            if not prompt:
                continue
            
            try:
                output_path = task_dir / f"scene_{i:03d}.png"
                result = await self._image_gen_adapter.generate(
                    prompt,
                    style=task.script.style or "anime",
                    ref_images=ref_images if ref_images else None,
                    output_path=output_path,
                )
                images.append(result.image_path)
            except Exception as e:
                logger.warning("图片生成失败 [%s] 场景 %d: %s", task.task_id, i, e)
        
        return images


    async def _generate_videos(self, task: BatchTask) -> list[Path]:
        """批量生成视频片段。"""
        if not self._video_gen_adapter or not task.images:
            return []
        
        videos = []
        task_dir = self._output_dir / task.task_id / "videos"
        task_dir.mkdir(parents=True, exist_ok=True)
        
        for i, image_path in enumerate(task.images):
            try:
                output_path = task_dir / f"scene_{i:03d}.mp4"
                
                # 获取场景的运动提示词
                prompt = ""
                if task.script and i < len(task.script.scenes):
                    scene = task.script.scenes[i]
                    prompt = f"gentle camera movement, {scene.emotion} mood"
                
                result = await self._video_gen_adapter.generate(
                    image_path,
                    prompt=prompt,
                    duration=4.0,
                    output_path=output_path,
                )
                videos.append(result.video_path)
            except Exception as e:
                logger.warning("视频生成失败 [%s] 场景 %d: %s", task.task_id, i, e)
        
        return videos
    
    async def run(
        self,
        on_progress: Callable[[BatchProgress], None] | None = None,
        *,
        generate_images: bool = True,
        generate_videos: bool = False,
    ) -> BatchResult:
        """执行批量生产。
        
        Args:
            on_progress: 进度回调函数。
            generate_images: 是否生成图片。
            generate_videos: 是否生成视频。
            
        Returns:
            批量任务结果。
        """
        self._cancelled = False
        self._progress = BatchProgress(total=len(self._tasks))
        
        for task in self._tasks:
            if self._cancelled:
                break
            
            task.status = "running"
            self._progress.current_task_id = task.task_id
            
            try:
                # 阶段1：生成剧本
                self._progress.current_stage = "script"
                self._progress.stage_progress = 0.0
                if on_progress:
                    on_progress(self._progress)
                
                script = await self._generate_script(task)
                if not script:
                    task.status = "failed"
                    self._progress.failed += 1
                    continue
                
                task.script = script
                self._progress.stage_progress = 100.0
                if on_progress:
                    on_progress(self._progress)
                
                # 阶段2：生成图片
                if generate_images and self._image_gen_adapter:
                    self._progress.current_stage = "image"
                    self._progress.stage_progress = 0.0
                    if on_progress:
                        on_progress(self._progress)
                    
                    images = await self._generate_images(task)
                    task.images = images
                    self._progress.stage_progress = 100.0
                    if on_progress:
                        on_progress(self._progress)
                
                # 阶段3：生成视频
                if generate_videos and self._video_gen_adapter and task.images:
                    self._progress.current_stage = "video"
                    self._progress.stage_progress = 0.0
                    if on_progress:
                        on_progress(self._progress)
                    
                    videos = await self._generate_videos(task)
                    task.videos = videos
                    self._progress.stage_progress = 100.0
                    if on_progress:
                        on_progress(self._progress)
                
                task.status = "completed"
                self._progress.completed += 1
                
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                self._progress.failed += 1
                logger.error("任务失败 [%s]: %s", task.task_id, e)
            
            if on_progress:
                on_progress(self._progress)
        
        return BatchResult(
            tasks=self._tasks,
            total=len(self._tasks),
            success_count=self._progress.completed,
            failed_count=self._progress.failed,
        )
    
    def cancel(self) -> None:
        """取消批量任务。"""
        self._cancelled = True
    
    @property
    def progress(self) -> BatchProgress:
        """当前进度。"""
        return self._progress
    
    @property
    def tasks(self) -> list[BatchTask]:
        """任务列表。"""
        return self._tasks


async def batch_generate_scripts(
    llm_provider,
    domain: str,
    topics: list[str],
    characters: list[Character],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[Script]:
    """批量生成剧本。
    
    Args:
        llm_provider: LLM provider 实例。
        domain: 领域。
        topics: 话题列表。
        characters: 角色列表。
        on_progress: 进度回调 (current, total)。
        
    Returns:
        生成的剧本列表。
    """
    from src.script.pipeline import run_script_pipeline
    
    scripts = []
    total = len(topics)
    
    for i, topic in enumerate(topics):
        if on_progress:
            on_progress(i, total)
        
        try:
            result = await run_script_pipeline(
                llm_provider=llm_provider,
                topic=topic,
                domain=domain,
                characters=characters,
                search_context="",
            )
            
            if result.success and result.script:
                scripts.append(result.script)
        except Exception as e:
            logger.warning("剧本生成失败 [%s]: %s", topic, e)
    
    if on_progress:
        on_progress(total, total)
    
    return scripts

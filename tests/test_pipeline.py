"""Pipeline 图片文件格式验证 单元测试。"""

from pathlib import Path

import pytest

from src.pipeline import (
    SUPPORTED_EXTENSIONS,
    validate_image_files,
    validate_single_image,
)


class TestValidateSingleImage:
    """validate_single_image() 测试。"""

    @pytest.mark.parametrize(
        "filename",
        ["photo.jpg", "photo.jpeg", "photo.png", "photo.webp"],
    )
    def test_accepts_supported_formats(self, filename: str):
        """JPG/JPEG/PNG/WEBP 格式应返回 None（无错误）。"""
        assert validate_single_image(Path(filename)) is None

    @pytest.mark.parametrize(
        "filename",
        ["photo.JPG", "photo.Jpeg", "photo.PNG", "photo.WEBP"],
    )
    def test_accepts_uppercase_extensions(self, filename: str):
        """大写扩展名也应被接受（大小写不敏感）。"""
        assert validate_single_image(Path(filename)) is None

    @pytest.mark.parametrize(
        "filename",
        ["photo.bmp", "photo.gif", "photo.tiff", "photo.svg", "document.pdf", "video.mp4"],
    )
    def test_rejects_unsupported_formats(self, filename: str):
        """不支持的格式应返回错误提示。"""
        error = validate_single_image(Path(filename))
        assert error is not None
        assert filename in error

    def test_rejects_file_without_extension(self):
        """无扩展名的文件应被拒绝。"""
        error = validate_single_image(Path("noextension"))
        assert error is not None
        assert "noextension" in error

    def test_error_message_includes_filename(self):
        """错误提示应包含文件名。"""
        error = validate_single_image(Path("test.bmp"))
        assert "test.bmp" in error

    def test_error_message_includes_extension(self):
        """错误提示应包含文件扩展名。"""
        error = validate_single_image(Path("test.gif"))
        assert ".gif" in error

    def test_mixed_case_extension(self):
        """混合大小写扩展名应被接受。"""
        assert validate_single_image(Path("photo.JpG")) is None
        assert validate_single_image(Path("photo.WeBp")) is None


class TestValidateImageFiles:
    """validate_image_files() 测试。"""

    def test_all_valid_files(self):
        """全部有效文件应全部返回，无错误。"""
        files = [Path("a.jpg"), Path("b.png"), Path("c.webp")]
        valid, errors = validate_image_files(files)
        assert valid == files
        assert errors == []

    def test_all_invalid_files(self):
        """全部无效文件应返回空有效列表和对应错误。"""
        files = [Path("a.bmp"), Path("b.gif"), Path("c.tiff")]
        valid, errors = validate_image_files(files)
        assert valid == []
        assert len(errors) == 3

    def test_mixed_valid_and_invalid(self):
        """混合文件应正确分离有效和无效。"""
        files = [Path("a.jpg"), Path("b.bmp"), Path("c.png"), Path("d.gif")]
        valid, errors = validate_image_files(files)
        assert valid == [Path("a.jpg"), Path("c.png")]
        assert len(errors) == 2

    def test_empty_list(self):
        """空列表应返回空结果。"""
        valid, errors = validate_image_files([])
        assert valid == []
        assert errors == []

    def test_preserves_order_of_valid_files(self):
        """有效文件应保持输入顺序。"""
        files = [
            Path("3.webp"),
            Path("bad.bmp"),
            Path("1.jpg"),
            Path("bad2.gif"),
            Path("2.png"),
        ]
        valid, errors = validate_image_files(files)
        assert valid == [Path("3.webp"), Path("1.jpg"), Path("2.png")]

    def test_single_valid_file(self):
        """单个有效文件。"""
        valid, errors = validate_image_files([Path("only.jpeg")])
        assert valid == [Path("only.jpeg")]
        assert errors == []

    def test_single_invalid_file(self):
        """单个无效文件。"""
        valid, errors = validate_image_files([Path("only.bmp")])
        assert valid == []
        assert len(errors) == 1

    def test_duplicate_files_preserved(self):
        """重复文件应保留（不去重）。"""
        files = [Path("a.jpg"), Path("a.jpg"), Path("a.jpg")]
        valid, errors = validate_image_files(files)
        assert len(valid) == 3


# ---------------------------------------------------------------------------
# PipelineManager 单元测试 (Task 9.1)
# ---------------------------------------------------------------------------

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from src.pipeline import PipelineManager, TaskContext, TaskStatus


def _make_ctx(
    task_id: str = "test-001",
    images: list | None = None,
    narration: str = "",
    status: TaskStatus = TaskStatus.PENDING,
) -> TaskContext:
    """创建测试用 TaskContext。"""
    return TaskContext(
        task_id=task_id,
        images=images or [Path("img1.jpg"), Path("img2.png")],
        aspect_ratio="9:16",
        llm_provider="qwen",
        llm_model="qwen-vl-max",
        tts_provider="edge_tts",
        tts_voice="zh-CN-XiaoxiaoNeural",
        narration=narration,
        status=status,
    )


class TestTaskStatusAndContext:
    """TaskStatus 和 TaskContext 数据类测试。"""

    def test_task_status_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"

    def test_task_context_defaults(self):
        ctx = _make_ctx()
        assert ctx.status == TaskStatus.PENDING
        assert ctx.narration == ""
        assert ctx.audio_path is None
        assert ctx.subtitle_data is None
        assert ctx.output_path is None
        assert ctx.error == ""
        assert ctx.progress == 0.0

    def test_task_context_custom_fields(self):
        ctx = _make_ctx(narration="测试解说词", status=TaskStatus.RUNNING)
        assert ctx.narration == "测试解说词"
        assert ctx.status == TaskStatus.RUNNING


class TestPipelineManagerRun:
    """PipelineManager.run() 测试。"""

    def _make_manager(self) -> PipelineManager:
        """创建带 mock 适配器的 PipelineManager。"""
        config = {
            "llm": {"qwen": {"api_key": "test", "default_model": "qwen-vl-max"}},
            "tts": {"edge_tts": {"default_voice": "zh-CN-XiaoxiaoNeural"}},
            "video": {},
            "subtitle": {},
        }
        manager = PipelineManager(config)
        return manager

    @pytest.mark.asyncio
    async def test_run_success_with_narration_provided(self):
        """当 narration 已提供时，跳过 LLM 调用，完成全流程。"""
        manager = self._make_manager()
        ctx = _make_ctx(narration="这是一段测试解说词，用于验证流水线功能。")

        # Mock TTS
        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/test_audio.mp3")
        mock_tts_result.duration = 10.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)

        # Mock video composer
        manager._composer.compose = MagicMock(return_value=Path("/tmp/output.mp4"))

        result = await manager.run(ctx)

        assert result.status == TaskStatus.COMPLETED
        assert result.progress == 1.0
        assert result.error == ""
        assert result.output_path == Path("/tmp/output.mp4")
        assert result.audio_path == Path("/tmp/test_audio.mp3")
        assert result.subtitle_data is not None

    @pytest.mark.asyncio
    async def test_run_generates_narration_when_empty(self):
        """当 narration 为空时，调用 LLM 生成解说词。"""
        manager = self._make_manager()
        ctx = _make_ctx(narration="")

        # Mock LLM
        mock_provider = AsyncMock()
        mock_provider.generate_narration = AsyncMock(return_value="AI生成的解说词")
        manager._llm.get_provider = MagicMock(return_value=mock_provider)

        # Mock TTS
        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/test_audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)

        # Mock video composer
        manager._composer.compose = MagicMock(return_value=Path("/tmp/output.mp4"))

        result = await manager.run(ctx)

        assert result.status == TaskStatus.COMPLETED
        assert result.narration == "AI生成的解说词"
        manager._llm.get_provider.assert_called_once_with("qwen", "qwen-vl-max")

    @pytest.mark.asyncio
    async def test_run_fails_with_invalid_images(self):
        """无效图片格式应导致任务失败。"""
        manager = self._make_manager()
        ctx = _make_ctx(images=[Path("bad.bmp"), Path("bad.gif")])

        result = await manager.run(ctx)

        assert result.status == TaskStatus.FAILED
        assert "图片验证失败" in result.error

    @pytest.mark.asyncio
    async def test_run_fails_on_tts_error(self):
        """TTS 合成失败应导致任务失败。"""
        manager = self._make_manager()
        ctx = _make_ctx(narration="测试文本")

        manager._tts.synthesize = AsyncMock(side_effect=RuntimeError("TTS服务不可用"))

        result = await manager.run(ctx)

        assert result.status == TaskStatus.FAILED
        assert "TTS服务不可用" in result.error

    @pytest.mark.asyncio
    async def test_run_progress_callback(self):
        """进度回调应在每个阶段被调用。"""
        manager = self._make_manager()
        ctx = _make_ctx(narration="测试解说词")

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        progress_calls = []
        def on_progress(c: TaskContext):
            progress_calls.append((c.task_id, c.progress, c.status))

        await manager.run(ctx, on_progress=on_progress)

        # Should have multiple progress updates
        assert len(progress_calls) >= 5  # initial + validate + narration + tts + subtitle + video
        # Last call should be completed
        assert progress_calls[-1][2] == TaskStatus.COMPLETED
        assert progress_calls[-1][1] == 1.0


class TestPipelineManagerRunBatch:
    """PipelineManager.run_batch() 测试。"""

    def _make_manager(self) -> PipelineManager:
        config = {
            "llm": {"qwen": {"api_key": "test", "default_model": "qwen-vl-max"}},
            "tts": {"edge_tts": {"default_voice": "zh-CN-XiaoxiaoNeural"}},
            "video": {},
            "subtitle": {},
        }
        return PipelineManager(config)

    @pytest.mark.asyncio
    async def test_batch_all_succeed(self):
        """所有任务成功时，全部标记为 COMPLETED。"""
        manager = self._make_manager()

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        tasks = [
            _make_ctx(task_id="t1", narration="解说词1"),
            _make_ctx(task_id="t2", narration="解说词2"),
        ]

        results = await manager.run_batch(tasks)

        assert len(results) == 2
        assert all(r.status == TaskStatus.COMPLETED for r in results)

    @pytest.mark.asyncio
    async def test_batch_partial_failure(self):
        """部分任务失败不影响其他任务完成。"""
        manager = self._make_manager()

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0

        call_count = 0
        async def tts_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("TTS失败")
            return mock_tts_result

        manager._tts.synthesize = AsyncMock(side_effect=tts_side_effect)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        tasks = [
            _make_ctx(task_id="t1", narration="解说词1"),
            _make_ctx(task_id="t2", narration="解说词2"),
            _make_ctx(task_id="t3", narration="解说词3"),
        ]

        results = await manager.run_batch(tasks)

        assert len(results) == 3
        completed = [r for r in results if r.status == TaskStatus.COMPLETED]
        failed = [r for r in results if r.status == TaskStatus.FAILED]
        assert len(completed) == 2
        assert len(failed) == 1
        assert failed[0].task_id == "t2"
        assert "TTS失败" in failed[0].error

    @pytest.mark.asyncio
    async def test_batch_all_fail(self):
        """所有任务失败时，全部标记为 FAILED。"""
        manager = self._make_manager()

        tasks = [
            _make_ctx(task_id="t1", images=[Path("bad.bmp")]),
            _make_ctx(task_id="t2", images=[Path("bad.gif")]),
        ]

        results = await manager.run_batch(tasks)

        assert len(results) == 2
        assert all(r.status == TaskStatus.FAILED for r in results)
        assert all(r.error != "" for r in results)

    @pytest.mark.asyncio
    async def test_batch_empty_list(self):
        """空任务列表应返回空结果。"""
        manager = self._make_manager()
        results = await manager.run_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_batch_progress_callback(self):
        """批量执行时进度回调应被调用。"""
        manager = self._make_manager()

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        tasks = [
            _make_ctx(task_id="t1", narration="解说词1"),
            _make_ctx(task_id="t2", narration="解说词2"),
        ]

        callback = MagicMock()
        results = await manager.run_batch(tasks, on_progress=callback)

        assert callback.call_count > 0
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_batch_completed_plus_failed_equals_total(self):
        """完成数 + 失败数 = 总任务数。"""
        manager = self._make_manager()

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0

        call_count = 0
        async def tts_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise RuntimeError("偶数任务失败")
            return mock_tts_result

        manager._tts.synthesize = AsyncMock(side_effect=tts_side_effect)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        tasks = [_make_ctx(task_id=f"t{i}", narration=f"解说词{i}") for i in range(5)]

        results = await manager.run_batch(tasks)

        completed = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
        failed = sum(1 for r in results if r.status == TaskStatus.FAILED)
        assert completed + failed == len(tasks)


# ---------------------------------------------------------------------------
# PipelineManager narration mode tests (Task 5.3)
# ---------------------------------------------------------------------------

from src.narration_mode import NarrationMode


def _make_ctx_with_mode(
    narration_mode: NarrationMode = NarrationMode.DESCRIBE_IMAGES,
    target_duration: int = 60,
    **kwargs,
) -> TaskContext:
    """创建带解说模式的测试用 TaskContext。"""
    ctx = _make_ctx(**kwargs)
    ctx.narration_mode = narration_mode
    ctx.target_duration = target_duration
    return ctx


class TestPipelineNarrationModes:
    """PipelineManager.run() 解说模式分支测试。"""

    def _make_manager(self, search_cfg: dict | None = None) -> PipelineManager:
        config = {
            "llm": {"qwen": {"api_key": "test", "default_model": "qwen-vl-max"}},
            "tts": {"edge_tts": {"default_voice": "zh-CN-XiaoxiaoNeural"}},
            "video": {},
            "subtitle": {},
        }
        if search_cfg is not None:
            config["search"] = search_cfg
        return PipelineManager(config)

    @pytest.mark.asyncio
    async def test_describe_images_mode_uses_prompt_builder(self):
        """DESCRIBE_IMAGES 模式应使用 PromptBuilder 生成提示词。"""
        manager = self._make_manager()
        ctx = _make_ctx_with_mode(
            narration_mode=NarrationMode.DESCRIBE_IMAGES,
            target_duration=90,
        )

        mock_provider = AsyncMock()
        mock_provider.generate_narration = AsyncMock(return_value="按图说话解说词")
        manager._llm.get_provider = MagicMock(return_value=mock_provider)

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        result = await manager.run(ctx)

        assert result.status == TaskStatus.COMPLETED
        assert result.narration == "按图说话解说词"
        # Verify the prompt contains duration and is describe_images style
        call_args = mock_provider.generate_narration.call_args
        prompt = call_args[0][1]
        assert "90" in prompt
        assert "内容创作者" in prompt

    @pytest.mark.asyncio
    async def test_news_commentary_mode_runs_full_pipeline(self):
        """NEWS_COMMENTARY 模式应执行关键词提取→搜索→新闻风格提示词。"""
        manager = self._make_manager()
        ctx = _make_ctx_with_mode(
            narration_mode=NarrationMode.NEWS_COMMENTARY,
            target_duration=120,
        )

        mock_provider = AsyncMock()
        # First call: keyword extraction, second call: narration generation
        mock_provider.generate_narration = AsyncMock(
            side_effect=[
                '{"keywords": ["测试关键词"]}',
                "新闻解说词内容",
            ]
        )
        manager._llm.get_provider = MagicMock(return_value=mock_provider)

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        # Mock WebSearcher to avoid real network calls
        with patch("src.search.web_searcher.WebSearcher") as MockWebSearcher:
            mock_searcher = MagicMock()
            mock_searcher.search = AsyncMock(return_value=[])
            mock_searcher.format_for_prompt = MagicMock(return_value="")
            MockWebSearcher.return_value = mock_searcher

            result = await manager.run(ctx)

        assert result.status == TaskStatus.COMPLETED
        assert result.narration == "新闻解说词内容"

    @pytest.mark.asyncio
    async def test_news_mode_keyword_extraction_failure_falls_back(self):
        """关键词提取失败时应回退到仅基于图片的解说。"""
        manager = self._make_manager()
        ctx = _make_ctx_with_mode(
            narration_mode=NarrationMode.NEWS_COMMENTARY,
        )

        mock_provider = AsyncMock()
        # Keyword extraction raises, then narration generation succeeds
        mock_provider.generate_narration = AsyncMock(
            side_effect=[
                Exception("LLM调用失败"),  # keyword extraction fails inside KeywordExtractor
                "回退解说词",
            ]
        )
        manager._llm.get_provider = MagicMock(return_value=mock_provider)

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        # Mock WebSearcher
        with patch("src.search.web_searcher.WebSearcher") as MockWebSearcher:
            mock_searcher = MagicMock()
            mock_searcher.search = AsyncMock(return_value=[])
            mock_searcher.format_for_prompt = MagicMock(return_value="")
            MockWebSearcher.return_value = mock_searcher

            result = await manager.run(ctx)

        assert result.status == TaskStatus.COMPLETED
        assert result.narration == "回退解说词"

    @pytest.mark.asyncio
    async def test_news_mode_search_failure_falls_back(self):
        """网络搜索失败时应回退到仅基于图片的新闻风格解说。"""
        manager = self._make_manager()
        ctx = _make_ctx_with_mode(
            narration_mode=NarrationMode.NEWS_COMMENTARY,
        )

        mock_provider = AsyncMock()
        mock_provider.generate_narration = AsyncMock(
            side_effect=[
                '{"keywords": ["关键词"]}',
                "搜索失败回退解说词",
            ]
        )
        manager._llm.get_provider = MagicMock(return_value=mock_provider)

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        # Mock WebSearcher to raise on search
        with patch("src.search.web_searcher.WebSearcher") as MockWebSearcher:
            mock_searcher = MagicMock()
            mock_searcher.search = AsyncMock(side_effect=Exception("搜索超时"))
            MockWebSearcher.return_value = mock_searcher

            result = await manager.run(ctx)

        assert result.status == TaskStatus.COMPLETED
        assert result.narration == "搜索失败回退解说词"

    @pytest.mark.asyncio
    async def test_narration_skipped_when_already_provided(self):
        """narration 已提供时，无论模式如何都应跳过生成。"""
        manager = self._make_manager()
        ctx = _make_ctx_with_mode(
            narration_mode=NarrationMode.NEWS_COMMENTARY,
            narration="已有解说词",
        )

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        result = await manager.run(ctx)

        assert result.status == TaskStatus.COMPLETED
        assert result.narration == "已有解说词"

    @pytest.mark.asyncio
    async def test_describe_images_mode_passes_duration(self):
        """DESCRIBE_IMAGES 模式应将 target_duration 传递给 PromptBuilder。"""
        manager = self._make_manager()
        ctx = _make_ctx_with_mode(
            narration_mode=NarrationMode.DESCRIBE_IMAGES,
            target_duration=30,
        )

        mock_provider = AsyncMock()
        mock_provider.generate_narration = AsyncMock(return_value="短解说词")
        manager._llm.get_provider = MagicMock(return_value=mock_provider)

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        result = await manager.run(ctx)

        assert result.status == TaskStatus.COMPLETED
        call_args = mock_provider.generate_narration.call_args
        prompt = call_args[0][1]
        assert "30" in prompt

    @pytest.mark.asyncio
    async def test_news_mode_uses_search_config(self):
        """NEWS_COMMENTARY 模式应使用配置中的搜索参数。"""
        manager = self._make_manager(search_cfg={"timeout": 5.0, "max_results": 3})
        ctx = _make_ctx_with_mode(
            narration_mode=NarrationMode.NEWS_COMMENTARY,
        )

        mock_provider = AsyncMock()
        mock_provider.generate_narration = AsyncMock(
            side_effect=[
                '{"keywords": ["测试"]}',
                "新闻解说词",
            ]
        )
        manager._llm.get_provider = MagicMock(return_value=mock_provider)

        mock_tts_result = MagicMock()
        mock_tts_result.audio_path = Path("/tmp/audio.mp3")
        mock_tts_result.duration = 5.0
        manager._tts.synthesize = AsyncMock(return_value=mock_tts_result)
        manager._composer.compose = MagicMock(return_value=Path("/tmp/out.mp4"))

        with patch("src.search.web_searcher.WebSearcher") as MockWebSearcher:
            mock_searcher = MagicMock()
            mock_searcher.search = AsyncMock(return_value=[])
            mock_searcher.format_for_prompt = MagicMock(return_value="")
            MockWebSearcher.return_value = mock_searcher

            result = await manager.run(ctx)

        MockWebSearcher.assert_called_once_with(timeout=5.0, max_results=3)
        assert result.status == TaskStatus.COMPLETED

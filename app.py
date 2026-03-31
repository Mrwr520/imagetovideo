"""图片转短视频解说工具 - Streamlit 入口"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path

import streamlit as st

from src.config_manager import ConfigManager, DEFAULT_CONFIG
from src.llm.adapter import LLMAdapter
from src.narration_mode import NarrationMode
from src.pipeline import PipelineManager, TaskContext, TaskStatus
from src.tts.adapter import TTSAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _init_session_state() -> None:
    """初始化 session_state 中的持久数据。"""
    if "uploaded_images" not in st.session_state:
        # list[dict] – 每项: {"name": str, "data": bytes}
        st.session_state["uploaded_images"] = []
    if "config" not in st.session_state:
        cm = ConfigManager()
        st.session_state["config"] = cm.load()
    if "config_toml_text" not in st.session_state:
        st.session_state["config_toml_text"] = ""
    # Pipeline interaction state
    if "pipeline_step" not in st.session_state:
        st.session_state["pipeline_step"] = 1  # 1-5
    if "narration" not in st.session_state:
        st.session_state["narration"] = ""
    if "narration_segments" not in st.session_state:
        st.session_state["narration_segments"] = []
    if "audio_path" not in st.session_state:
        st.session_state["audio_path"] = None
    if "audio_duration" not in st.session_state:
        st.session_state["audio_duration"] = 0.0
    if "word_timings" not in st.session_state:
        st.session_state["word_timings"] = None
    if "video_path" not in st.session_state:
        st.session_state["video_path"] = None
    # Batch mode state
    if "batch_mode" not in st.session_state:
        st.session_state["batch_mode"] = False
    if "batch_groups" not in st.session_state:
        # list[dict] – 每项: {"name": str, "images": list[dict]}
        st.session_state["batch_groups"] = []
    if "batch_results" not in st.session_state:
        # list[TaskContext] – 批量任务结果
        st.session_state["batch_results"] = []
    if "narration_mode" not in st.session_state:
        cfg = st.session_state.get("config", {})
        st.session_state["narration_mode"] = cfg.get("general", {}).get("default_narration_mode", "describe_images")
    if "target_duration" not in st.session_state:
        cfg = st.session_state.get("config", {})
        st.session_state["target_duration"] = cfg.get("general", {}).get("default_duration", 60)


def _get_config() -> dict:
    return st.session_state["config"]


# ---------------------------------------------------------------------------
# Sidebar – model / voice / aspect-ratio selectors
# ---------------------------------------------------------------------------

def _render_sidebar() -> dict:
    """渲染侧边栏，返回用户选择的参数字典。"""
    cfg = _get_config()

    llm_adapter = LLMAdapter(cfg.get("llm", {}))
    tts_adapter = TTSAdapter(cfg.get("tts", {}))

    selections: dict = {}

    st.sidebar.header("⚙️ 模型配置")

    # --- LLM provider / model ---
    st.sidebar.subheader("LLM 大模型")
    all_llm_providers = list(LLMAdapter.PROVIDERS.keys())
    configured_providers = llm_adapter.list_providers()

    llm_provider = st.sidebar.selectbox(
        "LLM Provider",
        options=all_llm_providers,
        format_func=lambda p: f"{p} ✓" if p in configured_providers else p,
        key="llm_provider_select",
    )
    selections["llm_provider"] = llm_provider

    llm_models = llm_adapter.list_models(llm_provider)
    llm_model = st.sidebar.selectbox(
        "模型名称",
        options=llm_models if llm_models else ["(无可用模型)"],
        key="llm_model_select",
    )
    selections["llm_model"] = llm_model

    if llm_provider not in configured_providers:
        st.sidebar.warning(f"⚠️ {llm_provider} 尚未配置 API Key，请在配置管理中设置。")

    # --- TTS provider / voice ---
    st.sidebar.subheader("TTS 语音合成")
    all_tts_providers = tts_adapter.list_providers()

    tts_provider = st.sidebar.selectbox(
        "TTS Provider",
        options=all_tts_providers,
        key="tts_provider_select",
    )
    selections["tts_provider"] = tts_provider

    try:
        voices = tts_adapter.list_voices(tts_provider)
    except Exception:
        voices = []

    if voices:
        voice_options = [v["id"] for v in voices]
        voice_labels = {v["id"]: v.get("name", v["id"]) for v in voices}
        tts_voice = st.sidebar.selectbox(
            "音色",
            options=voice_options,
            format_func=lambda vid: voice_labels.get(vid, vid),
            key="tts_voice_select",
        )
    else:
        tts_voice = ""
        st.sidebar.info("该 Provider 暂无可用音色列表。")
    selections["tts_voice"] = tts_voice

    # --- Aspect ratio ---
    st.sidebar.subheader("视频设置")
    aspect_ratio = st.sidebar.radio(
        "画面比例",
        options=["9:16", "16:9"],
        index=0 if cfg.get("general", {}).get("default_aspect_ratio", "9:16") == "9:16" else 1,
        horizontal=True,
        key="aspect_ratio_select",
    )
    selections["aspect_ratio"] = aspect_ratio

    # --- Config management ---
    _render_config_management()

    return selections


# ---------------------------------------------------------------------------
# Sidebar – config management
# ---------------------------------------------------------------------------

def _render_config_management() -> None:
    """在侧边栏渲染配置管理区域。"""
    st.sidebar.divider()
    st.sidebar.subheader("📝 配置管理")

    cm = ConfigManager()

    with st.sidebar.expander("编辑 config.toml", expanded=False):
        # Load current config as TOML text for editing
        import tomli_w

        current_cfg = _get_config()
        raw = tomli_w.dumps(current_cfg)
        default_text = raw.decode("utf-8") if isinstance(raw, bytes) else raw

        edited_text = st.text_area(
            "配置内容（TOML 格式）",
            value=default_text,
            height=300,
            key="config_editor",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 保存配置", key="save_config_btn"):
                _save_config(cm, edited_text)
        with col2:
            if st.button("🔄 恢复默认", key="reset_config_btn"):
                cm.save(DEFAULT_CONFIG)
                st.session_state["config"] = cm.load()
                st.success("已恢复默认配置。")
                st.rerun()


def _save_config(cm: ConfigManager, toml_text: str) -> None:
    """解析并保存用户编辑的 TOML 配置。"""
    import sys

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    try:
        parsed = tomllib.loads(toml_text)
    except Exception as e:
        st.error(f"TOML 格式错误：{e}")
        return

    missing = cm.validate(parsed)
    if missing:
        st.warning(f"以下必要字段缺失：{', '.join(missing)}")

    cm.save(parsed)
    st.session_state["config"] = parsed
    st.success("配置已保存！")
    st.rerun()


# ---------------------------------------------------------------------------
# Main area – image upload & preview
# ---------------------------------------------------------------------------

def _render_image_upload() -> None:
    """渲染图片上传区域和缩略图预览列表。"""
    st.header("📷 图片上传")

    uploaded_files = st.file_uploader(
        "选择图片文件（支持多选）",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="file_uploader",
    )

    # Merge newly uploaded files into session state (avoid duplicates by name)
    if uploaded_files:
        existing_names = {img["name"] for img in st.session_state["uploaded_images"]}
        for uf in uploaded_files:
            if uf.name not in existing_names:
                st.session_state["uploaded_images"].append(
                    {"name": uf.name, "data": uf.getvalue()}
                )
                existing_names.add(uf.name)

    images = st.session_state["uploaded_images"]

    if not images:
        st.info("请上传图片文件开始制作视频。支持 JPG、PNG、WEBP 格式，可多选。")
        return

    st.subheader(f"已选择 {len(images)} 张图片")

    # Render thumbnail grid with reorder / delete controls
    _render_image_list(images)


def _render_image_list(images: list[dict]) -> None:
    """渲染图片缩略图列表，支持上移、下移、删除操作。"""
    to_delete: int | None = None
    swap_pair: tuple[int, int] | None = None

    for idx, img in enumerate(images):
        col_img, col_name, col_up, col_down, col_del = st.columns([2, 3, 1, 1, 1])

        with col_img:
            st.image(img["data"], width=100)

        with col_name:
            st.markdown(f"**{idx + 1}.** {img['name']}")

        with col_up:
            if idx > 0:
                if st.button("⬆️", key=f"up_{idx}"):
                    swap_pair = (idx, idx - 1)

        with col_down:
            if idx < len(images) - 1:
                if st.button("⬇️", key=f"down_{idx}"):
                    swap_pair = (idx, idx + 1)

        with col_del:
            if st.button("🗑️", key=f"del_{idx}"):
                to_delete = idx

    # Apply mutations after rendering to avoid index issues
    if swap_pair is not None:
        i, j = swap_pair
        images[i], images[j] = images[j], images[i]
        st.rerun()

    if to_delete is not None:
        images.pop(to_delete)
        # 清空 file_uploader 的 key，防止 rerun 时被重新注入
        if "file_uploader" in st.session_state:
            del st.session_state["file_uploader"]
        st.rerun()


# ---------------------------------------------------------------------------
# Helper: run async from Streamlit
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from synchronous Streamlit context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _run_in_thread(fn, *args, **kwargs):
    """Run a blocking/CPU-intensive function in a background thread.

    This prevents Streamlit's main event loop from being blocked,
    which would cause the frontend WebSocket health checks to fail
    and trigger repeated 'host-config' / 'health' retry loops.
    """
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args, **kwargs)
        return future.result()


# ---------------------------------------------------------------------------
# Helper: save uploaded images to temp files
# ---------------------------------------------------------------------------

def _save_images_to_temp(images: list[dict]) -> list[Path]:
    """Save in-memory image data to temporary files and return paths."""
    paths = []
    temp_dir = Path(tempfile.mkdtemp(prefix="narrator_imgs_"))
    for img in images:
        p = temp_dir / img["name"]
        p.write_bytes(img["data"])
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# Helper: clean narration text for TTS
# ---------------------------------------------------------------------------

def _parse_narration_json(raw: str, image_count: int) -> list[str]:
    """从 LLM 返回的 JSON 中按 narration_1, narration_2... 取值。"""
    import json
    import re

    raw = raw.strip()

    def _extract_from_dict(d: dict) -> list[str]:
        segments = []
        for i in range(1, image_count + 1):
            val = d.get(f"narration_{i}", "")
            if isinstance(val, str) and val.strip():
                # 去掉可能混入的推荐语尾巴
                clean_val = re.split(
                    r'\n+(?:更适合|更有|更像|带镜头|带停顿|带分镜|如果你|你可以|我还可以)',
                    val
                )[0].strip()
                segments.append(clean_val)
        return segments

    # 尝试直接解析
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            segments = _extract_from_dict(result)
            if len(segments) == image_count:
                return segments
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 对象部分
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                segments = _extract_from_dict(result)
                if len(segments) == image_count:
                    return segments
        except json.JSONDecodeError:
            pass

    # 兼容数组格式
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(s).strip() for s in result[:image_count]]
        except json.JSONDecodeError:
            pass

    # 回退
    cleaned = _clean_narration_for_tts(raw)
    return _split_narration_segments(cleaned, image_count)


def _clean_narration_for_tts(text: str) -> str:
    """去除解说词中的非正文内容，使其适合语音合成。"""
    import re

    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()
        # 跳过空行保留
        if not stripped:
            cleaned_lines.append('')
            continue
        # 跳过开头介绍语行
        if any(stripped.startswith(prefix) for prefix in [
            '下面是', '以下是', '这是一段', '这段解说', '这里是',
            '当然可以', '当然，', '好的，', '没问题',
        ]):
            continue
        # 跳过结尾推荐语行
        if any(stripped.startswith(prefix) for prefix in [
            '如果你需要', '如果你愿意', '我还可以', '你要的话',
            '你可以', '以上就是', '希望以上', '如需',
            '更适合', '更像', '带停顿', '带分镜',
        ]):
            continue
        # 去掉 markdown 加粗/斜体
        stripped = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', stripped)
        # 去掉 markdown 标题符号
        stripped = re.sub(r'^#{1,6}\s*', '', stripped)
        # 去掉 "第X张图：xxx" / "第X张图 | xxx" / "图片1 | xxx" 图片编号
        stripped = re.sub(r'^第[一二三四五六七八九十\d]+张图\s*[：:|\|｜].*$', '', stripped)
        stripped = re.sub(r'^图片\s*\d+\s*[：:|\|｜].*$', '', stripped)
        # 去掉 markdown 列表符号
        stripped = re.sub(r'^\s*[-*+]\s+', '', stripped)
        # 去掉序号开头
        stripped = re.sub(r'^\s*\d+\.\s+', '', stripped)
        # 去掉 markdown 分隔线（但保留 ===）
        if re.match(r'^-{3,}$', stripped):
            continue

        if stripped:
            cleaned_lines.append(stripped)

    text = '\n'.join(cleaned_lines)
    # 合并多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _split_narration_segments(text: str, image_count: int) -> list[str]:
    """将解说词按 === 分隔符拆分为与图片数量对应的段落列表。"""
    import re

    # 先按 === 分隔
    segments = [s.strip() for s in text.split('===') if s.strip()]

    # 对每个段落做二次清洗：去掉混入的短推荐行
    cleaned_segments = []
    for seg in segments:
        lines = seg.split('\n')
        good_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 跳过短推荐行（不超过25字，且像是推荐版本描述）
            if len(line) <= 25 and re.search(r'版$|版本$', line):
                continue
            good_lines.append(line)
        cleaned = '\n'.join(good_lines).strip()
        if cleaned:
            cleaned_segments.append(cleaned)
    segments = cleaned_segments

    if len(segments) == image_count:
        return segments

    # 分段数不匹配，尝试按双换行分段
    segments = [s.strip() for s in text.split('\n\n') if s.strip()]

    if len(segments) == image_count:
        return segments

    # 还是不匹配，把全文均分
    if len(segments) > image_count:
        # 合并多余段落到最后一段
        result = segments[:image_count - 1]
        result.append('\n'.join(segments[image_count - 1:]))
        return result

    if len(segments) < image_count:
        # 段落不够，尝试按单换行再拆
        all_lines = [l.strip() for l in text.replace('===', '').split('\n') if l.strip()]
        if len(all_lines) >= image_count:
            # 按行数均分
            per = len(all_lines) // image_count
            result = []
            for i in range(image_count):
                start = i * per
                end = start + per if i < image_count - 1 else len(all_lines)
                result.append('\n'.join(all_lines[start:end]))
            return result
        # 实在不够，用已有段落补空
        return segments + ['（此段解说词待补充）'] * (image_count - len(segments))

    return segments


# ---------------------------------------------------------------------------
# Pipeline step indicator
# ---------------------------------------------------------------------------

def _render_step_indicator(current_step: int) -> None:
    """Render a visual step indicator showing pipeline progress."""
    steps = ["📷 上传图片", "📝 生成解说词", "🔊 合成语音", "🎬 合成视频", "✅ 预览下载"]
    cols = st.columns(len(steps))
    for i, (col, label) in enumerate(zip(cols, steps), 1):
        with col:
            if i < current_step:
                st.success(label, icon="✅")
            elif i == current_step:
                st.info(label, icon="👉")
            else:
                st.markdown(f"⬜ {label}")


# ---------------------------------------------------------------------------
# Step 2: Generate narration
# ---------------------------------------------------------------------------

def _render_step_narration(selections: dict) -> None:
    """Step 2: Generate narration from images using LLM, allow editing."""
    st.header("📝 步骤2：生成解说词")

    images = st.session_state["uploaded_images"]
    if not images:
        st.warning("请先上传图片。")
        return

    # 解说模式选择
    mode = st.radio(
        "解说模式",
        options=["按图说话", "新闻解说"],
        captions=["根据图片内容直接生成解说词，适合商业推广、个人品牌等",
                  "结合网络搜索生成新闻风格解说词，适合新闻报道、时事评论等"],
        horizontal=True,
        key="narration_mode_radio",
    )
    st.session_state["narration_mode"] = "describe_images" if mode == "按图说话" else "news_commentary"

    # 视频时长选择
    duration = st.selectbox(
        "目标视频时长",
        options=[30, 60, 90, 120, 180],
        format_func=lambda d: f"{d} 秒",
        index=1,  # 默认60秒
        key="duration_select",
    )
    st.session_state["target_duration"] = duration

    # Generate button
    if st.button("🤖 生成解说词", key="gen_narration_btn"):
        cfg = _get_config()
        llm_adapter = LLMAdapter(cfg.get("llm", {}))
        provider_name = selections.get("llm_provider", "qwen")
        model_name = selections.get("llm_model", "")

        configured = llm_adapter.list_providers()
        if provider_name not in configured:
            st.error(f"❌ {provider_name} 尚未配置 API Key，请在侧边栏配置管理中设置。")
            return

        try:
            provider = llm_adapter.get_provider(provider_name, model_name)
            image_paths = _save_images_to_temp(images)

            narration_mode = st.session_state.get("narration_mode", "describe_images")
            target_duration = st.session_state.get("target_duration", 60)
            mode_enum = NarrationMode(narration_mode)

            search_context = ""

            with st.spinner("正在调用AI生成解说词..."):
                progress_bar = st.progress(0, text="连接模型中...")

                # 新闻解说模式：先提取关键词并搜索
                if mode_enum == NarrationMode.NEWS_COMMENTARY:
                    try:
                        from src.llm.keyword_extractor import KeywordExtractor

                        progress_bar.progress(10, text="正在提取关键词...")
                        extractor = KeywordExtractor(provider)
                        keywords = _run_async(extractor.extract(image_paths))

                        if keywords:
                            from src.search.web_searcher import WebSearcher

                            progress_bar.progress(20, text="正在搜索相关新闻...")
                            search_cfg = cfg.get("search", {})
                            searcher = WebSearcher(
                                timeout=search_cfg.get("timeout", 10.0),
                                max_results=search_cfg.get("max_results", 10),
                                proxy=search_cfg.get("proxy"),
                            )
                            results = _run_async(searcher.search(keywords))
                            search_context = searcher.format_for_prompt(results)
                    except Exception:
                        import logging
                        logging.getLogger(__name__).warning(
                            "新闻解说模式：关键词提取或搜索失败，回退到无搜索上下文",
                            exc_info=True,
                        )
                        search_context = ""

                prompt = llm_adapter.render_prompt(
                    mode=mode_enum,
                    image_count=len(images),
                    duration=target_duration,
                    search_context=search_context,
                )

                progress_bar.progress(30, text="发送图片到模型...")

                # 第一步：生成解说词
                raw_response = _run_async(
                    provider.generate_narration(image_paths, prompt)
                )
                segments = _parse_narration_json(raw_response, len(images))
                progress_bar.progress(60, text="解说词已生成，正在审查...")

                # 第二步：让 AI 审查修正
                # 构建审查上下文（带上第一轮的对话）
                from src.llm.openai_compat import _build_messages
                first_round_messages = _build_messages(image_paths, prompt)
                first_round_messages.append({
                    "role": "assistant",
                    "content": raw_response,
                })

                review_prompt = (
                    f"请审查你刚才生成的JSON。要求：\n"
                    f"1. 必须恰好有{len(images)}个key（narration_1到narration_{len(images)}）\n"
                    f"2. 每个value必须是可以直接朗读的纯解说词，不能包含图片编号、标题、推荐语\n"
                    f"3. 每个value长度应大于20个字\n"
                    f"如果有问题请修正后重新输出完整JSON，如果没问题就原样输出。"
                )

                reviewed_response = _run_async(
                    provider.review_narration(first_round_messages, review_prompt)
                )
                reviewed_segments = _parse_narration_json(reviewed_response, len(images))

                # 用审查后的结果
                if len(reviewed_segments) == len(images) and all(len(s) > 10 for s in reviewed_segments):
                    segments = reviewed_segments

                progress_bar.progress(100, text="解说词生成完成！")

            st.session_state["narration_segments"] = segments
            st.session_state["narration"] = "\n\n".join(segments)
            st.session_state["pipeline_step"] = 2
        except Exception as e:
            st.error(f"❌ 解说词生成失败：{e}")
            return

    # Show editable narration text
    narration = st.session_state.get("narration", "")
    segments = st.session_state.get("narration_segments", [])
    if narration:
        # 显示分段对应关系
        if segments and len(segments) == len(images):
            st.subheader("📋 解说词分段预览（每段对应一张图片）")
            edited_segments = []
            for i, (seg, img) in enumerate(zip(segments, images)):
                col_img, col_text = st.columns([1, 4])
                with col_img:
                    st.image(img["data"], width=120, caption=img["name"])
                with col_text:
                    edited_seg = st.text_area(
                        f"第{i+1}段解说词",
                        value=seg,
                        height=100,
                        key=f"seg_editor_{i}",
                    )
                    edited_segments.append(edited_seg)
            # 用换行拼接完整解说词（不使用 === 分隔符，避免 TTS 朗读）
            full_narration = "\n\n".join(edited_segments)
            st.session_state["narration"] = full_narration
            st.session_state["narration_segments"] = edited_segments
        else:
            # 分段不匹配时显示完整编辑框
            edited = st.text_area(
                "解说词（可编辑后再进入下一步）",
                value=narration,
                height=200,
                key="narration_editor",
            )
            st.session_state["narration"] = edited

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 确认解说词，进入语音合成", key="confirm_narration_btn"):
                current_segments = st.session_state.get("narration_segments", [])
                full_text = "\n".join(s for s in current_segments if s.strip())
                if not full_text.strip():
                    st.error("解说词不能为空。")
                else:
                    st.session_state["narration"] = full_text
                    st.session_state["pipeline_step"] = 3
                    st.rerun()
        with col2:
            if st.button("🔄 重新生成", key="regen_narration_btn"):
                st.session_state["narration"] = ""
                st.session_state["narration_segments"] = []
                st.rerun()
    else:
        st.info("点击上方按钮，AI将根据图片内容生成解说词。")


# ---------------------------------------------------------------------------
# Step 3: TTS synthesis
# ---------------------------------------------------------------------------

def _render_step_tts(selections: dict) -> None:
    """Step 3: Synthesize speech from narration text."""
    st.header("🔊 步骤3：合成语音")

    narration = st.session_state.get("narration", "")
    if not narration:
        st.warning("请先生成解说词。")
        return

    st.text_area("当前解说词", value=narration, height=100, disabled=True, key="tts_narration_preview")

    if st.button("🎙️ 合成语音", key="synth_tts_btn"):
        cfg = _get_config()
        tts_adapter = TTSAdapter(cfg.get("tts", {}))
        provider_name = selections.get("tts_provider", "edge_tts")
        voice = selections.get("tts_voice", "")

        try:
            temp_dir = Path(tempfile.mkdtemp(prefix="narrator_tts_"))
            output_path = temp_dir / "narration.mp3"

            with st.spinner("正在合成语音..."):
                progress_bar = st.progress(0, text="初始化语音合成...")
                progress_bar.progress(30, text="合成中...")
                result = _run_async(
                    tts_adapter.synthesize(narration, provider_name, voice, output_path)
                )
                progress_bar.progress(100, text="语音合成完成！")

            st.session_state["audio_path"] = str(result.audio_path)
            st.session_state["audio_duration"] = result.duration
            st.session_state["word_timings"] = result.word_timings
            st.session_state["pipeline_step"] = 3
        except Exception as e:
            st.error(f"❌ 语音合成失败：{e}")
            return

    # Show audio player if available
    audio_path = st.session_state.get("audio_path")
    if audio_path and Path(audio_path).exists():
        st.audio(audio_path)
        duration = st.session_state.get("audio_duration", 0)
        if duration > 0:
            st.caption(f"音频时长：{duration:.1f} 秒")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 确认语音，进入视频合成", key="confirm_tts_btn"):
                st.session_state["pipeline_step"] = 4
                st.rerun()
        with col2:
            if st.button("🔄 重新合成", key="regen_tts_btn"):
                st.session_state["audio_path"] = None
                st.session_state["audio_duration"] = 0.0
                st.session_state["word_timings"] = None
                st.rerun()
    else:
        st.info("点击上方按钮合成语音。")


# ---------------------------------------------------------------------------
# Step 4: Video composition
# ---------------------------------------------------------------------------

def _render_step_video(selections: dict) -> None:
    """Step 4: Optional BGM upload + video composition."""
    st.header("🎬 步骤4：合成视频")

    # BGM upload (optional)
    st.subheader("🎵 背景音乐（可选）")
    bgm_file = st.file_uploader(
        "选择背景音乐文件",
        type=["mp3", "wav", "ogg"],
        key="bgm_uploader",
    )

    bgm_path = None
    if bgm_file:
        temp_dir = Path(tempfile.mkdtemp(prefix="narrator_bgm_"))
        bgm_path = temp_dir / bgm_file.name
        bgm_path.write_bytes(bgm_file.getvalue())
        st.audio(bgm_file)

    # Show current settings summary
    st.subheader("📋 合成参数")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("图片数量", len(st.session_state["uploaded_images"]))
    with col2:
        st.metric("音频时长", f"{st.session_state.get('audio_duration', 0):.1f}s")
    with col3:
        st.metric("画面比例", selections.get("aspect_ratio", "9:16"))

    if st.button("🎬 开始合成视频", key="compose_video_btn"):
        images = st.session_state["uploaded_images"]
        narration = st.session_state.get("narration", "")
        audio_path = st.session_state.get("audio_path")

        if not images:
            st.error("没有图片。")
            return
        if not narration:
            st.error("没有解说词。")
            return
        if not audio_path:
            st.error("没有语音文件。")
            return

        try:
            image_paths = _save_images_to_temp(images)
            task_id = str(uuid.uuid4())[:8]

            ctx = TaskContext(
                task_id=task_id,
                images=image_paths,
                aspect_ratio=selections.get("aspect_ratio", "9:16"),
                llm_provider=selections.get("llm_provider", "qwen"),
                llm_model=selections.get("llm_model", ""),
                tts_provider=selections.get("tts_provider", "edge_tts"),
                tts_voice=selections.get("tts_voice", ""),
                bgm_path=bgm_path,
                narration=narration,
                audio_path=Path(audio_path),
            )

            cfg = _get_config()
            pipeline = PipelineManager(cfg)

            # We already have narration and audio, so we run compose directly
            from src.subtitle.generator import SubtitleGenerator, SubtitleStyle
            from src.video.composer import VideoComposer, VideoConfig

            with st.spinner("正在合成视频，请稍候（视频编码较耗时，请耐心等待）..."):
                progress_bar = st.progress(0, text="准备素材...")

                # Generate subtitles
                progress_bar.progress(10, text="生成字幕...")
                subtitle_gen = SubtitleGenerator()
                audio_dur = st.session_state.get("audio_duration", 0)
                word_timings = st.session_state.get("word_timings")
                segments = subtitle_gen.generate(narration, audio_dur, word_timings=word_timings)
                ctx.subtitle_data = [
                    {"index": s.index, "start_time": s.start_time,
                     "end_time": s.end_time, "text": s.text}
                    for s in segments
                ]

                # Compose video in a background thread to avoid blocking
                # Streamlit's main loop (which causes health check failures)
                progress_bar.progress(20, text="合成视频中（编码耗时较长）...")
                composer = VideoComposer()
                video_config = VideoConfig.from_aspect_ratio(
                    selections.get("aspect_ratio", "9:16")
                )
                sub_cfg = cfg.get("subtitle", {})
                sub_style = SubtitleStyle(
                    font_family=sub_cfg.get("font_family", "Microsoft YaHei"),
                    font_size=sub_cfg.get("font_size", 24),
                    color=sub_cfg.get("color", "#FFFFFF"),
                    outline_color=sub_cfg.get("outline_color", "#000000"),
                    outline_width=sub_cfg.get("outline_width", 1),
                )
                output_path = _run_in_thread(
                    composer.compose,
                    ctx=ctx,
                    video_config=video_config,
                    subtitle_style=sub_style,
                    narration_segments=st.session_state.get("narration_segments"),
                    word_timings=word_timings,
                )
                progress_bar.progress(100, text="视频合成完成！")

            st.session_state["video_path"] = str(output_path)
            st.session_state["pipeline_step"] = 5
            st.rerun()
        except Exception as e:
            import traceback
            logger.error("视频合成失败: %s", e, exc_info=True)
            st.error(f"❌ 视频合成失败：{e}\n\n详细信息：{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Step 5: Preview and download
# ---------------------------------------------------------------------------

def _render_step_preview() -> None:
    """Step 5: Video preview and download."""
    st.header("✅ 步骤5：视频预览与下载")

    video_path = st.session_state.get("video_path")
    if not video_path or not Path(video_path).exists():
        st.warning("视频文件不存在，请重新合成。")
        return

    st.video(video_path)

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    st.download_button(
        label="⬇️ 下载视频",
        data=video_bytes,
        file_name=Path(video_path).name,
        mime="video/mp4",
        key="download_video_btn",
    )

    if st.button("🔄 制作新视频", key="restart_btn"):
        st.session_state["pipeline_step"] = 1
        st.session_state["narration"] = ""
        st.session_state["audio_path"] = None
        st.session_state["audio_duration"] = 0.0
        st.session_state["word_timings"] = None
        st.session_state["video_path"] = None
        st.session_state["uploaded_images"] = []
        st.rerun()


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def _render_batch_mode(selections: dict) -> None:
    """Render batch processing UI: multiple image groups → multiple videos."""
    st.header("📦 批量模式")
    st.markdown("添加多组图片，每组独立生成一个视频。")

    # Add new group from current uploaded images
    current_images = st.session_state["uploaded_images"]
    if current_images:
        group_name = st.text_input(
            "组名称", value=f"第{len(st.session_state['batch_groups']) + 1}组",
            key="batch_group_name",
        )
        if st.button("➕ 将当前图片添加为一组", key="add_batch_group_btn"):
            st.session_state["batch_groups"].append({
                "name": group_name,
                "images": list(current_images),
            })
            st.session_state["uploaded_images"] = []
            st.success(f"已添加 '{group_name}'（{len(current_images)} 张图片）")
            st.rerun()

    # Show existing groups
    groups = st.session_state["batch_groups"]
    if groups:
        st.subheader(f"已添加 {len(groups)} 组任务")
        for i, group in enumerate(groups):
            with st.expander(f"{group['name']}（{len(group['images'])} 张图片）"):
                cols = st.columns(min(len(group["images"]), 5))
                for j, img in enumerate(group["images"][:5]):
                    with cols[j]:
                        st.image(img["data"], width=80, caption=img["name"])
                if len(group["images"]) > 5:
                    st.caption(f"...共 {len(group['images'])} 张图片")
                if st.button("🗑️ 删除此组", key=f"del_group_{i}"):
                    groups.pop(i)
                    st.rerun()

        # Start batch processing
        if st.button("🚀 开始批量处理", key="start_batch_btn"):
            _run_batch_pipeline(groups, selections)
    else:
        st.info('请先上传图片，然后点击"将当前图片添加为一组"。')

    # Show batch results
    _render_batch_results()


def _run_batch_pipeline(groups: list[dict], selections: dict) -> None:
    """Execute batch pipeline for all groups."""
    cfg = _get_config()
    pipeline = PipelineManager(cfg)

    tasks = []
    for i, group in enumerate(groups):
        image_paths = _save_images_to_temp(group["images"])
        task_id = f"batch_{i}_{str(uuid.uuid4())[:6]}"
        ctx = TaskContext(
            task_id=task_id,
            images=image_paths,
            aspect_ratio=selections.get("aspect_ratio", "9:16"),
            llm_provider=selections.get("llm_provider", "qwen"),
            llm_model=selections.get("llm_model", ""),
            tts_provider=selections.get("tts_provider", "edge_tts"),
            tts_voice=selections.get("tts_voice", ""),
        )
        tasks.append(ctx)

    # Progress display
    progress_bar = st.progress(0, text="批量处理中...")
    status_container = st.container()

    completed_count = 0
    total = len(tasks)

    def on_progress(ctx: TaskContext):
        nonlocal completed_count
        if ctx.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            completed_count += 1
        pct = int((completed_count / total) * 100) if total > 0 else 0
        progress_bar.progress(
            min(pct, 100),
            text=f"已完成 {completed_count}/{total} 个任务",
        )

    try:
        results = _run_async(pipeline.run_batch(tasks, on_progress=on_progress))
        st.session_state["batch_results"] = results
        progress_bar.progress(100, text="批量处理完成！")
    except Exception as e:
        st.error(f"❌ 批量处理出错：{e}")


def _render_batch_results() -> None:
    """Display batch processing results."""
    results = st.session_state.get("batch_results", [])
    if not results:
        return

    st.subheader("📊 批量处理结果")

    completed = [r for r in results if r.status == TaskStatus.COMPLETED]
    failed = [r for r in results if r.status == TaskStatus.FAILED]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总任务数", len(results))
    with col2:
        st.metric("成功", len(completed))
    with col3:
        st.metric("失败", len(failed))

    for r in results:
        icon = "✅" if r.status == TaskStatus.COMPLETED else "❌"
        with st.expander(f"{icon} 任务 {r.task_id} - {r.status.value}"):
            if r.status == TaskStatus.COMPLETED and r.output_path:
                video_path = str(r.output_path)
                if Path(video_path).exists():
                    st.video(video_path)
                    with open(video_path, "rb") as f:
                        st.download_button(
                            f"⬇️ 下载 {r.task_id}",
                            data=f.read(),
                            file_name=Path(video_path).name,
                            mime="video/mp4",
                            key=f"dl_{r.task_id}",
                        )
            elif r.status == TaskStatus.FAILED:
                st.error(f"错误：{r.error}")


# ---------------------------------------------------------------------------
# Script Studio – 剧本工作台
# ---------------------------------------------------------------------------

def _init_script_state() -> None:
    """初始化剧本模式的 session state。"""
    if "script_topics" not in st.session_state:
        st.session_state["script_topics"] = []
    if "script_result" not in st.session_state:
        st.session_state["script_result"] = None
    if "script_step" not in st.session_state:
        st.session_state["script_step"] = 1  # 1=选领域 2=选话题 3=选角色 4=生成剧本 5=确认


def _render_script_studio(selections: dict) -> None:
    """剧本工作台主页面。"""
    _init_script_state()

    st.header("🎬 剧本工作台")
    st.markdown("选择领域 → 搜索热点 → 选角色 → AI 自动生成剧本 → 对接视频合成")

    step = st.session_state.get("script_step", 1)

    # Step 1: 选领域 + 搜热点
    _render_script_step1_domain(selections)

    # Step 2: 选话题
    if step >= 2:
        st.divider()
        _render_script_step2_topic()

    # Step 3: 选角色
    if step >= 3:
        st.divider()
        _render_script_step3_characters()

    # Step 4: 生成剧本
    if step >= 4:
        st.divider()
        _render_script_step4_generate(selections)

    # Step 5: 确认并对接 pipeline
    if step >= 5:
        st.divider()
        _render_script_step5_confirm(selections)


def _render_script_step1_domain(selections: dict) -> None:
    """步骤1：选领域 + 搜热点。"""
    from src.script.domains import load_domains

    st.subheader("📂 步骤1：选择领域")

    cfg = _get_config()
    domains = load_domains(cfg)

    col1, col2 = st.columns(2)
    with col1:
        domain_names = [d.name for d in domains]
        selected_domain_name = st.selectbox(
            "选择领域", options=domain_names, key="script_domain_select"
        )
        selected_domain = next((d for d in domains if d.name == selected_domain_name), domains[0])

    with col2:
        sub_options = selected_domain.sub_domains + ["自定义..."]
        selected_sub = st.selectbox(
            "选择子领域", options=sub_options, key="script_sub_select"
        )

    if selected_sub == "自定义...":
        selected_sub = st.text_input("输入自定义话题", key="script_custom_sub")

    if st.button("🔍 搜索热点", key="script_search_btn"):
        if not selected_sub or selected_sub == "自定义...":
            st.error("请选择或输入子领域")
            return

        cfg = _get_config()
        llm_adapter = LLMAdapter(cfg.get("llm", {}))
        provider_name = selections.get("llm_provider", "openai_compatible")
        model_name = selections.get("llm_model", "")

        try:
            provider = llm_adapter.get_provider(provider_name, model_name)
        except Exception as e:
            st.error(f"LLM 未配置: {e}")
            return

        with st.spinner("正在搜索热点话题..."):
            from src.script.hot_topic import search_hot_topics, TopicItem
            from src.search.web_searcher import WebSearcher

            search_cfg = cfg.get("search", {})
            searcher = WebSearcher(
                timeout=search_cfg.get("timeout", 10.0),
                max_results=search_cfg.get("max_results", 10),
                proxy=search_cfg.get("proxy"),
            )
            query = selected_domain.search_template.replace("{sub}", selected_sub)
            topics_raw = _run_async(_search_and_extract_topics(
                searcher, provider, selected_domain.name, selected_sub, query
            ))

            if topics_raw:
                st.session_state["script_topics"] = topics_raw
                st.session_state["script_domain"] = selected_domain
                st.session_state["script_sub"] = selected_sub
                st.session_state["script_step"] = 2
                st.rerun()
            else:
                st.warning("未找到热门话题，请尝试其他领域或子领域。")

    # 显示已搜索的话题
    topics = st.session_state.get("script_topics", [])
    if topics:
        st.success(f"找到 {len(topics)} 个热门话题")


async def _search_and_extract_topics(searcher, provider, domain_name, sub_domain, query):
    """搜索并提取话题（适配现有 WebSearcher 接口）。"""
    import json
    import re

    # 搜索
    results = await searcher.search([query])

    context = ""
    if results:
        context = "\n".join(
            f"- {r.get('title', '')}: {r.get('body', r.get('snippet', ''))}"
            for r in results[:10]
        )

    # 搜索成功时基于搜索结果提取话题，失败时让 LLM 直接生成
    topic_requirements = (
        "要求：\n"
        "1. 话题必须是一个【具体的小故事/小场景】，不能是大方向或大话题\n"
        "2. 标题要像短视频爆款标题，具体到一个人、一件事、一个瞬间\n"
        "3. 切入角度要精准到一个具体的情节点或转折点，30秒内能讲完\n"
        "4. 有情感冲击力，能在3秒内抓住观众\n\n"
        "❌ 错误示例：'婚后AA制' '婆媳关系' '职场压力'（太大太泛）\n"
        "✅ 正确示例：'她把离婚协议放在他生日蛋糕旁边' '实习生第一天就被甩了一巴掌' '妈妈偷偷把女儿的日记本烧了'\n\n"
    )

    if context:
        extract_prompt = (
            f"领域：{domain_name} - {sub_domain}\n\n"
            f"搜索结果：\n{context}\n\n"
            f"请基于搜索结果，提炼 3-5 个最适合做 30 秒动漫短剧的【具体小故事】。\n"
            f"{topic_requirements}"
            "严格输出 JSON 数组：\n"
            '[{"title": "具体故事标题（像爆款短视频标题）", "angle": "从哪个具体瞬间/情节切入", "score": 8.5, "reason": "为什么30秒能讲好这个故事"}]'
        )
    else:
        extract_prompt = (
            f"领域：{domain_name} - {sub_domain}\n\n"
            "网络搜索暂时不可用，请根据你的知识，直接推荐 3-5 个最适合做 30 秒动漫短剧的【具体小故事】。\n"
            f"{topic_requirements}"
            "严格输出 JSON 数组：\n"
            '[{"title": "具体故事标题（像爆款短视频标题）", "angle": "从哪个具体瞬间/情节切入", "score": 8.5, "reason": "为什么30秒能讲好这个故事"}]'
        )

    try:
        raw = await provider.generate_narration([], extract_prompt)
        # 解析 JSON
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        logger.warning("话题提取失败", exc_info=True)
    return []


def _render_script_step2_topic() -> None:
    """步骤2：选话题。"""
    st.subheader("🎯 步骤2：选择话题")

    topics = st.session_state.get("script_topics", [])
    if not topics:
        return

    for i, t in enumerate(topics):
        score = t.get("score", 0)
        col1, col2, col3 = st.columns([4, 2, 1])
        with col1:
            st.markdown(f"**{t.get('title', '')}** — {t.get('angle', '')}")
            st.caption(t.get("reason", ""))
        with col2:
            st.metric("热度", f"{score}/10")
        with col3:
            if st.button("选择", key=f"topic_select_{i}"):
                st.session_state["script_selected_topic"] = t
                st.session_state["script_step"] = 3
                st.rerun()

    # 自定义话题
    custom = st.text_input("或输入自定义话题", key="script_custom_topic")
    if custom and st.button("使用自定义话题", key="script_use_custom_topic"):
        st.session_state["script_selected_topic"] = {
            "title": custom, "angle": "", "score": 0, "reason": "用户自定义"
        }
        st.session_state["script_step"] = 3
        st.rerun()

    selected = st.session_state.get("script_selected_topic")
    if selected:
        st.info(f"已选话题：**{selected.get('title', '')}**")


def _render_script_step3_characters() -> None:
    """步骤3：选角色。"""
    from src.character.manager import CharacterManager

    st.subheader("🎭 步骤3：选择角色")

    mgr = CharacterManager()
    characters = mgr.list_characters()

    # 显示已有角色
    if characters:
        st.markdown("**已有角色：**")
        cols = st.columns(min(len(characters) + 1, 5))
        selected_names = st.session_state.get("script_selected_chars", [])

        for i, char in enumerate(characters):
            with cols[i % len(cols)]:
                is_selected = char.name in selected_names
                icon = "✅" if is_selected else "⬜"
                if st.button(f"{icon} {char.name}\n{char.role_type}", key=f"char_toggle_{i}"):
                    if is_selected:
                        selected_names.remove(char.name)
                    else:
                        selected_names.append(char.name)
                    st.session_state["script_selected_chars"] = selected_names
                    st.rerun()
                st.caption(char.appearance[:30] + "..." if len(char.appearance) > 30 else char.appearance)

    # 新建角色
    with st.expander("➕ 新建角色", expanded=not characters):
        new_name = st.text_input("角色名", key="new_char_name")
        new_appearance = st.text_area("外貌描述（用于出图提示词）", key="new_char_appearance",
                                       placeholder="例如：黑色长发少女，白色汉服，杏眼柳叶眉，身材纤细")
        new_role = st.selectbox("角色类型", ["narrator", "character"], key="new_char_role")

        # 音色选择
        from src.tts.adapter import TTSAdapter
        cfg = _get_config()
        tts_adapter = TTSAdapter(cfg.get("tts", {}))
        tts_provider = st.session_state.get("selections", {}).get("tts_provider", "edge_tts")
        try:
            voices = tts_adapter.list_voices(tts_provider)
        except Exception:
            voices = []
        voice_ids = [v["id"] for v in voices] if voices else [""]
        voice_labels = {v["id"]: v.get("name", v["id"]) for v in voices} if voices else {}
        new_voice = st.selectbox("绑定音色", options=voice_ids,
                                  format_func=lambda v: voice_labels.get(v, v),
                                  key="new_char_voice")

        new_emotion = st.selectbox("默认情感", ["neutral", "happy", "sad", "angry", "tender"],
                                    key="new_char_emotion")
        new_style = st.text_input("风格标签", value="anime style", key="new_char_style")

        # 参考图上传
        ref_files = st.file_uploader("上传参考图（3张，用于角色一致性）",
                                      type=["png", "jpg", "jpeg", "webp"],
                                      accept_multiple_files=True,
                                      key="new_char_refs")

        # LoRA 预留
        st.caption("💡 LoRA 模型文件：未来版本支持，当前使用参考图保持角色一致性")

        if st.button("保存角色", key="save_new_char"):
            if not new_name or not new_appearance:
                st.error("请填写角色名和外貌描述")
            else:
                from src.character.models import Character
                char = Character(
                    name=new_name,
                    appearance=new_appearance,
                    voice_type=new_voice,
                    emotion_default=new_emotion,
                    style_tags=new_style,
                    role_type=new_role,
                )
                ref_data = [(f.name, f.getvalue()) for f in ref_files] if ref_files else None
                mgr.save_character(char, ref_image_data=ref_data)
                st.success(f"角色 '{new_name}' 已保存")
                st.rerun()

    # 确认按钮
    selected_names = st.session_state.get("script_selected_chars", [])
    if selected_names:
        st.info(f"已选角色：{', '.join(selected_names)}")
        if st.button("✅ 确认角色，开始生成剧本", key="confirm_chars_btn"):
            st.session_state["script_step"] = 4
            st.rerun()
    else:
        st.warning("请至少选择 1 个角色")


def _render_script_step4_generate(selections: dict) -> None:
    """步骤4：生成剧本。"""
    st.subheader("📝 步骤4：生成剧本")

    topic_data = st.session_state.get("script_selected_topic", {})
    topic = topic_data.get("title", "")
    domain_cfg = st.session_state.get("script_domain")
    domain_name = domain_cfg.name if domain_cfg else ""
    selected_names = st.session_state.get("script_selected_chars", [])

    st.markdown(f"**话题：** {topic}　|　**领域：** {domain_name}　|　**角色：** {', '.join(selected_names)}")

    if st.button("🤖 生成剧本", key="gen_script_btn"):
        from src.character.manager import CharacterManager
        from src.script.pipeline import run_script_pipeline

        cfg = _get_config()
        llm_adapter = LLMAdapter(cfg.get("llm", {}))
        provider_name = selections.get("llm_provider", "openai_compatible")
        model_name = selections.get("llm_model", "")

        try:
            provider = llm_adapter.get_provider(provider_name, model_name)
        except Exception as e:
            st.error(f"LLM 未配置: {e}")
            return

        mgr = CharacterManager()
        characters = [mgr.get_character(n) for n in selected_names]
        characters = [c for c in characters if c is not None]

        if not characters:
            st.error("未找到选定的角色")
            return

        progress_bar = st.progress(0, text="准备中...")

        def on_progress(round_num, stage, message):
            pct = min(int((round_num - 1) * 33 + {"writer": 8, "validator": 16, "reviewer": 24, "prompter": 33}.get(stage, 0)), 99)
            progress_bar.progress(pct, text=message)

        search_context = topic_data.get("angle", "") + " " + topic_data.get("reason", "")

        result = _run_async(run_script_pipeline(
            llm_provider=provider,
            topic=topic,
            domain=domain_name,
            characters=characters,
            search_context=search_context,
            on_progress=on_progress,
        ))

        progress_bar.progress(100, text="剧本生成完成！")
        st.session_state["script_result"] = result

        if result.success:
            st.success(f"剧本生成成功（{result.rounds} 轮迭代）")
        else:
            st.warning(f"剧本经过 {result.rounds} 轮迭代未完全通过审核，可手动编辑调整")
            if result.errors:
                for err in result.errors:
                    st.caption(f"⚠️ {err}")

        if result.review and result.review.scores:
            cols = st.columns(5)
            labels = {"hook": "钩子力", "story": "故事性", "emotion": "情感", "punchline": "金句", "visual": "画面"}
            for i, (k, label) in enumerate(labels.items()):
                with cols[i]:
                    st.metric(label, f"{result.review.scores.get(k, '-')}/10")

        st.session_state["script_step"] = 5
        st.rerun()

    # 显示已生成的剧本
    result = st.session_state.get("script_result")
    if result and result.script:
        _display_script_preview(result.script)


def _display_script_preview(script) -> None:
    """显示剧本预览。"""
    st.markdown(f"### 📖 {script.title}")
    for i, scene in enumerate(script.scenes):
        with st.expander(f"场景 {i+1}：{scene.character} ({scene.emotion})", expanded=True):
            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown("**旁白：**")
                st.text_area(f"旁白_{i}", value=scene.narration, height=60,
                            key=f"script_narration_{i}")
            with col2:
                st.markdown("**画面描述：**")
                st.text_area(f"画面_{i}", value=scene.image_desc, height=60,
                            key=f"script_imgdesc_{i}")
            if scene.image_prompt:
                st.caption(f"🎨 出图提示词：{scene.image_prompt[:100]}...")


def _render_script_step5_confirm(selections: dict) -> None:
    """步骤5：确认剧本，对接现有 pipeline。"""
    st.subheader("✅ 步骤5：确认并合成视频")

    result = st.session_state.get("script_result")
    if not result or not result.script:
        st.warning("请先生成剧本")
        return

    script = result.script

    st.markdown("剧本确认后，请上传对应的图片（每个场景一张），然后进入语音合成和视频合成流程。")

    # 上传图片（每个场景一张）
    st.subheader(f"📷 上传 {len(script.scenes)} 张场景图片")
    uploaded = st.file_uploader(
        f"请上传 {len(script.scenes)} 张图片（按场景顺序）",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="script_images_upload",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 确认，进入语音合成", key="script_confirm_btn"):
            if not uploaded or len(uploaded) < len(script.scenes):
                st.error(f"请上传 {len(script.scenes)} 张图片")
                return

            # 将剧本数据注入到现有 pipeline 的 session state
            images = []
            for uf in uploaded[:len(script.scenes)]:
                images.append({"name": uf.name, "data": uf.getvalue()})

            # 收集旁白分段
            narration_segments = []
            for i, scene in enumerate(script.scenes):
                # 使用编辑后的值（如果用户修改了）
                edited = st.session_state.get(f"script_narration_{i}", scene.narration)
                narration_segments.append(edited)

            st.session_state["uploaded_images"] = images
            st.session_state["narration_segments"] = narration_segments
            st.session_state["narration"] = "\n\n".join(narration_segments)
            st.session_state["pipeline_step"] = 3  # 跳到 TTS 步骤
            st.session_state["script_mode"] = False
            st.session_state["batch_mode"] = False
            st.success("剧本已确认，切换到语音合成步骤...")
            st.rerun()

    with col2:
        if st.button("🔄 重新生成剧本", key="script_regen_btn"):
            st.session_state["script_result"] = None
            st.session_state["script_step"] = 4
            st.rerun()


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="图片转短视频解说工具",
        page_icon="🎬",
        layout="wide",
    )

    _init_session_state()

    st.title("🎬 图片转短视频解说工具")
    st.markdown("上传图片，AI自动生成解说文案和语音，合成短视频。")

    # Sidebar returns user selections for later pipeline use
    selections = _render_sidebar()

    # Store selections in session state for pipeline use
    st.session_state["selections"] = selections

    # Mode toggle: single vs batch vs script
    mode = st.radio(
        "处理模式",
        options=["单个视频", "批量模式", "剧本模式"],
        horizontal=True,
        key="mode_radio",
    )
    st.session_state["batch_mode"] = (mode == "批量模式")
    st.session_state["script_mode"] = (mode == "剧本模式")

    st.divider()

    if st.session_state.get("script_mode"):
        _render_script_studio(selections)
    elif st.session_state["batch_mode"]:
        # Batch mode: image upload + batch group management
        _render_image_upload()
        st.divider()
        _render_batch_mode(selections)
    else:
        # Single mode: step-by-step pipeline
        current_step = st.session_state.get("pipeline_step", 1)
        _render_step_indicator(current_step)
        st.divider()

        # Step 1: Image upload (always visible)
        _render_image_upload()

        # Auto-advance to step 2 when images are uploaded
        images = st.session_state["uploaded_images"]
        if images and current_step == 1:
            st.session_state["pipeline_step"] = 2
            current_step = 2

        # Step 2: Narration generation
        if current_step >= 2 and images:
            st.divider()
            _render_step_narration(selections)

        # Step 3: TTS synthesis
        if current_step >= 3:
            st.divider()
            _render_step_tts(selections)

        # Step 4: Video composition
        if current_step >= 4:
            st.divider()
            _render_step_video(selections)

        # Step 5: Preview and download
        if current_step >= 5:
            st.divider()
            _render_step_preview()


if __name__ == "__main__":
    main()

"""剧本生成流水线：编排 Writer → Validator → Reviewer → Prompter。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.character.models import Character
from src.script.models import Script
from src.script.reviewer import ReviewResult, review_script
from src.script.validator import validate_script
from src.script.writer import generate_script
from src.script.prompter import generate_prompts

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3


@dataclass
class ScriptResult:
    """剧本生成结果。"""
    script: Script | None
    review: ReviewResult | None
    rounds: int  # 实际迭代轮数
    errors: list[str]  # 最后一轮的错误（如果有）
    success: bool


async def run_script_pipeline(
    llm_provider,
    topic: str,
    domain: str,
    characters: list[Character],
    search_context: str = "",
    on_progress=None,
) -> ScriptResult:
    """执行完整的剧本生成流水线。

    Args:
        llm_provider: LLM provider
        topic: 话题
        domain: 领域
        characters: 角色列表
        search_context: 搜索素材
        on_progress: 进度回调 (round, stage, message)
    """
    character_names = [c.name for c in characters]
    feedback = ""
    last_script = None
    last_review = None
    last_errors = []

    for round_num in range(1, MAX_ROUNDS + 1):
        # ── Writer ──
        if on_progress:
            on_progress(round_num, "writer", f"第 {round_num} 轮：编剧创作中...")

        script = await generate_script(
            llm_provider, topic, domain, characters,
            search_context=search_context,
            revision_feedback=feedback,
        )

        if script is None:
            last_errors = ["Writer Agent 未能生成有效剧本"]
            feedback = "上一轮输出无法解析为 JSON，请严格按格式输出。"
            continue

        last_script = script

        # ── Validator ──
        if on_progress:
            on_progress(round_num, "validator", f"第 {round_num} 轮：格式校验中...")

        errors = validate_script(script, character_names)
        if errors:
            last_errors = errors
            feedback = "格式校验不通过，请修正以下问题：\n" + "\n".join(f"- {e}" for e in errors)
            logger.info("第 %d 轮校验不通过: %s", round_num, errors)
            continue

        # ── Reviewer ──
        if on_progress:
            on_progress(round_num, "reviewer", f"第 {round_num} 轮：内容审核中...")

        review = await review_script(llm_provider, script)
        last_review = review

        if not review.passed:
            last_errors = [review.feedback]
            feedback = f"内容审核不通过（总分 {review.total}）：{review.feedback}"
            logger.info("第 %d 轮审核不通过: %s", round_num, review.feedback)
            continue

        # ── Prompter ──
        if on_progress:
            on_progress(round_num, "prompter", f"第 {round_num} 轮：生成出图提示词...")

        await generate_prompts(llm_provider, script, characters)

        logger.info("剧本生成成功，共 %d 轮", round_num)
        return ScriptResult(
            script=script,
            review=review,
            rounds=round_num,
            errors=[],
            success=True,
        )

    # 3 轮都没通过，返回最后一版
    logger.warning("剧本 %d 轮迭代后仍未完全通过", MAX_ROUNDS)

    # 尝试为最后一版生成提示词
    if last_script:
        try:
            await generate_prompts(llm_provider, last_script, characters)
        except Exception:
            pass

    return ScriptResult(
        script=last_script,
        review=last_review,
        rounds=MAX_ROUNDS,
        errors=last_errors,
        success=False,
    )

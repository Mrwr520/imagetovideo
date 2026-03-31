"""Reviewer Agent：审核剧本内容质量。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from src.script.models import Script

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个短视频内容审核专家，专门审核 30 秒动漫短剧的剧本质量。

## 审核维度（每项 1-10 分）
1. 钩子力：第一个场景能否在 3 秒内抓住观众？
2. 故事性：中间场景是否用具体画面讲道理（而非抽象说教）？
3. 情感递进：情感是否有变化和递进？
4. 金句力：最后一个场景的收尾是否够扎心、适合截图传播？
5. 画面可行性：每个场景的画面描述是否足够具体，能让 AI 出图？

## 输出要求
严格输出 JSON，不要输出任何其他内容：
{
  "passed": true/false,
  "scores": {"hook": 8, "story": 7, "emotion": 8, "punchline": 9, "visual": 7},
  "total": 39,
  "feedback": "如果不通过，写具体的修改意见（100字以内）。通过则写空字符串。"
}

## 通过标准
- 总分 >= 35（满分 50）
- 任何单项不低于 6"""


@dataclass
class ReviewResult:
    """审核结果。"""
    passed: bool
    scores: dict
    total: float
    feedback: str


async def review_script(llm_provider, script: Script) -> ReviewResult:
    """审核剧本。"""
    script_json = json.dumps(script.to_dict(), ensure_ascii=False, indent=2)
    user_msg = f"请审核以下剧本：\n\n```json\n{script_json}\n```"

    try:
        full_prompt = SYSTEM_PROMPT + "\n\n" + user_msg
        raw = await llm_provider.generate_narration([], full_prompt)
        return _parse_review(raw)
    except Exception:
        logger.warning("剧本审核失败，默认通过", exc_info=True)
        return ReviewResult(passed=True, scores={}, total=0, feedback="审核异常，默认通过")


def _parse_review(raw: str) -> ReviewResult:
    """解析审核结果。"""
    raw = raw.strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return ReviewResult(
                passed=data.get("passed", True),
                scores=data.get("scores", {}),
                total=float(data.get("total", 0)),
                feedback=data.get("feedback", ""),
            )
        except (json.JSONDecodeError, ValueError):
            pass

    # 解析失败，默认通过
    return ReviewResult(passed=True, scores={}, total=0, feedback="审核结果解析失败，默认通过")

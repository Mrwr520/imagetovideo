"""剧本硬规则校验器（程序化，不依赖 LLM）。"""

from __future__ import annotations

from src.script.models import Script

MIN_SCENES = 3
MAX_SCENES = 5
MIN_NARRATION_LEN = 10
MAX_NARRATION_LEN = 50
MIN_IMAGE_DESC_LEN = 10


def validate_script(script: Script, character_names: list[str]) -> list[str]:
    """校验剧本格式和基本质量。

    Args:
        script: 待校验的剧本
        character_names: 合法的角色名列表

    Returns:
        错误列表，空列表表示通过
    """
    errors = []

    if not script.title:
        errors.append("缺少标题")

    if len(script.scenes) < MIN_SCENES:
        errors.append(f"场景数太少：{len(script.scenes)}，最少 {MIN_SCENES} 个")
    elif len(script.scenes) > MAX_SCENES:
        errors.append(f"场景数太多：{len(script.scenes)}，最多 {MAX_SCENES} 个")

    for i, scene in enumerate(script.scenes):
        prefix = f"场景{i+1}"

        if not scene.narration or not scene.narration.strip():
            errors.append(f"{prefix}：旁白为空")
        elif len(scene.narration) < MIN_NARRATION_LEN:
            errors.append(f"{prefix}：旁白太短（{len(scene.narration)}字，最少{MIN_NARRATION_LEN}字）")
        elif len(scene.narration) > MAX_NARRATION_LEN:
            errors.append(f"{prefix}：旁白太长（{len(scene.narration)}字，最多{MAX_NARRATION_LEN}字）")

        if not scene.character or scene.character not in character_names:
            errors.append(f"{prefix}：角色 '{scene.character}' 不在角色列表中 {character_names}")

        if not scene.image_desc or len(scene.image_desc) < MIN_IMAGE_DESC_LEN:
            errors.append(f"{prefix}：画面描述太短或为空（最少{MIN_IMAGE_DESC_LEN}字）")

        if not scene.emotion:
            errors.append(f"{prefix}：缺少情感标注")

    return errors

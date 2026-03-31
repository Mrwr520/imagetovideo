# 动漫短剧系统 - 技术设计

## 架构原则
- **纯新增，不修改现有代码**：所有新模块放在 src/script/、src/character/ 目录
- app.py 仅在处理模式 radio 中新增"剧本模式"选项，现有功能不受影响
- 复用现有模块：WebSearcher、LLMAdapter、TTSAdapter、VideoComposer、SubtitleGenerator

## 新增目录结构
```
src/
  script/                  # 新增：剧本系统
    __init__.py
    domains.py             # 领域配置读取
    hot_topic.py           # 热点搜索 Agent
    writer.py              # 编剧 Agent
    reviewer.py            # 审核 Agent
    prompter.py            # 提示词 Agent
    validator.py           # 硬规则校验（非 Agent）
    models.py              # 数据模型（Scene, Script）
  character/               # 新增：角色管理
    __init__.py
    manager.py             # 角色 CRUD
    models.py              # 角色数据模型
characters/                # 新增：角色数据存储目录
  _template/               # 角色目录模板
    config.json
```

## 数据模型

### Script（剧本）
```python
@dataclass
class Scene:
    narration: str          # 旁白文本（喂给 TTS）
    character: str          # 说话角色名（匹配音色）
    emotion: str            # 情感标注（TTS emotion 参数）
    image_desc: str         # 画面描述（Writer 输出）
    image_prompt: str       # 出图提示词（Prompter 输出）

@dataclass
class Script:
    title: str
    topic: str
    domain: str
    scenes: list[Scene]
    style: str              # 统一画风标签
```

### Character（角色）
```python
@dataclass
class Character:
    name: str               # 角色名
    appearance: str         # 外貌描述（用于提示词）
    voice_type: str         # 火山引擎音色 ID
    emotion_default: str    # 默认情感
    ref_images: list[Path]  # 参考图路径（3张）
    lora_path: Path | None  # 预留：LoRA 模型路径
    style_tags: str         # 风格标签
```

## Agent 设计

### Writer Agent
- 输入：topic, domain, characters, search_context
- System prompt：内置爆款叙事公式 + JSON 输出约束
- 输出：Script JSON

### Validator（代码，非 Agent）
- 校验：JSON 解析、场景数 3-5、旁白字数 10-40、character 在角色列表中、image_desc > 15 字
- 不通过：返回具体错误列表

### Reviewer Agent
- 输入：Script JSON + 原始搜索素材
- System prompt：短视频观众视角审核
- 输出：通过 / 不通过 + 修改意见

### Prompter Agent
- 输入：审核通过的 Script + 角色外貌描述
- 职责：image_desc → image_prompt（精确出图提示词）
- 统一风格标签、负面提示词

## 与现有 pipeline 的对接
剧本确认后，输出的数据直接映射到现有 TaskContext：
- script.scenes[i].narration → narration_segments[i]
- script.scenes[i].character + emotion → TTS 音色和情感参数切换
- 图片（出图或手动上传）→ TaskContext.images

## 预留接口（未来版本）
- Character.lora_path：LoRA 模型文件路径，当前版本 UI 显示但不实现训练
- ComfyUI API 集成：出图步骤当前版本为手动上传，预留 API 调用接口
- Wan2GP 集成：图生视频步骤当前版本复用现有静态图合成，预留视频生成接口
- 角色 LoRA 训练模块：预留 src/character/trainer.py 接口定义

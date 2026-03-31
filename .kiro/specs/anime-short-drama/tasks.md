# 动漫短剧系统 - 开发任务

## Phase 1：角色管理 + 剧本生成（当前版本）

### Task 1: 数据模型和角色管理
- [x] 创建 src/character/models.py（Character 数据类）
- [x] 创建 src/character/manager.py（角色 CRUD：创建、读取、列表、删除）
- [x] 创建 characters/ 目录和默认旁白员角色
- [x] 预留 lora_path 字段

### Task 2: 领域配置
- [x] 创建 src/script/domains.py（内置 10 大领域 + config.toml 扩展）
- [x] 支持大类 + 子领域 + 搜索关键词模板

### Task 3: 热点搜索
- [x] 创建 src/script/hot_topic.py（复用 WebSearcher + LLM 提取话题）
- [x] 输出：话题列表 + 热度评分 + 角度建议

### Task 4: 剧本生成 3 Agent
- [x] 创建 src/script/models.py（Scene, Script 数据类）
- [x] 创建 src/script/writer.py（Writer Agent）
- [x] 创建 src/script/validator.py（硬规则校验）
- [x] 创建 src/script/reviewer.py（Reviewer Agent）
- [x] 创建 src/script/prompter.py（Prompter Agent）
- [x] 创建 src/script/pipeline.py（最多 3 轮迭代编排）

### Task 5: Streamlit UI - 剧本工作台
- [x] app.py 处理模式 radio 新增"剧本模式"（不动现有模式）
- [x] 步骤1：领域选择 + 搜索热点 UI
- [x] 步骤2：话题选择 UI
- [x] 步骤3：角色选择/新建 UI（含参考图上传、音色绑定、LoRA 预留提示）
- [x] 步骤4：剧本生成 + 审核分数展示 + 预览/编辑 UI
- [x] 步骤5：确认后对接现有 pipeline（注入 narration_segments + images → TTS → 字幕 → 合成）

## Phase 2：AI 出图集成（未来版本）
- [ ] 接入 ComfyUI API 或通义万相 API
- [ ] Phantom 多图参考工作流
- [ ] 出图结果预览和单张重新生成
- [ ] 预留 LoRA 加载接口

## Phase 3：图生视频集成（未来版本）
- [ ] Wan2GP 命令行集成
- [ ] 或 Kling/Hailuo API Adapter
- [ ] FFmpeg xfade 转场
- [ ] 视频片段预览和重新生成

## Phase 4：增强功能（未来版本）
- [ ] 角色 LoRA 训练模块（src/character/trainer.py）
- [ ] 首尾帧控制（FLF2V）场景衔接
- [ ] 批量剧本生产（选领域 → 一键生成 N 条）
- [ ] 多角色对话场景音色自动切换优化

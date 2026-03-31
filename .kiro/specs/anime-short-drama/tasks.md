# 动漫短剧系统 - 开发任务

## Phase 1：角色管理 + 剧本生成（已完成）

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

## Phase 2：AI 出图集成

### Task 6: 出图 Provider 抽象层

- [x] 6.1 创建 src/image_gen/init_module.py
- [x] 6.2 创建 src/image_gen/base.py（BaseImageProvider 抽象基类 + ImageGenResult 数据类）
- [x] 6.3 创建 src/image_gen/adapter.py（ImageGenAdapter 适配器，支持多 provider 切换）

### Task 7: 通义万相 API 集成

- [x] 7.1 创建 src/image_gen/wanx.py（通义万相 WanxProvider）
- [x] 7.2 实现文生图接口（text-to-image，支持风格参数）
- [x] 7.3 实现角色参考图接口（Phantom 多图参考，保持角色一致性）
- [x] 7.4 config.toml 添加 [image_gen.wanx] 配置段

### Task 8: ComfyUI API 集成（预留）

- [x] 8.1 创建 src/image_gen/comfyui.py（ComfyUIProvider）
- [x] 8.2 实现 workflow JSON 模板加载和参数注入
- [x] 8.3 实现异步轮询出图结果
- [x] 8.4 config.toml 添加 [image_gen.comfyui] 配置段

### Task 9: 出图 Pipeline 编排

- [x] 9.1 创建 src/image_gen/pipeline.py（批量出图 + 单张重试）
- [x] 9.2 Prompter Agent 输出的 image_prompt 直接喂给出图 API
- [x] 9.3 角色参考图自动注入（从 Character.ref_images 读取）
- [x] 9.4 出图结果缓存（避免重复生成）

### Task 10: 出图 UI

- [x] 10.1 剧本工作台新增"AI出图"步骤（步骤4.5，在剧本确认后、TTS之前）
- [x] 10.2 每个场景显示出图结果 + "重新生成"按钮
- [x] 10.3 支持手动替换图片（上传覆盖）
- [x] 10.4 出图 provider 选择器（侧边栏）

## Phase 3：图生视频集成

### Task 11: 视频生成 Provider 抽象层

- [x] 11.1 创建 src/video_gen/init_module.py
- [x] 11.2 创建 src/video_gen/base.py（BaseVideoGenProvider 抽象基类）
- [x] 11.3 创建 src/video_gen/adapter.py（VideoGenAdapter 适配器）

### Task 12: Wan2GP 本地集成

- [x] 12.1 创建 src/video_gen/wan2gp.py（Wan2GPProvider）
- [x] 12.2 实现 I2V（图生视频）命令行调用封装
- [x] 12.3 实现显存管理（8GB 优化：低分辨率 + 分段生成）
- [x] 12.4 config.toml 添加 [video_gen.wan2gp] 配置段

### Task 13: Kling/Hailuo API 集成（预留）

- [x] 13.1 创建 src/video_gen/kling.py（KlingProvider）
- [x] 13.2 创建 src/video_gen/hailuo.py（HailuoProvider）
- [x] 13.3 实现异步提交 + 轮询结果

### Task 14: 视频片段合成

- [x] 14.1 FFmpeg xfade 转场封装（src/video/transitions.py）
- [x] 14.2 多片段拼接 + 转场 + 配音 + 字幕 → 最终视频
- [x] 14.3 替换现有静态图合成为动态视频合成（可选切换）

### Task 15: 图生视频 UI

- [x] 15.1 剧本工作台新增"生成视频片段"步骤
- [x] 15.2 每个场景显示视频预览 + "重新生成"按钮
- [x] 15.3 视频生成 provider 选择器（侧边栏）
- [x] 15.4 进度条和显存监控提示

## Phase 4：增强功能

### Task 16: 角色 LoRA 训练模块

- [x] 16.1 创建 src/character/trainer.py（LoRA 训练接口）
- [x] 16.2 集成 kohya_ss 或 SimpleTuner 训练脚本
- [x] 16.3 训练参数自动配置（适配 8GB 显存）
- [x] 16.4 训练进度 UI + 模型管理

### Task 17: 首尾帧控制

- [x] 17.1 FLF2V 场景衔接（上一场景末帧 → 下一场景首帧）
- [x] 17.2 自动提取关键帧作为下一场景参考

### Task 18: 批量生产

- [x] 18.1 选领域 → 一键生成 N 条剧本
- [x] 18.2 批量出图 + 批量生成视频
- [x] 18.3 批量任务队列和进度管理

### Task 19: 多角色对话优化

- [x] 19.1 根据 character 字段自动切换 TTS 音色
- [x] 19.2 根据 emotion 字段设置 TTS 情感参数
- [x] 19.3 对话场景字幕样式区分（不同角色不同颜色）

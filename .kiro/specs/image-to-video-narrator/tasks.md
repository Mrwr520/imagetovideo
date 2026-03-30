# 实现计划：图片转短视频解说工具

## 概述

基于模块化流水线架构，按自底向上的顺序实现各模块：先搭建项目骨架和配置管理，再实现核心服务层（字幕、视频、LLM、TTS适配器），最后实现流水线编排和Web界面。每个模块实现后紧跟测试任务，确保增量验证。

## 任务

- [x] 1. 搭建项目结构与配置管理
  - [x] 1.1 创建项目目录结构和依赖文件
    - 创建 `src/`、`src/llm/`、`src/tts/`、`src/video/`、`src/subtitle/`、`tests/` 目录及 `__init__.py`
    - 创建 `requirements.txt`，包含：streamlit, httpx, moviepy, Pillow, edge-tts, tomli, tomli-w, hypothesis, pytest
    - 创建 `app.py` 入口文件骨架
    - _Requirements: 7.1, 8.1_

  - [x] 1.2 实现 ConfigManager（配置管理器）
    - 创建 `src/config_manager.py`
    - 实现 `load()`：读取TOML配置文件，文件不存在时生成默认模板
    - 实现 `save()`：将配置字典写入TOML文件
    - 实现 `validate()`：校验必要字段，返回缺失字段名称列表
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 1.3 编写 ConfigManager 属性测试
    - **Property 13: 配置文件Round-Trip一致性**
    - **Property 14: 配置校验缺失字段检测**
    - **Validates: Requirements 7.1, 7.2**

- [x] 2. 实现字幕生成模块
  - [x] 2.1 实现 SubtitleGenerator
    - 创建 `src/subtitle/generator.py`
    - 实现 `split_text()`：按标点符号和语义边界分割文本，每段不超过15个中文字符
    - 实现 `assign_timestamps()`：按字符数比例分配起止时间
    - 实现 `generate()`：组合分割和时间分配，返回 SubtitleSegment 列表
    - 定义 SubtitleSegment 和 SubtitleStyle 数据类
    - _Requirements: 5.1, 5.3, 5.4_

  - [ ]* 2.2 编写 SubtitleGenerator 属性测试
    - **Property 9: 字幕时间轴覆盖与无重叠**
    - **Property 10: 字幕分行长度限制**
    - **Validates: Requirements 5.1, 5.4**

- [x] 3. 实现视频合成模块
  - [x] 3.1 实现 Ken Burns 效果
    - 创建 `src/video/ken_burns.py`
    - 实现图片缩放、平移、淡入淡出动画效果函数
    - 定义 KenBurnsParams 数据类
    - _Requirements: 4.3_

  - [x] 3.2 实现 VideoComposer
    - 创建 `src/video/composer.py`
    - 实现 `calculate_image_durations()`：根据图片数量和总时长均匀分配每张图片展示时长
    - 实现 `create_image_clips()`：为每张图片创建带Ken Burns效果的视频片段
    - 实现 `add_subtitles()`：将字幕硬编码到视频画面底部
    - 实现 `mix_audio()`：混合解说语音和背景音乐（音量20%-30%，循环/淡出逻辑）
    - 实现 `compose()`：组合所有步骤输出H.264 MP4文件
    - 定义 VideoConfig 数据类，支持9:16和16:9分辨率映射
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.2, 6.3, 6.4_

  - [ ]* 3.3 编写 VideoComposer 属性测试
    - **Property 7: 画面比例分辨率映射**
    - **Property 8: 图片展示时长分配不变量**
    - **Property 11: BGM音量混合比例**
    - **Property 12: BGM循环播放时长匹配**
    - **Validates: Requirements 4.2, 4.4, 6.2, 6.3**

- [x] 4. Checkpoint - 确保核心模块测试通过
  - 确保所有测试通过，如有问题请向用户确认。

- [x] 5. 实现 LLM 适配器模块
  - [x] 5.1 实现 BaseLLMProvider 和 OpenAICompatibleProvider
    - 创建 `src/llm/base.py`：定义 BaseLLMProvider 抽象基类
    - 创建 `src/llm/openai_compat.py`：实现 OpenAI 兼容的 Provider
    - 图片编码为base64，构造多模态API请求
    - 支持通过参数指定模型名称
    - _Requirements: 2.1, 2.2_

  - [x] 5.2 实现 WenxinProvider
    - 创建 `src/llm/wenxin.py`：实现百度文心一言独立鉴权和API格式
    - 支持通过参数指定模型名称
    - _Requirements: 2.2_

  - [x] 5.3 实现 LLMAdapter
    - 创建 `src/llm/adapter.py`
    - 注册所有 Provider（qwen, deepseek, glm, wenxin, openai_compatible）
    - 实现 `get_provider()`：根据名称和可选模型参数返回 Provider 实例
    - 实现 `list_models()`：返回指定 provider 的可用模型列表
    - 实现 `list_providers()`：返回已配置的 provider 列表
    - 实现提示词模板渲染逻辑（支持 style、duration、tone 参数）
    - _Requirements: 2.2, 2.3_

  - [ ]* 5.4 编写 LLM 适配器属性测试
    - **Property 3: 适配器注册完整性（LLM部分）**
    - **Property 4: 提示词模板渲染完整性**
    - **Validates: Requirements 2.2, 2.3**

- [x] 6. 实现 TTS 适配器模块
  - [x] 6.1 实现 BaseTTSProvider 和 EdgeTTSProvider
    - 创建 `src/tts/base.py`：定义 BaseTTSProvider 抽象基类和 TTSResult 数据类
    - 创建 `src/tts/edge_tts_provider.py`：实现 Edge TTS（兜底方案）
    - 实现 `synthesize()` 和 `list_voices()` 方法
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 6.2 实现其他 TTS Provider
    - 创建 `src/tts/cosyvoice.py`、`src/tts/fish_speech.py`、`src/tts/chattts.py`、`src/tts/melotts.py`
    - 每个 Provider 实现 `synthesize()` 和 `list_voices()` 方法
    - 通过 HTTP API 调用对应的本地/远程 TTS 服务
    - _Requirements: 3.2, 3.4_

  - [x] 6.3 实现 TTSAdapter（含回退逻辑）
    - 创建 `src/tts/adapter.py`
    - 注册所有 TTS Provider
    - 实现 `synthesize()`：调用指定 provider，失败时自动回退到 Edge TTS
    - 实现 `list_providers()` 和 `list_voices()` 方法
    - _Requirements: 3.2, 3.5_

  - [ ]* 6.4 编写 TTS 适配器属性测试
    - **Property 3: 适配器注册完整性（TTS部分）**
    - **Property 5: TTS输出格式合规性**
    - **Property 6: TTS回退机制可靠性**
    - **Validates: Requirements 3.2, 3.3, 3.5**

- [x] 7. 实现文件格式验证
  - [x] 7.1 实现图片文件格式验证逻辑
    - 在 `src/pipeline.py` 中实现文件格式校验函数
    - 接受 JPG/JPEG、PNG、WEBP 格式，拒绝其他格式并返回错误提示
    - _Requirements: 1.1, 1.3_

  - [ ]* 7.2 编写文件格式验证属性测试
    - **Property 1: 文件格式验证正确性**
    - **Property 2: 图片顺序保持不变量**
    - **Validates: Requirements 1.1, 1.2, 1.3**

- [x] 8. Checkpoint - 确保所有适配器模块测试通过
  - 确保所有测试通过，如有问题请向用户确认。

- [x] 9. 实现 PipelineManager（流水线编排）
  - [x] 9.1 实现 PipelineManager
    - 创建 `src/pipeline.py` 中的 PipelineManager 类（与7.1的验证函数在同一文件）
    - 定义 TaskContext 和 TaskStatus 数据类
    - 实现 `run()`：按顺序执行解说词生成→语音合成→字幕生成→视频合成
    - 实现 `run_batch()`：批量执行多个任务，单个失败不影响其他任务
    - 实现进度回调机制
    - _Requirements: 8.2, 8.4_

  - [ ]* 9.2 编写批量任务隔离性属性测试
    - **Property 15: 批量任务隔离性**
    - **Validates: Requirements 8.2, 8.4**

- [x] 10. 实现 Streamlit Web 界面
  - [x] 10.1 实现主界面布局
    - 在 `app.py` 中实现 Streamlit 界面
    - 侧边栏：LLM provider/模型选择、TTS provider/音色选择、画面比例选择
    - 主区域：图片上传（支持多文件，拖拽排序）、图片预览列表
    - 配置管理页面：编辑和保存 config.toml
    - _Requirements: 8.1, 1.4, 7.3_

  - [x] 10.2 实现流水线交互流程
    - 步骤1：上传图片并预览
    - 步骤2：点击生成解说词，展示结果并允许编辑
    - 步骤3：点击合成语音
    - 步骤4：选择背景音乐（可选），点击合成视频
    - 步骤5：视频预览和下载
    - 支持批量模式：多组图片同时提交，显示进度
    - _Requirements: 2.4, 8.1, 8.2, 8.3_

- [x] 11. 最终 Checkpoint - 确保所有测试通过
  - 确保所有测试通过，如有问题请向用户确认。

## 备注

- 标记 `*` 的任务为可选任务，可跳过以加快MVP开发
- 每个任务引用了具体的需求编号，确保可追溯性
- Checkpoint任务用于增量验证，确保每个阶段的代码质量
- 属性测试验证通用正确性属性，单元测试验证具体示例和边界情况

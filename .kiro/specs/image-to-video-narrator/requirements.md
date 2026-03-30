# 需求文档

## 简介

图片转短视频解说工具：用户提供一组图片，系统通过AI大语言模型（多模态）分析图片内容并生成解说文案，再通过国产TTS语音模型将文案转为语音，最终将图片、语音、字幕、背景音乐合成为适配短视频平台（抖音、快手等）的短视频。本工具为个人自用，提供简洁的Web操作界面。

## 术语表

- **Pipeline（流水线）**：从图片输入到视频输出的完整处理流程
- **LLM_Adapter（大模型适配器）**：统一封装不同大语言模型API调用的适配层
- **TTS_Adapter（语音合成适配器）**：统一封装不同语音合成模型API调用的适配层
- **Video_Composer（视频合成器）**：负责将图片、音频、字幕合成为最终视频的模块
- **Subtitle_Generator（字幕生成器）**：根据解说词文本和语音时长生成带时间轴的字幕的模块
- **Narration（解说词）**：AI根据图片内容生成的解说文案文本
- **Ken_Burns_Effect（肯·伯恩斯效果）**：对静态图片施加缩放和平移动画，使画面产生动态感的转场技术
- **Aspect_Ratio（画面比例）**：视频的宽高比，竖屏为9:16，横屏为16:9

## 需求

### 需求 1：图片输入与管理

**用户故事：** 作为用户，我希望能够上传一组图片作为视频素材，以便系统根据这些图片生成短视频。

#### 验收标准

1. WHEN 用户通过Web界面上传图片 THEN THE Pipeline SHALL 接受 JPG、PNG、WEBP 格式的图片文件
2. WHEN 用户上传图片 THEN THE Pipeline SHALL 按照用户指定的顺序排列图片
3. WHEN 用户上传的文件不是支持的图片格式 THEN THE Pipeline SHALL 拒绝该文件并返回明确的格式错误提示
4. WHEN 用户上传图片后 THEN THE Pipeline SHALL 显示图片缩略图预览列表，允许用户调整顺序或删除

### 需求 2：AI解说词生成

**用户故事：** 作为用户，我希望AI能根据图片内容自动生成解说文案，以便快速制作有吸引力的短视频解说。

#### 验收标准

1. WHEN 用户提交图片并选择LLM模型后 THEN THE LLM_Adapter SHALL 将图片发送至所选多模态大模型并返回解说词文本
2. THE LLM_Adapter SHALL 支持以下模型后端：通义千问（Qwen）、DeepSeek、智谱AI（GLM）、百度文心一言、以及任何兼容OpenAI API格式的模型
3. WHEN 调用LLM生成解说词时 THEN THE LLM_Adapter SHALL 使用可配置的提示词模板，模板中包含视频风格、时长、语气等参数
4. WHEN LLM返回解说词后 THEN THE Pipeline SHALL 在Web界面展示解说词文本，允许用户手动编辑后再进入下一步
5. IF LLM调用失败或超时 THEN THE LLM_Adapter SHALL 返回包含错误原因的错误信息，并允许用户重试

### 需求 3：语音合成

**用户故事：** 作为用户，我希望系统能将解说词转为自然流畅的语音，以便用作视频的旁白配音。

#### 验收标准

1. WHEN 用户确认解说词并选择TTS模型后 THEN THE TTS_Adapter SHALL 将解说词文本合成为音频文件
2. THE TTS_Adapter SHALL 支持以下语音合成后端：CosyVoice、Fish-Speech、ChatTTS、MeloTTS、Edge TTS
3. WHEN 语音合成完成后 THEN THE TTS_Adapter SHALL 输出WAV或MP3格式的音频文件
4. WHEN 用户选择TTS模型时 THEN THE TTS_Adapter SHALL 提供可选的音色列表供用户选择
5. IF 语音合成失败 THEN THE TTS_Adapter SHALL 自动回退到 Edge TTS 作为兜底方案，并通知用户

### 需求 4：视频合成

**用户故事：** 作为用户，我希望系统能将图片、语音、字幕合成为一个完整的短视频，以便直接发布到短视频平台。

#### 验收标准

1. WHEN 图片和语音素材准备就绪后 THEN THE Video_Composer SHALL 将图片序列与语音音频合成为MP4格式视频
2. THE Video_Composer SHALL 支持竖屏（9:16，1080x1920）和横屏（16:9，1920x1080）两种输出分辨率
3. WHEN 合成视频时 THEN THE Video_Composer SHALL 对每张图片施加 Ken_Burns_Effect 转场动画，包括缩放、平移、淡入淡出效果
4. WHEN 合成视频时 THEN THE Video_Composer SHALL 根据语音总时长自动计算每张图片的展示时长，使图片均匀分布在整个视频时间线上
5. WHEN 视频合成完成后 THEN THE Video_Composer SHALL 输出编码为H.264的MP4文件，视频码率不低于4Mbps

### 需求 5：字幕生成与叠加

**用户故事：** 作为用户，我希望视频自动带有字幕，以便观众在静音状态下也能理解视频内容。

#### 验收标准

1. WHEN 解说词和语音时长确定后 THEN THE Subtitle_Generator SHALL 根据文本内容和语音时长生成带时间轴的字幕数据
2. WHEN 合成视频时 THEN THE Video_Composer SHALL 将字幕以硬字幕方式渲染到视频画面底部区域
3. THE Subtitle_Generator SHALL 支持配置字幕字体、字号、颜色和描边样式
4. WHEN 单条字幕文本过长时 THEN THE Subtitle_Generator SHALL 自动按标点符号或语义边界进行分行，每行不超过15个中文字符

### 需求 6：背景音乐

**用户故事：** 作为用户，我希望能为视频添加背景音乐，以便提升视频的观感和吸引力。

#### 验收标准

1. WHEN 用户选择背景音乐文件后 THEN THE Video_Composer SHALL 将背景音乐混合到视频音轨中
2. WHEN 混合背景音乐时 THEN THE Video_Composer SHALL 将背景音乐音量降低至解说语音音量的20%-30%，确保解说清晰可辨
3. WHEN 背景音乐时长短于视频时长时 THEN THE Video_Composer SHALL 自动循环播放背景音乐直至视频结束
4. WHEN 背景音乐时长长于视频时长时 THEN THE Video_Composer SHALL 在视频结束前2秒开始淡出背景音乐

### 需求 7：配置管理

**用户故事：** 作为用户，我希望通过配置文件管理各模型的API密钥和参数，以便灵活切换不同的模型后端。

#### 验收标准

1. THE Pipeline SHALL 使用TOML格式的配置文件存储所有模型的API地址、密钥和默认参数
2. WHEN 配置文件中缺少必要字段时 THEN THE Pipeline SHALL 在启动时报告具体缺失的配置项名称
3. WHEN 用户在Web界面修改配置后 THEN THE Pipeline SHALL 将修改持久化到配置文件中

### 需求 8：Web界面与批量处理

**用户故事：** 作为用户，我希望通过简洁的Web界面操作整个流程，并支持批量生成多个视频。

#### 验收标准

1. THE Pipeline SHALL 提供基于Streamlit的Web界面，包含图片上传、LLM/TTS模型及模型名称选择、解说词编辑、视频预览和下载功能
2. WHEN 用户提交批量任务时 THEN THE Pipeline SHALL 支持同时处理多组图片，每组独立生成一个视频
3. WHEN 批量任务执行中 THEN THE Pipeline SHALL 在Web界面显示每个任务的处理进度和状态
4. WHEN 任一批量子任务失败时 THEN THE Pipeline SHALL 继续处理剩余任务，并在最终结果中标记失败任务及其错误原因

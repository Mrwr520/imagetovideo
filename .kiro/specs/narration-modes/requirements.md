# Requirements Document

## Introduction

本功能为现有的图片转短视频解说工具新增"解说模式选择"和"视频时长选择"能力。当前系统仅支持"按图说话"模式（根据图片内容直接生成解说词）。本次扩展将新增"新闻解说"模式（结合网络搜索结果生成新闻风格解说词），并允许用户选择目标视频时长，使解说词长度、语音合成和视频合成均适配所选时长。

## Glossary

- **Narration_Mode_Selector**: Streamlit UI 中供用户选择解说模式的组件
- **Duration_Selector**: Streamlit UI 中供用户选择目标视频时长的组件
- **Describe_Images_Mode**: "按图说话"解说模式，根据图片内容直接生成解说词
- **News_Commentary_Mode**: "新闻解说"解说模式，先从图片提取关键词，再搜索网络获取相关新闻上下文，最后结合图片和搜索结果生成新闻风格解说词
- **Keyword_Extractor**: 使用 LLM 从上传图片中提取新闻关键词的组件
- **Web_Searcher**: 使用关键词调用搜索 API 获取相关新闻和上下文信息的组件
- **Prompt_Builder**: 根据解说模式、时长、图片数量等参数构建 LLM 提示词的组件
- **LLM_Adapter**: 管理 LLM Provider 选择和提示词渲染的适配器
- **Pipeline_Manager**: 编排图片到视频完整流水线的管理器
- **Config_Manager**: 管理 TOML 格式配置文件的组件

## Requirements

### Requirement 1: 解说模式选择

**User Story:** As a 内容创作者, I want to 在 UI 中选择不同的解说模式, so that I can 根据不同场景（商业推广或新闻报道）生成合适风格的解说词。

#### Acceptance Criteria

1. WHEN the user reaches the narration generation step, THE Narration_Mode_Selector SHALL display two mode options: "按图说话"（Describe Images）and "新闻解说"（News Commentary）
2. THE Narration_Mode_Selector SHALL default to "按图说话" mode
3. WHEN the user selects "按图说话" mode, THE system SHALL use the existing image-based narration generation logic without web search
4. WHEN the user selects "新闻解说" mode, THE system SHALL trigger the keyword extraction and web search pipeline before generating narration

### Requirement 2: 视频时长选择

**User Story:** As a 内容创作者, I want to 选择目标视频时长, so that I can 生成符合不同平台和场景需求的视频。

#### Acceptance Criteria

1. WHEN the user reaches the narration generation step, THE Duration_Selector SHALL display duration options: 30 秒, 60 秒, 90 秒, 120 秒, 180 秒
2. THE Duration_Selector SHALL default to 60 秒
3. WHEN the user selects a target duration, THE Prompt_Builder SHALL include the selected duration in the LLM prompt to guide narration length
4. WHEN the user selects a target duration, THE Pipeline_Manager SHALL pass the duration context through the narration generation, TTS synthesis, and video composition stages

### Requirement 3: 关键词提取

**User Story:** As a 内容创作者 using 新闻解说 mode, I want the system to 自动从图片中提取新闻关键词, so that the system can 搜索相关的新闻上下文。

#### Acceptance Criteria

1. WHEN the user selects "新闻解说" mode and triggers narration generation, THE Keyword_Extractor SHALL send the uploaded images to the LLM with a keyword extraction prompt
2. WHEN the LLM returns keywords, THE Keyword_Extractor SHALL parse the response into a list of keyword strings
3. IF the LLM returns an empty or unparseable keyword response, THEN THE Keyword_Extractor SHALL return a fallback empty list and log a warning
4. THE Keyword_Extractor SHALL extract between 3 and 10 keywords from the images

### Requirement 4: 网络搜索集成

**User Story:** As a 内容创作者 using 新闻解说 mode, I want the system to 搜索网络获取相关新闻信息, so that the generated narration is 基于真实的新闻上下文。

#### Acceptance Criteria

1. WHEN the Keyword_Extractor provides keywords, THE Web_Searcher SHALL query a web search API using those keywords
2. WHEN the search API returns results, THE Web_Searcher SHALL extract title and snippet text from each result
3. IF the search API request fails or times out, THEN THE Web_Searcher SHALL return an empty result list and log a warning without blocking the pipeline
4. THE Web_Searcher SHALL limit search results to a maximum of 10 items per query
5. WHEN search results are obtained, THE Web_Searcher SHALL serialize the results into a structured text format suitable for inclusion in an LLM prompt

### Requirement 5: 新闻解说词生成

**User Story:** As a 内容创作者, I want the system to 结合图片内容和网络搜索结果生成新闻风格解说词, so that the narration is 信息丰富且具有新闻报道风格。

#### Acceptance Criteria

1. WHEN in "新闻解说" mode with search results available, THE Prompt_Builder SHALL construct a prompt that includes both the image content references and the serialized search results
2. WHEN in "新闻解说" mode, THE Prompt_Builder SHALL instruct the LLM to generate narration in a news commentary style
3. WHEN in "新闻解说" mode with no search results (due to failure or empty keywords), THE Prompt_Builder SHALL fall back to generating narration based on image content alone with a news commentary tone
4. THE Prompt_Builder SHALL preserve the existing JSON template approach for structuring the narration output across all modes

### Requirement 6: 提示词构建

**User Story:** As a developer, I want the Prompt_Builder to 根据模式和时长参数构建不同的提示词, so that the LLM receives 适当的指令来生成对应风格和长度的解说词。

#### Acceptance Criteria

1. WHEN rendering a prompt for "按图说话" mode, THE Prompt_Builder SHALL produce a prompt that instructs the LLM to generate narration based on image content in a promotional style
2. WHEN rendering a prompt for "新闻解说" mode, THE Prompt_Builder SHALL produce a prompt that includes search context and instructs the LLM to generate narration in a news commentary style
3. THE Prompt_Builder SHALL include the target duration in all generated prompts to guide narration length
4. THE Prompt_Builder SHALL include the JSON template structure in all generated prompts
5. FOR ALL valid combinations of mode and duration, THE Prompt_Builder SHALL produce a non-empty prompt string containing the JSON template

### Requirement 7: 配置扩展

**User Story:** As a developer, I want the configuration to 支持新解说模式和搜索相关的设置, so that the system behavior can be 通过配置文件调整。

#### Acceptance Criteria

1. THE Config_Manager SHALL support a web search configuration section containing API endpoint and timeout settings
2. THE Config_Manager SHALL support narration mode default settings in the general configuration section
3. WHEN the configuration file lacks the new web search section, THE Config_Manager SHALL provide sensible default values

### Requirement 8: 流水线集成

**User Story:** As a developer, I want the Pipeline_Manager to 支持不同解说模式的完整流水线, so that 模式选择能贯穿从解说词生成到视频合成的全流程。

#### Acceptance Criteria

1. WHEN running the pipeline in "按图说话" mode, THE Pipeline_Manager SHALL execute the existing narration generation flow without web search
2. WHEN running the pipeline in "新闻解说" mode, THE Pipeline_Manager SHALL execute keyword extraction, web search, and news-style narration generation in sequence
3. WHEN running the pipeline with a specified target duration, THE Pipeline_Manager SHALL pass the duration to the prompt builder and through subsequent stages
4. IF any step in the news commentary pipeline fails (keyword extraction or web search), THEN THE Pipeline_Manager SHALL fall back to image-only narration generation and log the failure

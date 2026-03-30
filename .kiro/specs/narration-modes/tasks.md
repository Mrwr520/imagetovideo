# Implementation Plan: Narration Modes

## Overview

Incrementally add narration mode selection (按图说话 / 新闻解说) and video duration selection to the existing image-to-video narration tool. Implementation follows the architecture from the design document, building new modules and extending existing ones with minimal disruption.

## Tasks

- [x] 1. Create NarrationMode enum and PromptBuilder
  - [x] 1.1 Create `src/narration_mode.py` with `NarrationMode` enum (DESCRIBE_IMAGES, NEWS_COMMENTARY)
    - _Requirements: 1.1, 1.2_
  - [x] 1.2 Create `src/llm/prompt_builder.py` with `PromptBuilder` class
    - Implement `build()` method that accepts mode, image_count, duration, search_context, style, tone
    - Generate JSON template with `narration_1` through `narration_{image_count}` keys
    - For DESCRIBE_IMAGES mode: use existing promotional-style prompt template
    - For NEWS_COMMENTARY mode: use news-style prompt template with search context section
    - For NEWS_COMMENTARY mode with empty search context: fall back to image-only news tone prompt
    - Include duration in all prompts
    - _Requirements: 2.3, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 6.5_
  - [ ]* 1.3 Write property tests for PromptBuilder
    - **Property 1: Prompt always contains target duration**
    - **Validates: Requirements 2.3, 6.3**
    - **Property 2: Prompt always contains JSON template**
    - **Validates: Requirements 5.4, 6.4, 6.5**
    - **Property 6: News mode prompt includes search context**
    - **Validates: Requirements 5.1**
  - [ ]* 1.4 Write unit tests for PromptBuilder
    - Test describe_images mode produces promotional-style prompt
    - Test news_commentary mode produces news-style prompt with search context
    - Test news_commentary mode with empty search context falls back gracefully
    - _Requirements: 5.2, 5.3, 6.1, 6.2_

- [x] 2. Implement KeywordExtractor
  - [x] 2.1 Create `src/llm/keyword_extractor.py` with `KeywordExtractor` class
    - Accept a `BaseLLMProvider` in constructor
    - Implement `extract(images: list[Path]) -> list[str]` method
    - Build keyword extraction prompt instructing LLM to return JSON `{"keywords": [...]}`
    - Parse LLM response JSON, extract keyword list (3-10 items)
    - Implement `parse_keywords(raw: str) -> list[str]` as a static/standalone parsing function
    - On parse failure or empty response, return empty list and log warning
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - [ ]* 2.2 Write property test for keyword parsing
    - **Property 3: Keyword parsing produces string list from valid JSON**
    - **Validates: Requirements 3.2, 3.3**
  - [ ]* 2.3 Write unit tests for KeywordExtractor
    - Test parsing valid JSON with keywords list
    - Test parsing empty string returns empty list
    - Test parsing invalid JSON returns empty list
    - _Requirements: 3.2, 3.3_

- [ ] 3. Implement WebSearcher
  - [x] 3.1 Create `src/search/__init__.py` and `src/search/web_searcher.py`
    - Define `SearchResult` dataclass with title, snippet, url fields
    - Implement `WebSearcher` class with configurable timeout and max_results
    - Implement `search(keywords: list[str]) -> list[SearchResult]` using `duckduckgo-search` package
    - Join keywords with spaces for the search query
    - Limit results to max_results (default 10)
    - On failure/timeout, return empty list and log warning
    - Implement `format_for_prompt(results: list[SearchResult]) -> str` to serialize results for LLM prompt
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - [ ]* 3.2 Write property tests for WebSearcher
    - **Property 4: Search result count is bounded**
    - **Validates: Requirements 4.4**
    - **Property 5: Search result serialization contains all result information**
    - **Validates: Requirements 4.5**
    - **Property 7: Search result parsing extracts title and snippet**
    - **Validates: Requirements 4.2**
  - [ ]* 3.3 Write unit tests for WebSearcher
    - Test format_for_prompt with empty list returns empty string
    - Test search with empty keywords returns empty list
    - _Requirements: 4.3_

- [x] 4. Checkpoint - Core modules complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Extend configuration and pipeline
  - [x] 5.1 Extend `DEFAULT_CONFIG` in `src/config_manager.py`
    - Add `[search]` section with engine, timeout, max_results defaults
    - Add `default_narration_mode` and `default_duration` to `[general]` section
    - _Requirements: 7.1, 7.2, 7.3_
  - [x] 5.2 Extend `TaskContext` in `src/pipeline.py`
    - Add `narration_mode: NarrationMode` field (default DESCRIBE_IMAGES)
    - Add `target_duration: int` field (default 60)
    - Add `search_results: list[dict] | None` field (default None)
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 5.3 Extend `PipelineManager.run()` in `src/pipeline.py`
    - Before narration generation, check narration_mode
    - For NEWS_COMMENTARY: run KeywordExtractor → WebSearcher → PromptBuilder with search context
    - For DESCRIBE_IMAGES: use existing flow with PromptBuilder
    - Pass target_duration to PromptBuilder
    - On keyword extraction or search failure, fall back to image-only narration with warning log
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [x] 5.4 Update `LLMAdapter.render_prompt()` to delegate to `PromptBuilder`
    - Add mode and search_context parameters with backward-compatible defaults
    - Internally create PromptBuilder and call build()
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 6. Update Streamlit UI
  - [x] 6.1 Update `_render_step_narration()` in `app.py`
    - Add narration mode radio selector (按图说话 / 新闻解说) with Chinese captions before the generate button
    - Add duration selectbox (30, 60, 90, 120, 180 秒) defaulting to 60
    - Store selections in session_state
    - _Requirements: 1.1, 1.2, 2.1, 2.2_
  - [x] 6.2 Update narration generation logic in `_render_step_narration()`
    - When mode is 新闻解说: run KeywordExtractor, WebSearcher, then generate with search context
    - When mode is 按图说话: use existing generation logic
    - Pass selected duration to prompt builder
    - Show progress for keyword extraction and web search steps
    - _Requirements: 1.3, 1.4, 2.3, 2.4_
  - [x] 6.3 Update `_init_session_state()` in `app.py`
    - Add `narration_mode` and `target_duration` to session state initialization
    - _Requirements: 1.2, 2.2_
  - [x] 6.4 Update sidebar default settings display
    - Read default_narration_mode and default_duration from config for initial values
    - _Requirements: 7.2_

- [x] 7. Checkpoint - Integration complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Add `duckduckgo-search` dependency
  - [x] 8.1 Add `duckduckgo-search` to project dependencies (requirements.txt or pyproject.toml)
    - _Requirements: 4.1_

- [x] 9. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using `hypothesis`
- Unit tests validate specific examples and edge cases using `pytest`

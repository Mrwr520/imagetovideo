# imagetovideo — 小说→漫画视频生成系统

## 项目概述

本项目的核心能力：**写小说 → 漫画分镜 → AI出图 → 多角色配音 → 视频合成**。
两套引擎协同工作：

| 引擎 | 目录 | 职责 |
|------|------|------|
| **Novel-OS** | `novel-os/` | 多Agent协作写小说（Architect→Scribe→Editor→Guardian） |
| **Video管线** | `src/`, `generate_auto_news.py` | 图片生成+TTS配音+字幕+视频合成 |

## 如何恢复上下文（新对话启动）

当用户说"继续写下一章"、"下一章"、"继续"时，执行以下步骤：

### 1. 首先读取项目状态

```bash
python next_chapter.py status
```

这会显示：
- 当前写到了第几章
- Novel-OS 内部状态
- 已生成的视频文件

### 2. 关键文件速查

| 想了解什么 | 读哪个文件 |
|-----------|-----------|
| 当前有哪些书在写 | `ls characters/` |
| 《X》的角色和音色 | `characters/<书名>/characters.json` |
| 《X》写到哪了 | `characters/<书名>/progress.json` |
| 小说完整状态(角色/情节/章节) | `novel-os/outputs/state/story_state.json` |
| 第N章正文 | `novel-os/outputs/manuscript/chapter_00N_revised.md` |
| 第N章章纲 | `novel-os/outputs/chapter_00N_outline.md` |
| Novel-OS 配置 | `novel-os/.env` |
| 漫画分镜JSON | `output/<书名>_ch*_manga.json` |

### 3. 继续写下一章

```bash
# 只写小说
python next_chapter.py write

# 写小说 + 生成视频
python next_chapter.py write --video
```

`next_chapter.py write` 会自动：
1. 检测最新的已完成章节号
2. 用中文 Agent 提示词调用 DeepSeek
3. 走完整流程：规划→写作→编辑→验证→批准
4. 可选：自动调用 `novel_to_manga.py` 转化为漫画分镜
5. 可选：自动调用 `generate_auto_news.py` 生成视频

### 4. 初始化新书

```bash
python next_chapter.py init --title "书名" --genre "仙侠"
python next_chapter.py character add --name "主角" --role protagonist --appearance "..." --personality "..."
```

### 5. 手动转化已有章节为漫画分镜

```bash
python novel_to_manga.py --project novel-os/outputs --chapter 1 --chars characters/<书名>/characters.json --title "书名" --generate-video
```

## 技术细节

- **LLM**: DeepSeek (`deepseek-chat`, 128K上下文), key 在 `novel-os/.env`
- **TTS**: 火山引擎, 配置在 `config.toml` → `[tts.volcano]`
- **图片生成**: gpt-image-2 API, key 在 `generate_auto_news.py` 顶部
- **视频合成**: moviepy + FFmpeg, `src/video/composer.py`
- **Agent 提示词**: `novel-os/agents/*/prompt_zh.md` (中文网文版)
- **原版英文提示词**: `novel-os/agents/*/prompt_en.md` (备份)

## 已有项目

| 书名 | 类型 | 状态 |
|------|------|------|
| 凡人修仙传 | 仙侠同人 | EP01已出(704-710章), EP02待出 |
| 剑道独尊 | 仙侠原创 | 第1章已完成(测试项目) |

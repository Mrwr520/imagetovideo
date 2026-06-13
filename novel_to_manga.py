"""小说章节 → 漫画分镜 JSON 桥接脚本。

读取 Novel-OS 输出的章节正文 + story_state.json，
调用 LLM 将小说内容转化为漫画分镜 JSON，
直接喂给 generate_auto_news.py 生成视频。

用法:
    # 转化最新章节（自动检测）
    python novel_to_manga.py --project novel-os/outputs

    # 指定项目目录和章节
    python novel_to_manga.py --project novel-os/outputs --chapter 3

    # 指定角色配置文件
    python novel_to_manga.py --project novel-os/outputs --chars characters/my_novel/characters.json

    # 转化后自动生成视频
    python novel_to_manga.py --project novel-os/outputs --generate-video
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import ssl
import http.client
from pathlib import Path
from datetime import datetime


# ═══════════════════════════════════════════════════
# LLM 调用（复用现有 API）
# ═══════════════════════════════════════════════════

def call_llm(system_prompt: str, user_prompt: str, api_key: str = None,
             api_base: str = None, model: str = None) -> str:
    """调用 OpenAI 兼容 API。"""
    api_key = api_key or "sk-44a8a80025324b83a88ccee290697399"
    api_base = api_base or "https://api.deepseek.com/v1"
    model = model or "deepseek-chat"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 16384,
        "temperature": 0.8,
    }).encode("utf-8")

    url = f"{api_base}/chat/completions"
    url_obj = urllib.parse.urlparse(url)
    context = ssl.create_default_context()
    conn = http.client.HTTPSConnection(url_obj.hostname, timeout=300, context=context)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        conn.request("POST", url_obj.path, body=payload, headers=headers)
        if conn.sock:
            conn.sock.settimeout(300)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")

        if resp.status == 200:
            result = json.loads(data)
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content
        else:
            raise RuntimeError(f"LLM 调用失败 (HTTP {resp.status}): {data[:500]}")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════
# 章节读取
# ═══════════════════════════════════════════════════

def find_latest_chapter(project_dir: Path) -> tuple[int, str]:
    """找到最新的已完成/已编辑章节。"""
    manuscript_dir = project_dir / "manuscript"

    # 优先 revised，其次 draft
    chapters = []
    for pattern in ["chapter_*_revised.md", "chapter_*_draft.md"]:
        for f in manuscript_dir.glob(pattern):
            num = int(f.stem.split("_")[1])
            chapters.append((num, f))

    if not chapters:
        raise FileNotFoundError(f"在 {manuscript_dir} 中未找到章节文件")

    chapters.sort(key=lambda x: x[0])
    latest_num, latest_path = chapters[-1]
    text = latest_path.read_text(encoding="utf-8")
    return latest_num, text


def read_chapter(project_dir: Path, chapter_num: int) -> str:
    """读取指定章节。"""
    manuscript_dir = project_dir / "manuscript"
    for suffix in ["_revised.md", "_draft.md"]:
        path = manuscript_dir / f"chapter_{chapter_num:03d}{suffix}"
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"未找到第 {chapter_num} 章")


def read_story_state(project_dir: Path) -> dict:
    """读取故事状态 JSON。"""
    state_path = project_dir / "state" / "story_state.json"
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def read_characters(char_path: Path) -> dict:
    """读取角色配置（兼容现有 characters.json 格式）。"""
    if char_path.exists():
        return json.loads(char_path.read_text(encoding="utf-8"))
    return {}


# ═══════════════════════════════════════════════════
# 小说 → 分镜 转化
# ═══════════════════════════════════════════════════

MANGA_ADAPTER_PROMPT = """你是一位专业的漫画分镜师。你的任务是把小说章节转化成动态漫画视频的分镜脚本。

## 核心规则

1. 把章节拆成 8-12 个分镜场景
2. 每个分镜 = 一张漫画图片 + 对应语音台词
3. 打斗场景拆细（挑衅→出手→交锋→变招→决胜），情感场景也拆细
4. 每句台词 ≤ 25 字，简短有力像漫画对话气泡
5. 图片提示词必须包含：角色外观 + 动作 + 构图 + 中文对话气泡 + 风格标签
6. 构图交替：特写（情感）/ 半身（对话）/ 中景（动作）/ 远景（场景建立）
7. 开场要有冲击力，结尾必须有悬念钩子
8. **人物一致性（极其重要）**：使用下文 ROLE APPEARANCE REFERENCE 中每个角色的 reference_appearance，逐字复制到 image_prompt 中。不要改写、简化或修改。同一角色在所有面板中外观必须一致。

## 输出格式约束

你必须输出一个 JSON 数组，放在 ```json ``` 代码块中：

```json
[
  {
    "panel": 1,
    "speaker": "角色名",
    "dialogue": "台词文本（中文，≤25字）",
    "image_prompt": "英文提示词 = [角色的 reference_appearance 逐字复制] + [动作/表情/构图描述] + Chinese dialogue bubble with text '对话内容' + Chinese manga panel style, dramatic lighting, high quality anime art, consistent character design"
  }
]
```

**关键约束：**
- dialogue 字段：中文台词，≤25字
- image_prompt：必须把对应 speaker 的 reference_appearance 完整复制到最前面，然后加动作/构图/气泡
- speaker 必须是 ROLE APPEARANCE REFERENCE 中列出的名字
- 输出纯 JSON 数组，放在 ```json ``` 代码块中"""

# User prompt template
MANGA_USER_PROMPT = """请将以下小说章节转化为漫画分镜 JSON 数组。

## 小说信息
- 标题：{title}
- 章节：第 {chapter_num} 章
- 画风：{style}

## ROLE APPEARANCE REFERENCE（人物一致性强制规则）

以下每个角色的 reference_appearance 必须在 image_prompt 中逐字复制，不得修改。
同一角色在所有分镜中外观完全相同，仅表情/动作随剧情变化。

{ref_appearances}

## 角色设定（完整描述，含性格和音色）
{characters_info}

## 小说正文
---
{chapter_text}
---

## 输出要求
生成 8-12 个分镜。每个 image_prompt 必须以对应 speaker 的 reference_appearance 开头。
直接输出 JSON 数组（放在 ```json ``` 代码块中），严格按照格式约束。"""


def build_manga_prompt(chapter_text: str, characters_info: str,
                       ref_appearances: str,
                       title: str = "", chapter_num: int = 1,
                       style: str = "Chinese xianxia manga") -> str:
    """构建漫画分镜转化的 prompt（严格约束输出格式 + 人物一致性）。"""
    return MANGA_USER_PROMPT.format(
        title=title or "未命名",
        chapter_num=chapter_num,
        style=style,
        characters_info=characters_info,
        ref_appearances=ref_appearances,
        chapter_text=chapter_text[:10000],
    )


def _extract_json(text: str) -> dict | None:
    """从 LLM 响应中提取 JSON，处理多种格式问题。"""
    import re

    text = text.strip()

    # 方式1：从 ```json ... ``` 代码块提取（DeepSeek 常见输出）
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        inner = m.group(1).strip()
        result = _extract_json(inner)
        if result:
            return result

    # 方式2：直接解析（自动包装列表）
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            print(f"  🔧 从响应中提取到 {len(parsed)} 个 panel 的 JSON 数组")
            return {"panels": parsed}
        return parsed
    except json.JSONDecodeError:
        pass

    # 方式3：尝试提取数组 [...]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            arr = json.loads(text[start:end + 1])
            if isinstance(arr, list):
                print(f"  🔧 从响应中提取到 {len(arr)} 个 panel 的 JSON 数组")
                return {"panels": arr}
        except json.JSONDecodeError:
            pass

    # 方式4：提取 {...} 包裹的单个对象
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 方式5：多个独立对象 → 包装成数组
    objects = []
    depth = 0
    obj_start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start != -1:
                try:
                    obj = json.loads(text[obj_start:i + 1])
                    objects.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = -1

    if objects:
        print(f"  🔧 从响应中提取到 {len(objects)} 个独立 JSON 对象，合并为数组")
        return {"panels": objects}

    return None


def _lookup_voice(speaker: str, characters: dict) -> str:
    """根据角色名查找对应的音色ID。"""
    # 提取内层角色字典（兼容 characters.json 格式）
    if "characters" in characters:
        inner = characters["characters"]
    else:
        inner = characters

    if not speaker or speaker in ("旁白", "（风声与远处兽吼）", "（风声与兽吼）"):
        narrator = inner.get("旁白", {})
        if isinstance(narrator, dict):
            return narrator.get("voice", "")
        return ""

    for name, info in inner.items():
        if name == speaker and isinstance(info, dict):
            return info.get("voice", "")
    return ""


def _normalize_to_news_format(manga_data: dict, title: str, chapter_num: int,
                             characters: dict = None) -> dict:
    """将漫画分镜数据转换为 generate_auto_news.py 所需的格式。"""
    if characters is None:
        characters = {}

    panels = manga_data.get("panels", [])

    # 如果已经是 news 格式，直接返回
    if "news" in manga_data or "opening" in manga_data:
        return manga_data

    # 如果是 panels 格式，转换（字段名已由 prompt 约束固定）
    if panels:
        news_items = []
        for i, panel in enumerate(panels):
            narration = panel.get("dialogue", "")
            image_prompt = panel.get("image_prompt", "")
            speaker = panel.get("speaker", "")
            panel_id = panel.get("panel", i + 1)
            headline = f"场景{panel_id}"

            voice = _lookup_voice(speaker, characters)

            news_items.append({
                "headline": headline,
                "narration": narration,
                "image_prompt": image_prompt,
                "voice": voice,
            })

        # 生成标题和描述
        video_title = f"《{title}》第{chapter_num}集"
        video_desc = manga_data.get("description", f"《{title}》漫画视频第{chapter_num}集")

        # 使用第一个 panel 作为开场
        opening = news_items[0] if news_items else {"narration": "", "image_prompt": ""}
        # 使用最后一个 panel 作为收尾
        closing = news_items[-1] if len(news_items) > 1 else {"narration": "", "image_prompt": ""}

        # 中间部分是新闻主体
        middle = news_items[1:-1] if len(news_items) > 2 else news_items

        return {
            "title": video_title,
            "description": video_desc,
            "opening": opening,
            "news": middle,
            "closing": closing,
        }

    # 未知格式，原样返回
    return manga_data


def convert_to_manga(chapter_text: str, characters: dict,
                     title: str = "", chapter_num: int = 1,
                     style: str = "Chinese xianxia manga") -> dict:
    """调用 LLM 将章节转化为漫画分镜 JSON。"""
    # 构建角色描述文本（含 reference_appearance 用于人物一致性）
    chars_text = ""
    ref_appearances = ""
    # 提取内层角色字典（兼容 characters.json 格式）
    inner_chars = characters.get("characters", characters) if characters else {}
    if inner_chars:
        for name, info in inner_chars.items():
            if isinstance(info, dict) and "appearance" in info:
                chars_text += f"\n### {name}\n"
                chars_text += f"- 完整外观：{info['appearance']}\n"
                if "voice" in info:
                    chars_text += f"- 音色ID：{info['voice']}\n"
                if "voice_name" in info:
                    chars_text += f"- 音色名：{info['voice_name']}\n"
                if "personality" in info:
                    chars_text += f"- 性格：{info['personality']}\n"

                # 收集 reference_appearance
                ref = info.get("reference_appearance", info.get("appearance", ""))
                if ref:
                    ref_appearances += f"\n**{name}**: {ref}\n"

    user_prompt = build_manga_prompt(chapter_text, chars_text, ref_appearances,
                                      title, chapter_num, style)

    print(f"  🎬 正在将第 {chapter_num} 章转化为漫画分镜...")
    print(f"     章节长度: {len(chapter_text)} 字")
    print(f"     角色数量: {len(characters)} 个")

    response = call_llm(MANGA_ADAPTER_PROMPT, user_prompt)

    # 提取 JSON（LLM 可能在前后加文字）
    response = response.strip()
    # 保存原始响应用于调试
    debug_path = Path("output/manga_debug_response.txt")
    debug_path.write_text(response, encoding="utf-8")

    # 尝试多种方式提取 JSON
    manga_script = _extract_json(response)
    if manga_script is None:
        print(f"  ❌ JSON 解析失败，原始响应已保存到 {debug_path}")
        raise ValueError("无法从 LLM 响应中提取有效的 JSON")

    # 转换为视频管线所需的格式
    return _normalize_to_news_format(manga_script, title, chapter_num, characters)


# ═══════════════════════════════════════════════════
# 角色自动生成
# ═══════════════════════════════════════════════════

def extract_characters_from_state(story_state: dict) -> dict:
    """从 Novel-OS story_state.json 提取角色信息，生成 characters.json 格式。"""
    characters = {}

    for char_data in story_state.get("characters", {}).values():
        if not isinstance(char_data, dict):
            continue
        name = char_data.get("full_name", "")
        if not name:
            continue

        characters[name] = {
            "appearance": char_data.get("physical_description", ""),
            "personality": f"{char_data.get('strength', '')}，{char_data.get('weakness', '')}",
            "voice": "",
            "voice_name": "",
            "age": str(char_data.get("age", "")),
        }

    return characters


# ═══════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="小说章节 → 漫画分镜 JSON 转化器")
    parser.add_argument("--project", type=str, required=True,
                        help="Novel-OS 项目目录 (outputs/)")
    parser.add_argument("--chapter", type=int, default=0,
                        help="章节号（0=自动检测最新）")
    parser.add_argument("--chars", type=str, default="",
                        help="角色 JSON 文件路径")
    parser.add_argument("--title", type=str, default="",
                        help="小说标题")
    parser.add_argument("--style", type=str, default="Chinese xianxia manga",
                        help="画风标签")
    parser.add_argument("--generate-video", action="store_true",
                        help="转化后自动生成视频")
    parser.add_argument("--output", type=str, default="",
                        help="输出 JSON 路径")
    args = parser.parse_args()

    project_dir = Path(args.project)
    if not project_dir.exists():
        print(f"❌ 项目目录不存在: {project_dir}")
        sys.exit(1)

    # 1. 读取章节
    if args.chapter > 0:
        chapter_text = read_chapter(project_dir, args.chapter)
        chapter_num = args.chapter
    else:
        chapter_num, chapter_text = find_latest_chapter(project_dir)

    print(f"📖 读取第 {chapter_num} 章 ({len(chapter_text)} 字)")

    # 2. 读取角色
    if args.chars:
        characters = read_characters(Path(args.chars))
        print(f"👥 从 {args.chars} 加载 {len(characters)} 个角色")
    else:
        # 尝试从 story_state 提取
        story_state = read_story_state(project_dir)
        characters = extract_characters_from_state(story_state)
        if characters:
            print(f"👥 从 story_state.json 提取 {len(characters)} 个角色")
        else:
            print("⚠️  未找到角色信息，将让 AI 自由发挥")
            characters = {}

    # 3. 读取标题
    title = args.title
    if not title:
        story_state = read_story_state(project_dir)
        title = story_state.get("metadata", {}).get("title", "")

    # 4. 转化
    manga_script = convert_to_manga(
        chapter_text, characters, title, chapter_num, args.style
    )

    # 5. 保存
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = Path(args.output)
    else:
        safe_title = title.replace(" ", "_").replace("/", "_") if title else "novel"
        output_path = output_dir / f"{safe_title}_ch{chapter_num:03d}_manga.json"

    output_path.write_text(
        json.dumps(manga_script, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"✅ 漫画分镜已保存: {output_path}")

    # 6. 可选：生成视频
    if args.generate_video:
        print("\n🎬 自动生成视频...")
        import subprocess
        result = subprocess.run([
            "python", "generate_auto_news.py",
            "--script", str(output_path),
            "--output-name", output_path.stem,
        ])
        if result.returncode == 0:
            print("✅ 视频生成完成！")
        else:
            print(f"❌ 视频生成失败 (exit code {result.returncode})")

    return output_path


if __name__ == "__main__":
    main()

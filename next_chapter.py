"""一键"下一章"——写小说 + 转化漫画分镜 + 生成视频。

用法:
    # 初始化新书
    python next_chapter.py init --title "我的修仙模拟器" --genre "仙侠"

    # 写下一章（自动检测进度）
    python next_chapter.py write

    # 写下一章 + 生成视频
    python next_chapter.py write --video

    # 查看进度
    python next_chapter.py status
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime


# ═══════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════

NOVEL_OS_DIR = Path(__file__).parent / "novel-os"
NOVEL_TO_MANGA = Path(__file__).parent / "novel_to_manga.py"
GENERATE_VIDEO = Path(__file__).parent / "generate_auto_news.py"
OUTPUT_DIR = Path(__file__).parent / "output"
CHARACTERS_DIR = Path(__file__).parent / "characters"

# 中文 Agent 提示词映射
AGENT_OVERRIDES = {
    "scribe": "prompt_zh.md",
    "architect": "prompt_zh.md",
    "editor": "prompt_zh.md",
    "continuity_guardian": "prompt_zh.md",
}


def setup_env():
    """确保环境变量正确（从 config.toml 或现有 .env 读取）。"""
    env_path = NOVEL_OS_DIR / ".env"
    if env_path.exists():
        return

    # 从现有 config.toml 提取配置
    import tomllib
    config_path = Path(__file__).parent / "config.toml"
    if config_path.exists():
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        llm_cfg = config.get("llm", {}).get("openai_compatible", {})
        env_content = f"""NOVEL_OS_LLM_PROVIDER=openai_compatible
NOVEL_OS_BASE_URL={llm_cfg.get('api_base', '')}
NOVEL_OS_API_KEY={llm_cfg.get('api_key', '')}
NOVEL_OS_MODEL={llm_cfg.get('default_model', 'gpt-5.4')}
NOVEL_OS_MAX_TOKENS=16384
"""
        env_path.write_text(env_content)
        print("✅ 已从 config.toml 创建 .env 配置")


def use_chinese_prompts():
    """将中文 Agent 提示词切换为当前使用的提示词。"""
    for agent_name, zh_file in AGENT_OVERRIDES.items():
        zh_path = NOVEL_OS_DIR / "agents" / agent_name / zh_file
        prompt_path = NOVEL_OS_DIR / "agents" / agent_name / "prompt.md"
        if zh_path.exists():
            # 备份英文原版
            en_backup = NOVEL_OS_DIR / "agents" / agent_name / "prompt_en.md"
            if prompt_path.exists() and not en_backup.exists():
                prompt_path.rename(en_backup)
            # 复制中文版为当前使用版
            prompt_path.write_text(zh_path.read_text(encoding="utf-8"), encoding="utf-8")
    print("✅ 已切换为中文网文 Agent 提示词")


def get_project_name() -> str:
    """从 outputs/state/story_state.json 获取项目名。"""
    state_path = NOVEL_OS_DIR / "outputs" / "state" / "story_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return state.get("metadata", {}).get("title", "novel")
    return "novel"


def get_latest_chapter_num() -> int:
    """获取最新的已完成章节号。"""
    manuscript_dir = NOVEL_OS_DIR / "outputs" / "manuscript"
    if not manuscript_dir.exists():
        return 0

    max_num = 0
    for f in manuscript_dir.glob("chapter_*_revised.md"):
        try:
            num = int(f.stem.split("_")[1])
            max_num = max(max_num, num)
        except (ValueError, IndexError):
            pass
    if max_num == 0:
        for f in manuscript_dir.glob("chapter_*_draft.md"):
            try:
                num = int(f.stem.split("_")[1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                pass
    return max_num


def run_novel_os_command(cmd: list[str]) -> int:
    """在 Novel-OS 目录中运行命令。"""
    env = os.environ.copy()
    # 确保 core 目录在 PYTHONPATH 中
    core_path = str(NOVEL_OS_DIR / "core")
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{core_path};{existing_path}" if existing_path else core_path
    full_cmd = [sys.executable, "-m", "core.orchestrator"] + cmd
    result = subprocess.run(full_cmd, cwd=str(NOVEL_OS_DIR), env=env)
    return result.returncode


def cmd_init(args):
    """初始化新小说项目。"""
    setup_env()
    use_chinese_prompts()

    total_chapters = getattr(args, 'chapters', 60)
    print(f"\n🆕 初始化新书: 《{args.title}》")
    print(f"   类型: {args.genre}")
    print(f"   计划章节: {total_chapters} 章")
    if total_chapters >= 500:
        print(f"   📚 长篇模式：支持 {total_chapters} 章，记忆系统自动分层压缩")

    # 初始化 Novel-OS 项目
    ret = run_novel_os_command([
        "init", "--title", args.title, "--genre", args.genre
    ])
    if ret != 0:
        print("❌ 初始化失败")
        return ret

    # 创建角色目录
    char_dir = CHARACTERS_DIR / args.title
    char_dir.mkdir(parents=True, exist_ok=True)

    # 创建默认角色配置模板
    default_chars = {
        "series": args.title,
        "style": "Chinese xianxia manga style, dramatic lighting, detailed character art, dynamic action poses",
        "voice": "zh_male_ruyayichen_uranus_bigtts",
        "episodes_per_arc": 5,
        "images_per_episode": 8,
        "duration_target_seconds": 60,
        "characters": {
            "旁白": {
                "voice": "zh_male_ruyayichen_uranus_bigtts",
                "voice_name": "儒雅逸辰（沉稳大气）",
                "note": "用于叙事过渡"
            }
        }
    }
    chars_path = char_dir / "characters.json"
    chars_path.write_text(
        json.dumps(default_chars, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 创建进度文件
    progress_path = char_dir / "progress.json"
    progress = {
        "series": args.title,
        "current_chapter": 0,
        "total_chapters": total_chapters,
        "episodes": [],
        "next_chapter_plan": {
            "chapter": 1,
            "title_hint": "",
            "key_events": []
        }
    }
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 写入完整世界观模板
    bible_path = NOVEL_OS_DIR / "outputs" / "story_bible.md"
    bible_path.write_text(_generate_world_bible(args.title, args.genre, total_chapters),
                          encoding="utf-8")
    print(f"   📖 世界观模板: {bible_path}")

    # 生成大纲（传入章节数）
    run_novel_os_command([
        "plan", "outline", "--chapters", str(total_chapters),
        "--words", str(total_chapters * 2500)
    ])

    print(f"\n✅ 项目已初始化！")
    print(f"   角色目录: {char_dir}")
    print(f"   角色配置: {chars_path}")
    print(f"\n📝 下一步：添加角色")
    print(f"   python next_chapter.py character add --name \"主角名\" --role protagonist")
    print(f"\n   或者直接开始写第一章：")
    print(f"   python next_chapter.py write")


def cmd_character(args):
    """管理角色。"""
    char_dir = CHARACTERS_DIR / get_project_name()
    chars_path = char_dir / "characters.json"

    if args.action == "add":
        if not chars_path.exists():
            print("❌ 请先初始化项目: python next_chapter.py init --title \"书名\" --genre \"类型\"")
            return 1

        chars = json.loads(chars_path.read_text(encoding="utf-8"))

        # 添加角色
        chars["characters"][args.name] = {
            "appearance": args.appearance or "",
            "name_tag": args.name,
            "voice": args.voice or "zh_male_m191_uranus_bigtts",
            "voice_name": args.voice_name or "",
            "age": args.age or "",
            "personality": args.personality or "",
        }

        chars_path.write_text(
            json.dumps(chars, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # 同时添加到 Novel-OS
        run_novel_os_command([
            "character", "add", "--name", args.name, "--role", args.role
        ])

        print(f"✅ 角色已添加: {args.name}")

    elif args.action == "list":
        if chars_path.exists():
            chars = json.loads(chars_path.read_text(encoding="utf-8"))
            print("\n👥 角色列表:")
            print("-" * 50)
            for name, info in chars.get("characters", {}).items():
                voice_name = info.get("voice_name", info.get("voice", ""))
                personality = info.get("personality", "")
                print(f"  {name}")
                if voice_name:
                    print(f"    音色: {voice_name}")
                if personality:
                    print(f"    性格: {personality}")
                print()


def cmd_write(args):
    """写下一章。"""
    setup_env()
    use_chinese_prompts()

    # 1. 获取进度
    current = get_latest_chapter_num()
    next_ch = current + 1

    if current == 0:
        print("📝 开始写第一章...")
        # 先生成大纲
        print("  🏗️  生成故事大纲...")
        run_novel_os_command(["plan", "outline", "--chapters", str(args.total_chapters)])
        print("  📋 规划第一章...")
        run_novel_os_command(["plan", "chapter", "--number", "1"])
    else:
        print(f"📝 第 {current} 章已完成，开始写第 {next_ch} 章...")

    # 2. 规划章节
    if next_ch > 1:
        run_novel_os_command(["plan", "chapter", "--number", str(next_ch)])

    # 3. 写章节
    print(f"\n✍️  执笔人正在写第 {next_ch} 章...")
    ret = run_novel_os_command(["write", "--chapter", str(next_ch)])
    if ret != 0:
        print("❌ 写作失败")
        return ret

    # 4. 编辑
    print(f"\n🔍 编辑审核第 {next_ch} 章...")
    run_novel_os_command(["edit", "--chapter", str(next_ch), "--mode", "line"])

    # 5. 验证
    print(f"\n🛡️  连续性检查...")
    run_novel_os_command(["validate", "--chapter", str(next_ch)])

    # 6. 批准
    print(f"\n✅ 批准第 {next_ch} 章...")
    run_novel_os_command(["approve", "--chapter", str(next_ch)])

    # 7. 更新进度
    project_name = get_project_name()
    progress_path = CHARACTERS_DIR / project_name / "progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        progress["current_chapter"] = next_ch
        progress["episodes"].append({
            "chapter": next_ch,
            "date": datetime.now().strftime("%Y-%m-%d"),
        })
        progress["next_chapter_plan"] = {
            "chapter": next_ch + 1,
            "title_hint": "",
            "key_events": []
        }
        progress_path.write_text(
            json.dumps(progress, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    print(f"\n✅ 第 {next_ch} 章完成！")

    # 8. 可选：生成视频
    if args.video:
        print(f"\n🎬 转化为漫画分镜并生成视频...")
        chars_path = CHARACTERS_DIR / project_name / "characters.json"
        novel_cmd = [
            sys.executable, str(NOVEL_TO_MANGA),
            "--project", str(NOVEL_OS_DIR / "outputs"),
            "--chapter", str(next_ch),
            "--title", project_name,
        ]
        if chars_path.exists():
            novel_cmd += ["--chars", str(chars_path)]
        novel_cmd += ["--generate-video"]

        result = subprocess.run(novel_cmd)
        if result.returncode == 0:
            print(f"\n🎉 第 {next_ch} 章视频已生成！")
        else:
            print(f"\n⚠️  视频生成失败，但章节已保存。可手动运行：")
            print(f"   python novel_to_manga.py --project novel-os/outputs --chapter {next_ch} --chars {chars_path} --generate-video")


def cmd_status(args):
    """查看进度。"""
    project_name = get_project_name()
    current = get_latest_chapter_num()

    print("\n" + "=" * 50)
    print(f"📖 《{project_name}》")
    print("=" * 50)
    print(f"  已完成: {current} 章")

    progress_path = CHARACTERS_DIR / project_name / "progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        print(f"  已生成视频: {len(progress.get('episodes', []))} 集")
        if progress.get("episodes"):
            for ep in progress["episodes"]:
                print(f"    - 第{ep['chapter']}章 ({ep.get('date', '')})")
        if progress.get("next_chapter_plan"):
            plan = progress["next_chapter_plan"]
            print(f"\n  下一章: 第{plan['chapter']}章")
            if plan.get("title_hint"):
                print(f"  提示: {plan['title_hint']}")

    # 显示 Novel-OS 状态
    print("\n📊 Novel-OS 状态:")
    run_novel_os_command(["status"])

    # 检查输出文件
    output_dir = OUTPUT_DIR
    videos = list(output_dir.glob(f"{project_name}*.mp4"))
    if videos:
        print(f"\n🎬 已生成视频 ({len(videos)} 个):")
        for v in sorted(videos, key=lambda p: p.stat().st_mtime, reverse=True):
            size_mb = v.stat().st_size / (1024 * 1024)
            print(f"    {v.name} ({size_mb:.1f} MB)")

    # ── 记忆系统状态 ──
    print("\n🧠 分层记忆系统:")
    memory_dir = NOVEL_OS_DIR / "outputs" / "memory"
    if memory_dir.exists():
        # 章节摘要
        ch_dir = memory_dir / "chapter_summaries"
        if ch_dir.exists():
            ch_count = len(list(ch_dir.glob("ch_*.json")))
            print(f"   Layer 1 章节摘要: {ch_count} 章")

        # 弧摘要
        arc_dir = memory_dir / "arc_summaries"
        if arc_dir.exists():
            arc_count = len(list(arc_dir.glob("arc_*.json")))
            if arc_count > 0:
                print(f"   Layer 2 弧摘要: {arc_count} 弧")
            else:
                print(f"   Layer 2 弧摘要: 待生成（每10章一个弧）")

        # 全局摘要
        gs_path = memory_dir / "global_summary.json"
        if gs_path.exists():
            print(f"   Layer 3 全局摘要: ✅ 已生成")
        else:
            print(f"   Layer 3 全局摘要: 待生成（需要至少一个弧摘要）")

        # 关键事件
        ke_path = memory_dir / "key_events.jsonl"
        if ke_path.exists():
            ke_count = sum(1 for _ in open(ke_path, encoding="utf-8"))
            print(f"   关键事件时间线: {ke_count} 条")
    else:
        print(f"   ⚠️  记忆系统尚未初始化（批准第一章后自动创建）")


def _generate_world_bible(title: str, genre: str, total_chapters: int) -> str:
    """生成包含完整修炼体系的世界观模板。"""
    scale_note = ""
    if total_chapters >= 500:
        scale_note = f"""
## 长篇扩展路线 ({total_chapters}章)

```
凡境 (Ch1-{total_chapters//6}):   练气→筑基→结丹  快速成长+打脸+初期主线
灵境 (Ch{total_chapters//6+1}-{total_chapters*2//3}): 金丹→元婴→化神  势力博弈+核心冲突
圣境 (Ch{total_chapters*2//3+1}-{total_chapters}): 合体→大乘→渡劫  世界真相+最终对决
```
"""

    return f"""# 📖 世界观设定总纲 — 《{title}》

> **本文档是所有 Agent 的强制性世界规则。任何章节写作时必须遵循本文档中的设定。**
> **计划 {total_chapters} 章。记忆系统自动分层压缩，第{total_chapters//2}章时上下文仅占DeepSeek 128K的~10%。**

---

## 一、修炼体系

### 1.1 境界体系（九境三劫）

```
凡境三关 ─────────────────────────────────────────────
├─ 练气期 (1-9层) · 寿元120 · 感应天地灵气 · 灵气外放
├─ 筑基期 (初/中/后/圆满) · 寿元250 · 灵力固化 · 御器飞行 ⚡小天劫
├─ 结丹期 (虚丹/实丹/金丹) · 寿元500 · 丹田凝丹 · 丹火外放
灵境三关 ─────────────────────────────────────────────
├─ 金丹期 (1-9转) · 寿元1000 · 丹火外放 · 神识百丈
├─ 元婴期 (1-9变) · 寿元3000 · 丹破婴生 · 分神化身 ⚡大天劫
├─ 化神期 (1-9劫) · 寿元10000 · 元神出窍 · 一念千里
圣境三关 ─────────────────────────────────────────────
├─ 合体期 · 数十万载 · 身神合一 · 法则初悟
├─ 大乘期 · 百万载 · 法则掌控 · 言出法随
└─ 渡劫期 · ⚡飞升天劫（渡过=飞升/失败=散仙或陨落）
```

### 1.2 战力标尺

| 检测方式 | 可见内容 | 打脸应用 |
|----------|---------|---------|
| 灵气波动 | 同级互感知修为 | 隐藏战力=被低估 |
| 灵压（筑基起）| 主动释放压制低境界 | 主角不受灵压=困惑 |
| 丹田光晕 | 白(练气)→青(筑基)→金(金丹)→紫(元婴) | 灰色/无色=废物判定 |
| 神识范围 | 筑基10丈→金丹百丈→元婴十里 | 隐藏神识=扮猪吃虎 |

**境界压制公式**：一大境界碾压≈1:5战力比。同境界每小层差距≈30%。

---

## 二、功法/技能体系

**功法品级**：黄阶→玄阶→地阶→天阶→圣阶→神阶→混沌（七级）
**技能分类**：功法×1 + 武技×3 + 秘术×1 + 禁术×1（每境界上限）
**规则**：圆满低阶可碾压入门高阶。越级使用需承受反噬。

---

## 三、宗门/势力体系

**七级**：不入流→三流→二流→一流→顶尖→超然→已灭

---

## 四、宝物/法器体系

**六级**：凡阶→灵阶→宝阶→仙阶→神阶→混沌

---

## 五、Agent 强制规则

1. **命名统一**：使用本文档体系，不编造。
2. **新元素登记**：章节 STATE_UPDATE 块附加 WORLD_STATE_UPDATE：
   ```
   [WORLD_STATE_UPDATE]
   new_techniques: [名称] - [品级 类别]，[简要描述]
   new_sects: [名称] - [层级]
   new_treasures: [名称] - [品级]
   [/WORLD_STATE_UPDATE]
   ```
3. **战力不崩**：同境界最多越2小级。跨大境界需特殊手段+代价。
4. **品级统一**：功法七级/宝物六级/势力七级。
{scale_note}
---

*本文件由 `next_chapter.py init` 自动生成。可根据需要手动编辑补充本作特有设定。*
"""


def main():
    parser = argparse.ArgumentParser(
        description="一键小说+漫画视频生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # init
    init_p = subparsers.add_parser("init", help="初始化新书")
    init_p.add_argument("--title", required=True, help="书名")
    init_p.add_argument("--genre", default="仙侠", help="类型（仙侠/玄幻/都市/悬疑/科幻）")
    init_p.add_argument("--chapters", type=int, default=60, help="计划章节数（支持1000+章长篇）")

    # character
    char_p = subparsers.add_parser("character", help="角色管理")
    char_p.add_argument("action", choices=["add", "list"], help="操作")
    char_p.add_argument("--name", default="", help="角色名")
    char_p.add_argument("--role", default="protagonist",
                        choices=["protagonist", "antagonist", "supporting", "minor"])
    char_p.add_argument("--appearance", default="", help="外貌描述（用于图片生成）")
    char_p.add_argument("--voice", default="", help="TTS音色ID")
    char_p.add_argument("--voice-name", default="", help="音色名称")
    char_p.add_argument("--age", default="", help="年龄")
    char_p.add_argument("--personality", default="", help="性格描述")

    # write
    write_p = subparsers.add_parser("write", help="写下一章")
    write_p.add_argument("--video", action="store_true", help="写完后自动生成视频")
    write_p.add_argument("--total-chapters", type=int, default=60, help="计划总章节数")

    # status
    subparsers.add_parser("status", help="查看进度")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "init":
        cmd_init(args)
    elif args.command == "character":
        cmd_character(args)
    elif args.command == "write":
        cmd_write(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()

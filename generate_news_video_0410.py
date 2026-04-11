"""生成16:9新闻视频 - 2026年4月10日国际快讯。"""

import asyncio
import uuid
from pathlib import Path

from src.config_manager import ConfigManager
from src.tts.volcano import VolcanoTTSProvider
from src.subtitle.generator import SubtitleGenerator, SubtitleStyle
from src.video.composer import VideoComposer, VideoConfig


# ── 每张幻灯片对应一段解说词（严格一一对应）──
SLIDE_NARRATION = [
    # 封面
    (
        Path("news_slides/bi8Au.png"),
        "停火才几个小时，炸弹就落下来了。4月10号，中东局势大反转，五条消息，两分钟说清楚。"
    ),
    # 新闻1：美伊停火
    (
        Path("news_slides/X3x98.png"),
        "先说最猛的。特朗普突然撤回了对伊朗的毁灭性打击威胁，美伊双方达成了两周临时停火。"
        "伊朗同意重新开放霍尔木兹海峡，全球能源运输通道终于恢复了。"
        "但这停火极其脆弱，以色列明确说了黎巴嫩不在停火范围内，伊朗也警告说违约就退出。"
        "两周窗口期更像是双方喘口气，而不是真正的和平。"
    ),
    # 新闻2：以色列空袭贝鲁特
    (
        Path("news_slides/zeHTH.png"),
        "停火协议墨迹未干，以色列就对黎巴嫩贝鲁特发动了无预警空袭。"
        "打的是繁忙商业区和住宅区，至少182人死亡，数百人受伤，成了最致命的一天。"
        "以色列说停火不适用黎巴嫩，实质上把停火变成了单方面的战略优势窗口。"
        "这次袭击严重考验美伊停火协议，伊朗要是退出，中东局势立马恶化。"
    ),
    # 新闻3：美股暴涨
    (
        Path("news_slides/fwfsa.png"),
        "停火消息一出，华尔街直接起飞。道指单日暴涨1300点，涨幅2.7%，"
        "创2025年4月以来最佳表现。标普涨0.62%，纳指涨0.83%，道指年内终于转正了。"
        "市场这是对停火的短期情绪释放，但持续性存疑。"
        "油价下跌利好能源成本，但停火只有两周，地缘风险并没消除。"
    ),
    # 新闻4：沙特石油遇袭
    (
        Path("news_slides/81Mxe.png"),
        "再来个猛料。尽管停火了，伊朗还是对沙特关键石油管道和生产设施发动了攻击，"
        "导致沙特石油产量大幅削减。这是伊朗首次在停火期间对海湾国家下手。"
        "油价在停火后下跌，但因为沙特遇袭又开始波动了。"
        "这表明停火协议极其脆弱，地区紧张局势根本没缓解。"
    ),
    # 新闻5：美国征兵新政
    (
        Path("news_slides/DE3pt.png"),
        "最后一个，五角大楼的文件显示，美国计划在12月前实施自动征兵登记制度。"
        "新政策会自动把符合条件的公民纳入征兵系统，不用手动注册了。"
        "这是美国军事战略调整的信号。中东冲突持续，国防部长警告更多美军伤亡可能，"
        "自动登记为快速动员提供基础。虽然不等于强制征兵，但五角大楼显然在为长期冲突做准备。"
        "好了，今天就聊到这儿，觉得有用的点个关注，咱们明天见。"
    ),
]

IMAGES = [s[0] for s in SLIDE_NARRATION]
SEGMENTS = [s[1] for s in SLIDE_NARRATION]
FULL_NARRATION = "\n".join(SEGMENTS)


async def main():
    task_id = uuid.uuid4().hex[:8]
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    config = ConfigManager().load()
    tts_cfg = config.get("tts", {}).get("volcano", {})

    # 1. TTS 语音合成（1倍速）
    print("[1/4] 正在合成语音（火山引擎·大壹·1倍速）...")
    tts = VolcanoTTSProvider(
        appid=tts_cfg.get("appid", ""),
        access_token=tts_cfg.get("access_token", ""),
        cluster=tts_cfg.get("cluster", "volcano_tts"),
        resource_id=tts_cfg.get("resource_id"),
        default_voice="zh_male_dayi_uranus_bigtts",
        default_speed_ratio=1.0,
    )
    audio_path = output_dir / f"{task_id}_narration.mp3"
    tts_result = await tts.synthesize(
        text=FULL_NARRATION,
        voice="zh_male_dayi_uranus_bigtts",
        output_path=audio_path,
        speed_ratio=1.0,
    )
    print(f"  完成: {tts_result.duration:.1f}s")

    # 2. 生成字幕（用 word_timings 精确对齐）
    print("[2/4] 正在生成字幕...")
    subtitle_gen = SubtitleGenerator()
    subtitles = subtitle_gen.generate(
        FULL_NARRATION,
        tts_result.duration,
        word_timings=tts_result.word_timings,
    )
    subtitle_data = [
        {"index": s.index, "start_time": s.start_time, "end_time": s.end_time, "text": s.text}
        for s in subtitles
    ]
    print(f"  完成: {len(subtitle_data)} 条字幕")

    # 3. 合成视频（传入 narration_segments 实现图片-解说词精确同步）
    print("[3/4] 正在合成视频...")
    composer = VideoComposer()
    video_config = VideoConfig.from_aspect_ratio("16:9", fps=30, bitrate="4M")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.task_id = task_id
    ctx.images = IMAGES
    ctx.audio_path = tts_result.audio_path
    ctx.bgm_path = None
    ctx.subtitle_data = subtitle_data
    ctx.output_path = output_dir / f"global_news_0410.mp4"

    final_path = composer.compose(
        ctx=ctx,
        video_config=video_config,
        subtitle_style=SubtitleStyle(font_size=28, outline_width=2),
        narration_segments=SEGMENTS,
        word_timings=tts_result.word_timings,
        enable_pan=False,
    )

    print(f"[4/4] 完成!")
    print(f"  输出: {final_path}")


if __name__ == "__main__":
    asyncio.run(main())

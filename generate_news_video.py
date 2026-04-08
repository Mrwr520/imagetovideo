"""生成16:9新闻视频 - 图片与解说词精确同步。"""

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
        Path("news_slides/q1NU6.png"),
        "家人们，今天的国际新闻属实炸裂。4月8号，五件大事，条条跟咱有关，两分钟给你讲明白。"
    ),
    # 新闻1：伊朗
    (
        Path("news_slides/RFe87.png"),
        "先说最猛的。特朗普给伊朗下了最后通牒，要求重新打开霍尔木兹海峡，不然就动手。"
        "结果伊朗还真交了个十点方案，巴基斯坦赶紧出来当和事佬，约双方周五到伊斯兰堡谈。"
        "油价直接坐过山车，全球市场都在看这场戏怎么收场。"
    ),
    # 新闻2：Artemis II
    (
        Path("news_slides/d8wRq.png"),
        "再来个振奋人心的。NASA四个宇航员坐猎户座飞船绕月球飞了一圈，离地球25万英里，"
        "直接破了阿波罗13号五十多年的纪录。人类上次到月球附近还是1972年，这次终于又回去了。"
        "宇航员们还想给月球背面一个坑起名叫Carroll，纪念指挥官去世的妻子，挺感人的。"
    ),
    # 新闻3：Anthropic Mythos
    (
        Path("news_slides/OntM3.png"),
        "AI圈也出大事了。做Claude的那个Anthropic，拉上苹果和谷歌搞了个网络安全项目，代号Glasswing。"
        "放出来一个新模型叫Mythos，据说比Claude Opus还强一大截。"
        "现在只给安全领域的合作伙伴用，但这信号很明确，AI军备竞赛又升级了。"
    ),
    # 新闻4：科技股
    (
        Path("news_slides/uAASo.png"),
        "炒股的朋友注意了。科技七巨头这两天被锤得够呛，市值蒸发了好几万亿。"
        "一边是中东局势推高油价，一边是华尔街开始质疑AI烧钱到底值不值。"
        "两头夹击，美股震荡得厉害，通胀的阴影又回来了。"
    ),
    # 新闻5：数据中心
    (
        Path("news_slides/uCaiW.png"),
        "最后一个，美国11个州要立法限制建数据中心了。谷歌Meta这些大厂到处建机房，"
        "当地人不干了，说你们太费电费水，电网都快扛不住了。"
        "这事儿要是真落地，对AI算力的扩张影响可不小。"
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
    ctx.output_path = output_dir / f"global_news_0408.mp4"

    final_path = composer.compose(
        ctx=ctx,
        video_config=video_config,
        subtitle_style=SubtitleStyle(font_size=28, outline_width=2),
        narration_segments=SEGMENTS,
        word_timings=tts_result.word_timings,
        enable_pan=True,
    )

    print(f"[4/4] 完成!")
    print(f"  输出: {final_path}")


if __name__ == "__main__":
    asyncio.run(main())

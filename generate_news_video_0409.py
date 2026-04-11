"""生成16:9新闻视频 - 2026年4月9日国际快讯。"""

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
        Path("news_slides/TW5H2.png"),
        "家人们，今天的国际新闻属实炸裂。4月9号，五件大事，条条跟咱有关，两分钟给你讲明白。"
    ),
    # 新闻1：美伊停火
    (
        Path("news_slides/X3x98.png"),
        "先说最大的。打了整整40天，美国和伊朗终于在巴基斯坦的斡旋下达成了两周临时停火。"
        "伊朗同意临时重新开放霍尔木兹海峡，全球能源运输的命脉总算暂时通了。"
        "谈判定在4月10号在伊斯兰堡正式启动。但说实话，这个停火极其脆弱。"
        "以色列明确说黎巴嫩不在停火范围内，伊朗也警告说如果对方违约就立刻退出。"
        "两周窗口期，更像是双方的战略喘息，而不是真正的和平转折。"
    ),
    # 新闻2：以色列轰炸黎巴嫩
    (
        Path("news_slides/zeHTH.png"),
        "停火墨迹还没干呢，以色列就动手了。50架战机出动，10分钟内向黎巴嫩投下160枚炸弹。"
        "贝鲁特、南部、贝卡谷地全部遭到打击，至少254人遇难，837人受伤。"
        "以色列管这叫永恒黑暗行动，说是针对真主党指挥中心。"
        "但问题是，停火协议存在致命漏洞，根本没覆盖黎巴嫩战场。"
        "以色列借这个空间搞清场式打击，实质上把停火变成了自己的战略优势窗口。"
        "伊朗已经放话，局势再恶化就退出停火。中东这盘棋，越来越危险了。"
    ),
    # 新闻3：油价暴跌
    (
        Path("news_slides/fwfsa.png"),
        "停火消息一出，油价直接跳水。美国WTI原油暴跌16.4%，收在94块4毛1。"
        "布伦特原油跌了13.3%，到94块7毛5。这是2020年新冠疫情以来最大的单日跌幅。"
        "要知道之前因为海峡封锁，油价一度飙到118美元。"
        "但别高兴太早，海峡只是临时开放，两周后如果谈判崩了，油价会迅速反弹。"
        "当前价格已经消化了最乐观的预期，后面怎么走，得看4月10号伊斯兰堡谈判的结果。"
    ),
    # 新闻4：美股暴涨
    (
        Path("news_slides/81Mxe.png"),
        "油价暴跌的另一面，就是华尔街狂欢。道琼斯指数飙升1325点，涨幅2.85%，"
        "创下2025年4月以来最大单日涨幅。标普500涨了2.51%，纳斯达克涨了2.8%。"
        "航空、运输板块大涨，能源股则遭到重挫。市场一口气释放了1.5万亿美元的解套行情。"
        "但这是典型的利空出尽反弹，不是趋势反转。"
        "停火只有两周，美联储higher for longer的立场也没变，通胀压力还在。"
        "短线可以参与反弹，中线一定要保持谨慎。"
    ),
    # 新闻5：NATO军费
    (
        Path("news_slides/DE3pt.png"),
        "最后一条。欧洲正在经历冷战后最大规模的军事重整。"
        "海牙峰会上，32个NATO成员国里31个承诺把军费提到GDP的3.5%，"
        "再加1.5%的安全投资，总目标直接干到5%。"
        "2024年欧洲盟国军费已经超过4820亿美元，是冷战以来最高水平。"
        "但问题是，钱花了，产出没跟上。装备库存反而在缩水。"
        "中东冲突加速了这个进程，7月安卡拉峰会将是检验各国承诺的关键节点。"
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

    # 1. TTS 语音合成（火山引擎·大壹·1倍速）
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
    ctx.output_path = output_dir / "global_news_0409.mp4"

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

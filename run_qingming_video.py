"""清明节视频生成脚本 - 分段情感配音版。"""

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config_manager import ConfigManager
from src.tts.adapter import TTSAdapter
from src.subtitle.generator import SubtitleGenerator
from src.video.composer import VideoComposer, VideoConfig
from src.pipeline import TaskContext, TaskStatus


# 图片顺序
IMAGE_DIR = Path("output/qingming_slides")
IMAGES = [
    IMAGE_DIR / "A24a6.png",
    IMAGE_DIR / "Pvg0K.png",
    IMAGE_DIR / "T2Rpp.png",
    IMAGE_DIR / "n0XHf.png",
    IMAGE_DIR / "G0jXE.png",
    IMAGE_DIR / "ev9a1.png",
    IMAGE_DIR / "WDXJg.png",
]

# 每段解说词 + 对应情感
SEGMENTS = [
    {
        "text": "清明节，一个传承了两千五百年的中国传统节日。今天，让我们一起走进清明节的前世今生。",
        "emotion": "gentle",
    },
    {
        "text": "故事要从春秋时期说起。晋国公子重耳流亡十九年，随臣介子推割股奉君，忠心耿耿。重耳复国后封赏群臣，唯独忘了介子推。介子推携母隐居绵山，重耳放火烧山逼其出山，介子推却抱树而死。重耳悲痛万分，下令这一天禁火寒食，这就是寒食节的由来。",
        "emotion": "sad",
    },
    {
        "text": "到了唐代，唐玄宗下诏将清明扫墓编入礼典，正式成为国家祭祀节日。宋代更是达到鼎盛，张择端的清明上河图描绘了汴京清明时节的繁华景象。扫墓、踏青、插柳、放风筝，成为固定习俗。",
        "emotion": "",
    },
    {
        "text": "说到清明习俗，最重要的是扫墓祭祖，携带酒食果品祭拜先人。其次是踏青郊游，感受春天气息。还有放风筝，古人认为可以放走晦气。以及插柳戴柳，民谚说清明不戴柳，红颜成皓首。",
        "emotion": "happy",
    },
    {
        "text": "清明时节雨纷纷，路上行人欲断魂。借问酒家何处有，牧童遥指杏花村。杜牧的这首清明，是中国人最熟悉的清明诗词。千百年来，无数文人墨客在清明时节留下了动人的诗篇。",
        "emotion": "sad",
    },
    {
        "text": "进入现代，清明节入选国家级非物质文化遗产名录，被列为法定假日。鲜花祭扫、网络祭祀等新方式正在取代传统习俗，清明节的内涵也在与时俱进。",
        "emotion": "",
    },
    {
        "text": "慎终追远，民德归厚。清明不只是一个节日，更是中华民族对生命的敬畏，对先人的感恩，对春天的热爱。点赞关注，了解更多传统文化。",
        "emotion": "gentle",
    },
]

VOICE = "zh_male_ruyayichen_uranus_bigtts"


async def main():
    for img in IMAGES:
        if not img.exists():
            print(f"❌ 图片不存在: {img}")
            return

    print("✅ 图片就绪")

    cm = ConfigManager()
    config = cm.load()
    tts = TTSAdapter(config.get("tts", {}))

    # 分段合成语音（带情感）
    tmp_dir = Path(tempfile.mkdtemp(prefix="qm_tts_"))
    audio_parts = []
    all_timings = []
    total_duration = 0.0

    for i, seg in enumerate(SEGMENTS):
        out_path = tmp_dir / f"seg_{i:02d}.mp3"
        emotion = seg["emotion"]
        print(f"  🎙️ 合成第{i+1}段 (emotion={emotion or 'neutral'})...")

        kwargs = {}
        if emotion:
            kwargs["emotion"] = emotion
            kwargs["emotion_scale"] = 4

        result = await tts.synthesize(
            text=seg["text"],
            provider_name="volcano",
            voice=VOICE,
            output_path=out_path,
            **kwargs,
        )

        audio_parts.append(result.audio_path)

        if result.word_timings:
            for offset, dur, word in result.word_timings:
                all_timings.append((offset + total_duration, dur, word))

        total_duration += result.duration
        print(f"    ✅ {result.duration:.1f}s")

    print(f"\n📊 总时长: {total_duration:.1f}s")

    # 拼接所有音频
    merged_audio = tmp_dir / "merged.mp3"
    list_file = tmp_dir / "list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in audio_parts:
            f.write(f"file '{p.absolute()}'\n")

    from moviepy.config import FFMPEG_BINARY
    subprocess.run(
        [FFMPEG_BINARY, "-y", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c", "copy", str(merged_audio)],
        capture_output=True, timeout=60,
    )
    print(f"✅ 音频拼接完成: {merged_audio}")

    # 生成字幕
    subtitle_gen = SubtitleGenerator()
    full_text = "\n".join(s["text"] for s in SEGMENTS)
    subtitles = subtitle_gen.generate(full_text, total_duration)
    subtitle_data = [
        {"index": s.index, "start_time": s.start_time,
         "end_time": s.end_time, "text": s.text}
        for s in subtitles
    ]

    # 合成视频
    output_path = Path("output/qingming_2026_emotion.mp4")
    ctx = TaskContext(
        task_id="qingming_emotion",
        images=IMAGES,
        aspect_ratio="9:16",
        llm_provider="", llm_model="",
        tts_provider="volcano", tts_voice=VOICE,
        narration=full_text,
        audio_path=merged_audio,
        subtitle_data=subtitle_data,
        output_path=output_path,
    )

    composer = VideoComposer()
    video_config = VideoConfig.from_aspect_ratio("9:16")

    narration_segments = [s["text"] for s in SEGMENTS]

    print("🎬 合成视频中...")
    result_path = composer.compose(
        ctx=ctx,
        video_config=video_config,
        narration_segments=narration_segments,
        word_timings=all_timings if all_timings else None,
    )

    print(f"\n✅ 视频生成成功: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())

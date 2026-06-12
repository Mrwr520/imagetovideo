"""用已有图片+多角色语音合成凡人EP01视频。"""
import asyncio
import json
import tempfile
from pathlib import Path

from src.config_manager import ConfigManager
from src.tts.volcano import VolcanoTTSProvider
from src.tts.base import TTSResult
from src.subtitle.generator import SubtitleGenerator, SubtitleStyle
from src.video.composer import VideoComposer, VideoConfig


async def main():
    # 读取脚本
    script = json.loads(Path("output/fanren_ep01.json").read_text(encoding="utf-8"))
    
    # 已有图片目录
    slides_dir = Path("auto_slides/1ad314b4")
    
    # 构建段落
    slide_items = []
    for news in script.get("news", []):
        if news.get("narration"):
            slide_items.append(news)

    # 图片列表
    images = sorted(slides_dir.glob("slide_*.png"))
    print(f"图片: {len(images)}张, 段落: {len(slide_items)}个")

    # 多角色TTS
    config = ConfigManager().load()
    tts_cfg = config.get("tts", {}).get("volcano", {})
    tts = VolcanoTTSProvider(
        appid=tts_cfg.get("appid", ""),
        access_token=tts_cfg.get("access_token", ""),
        cluster=tts_cfg.get("cluster", "volcano_tts"),
        resource_id=tts_cfg.get("resource_id"),
        default_voice="zh_male_ruyayichen_uranus_bigtts",
        default_speed_ratio=1.0,
    )

    default_voice = "zh_male_ruyayichen_uranus_bigtts"
    all_audio_bytes = bytearray()
    all_word_timings = []
    total_duration = 0.0

    print("语音合成（多角色）...")
    for i, item in enumerate(slide_items):
        voice = item.get("voice", default_voice)
        text = item["narration"]
        if not text.strip():
            continue
        tmp_path = Path(tempfile.mktemp(suffix=".mp3"))
        try:
            result = await tts.synthesize(text=text, voice=voice, output_path=tmp_path, speed_ratio=1.0)
            all_audio_bytes.extend(tmp_path.read_bytes())
            if result.word_timings:
                for offset, dur, word in result.word_timings:
                    all_word_timings.append((offset + total_duration, dur, word))
            total_duration += result.duration
            print(f"  [{i+1}] {item.get('headline','')}: {result.duration:.1f}s ({voice.split('_')[2] if len(voice.split('_'))>2 else voice})")
        finally:
            tmp_path.unlink(missing_ok=True)

    audio_path = Path("output/fanren_ep01_final_narration.mp3")
    audio_path.write_bytes(bytes(all_audio_bytes))
    tts_result = TTSResult(audio_path=audio_path, duration=total_duration, sample_rate=24000, word_timings=all_word_timings or None)
    print(f"  总时长: {total_duration:.1f}s")

    # 字幕
    segments = [item["narration"] for item in slide_items]
    full_narration = "\n".join(segments)
    subtitle_gen = SubtitleGenerator()
    subtitles = subtitle_gen.generate(full_narration, tts_result.duration, word_timings=tts_result.word_timings)
    subtitle_data = [{"index": s.index, "start_time": s.start_time, "end_time": s.end_time, "text": s.text} for s in subtitles]

    # 合成视频
    print("合成视频...")
    composer = VideoComposer()
    video_config = VideoConfig.from_aspect_ratio("16:9", fps=30, bitrate="4M")

    class Ctx:
        pass
    ctx = Ctx()
    ctx.task_id = "fanren01"
    ctx.images = list(images)[:len(slide_items)]  # 匹配段落数
    ctx.audio_path = tts_result.audio_path
    ctx.bgm_path = None
    ctx.subtitle_data = subtitle_data
    ctx.output_path = Path("output/fanren_ep01_final.mp4")

    final_path = composer.compose(
        ctx=ctx,
        video_config=video_config,
        subtitle_style=SubtitleStyle(font_size=28, outline_width=2),
        narration_segments=segments,
        word_timings=tts_result.word_timings,
        enable_pan=False,
    )
    print(f"\n✅ 完成: {final_path}")


if __name__ == "__main__":
    asyncio.run(main())

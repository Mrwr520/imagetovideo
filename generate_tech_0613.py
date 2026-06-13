"""科技快讯 6月13日 - 使用Edge TTS生成视频。"""

import asyncio
import json
import time
import base64
import urllib.request
import urllib.parse
import http.client
import ssl
import socket
from pathlib import Path

from src.tts.volcano import VolcanoTTSProvider
from src.config_manager import ConfigManager
from src.subtitle.generator import SubtitleGenerator, SubtitleStyle
from src.video.composer import VideoComposer, VideoConfig


# 图片生成配置
IMAGE_GEN_URL = "https://jiuuij.de5.net/v1/images/generations"
IMAGE_GEN_KEY = "sk-GyiLtk9MfHxHKzv7wjmLUMeG8Vnhsw0fHPvSIK0tKK0oWDIm"
IMAGE_GEN_MODEL = "gpt-image-2"
IMAGE_SIZE = "768x432"
IMAGE_QUALITY = "low"


def generate_image(prompt: str, output_path: Path) -> Path | None:
    """生成一张图片。"""
    payload = json.dumps({
        "model": IMAGE_GEN_MODEL,
        "prompt": prompt,
        "n": 1,
        "size": IMAGE_SIZE,
        "quality": IMAGE_QUALITY,
        "response_format": "b64_json",
    }).encode("utf-8")

    url_obj = urllib.parse.urlparse(IMAGE_GEN_URL)
    context = ssl.create_default_context()
    conn = http.client.HTTPSConnection(url_obj.hostname, timeout=180, context=context)

    headers = {
        "Authorization": f"Bearer {IMAGE_GEN_KEY}",
        "Content-Type": "application/json",
        "Content-Length": str(len(payload)),
    }

    try:
        conn.request("POST", url_obj.path, body=payload, headers=headers)
        if conn.sock:
            conn.sock.settimeout(180)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")

        if resp.status == 200:
            result = json.loads(data)
            if result.get("data") and result["data"][0].get("b64_json"):
                img_bytes = base64.b64decode(result["data"][0]["b64_json"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(img_bytes)
                return output_path
        print(f"       ❌ HTTP {resp.status}: {data[:200]}")
        return None
    except Exception as e:
        print(f"       ❌ 异常: {e}")
        return None
    finally:
        conn.close()


async def main():
    output_dir = Path("output")
    slides_dir = Path("auto_slides/tech_0613")
    slides_dir.mkdir(parents=True, exist_ok=True)

    # 读取脚本
    script = json.loads(Path("output/tech_0613.json").read_text(encoding="utf-8"))
    print(f"📰 标题: {script['title']}")

    # 构建段落列表
    slide_items = []
    opening = script.get("opening", {})
    if opening.get("narration"):
        slide_items.append(opening)

    for news in script.get("news", []):
        if news.get("narration"):
            slide_items.append(news)

    closing = script.get("closing", {})
    if closing.get("narration"):
        slide_items.append(closing)

    print(f"共 {len(slide_items)} 个段落")

    # ═══════ 图片生成 ═══════
    print("\n[1] 🎨 生成配图...")
    existing_dir = Path("auto_slides/65b8543e")
    final_images = []

    for i, item in enumerate(slide_items):
        target = slides_dir / f"slide_{i:02d}.png"

        # 如果已存在，跳过
        if target.exists():
            print(f"    ✅ slide_{i:02d}.png 已存在，跳过")
            final_images.append(target)
            continue

        # 复用之前生成的图片
        existing = existing_dir / f"slide_{i:02d}.png"
        if existing.exists():
            import shutil
            shutil.copy2(existing, target)
            print(f"    ♻️  slide_{i:02d}.png 复用已有")
            final_images.append(target)
            continue

        # 需要新生成
        prompt = item.get("image_prompt", "")
        if prompt:
            print(f"    🎨 生成 slide_{i:02d}.png...")
            result = generate_image(prompt, target)
            if result:
                print(f"       ✅ 完成 ({target.stat().st_size // 1024} KB)")
                final_images.append(result)
            else:
                final_images.append(None)
            time.sleep(2)
        else:
            final_images.append(None)

    # 用第一张有效图作为占位
    valid_images = [p for p in final_images if p is not None]
    if not valid_images:
        print("❌ 无有效图片，使用 news_slides 目录中的图片")
        fallback_list = list(Path("news_slides").glob("*.png"))
        if fallback_list:
            valid_images = fallback_list[:len(slide_items)]
        else:
            print("❌ 无任何图片可用")
            return

    fallback = valid_images[0]
    final_images = [p if p is not None else fallback for p in final_images]
    # 确保数量匹配
    while len(final_images) < len(slide_items):
        final_images.append(fallback)

    # ═══════ TTS（火山引擎） ═══════
    print("\n[2] 🔊 火山引擎 TTS 语音合成...")
    config = ConfigManager().load()
    tts_cfg = config.get("tts", {}).get("volcano", {})
    tts = VolcanoTTSProvider(
        appid=tts_cfg.get("appid", ""),
        access_token=tts_cfg.get("access_token", ""),
        cluster=tts_cfg.get("cluster", "volcano_tts"),
        resource_id=tts_cfg.get("resource_id"),
        default_voice="zh_male_dayi_uranus_bigtts",
        default_speed_ratio=1.0,
    )

    segments = [item["narration"] for item in slide_items]
    full_narration = "\n".join(segments)

    audio_path = output_dir / "tech_0613_narration.mp3"
    tts_result = await tts.synthesize(
        text=full_narration,
        voice="zh_male_dayi_uranus_bigtts",
        output_path=audio_path,
        speed_ratio=1.0,
    )
    print(f"  ✅ 完成: {tts_result.duration:.1f}秒")

    # ═══════ 视频合成 ═══════
    print("\n[3] 🎬 合成视频...")

    subtitle_gen = SubtitleGenerator()
    subtitles = subtitle_gen.generate(
        full_narration,
        tts_result.duration,
        word_timings=tts_result.word_timings,
    )
    subtitle_data = [
        {"index": s.index, "start_time": s.start_time, "end_time": s.end_time, "text": s.text}
        for s in subtitles
    ]

    composer = VideoComposer()
    video_config = VideoConfig.from_aspect_ratio("16:9", fps=30, bitrate="4M")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.task_id = "tech_0613"
    ctx.images = final_images
    ctx.audio_path = tts_result.audio_path
    ctx.bgm_path = None
    ctx.subtitle_data = subtitle_data
    ctx.output_path = output_dir / "tech_0613.mp4"

    final_path = composer.compose(
        ctx=ctx,
        video_config=video_config,
        subtitle_style=SubtitleStyle(font_size=28, outline_width=2),
        narration_segments=segments,
        word_timings=tts_result.word_timings,
        enable_pan=False,
    )

    print("\n" + "=" * 60)
    print("✅ 视频生成完成!")
    print(f"  📹 输出: {final_path}")
    print(f"  ⏱️  时长: {tts_result.duration:.1f}秒")
    print(f"  📊 段落: {len(slide_items)}个")
    print(f"  🎯 标题: {script['title']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

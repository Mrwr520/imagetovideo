"""字幕生成器模块：根据解说词文本和语音时长生成带时间轴的字幕数据。"""

import re
from dataclasses import dataclass


@dataclass
class SubtitleSegment:
    """字幕段落数据类。"""
    index: int
    start_time: float  # 秒
    end_time: float    # 秒
    text: str


@dataclass
class SubtitleStyle:
    """字幕样式配置数据类。"""
    font_family: str = "Microsoft YaHei"
    font_size: int = 24
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 1
    position: str = "bottom"  # 字幕位置


# Chinese punctuation marks used as split points
_PUNCTUATION = set("，。！？、；：""''（）,.!?;:()")


class SubtitleGenerator:
    """根据解说词文本和语音时长生成字幕段落列表。"""

    MAX_CHARS_PER_LINE: int = 20  # 每行最大中文字符数

    def generate(
        self,
        text: str,
        total_duration: float,
        word_timings: list[tuple[float, float, str]] | None = None,
    ) -> list[SubtitleSegment]:
        """根据文本和总时长生成字幕段落列表。

        如果提供了 word_timings（来自 TTS 的词级时间戳），则使用精确时间；
        否则回退到按字符数比例分配。

        Args:
            text: 解说词文本。
            total_duration: 语音总时长（秒）。
            word_timings: 可选的词级时间戳 [(offset_sec, duration_sec, word), ...]

        Returns:
            带时间轴的 SubtitleSegment 列表。
        """
        if word_timings:
            return self._generate_from_word_timings(word_timings, total_duration)

        segments = self.split_text(text)
        if not segments:
            return []
        return self.assign_timestamps(segments, total_duration)

    def _generate_from_word_timings(
        self,
        word_timings: list[tuple[float, float, str]],
        total_duration: float,
    ) -> list[SubtitleSegment]:
        """从 TTS 词级时间戳生成精确同步的字幕。

        策略：
        1. 先过滤掉纯标点词（TTS 返回的标点不发音，只占时间轴位置）
        2. 将连续的词合并，在标点处或达到 MAX_CHARS_PER_LINE 时断句
        3. 每条字幕的 start_time = 第一个字开始发音的时间
        4. 每条字幕的 end_time = 下一条字幕第一个字开始发音的时间
           （最后一条用 total_duration），确保字幕无缝衔接、不重叠
        """
        if not word_timings:
            return []

        limit = self.MAX_CHARS_PER_LINE

        # 第一步：收集所有"段"的文本和精确时间范围
        raw_segments: list[tuple[str, float, float]] = []  # (text, start, end)
        current_text = ""
        current_start = word_timings[0][0]
        current_end = word_timings[0][0]

        for offset, dur, word in word_timings:
            word_end = offset + dur
            is_punct = all(c in _PUNCTUATION for c in word)

            if is_punct:
                # 标点不加入字幕文本，但更新 end 时间
                current_end = word_end
                # 在标点处断句（如果已有文本）
                if current_text:
                    raw_segments.append((current_text, current_start, current_end))
                    current_text = ""
                    current_start = -1  # 等下一个实际字来设置
                continue

            # 超过字数限制时强制断句
            if current_text and len(current_text) + len(word) > limit:
                raw_segments.append((current_text, current_start, current_end))
                current_text = word
                current_start = offset
                current_end = word_end
            else:
                if current_start < 0:
                    current_start = offset
                current_text += word
                current_end = word_end

        # 收尾
        if current_text:
            raw_segments.append((current_text, current_start, current_end))

        if not raw_segments:
            return []

        # 第二步：构建 SubtitleSegment 列表
        # end_time 设为下一条的 start_time，实现无缝衔接
        result: list[SubtitleSegment] = []
        for i, (text, start, end) in enumerate(raw_segments):
            if i < len(raw_segments) - 1:
                next_start = raw_segments[i + 1][1]
                seg_end = next_start
            else:
                seg_end = min(end, total_duration)

            result.append(SubtitleSegment(
                index=i,
                start_time=start,
                end_time=seg_end,
                text=text,
            ))

        return result

    def split_text(self, text: str) -> list[str]:
        """按标点符号和语义边界分割文本，每段不超过 MAX_CHARS_PER_LINE 个字符。

        分割策略：
        1. 先按标点符号拆分为初始片段
        2. 对超过长度限制的片段，强制按 MAX_CHARS_PER_LINE 截断

        Args:
            text: 待分割的文本。

        Returns:
            分割后的文本片段列表（不含空字符串）。
        """
        if not text or not text.strip():
            return []

        # Step 1: Split by punctuation
        # Build a regex that splits on any punctuation character, keeping non-empty parts
        pattern = "[" + re.escape("".join(_PUNCTUATION)) + "]"
        raw_parts = re.split(pattern, text)

        # Step 2: Strip whitespace and filter empty strings
        parts = [p.strip() for p in raw_parts if p.strip()]

        # Step 3: Force-split any segment that still exceeds the limit
        result: list[str] = []
        limit = self.MAX_CHARS_PER_LINE
        for part in parts:
            while len(part) > limit:
                result.append(part[:limit])
                part = part[limit:]
            if part:
                result.append(part)

        return result

    def assign_timestamps(
        self, segments: list[str], total_duration: float
    ) -> list[SubtitleSegment]:
        """按字符数比例分配每段字幕的起止时间。

        时间分配保证：
        - 第一段从 0 开始
        - 最后一段在 total_duration 结束
        - 相邻段落无间隙、无重叠

        Args:
            segments: 文本片段列表（不可为空）。
            total_duration: 总时长（秒），必须为正数。

        Returns:
            SubtitleSegment 列表。
        """
        if not segments:
            return []

        total_chars = sum(len(s) for s in segments)
        if total_chars == 0:
            return []

        result: list[SubtitleSegment] = []
        current_time = 0.0

        for i, seg_text in enumerate(segments):
            if i == len(segments) - 1:
                # Last segment always ends exactly at total_duration
                end_time = total_duration
            else:
                proportion = len(seg_text) / total_chars
                end_time = current_time + proportion * total_duration

            result.append(
                SubtitleSegment(
                    index=i,
                    start_time=current_time,
                    end_time=end_time,
                    text=seg_text,
                )
            )
            current_time = end_time

        return result

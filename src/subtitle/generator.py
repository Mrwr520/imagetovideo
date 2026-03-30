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
    font_size: int = 36
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 2
    position: str = "bottom"  # 字幕位置


# Chinese punctuation marks used as split points
_PUNCTUATION = set("，。！？、；：""''（）,.!?;:()")


class SubtitleGenerator:
    """根据解说词文本和语音时长生成字幕段落列表。"""

    MAX_CHARS_PER_LINE: int = 15  # 每行最大中文字符数

    def generate(self, text: str, total_duration: float) -> list[SubtitleSegment]:
        """根据文本和总时长生成字幕段落列表。

        Args:
            text: 解说词文本。
            total_duration: 语音总时长（秒），必须为正数。

        Returns:
            带时间轴的 SubtitleSegment 列表。
        """
        segments = self.split_text(text)
        if not segments:
            return []
        return self.assign_timestamps(segments, total_duration)

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

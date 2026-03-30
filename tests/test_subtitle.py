"""SubtitleGenerator 单元测试。"""

import pytest

from src.subtitle.generator import SubtitleGenerator, SubtitleSegment, SubtitleStyle


@pytest.fixture
def gen() -> SubtitleGenerator:
    return SubtitleGenerator()


# --- SubtitleStyle defaults ---

class TestSubtitleStyle:
    def test_default_values(self):
        style = SubtitleStyle()
        assert style.font_family == "Microsoft YaHei"
        assert style.font_size == 36
        assert style.color == "#FFFFFF"
        assert style.outline_color == "#000000"
        assert style.outline_width == 2
        assert style.position == "bottom"

    def test_custom_values(self):
        style = SubtitleStyle(font_family="SimSun", font_size=48, color="#FF0000")
        assert style.font_family == "SimSun"
        assert style.font_size == 48
        assert style.color == "#FF0000"


# --- split_text ---

class TestSplitText:
    def test_empty_string(self, gen: SubtitleGenerator):
        assert gen.split_text("") == []

    def test_whitespace_only(self, gen: SubtitleGenerator):
        assert gen.split_text("   ") == []

    def test_short_text_no_punctuation(self, gen: SubtitleGenerator):
        result = gen.split_text("你好世界")
        assert result == ["你好世界"]

    def test_split_on_chinese_comma(self, gen: SubtitleGenerator):
        result = gen.split_text("你好，世界")
        assert result == ["你好", "世界"]

    def test_split_on_chinese_period(self, gen: SubtitleGenerator):
        result = gen.split_text("第一句话。第二句话")
        assert result == ["第一句话", "第二句话"]

    def test_split_on_multiple_punctuation(self, gen: SubtitleGenerator):
        result = gen.split_text("你好！世界？再见。")
        assert result == ["你好", "世界", "再见"]

    def test_split_on_enumeration_comma(self, gen: SubtitleGenerator):
        result = gen.split_text("苹果、香蕉、橘子")
        assert result == ["苹果", "香蕉", "橘子"]

    def test_force_split_long_segment(self, gen: SubtitleGenerator):
        # 20 chars, no punctuation -> should be split into 15 + 5
        text = "一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾"
        result = gen.split_text(text)
        assert len(result) == 2
        assert len(result[0]) == 15
        assert len(result[1]) == 5
        assert result[0] + result[1] == text

    def test_all_segments_within_limit(self, gen: SubtitleGenerator):
        text = "这是一段比较长的中文文本，用来测试字幕生成器的分割功能，确保每段不超过十五个字符。"
        result = gen.split_text(text)
        for seg in result:
            assert len(seg) <= gen.MAX_CHARS_PER_LINE

    def test_consecutive_punctuation(self, gen: SubtitleGenerator):
        result = gen.split_text("你好，，世界")
        assert result == ["你好", "世界"]

    def test_english_punctuation(self, gen: SubtitleGenerator):
        result = gen.split_text("Hello, world. Bye!")
        assert result == ["Hello", "world", "Bye"]

    def test_mixed_chinese_english(self, gen: SubtitleGenerator):
        result = gen.split_text("你好，hello世界")
        assert result == ["你好", "hello世界"]


# --- assign_timestamps ---

class TestAssignTimestamps:
    def test_single_segment(self, gen: SubtitleGenerator):
        result = gen.assign_timestamps(["你好世界"], 10.0)
        assert len(result) == 1
        assert result[0].start_time == 0.0
        assert result[0].end_time == 10.0
        assert result[0].text == "你好世界"
        assert result[0].index == 0

    def test_equal_length_segments(self, gen: SubtitleGenerator):
        result = gen.assign_timestamps(["你好", "世界"], 10.0)
        assert len(result) == 2
        assert result[0].start_time == 0.0
        assert result[0].end_time == pytest.approx(5.0)
        assert result[1].start_time == pytest.approx(5.0)
        assert result[1].end_time == 10.0

    def test_proportional_distribution(self, gen: SubtitleGenerator):
        # "你好" (2 chars) and "世界你好" (4 chars) -> 1/3 and 2/3
        result = gen.assign_timestamps(["你好", "世界你好"], 12.0)
        assert len(result) == 2
        assert result[0].start_time == 0.0
        assert result[0].end_time == pytest.approx(4.0)
        assert result[1].start_time == pytest.approx(4.0)
        assert result[1].end_time == 12.0

    def test_no_gaps_no_overlaps(self, gen: SubtitleGenerator):
        segments = ["第一段", "第二段", "第三段", "第四段"]
        result = gen.assign_timestamps(segments, 20.0)
        assert result[0].start_time == 0.0
        assert result[-1].end_time == 20.0
        for i in range(len(result) - 1):
            assert result[i].end_time == pytest.approx(result[i + 1].start_time)

    def test_empty_segments(self, gen: SubtitleGenerator):
        assert gen.assign_timestamps([], 10.0) == []

    def test_indices_are_sequential(self, gen: SubtitleGenerator):
        result = gen.assign_timestamps(["一", "二", "三"], 9.0)
        for i, seg in enumerate(result):
            assert seg.index == i


# --- generate (integration) ---

class TestGenerate:
    def test_basic_generation(self, gen: SubtitleGenerator):
        result = gen.generate("你好，世界", 10.0)
        assert len(result) == 2
        assert result[0].start_time == 0.0
        assert result[-1].end_time == 10.0
        assert result[0].text == "你好"
        assert result[1].text == "世界"

    def test_empty_text(self, gen: SubtitleGenerator):
        assert gen.generate("", 10.0) == []

    def test_long_text_all_within_limit(self, gen: SubtitleGenerator):
        text = "这是一段比较长的中文文本，用来测试字幕生成器的分割功能，确保每段不超过十五个字符。"
        result = gen.generate(text, 30.0)
        assert len(result) > 0
        for seg in result:
            assert len(seg.text) <= gen.MAX_CHARS_PER_LINE
        assert result[0].start_time == 0.0
        assert result[-1].end_time == 30.0

    def test_timeline_coverage(self, gen: SubtitleGenerator):
        text = "春天来了，万物复苏。小鸟在枝头歌唱，花儿在微风中摇曳。"
        duration = 15.0
        result = gen.generate(text, duration)
        assert result[0].start_time == 0.0
        assert result[-1].end_time == duration
        for i in range(len(result) - 1):
            assert result[i].end_time == pytest.approx(result[i + 1].start_time)

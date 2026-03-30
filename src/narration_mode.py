from enum import Enum


class NarrationMode(str, Enum):
    DESCRIBE_IMAGES = "describe_images"  # 按图说话
    NEWS_COMMENTARY = "news_commentary"  # 新闻解说

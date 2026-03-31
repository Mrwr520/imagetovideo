"""领域配置：从 config.toml 读取，支持无限扩展。"""

from __future__ import annotations

from dataclasses import dataclass, field

# 内置默认领域（config.toml 未配置时使用）
DEFAULT_DOMAINS: list[dict] = [
    {
        "key": "classic_books",
        "name": "📚 书籍名著",
        "sub_domains": ["红楼梦", "三国演义", "西游记", "水浒传", "小王子", "百年孤独", "道德经", "孙子兵法", "鬼谷子", "人间失格", "活着"],
        "search_template": "{sub} 经典语录 道理 热门解读 短视频",
        "style_hint": "古风动漫",
    },
    {
        "key": "emotion",
        "name": "💔 情感",
        "sub_domains": ["恋爱", "分手", "婚姻", "暗恋", "异地恋", "亲情", "友情", "自愈", "成长"],
        "search_template": "{sub} 情感语录 热门 扎心 短视频",
        "style_hint": "唯美动漫",
    },
    {
        "key": "military",
        "name": "⚔️ 军事",
        "sub_domains": ["中东局势", "大国博弈", "军事历史", "武器装备", "战争故事"],
        "search_template": "{sub} 军事 热点 最新 解读",
        "style_hint": "写实风格",
    },
    {
        "key": "campus",
        "name": "🎓 校园",
        "sub_domains": ["校园恋爱", "考研考公", "室友关系", "毕业季", "社团生活"],
        "search_template": "{sub} 校园 热门话题 大学生",
        "style_hint": "清新动漫",
    },
    {
        "key": "workplace",
        "name": "💼 职场",
        "sub_domains": ["办公室政治", "跳槽", "创业", "领导力", "向上管理"],
        "search_template": "{sub} 职场 道理 热门 经验",
        "style_hint": "现代动漫",
    },
    {
        "key": "psychology",
        "name": "🧠 心理/哲学",
        "sub_domains": ["认知偏差", "人性弱点", "博弈论", "存在主义", "斯多葛哲学"],
        "search_template": "{sub} 心理学 哲学 道理 热门",
        "style_hint": "抽象艺术风",
    },
    {
        "key": "finance",
        "name": "📈 财经",
        "sub_domains": ["投资理财", "经济周期", "商业案例", "穷人思维", "财富自由"],
        "search_template": "{sub} 财经 道理 热门 短视频",
        "style_hint": "商务动漫",
    },
    {
        "key": "science",
        "name": "🔬 科普",
        "sub_domains": ["宇宙", "量子力学", "生物进化", "AI", "脑科学"],
        "search_template": "{sub} 科普 有趣 热门 解读",
        "style_hint": "科幻风格",
    },
    {
        "key": "history",
        "name": "🏛️ 历史",
        "sub_domains": ["中国古代", "二战", "冷战", "帝王将相", "历史悬案"],
        "search_template": "{sub} 历史 真相 热门 故事",
        "style_hint": "古风写实",
    },
    {
        "key": "mythology",
        "name": "🎭 民间/神话",
        "sub_domains": ["山海经", "希腊神话", "北欧神话", "民间传说", "志怪故事"],
        "search_template": "{sub} 神话 故事 热门 解读",
        "style_hint": "奇幻动漫",
    },
]


@dataclass
class DomainConfig:
    """单个领域配置。"""
    key: str
    name: str
    sub_domains: list[str] = field(default_factory=list)
    search_template: str = "{sub} 热门 短视频"
    style_hint: str = "anime style"


def load_domains(config: dict) -> list[DomainConfig]:
    """从 config.toml 加载领域配置，未配置则使用内置默认值。"""
    script_cfg = config.get("script", {})
    domains_cfg = script_cfg.get("domains", {})

    if not domains_cfg:
        # 使用内置默认领域
        return [DomainConfig(**d) for d in DEFAULT_DOMAINS]

    result = []
    for key, val in domains_cfg.items():
        result.append(DomainConfig(
            key=key,
            name=val.get("name", key),
            sub_domains=val.get("sub_domains", []),
            search_template=val.get("search_keywords", "{sub} 热门 短视频"),
            style_hint=val.get("style_hint", "anime style"),
        ))
    return result

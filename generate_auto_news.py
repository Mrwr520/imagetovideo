"""自动化资讯视频生成 - 全自动流程。

流程：
1. 调用社交搜索Agent接口获取热点新闻
2. 由AI助手（Kiro）根据热点生成脚本JSON
3. 图片生成 + TTS + 视频合成

使用方法：
    # 方式1：全自动（搜索热点 → 生成脚本 → 生成视频）
    python generate_auto_news.py --search "今日热点新闻"

    # 方式2：指定已有脚本文件
    python generate_auto_news.py --script output/my_script.json

    # 方式3：手动指定新闻标题
    python generate_auto_news.py --manual-news "标题1|标题2|标题3"
"""

import asyncio
import json
import time
import uuid
import base64
import urllib.request
import urllib.error
import urllib.parse
import http.client
import ssl
import socket
from pathlib import Path
from datetime import datetime

from src.config_manager import ConfigManager
from src.tts.volcano import VolcanoTTSProvider
from src.subtitle.generator import SubtitleGenerator, SubtitleStyle
from src.video.composer import VideoComposer, VideoConfig


# ═══════════════════════════════════════════════════════════════════
# 配置区
# ═══════════════════════════════════════════════════════════════════

# TikHub API 配置（抖音/B站热搜）
TIKHUB_BASE_URL = "https://api.tikhub.dev"
TIKHUB_TOKEN = "p8tTXYZL+E6atUy+TZ6G0U7bKTehfLJD3Cjml2ONB9e+kFetG16jWRuhMw=="

# 社交搜索Agent接口配置（备用）
SOCIAL_SEARCH_URL = "https://social.348349.xyz/agents/social-search/s-nwj4bxvp"
SOCIAL_SEARCH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOjE0LCJ1c2VybmFtZSI6IjUyMDEzNHl1MzlAZ21haWwuY29tIiwiaWF0IjoxNzgwOTg3ODk2LCJleHAiOjE3ODE1OTI2OTZ9.PtRy91aPzxydN9ntoiiJGQDzXhly5WUNvEl320W96b8"
SOCIAL_SEARCH_CF_CLEARANCE = ""

# AI 图片生成 API 配置
IMAGE_GEN_URL = "https://jiuuij.de5.net/v1/images/generations"
IMAGE_GEN_KEY = "sk-GyiLtk9MfHxHKzv7wjmLUMeG8Vnhsw0fHPvSIK0tKK0oWDIm"
IMAGE_GEN_MODEL = "gpt-image-2"
IMAGE_SIZE = "768x432"  # 16:9 小分辨率，手机观看足够，生成更快
IMAGE_QUALITY = "low"  # low/medium/high，低质量加快速度


# ═══════════════════════════════════════════════════════════════════
# 模块1：TikHub热搜抓取（主力）
# ═══════════════════════════════════════════════════════════════════

class TikHubCollector:
    """通过TikHub API采集抖音热搜。"""

    def __init__(self, base_url: str = TIKHUB_BASE_URL, token: str = TIKHUB_TOKEN):
        self.base_url = base_url
        self.token = token

    def _get(self, path: str, params: dict = None) -> dict:
        """GET请求TikHub API。"""
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "NewsVideoBot/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"    [警告] TikHub {path}: HTTP {e.code}")
            return {}
        except Exception as e:
            print(f"    [警告] TikHub请求失败: {e}")
            return {}

    def fetch_douyin_hot(self) -> list[dict]:
        """获取抖音热搜榜（自动过滤政治敏感内容）。"""
        print("  📡 抓取抖音热搜...")
        data = self._get("/api/v1/douyin/app/v3/fetch_hot_search_list")
        items = []
        word_list = data.get("data", {}).get("data", {}).get("word_list", [])

        # 政治/敏感关键词过滤
        skip_keywords = [
            "习近平", "彭丽媛", "总书记", "国务院", "中央政治局",
            "党委", "政协", "人大常委", "两会", "意识形态",
            "统战", "纪委", "反腐", "政治局", "中共",
            "朝鲜", "友谊塔", "国事访问", "金正恩",
            "战略引领", "情深意笃", "高考政治",
        ]

        for item in word_list[:30]:
            word = item.get("word", "")
            if not word:
                continue
            # 过滤政治内容
            if any(kw in word for kw in skip_keywords):
                continue
            items.append({
                "title": word,
                "source": "抖音",
                "hot_value": item.get("hot_value", 0),
            })
            if len(items) >= 20:
                break

        print(f"    ✅ 获取到 {len(items)} 条")
        return items

    def fetch_douyin_trending(self) -> list[dict]:
        """获取抖音热门视频。"""
        print("  📡 抓取抖音热门...")
        data = self._get("/api/v1/douyin/web/fetch_trending_post")
        items = []
        aweme_list = data.get("data", {}).get("aweme_list", [])
        if not aweme_list:
            aweme_list = data.get("data", {}).get("data", {}).get("aweme_list", [])
        for item in aweme_list[:10]:
            desc = item.get("desc", "")
            if desc and len(desc) > 5:
                # 清理hashtag
                import re
                clean = re.sub(r'#\S+', '', desc).strip()
                if clean:
                    items.append({
                        "title": clean[:60],
                        "source": "抖音热门",
                        "hot_value": item.get("statistics", {}).get("digg_count", 0),
                    })
        print(f"    ✅ 获取到 {len(items)} 条")
        return items

    def collect_all(self) -> list[dict]:
        """采集所有可用的热搜数据。"""
        all_items = []
        all_items.extend(self.fetch_douyin_hot())
        # 如果热搜数据不够，补充热门视频
        if len(all_items) < 5:
            all_items.extend(self.fetch_douyin_trending())
        return all_items


# ═══════════════════════════════════════════════════════════════════
# 模块1b：社交搜索Agent（备用/深度搜索）
# ═══════════════════════════════════════════════════════════════════

class SocialSearchAgent:
    """调用社交搜索Agent获取热点资讯。"""

    def __init__(self, url: str = SOCIAL_SEARCH_URL, token: str = SOCIAL_SEARCH_TOKEN, cf_clearance: str = SOCIAL_SEARCH_CF_CLEARANCE):
        self.url = url
        self.token = token
        self.cf_clearance = cf_clearance

    def search(self, query: str) -> list[dict]:
        """搜索热点，返回提取后的新闻摘要列表。

        Args:
            query: 搜索关键词，如"今日热点新闻 top 10"

        Returns:
            [{"title": "标题", "desc": "描述", "source": "来源平台"}, ...]
        """
        print(f"  📡 调用社交搜索Agent: {query}")

        url_obj = urllib.parse.urlparse(self.url)
        context = ssl.create_default_context()
        conn = http.client.HTTPSConnection(url_obj.hostname, timeout=60, context=context)

        headers = {
            "accept": "text/event-stream",
            "authorization": f"Bearer {self.token}",
            "content-type": "application/json",
            "origin": "https://social.348349.xyz",
            "referer": "https://social.348349.xyz/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        }
        if self.cf_clearance:
            headers["cookie"] = f"cf_clearance={self.cf_clearance}"

        body = json.dumps({"message": query}).encode("utf-8")

        try:
            conn.request("POST", url_obj.path, body=body, headers=headers)
            resp = conn.getresponse()

            if resp.status != 200:
                # 尝试读取错误信息
                err_body = resp.read().decode("utf-8", errors="replace")
                try:
                    err_json = json.loads(err_body)
                    err_msg = err_json.get("message", f"HTTP {resp.status}")
                except json.JSONDecodeError:
                    err_msg = f"HTTP {resp.status}"
                print(f"  [错误] 搜索Agent: {err_msg}")
                return []

            # 读取SSE流（设置超时避免挂住）
            conn.sock.settimeout(45)  # 45秒超时
            buffer = b""
            try:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    buffer += chunk
                    # 收到足够数据或检测到结束标记
                    if len(buffer) > 200000 or b'"type":"idle"' in chunk:
                        break
            except (socket.timeout, http.client.IncompleteRead):
                pass  # 超时或连接关闭，正常

            raw_data = buffer.decode("utf-8", errors="replace")
            return self._parse_sse_response(raw_data)

        except Exception as e:
            print(f"  [警告] 搜索Agent请求失败: {e}")
            return []
        finally:
            conn.close()

    def _parse_sse_response(self, raw_data: str) -> list[dict]:
        """从SSE响应中提取新闻数据。

        Agent返回的数据包含抖音/微博等平台的搜索结果，
        我们提取视频标题(desc)和作者信息作为新闻线索。
        """
        news_items = []
        seen_titles = set()

        # 逐行解析SSE事件
        for line in raw_data.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue

            data_str = line[5:].strip()
            if not data_str or data_str == "[DONE]":
                continue

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            # 提取不同格式的数据
            self._extract_from_event(event, news_items, seen_titles)

        print(f"    提取到 {len(news_items)} 条新闻线索")
        return news_items

    def _extract_from_event(self, event: dict, news_items: list, seen_titles: set):
        """从单个SSE事件中提取新闻信息。"""

        # 格式1：tool_result中包含抖音搜索结果
        if event.get("type") == "tool_result":
            content = event.get("content", "")
            if isinstance(content, str):
                try:
                    content_data = json.loads(content)
                    self._extract_from_search_data(content_data, news_items, seen_titles)
                except json.JSONDecodeError:
                    pass
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        try:
                            text_data = json.loads(item.get("text", ""))
                            self._extract_from_search_data(text_data, news_items, seen_titles)
                        except json.JSONDecodeError:
                            pass

        # 格式2：message_end 中的assistant消息（Agent的总结文本）
        if event.get("type") == "message_end":
            msg = event.get("message", {})
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 50:
                    # Agent的文字总结，可以直接用
                    self._extract_from_text_summary(content, news_items, seen_titles)

        # 格式3：直接的搜索数据（抖音/微博格式）
        if isinstance(event, dict):
            self._extract_from_search_data(event, news_items, seen_titles)

    def _extract_from_search_data(self, data: dict, news_items: list, seen_titles: set):
        """从搜索API返回的数据中提取标题。"""

        # 抖音搜索结果格式
        if "data" in data:
            items = data.get("data", [])
            if isinstance(items, dict):
                # 嵌套的data格式
                items = items.get("data", [])
                if isinstance(items, dict):
                    items = items.get("aweme_list", []) or items.get("data", [])

            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # 抖音视频格式
                    aweme = item.get("aweme_info", item)
                    desc = aweme.get("desc", "")
                    if desc and len(desc) > 5 and desc not in seen_titles:
                        # 清理desc，去除hashtag
                        clean_desc = self._clean_title(desc)
                        if clean_desc and len(clean_desc) > 5:
                            seen_titles.add(desc)
                            author = aweme.get("author", {}).get("nickname", "")
                            stats = aweme.get("statistics", {})
                            news_items.append({
                                "title": clean_desc,
                                "desc": desc,
                                "source": "抖音",
                                "author": author,
                                "digg_count": stats.get("digg_count", 0),
                                "comment_count": stats.get("comment_count", 0),
                            })

        # 微博热搜格式
        if "realtime" in data:
            for item in data.get("realtime", []):
                word = item.get("word", "") or item.get("note", "")
                if word and word not in seen_titles:
                    seen_titles.add(word)
                    news_items.append({
                        "title": word,
                        "desc": word,
                        "source": "微博",
                        "hot_value": item.get("num", 0),
                    })

    def _extract_from_text_summary(self, text: str, news_items: list, seen_titles: set):
        """从Agent文字总结中提取新闻条目。"""
        # 按行分割，寻找有编号或bullet的行
        for line in text.split("\n"):
            line = line.strip()
            # 匹配 "1. xxx" 或 "- xxx" 或 "• xxx" 格式
            if len(line) > 10:
                # 去除编号前缀
                import re
                clean = re.sub(r'^[\d]+[.、)\]]\s*', '', line)
                clean = re.sub(r'^[-•·]\s*', '', clean)
                if clean and len(clean) > 8 and clean not in seen_titles:
                    seen_titles.add(clean)
                    news_items.append({
                        "title": clean,
                        "desc": clean,
                        "source": "Agent总结",
                    })

    @staticmethod
    def _clean_title(text: str) -> str:
        """清理标题文本，去除hashtag和多余符号。"""
        import re
        # 去除 #xxx# 和 #xxx 格式的hashtag
        text = re.sub(r'#[^#\s]+#?', '', text)
        # 去除 @xxx 
        text = re.sub(r'@\S+', '', text)
        # 去除多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        return text


# ═══════════════════════════════════════════════════════════════════
# 模块2：脚本生成（由AI助手完成，这里提供模板）
# ═══════════════════════════════════════════════════════════════════

def build_script_from_news(news_items: list[dict], count: int = 5) -> dict:
    """从热搜列表构建资讯解说脚本。

    风格：日常聊天、轻松有趣，像朋友分享见闻
    图片：动漫美少女"小星"，性感有魅力，中文对话气泡和主题强相关
    标题：吸睛爆款风格，每次随机不重复
    """
    import random

    today_short = datetime.now().strftime("%m月%d日")
    selected = news_items[:count]

    # 生成吸睛标题和描述
    video_title, video_desc = _generate_viral_title(selected, today_short)

    script = {
        "title": video_title,
        "description": video_desc,
        "opening": {
            "narration": random.choice([
                f"嗨，{today_short}，刷了一圈全网，挑了几个有意思的话题跟你们唠唠。",
                f"家人们，{today_short}，今天网上可太热闹了，我挑了几个最火的来聊。",
                f"宝子们好，{today_short}了，最近全网都在讨论这几件事你知道吗？",
                f"来了来了，{today_short}，今天的瓜真的一个比一个大，给你们盘一下。",
                f"Hello，{today_short}份的热搜盘点来了，跟不上节奏的赶紧来。",
            ]),
            "image_prompt": _build_image_prompt("开场", "今天有料！", "sitting at glowing desk with holographic screens, winking at viewer"),
        },
        "news": [],
        "closing": {
            "narration": random.choice([
                "行，今天就聊到这儿，你们觉得哪个最有意思？评论区聊聊，回见！",
                "好了，今天的瓜就分享到这，喜欢的话点个赞加个关注，明天继续！",
                "以上就是今天的全部内容，有想法的评论区见，拜拜咯！",
                "OK收工，觉得有意思的双击一下，咱们下期再见！",
                "就聊到这吧，点个关注不迷路，咱们明天接着唠！",
            ]),
            "image_prompt": _build_image_prompt("告别", "明天见~❤", "waving at viewer, soft sunset light through window, cherry blossoms"),
        },
    }

    transitions = [
        "第一个，", "然后呢，", "还有个事儿，", "对了，", "最后一个，",
        "先聊这个，", "再说说，", "还有，", "另外，", "压轴的，",
    ]
    random.shuffle(transitions)

    for i, item in enumerate(selected):
        title = item["title"]
        hot_val = item.get("hot_value", 0)
        transition = transitions[i] if i < len(transitions) else ""

        if hot_val > 10000000:
            narration = random.choice([
                f"{transition}{title}，全网都在讨论这个，属实火了。",
                f"{transition}{title}，这个话题直接爆了，到处都是。",
                f"{transition}{title}，热度拉满了，你们刷到没？",
            ])
        elif hot_val > 5000000:
            narration = random.choice([
                f"{transition}{title}，挺多人关注的。",
                f"{transition}{title}，讨论度还挺高。",
                f"{transition}{title}，不少人在聊这个。",
            ])
        else:
            narration = random.choice([
                f"{transition}{title}，蛮有意思的。",
                f"{transition}{title}，我觉得值得说说。",
                f"{transition}{title}，这个挺有意思的你们看看。",
            ])

        speech, scene, extra = _generate_topic_context(title)
        image_prompt = _build_image_prompt(title, speech, scene, extra)

        script["news"].append({
            "headline": title[:20],
            "narration": narration,
            "image_prompt": image_prompt,
        })

    return script


def _generate_viral_title(news_items: list[dict], today_short: str) -> tuple[str, str]:
    """生成吸睛爆款标题和描述，和热搜内容强关联，每次随机不重复。

    Returns:
        (title, description)
    """
    import random

    top1 = news_items[0]["title"] if len(news_items) > 0 else "今日热点"
    top2 = news_items[1]["title"] if len(news_items) > 1 else ""
    top3 = news_items[2]["title"] if len(news_items) > 2 else ""
    t1_short = top1[:12]
    t2_short = top2[:10]

    # 标题模板库 - 全部和实际热搜内容强关联
    title_templates = [
        # 直接点题型
        f"{t1_short}！全网都炸了",
        f"{t1_short}，你怎么看？",
        f"关于{t1_short}，我有话说",
        f"{t1_short}这事儿太离谱了吧",
        # 组合型（多个热搜）
        f"{t1_short}＋{t2_short}，今天信息量有点大",
        f"从{t1_short}到{t2_short}，今天热搜质量真高",
        f"{t1_short}霸榜了！顺便聊聊{t2_short}",
        # 悬念+热搜型
        f"刷到{t1_short}我直接愣住了",
        f"{t1_short}后续来了，比想象的还离谱",
        f"为什么全网都在讨论{t1_short}？",
        f"一觉醒来{t1_short}居然上热搜了",
        # 互动型
        f"{t1_short}，评论区已经吵翻了",
        f"今天聊点轻松的：{t1_short}",
        f"{t1_short}这个话题，你站哪边？",
        # 反转/情绪型
        f"本来只想刷五分钟，结果看到{t1_short}...",
        f"被{t1_short}刷屏了，到底怎么回事",
        f"不是，{t1_short}也太上头了吧",
        f"救命！{t1_short}笑不活了",
    ]

    # 描述模板库 - 设悬念引好奇，不是陈述
    all_topics = "、".join([item["title"][:8] for item in news_items[:3]])
    desc_templates = [
        f"{t1_short}？什么情况？今天热搜有点东西👀 评论区说说你怎么看 #热搜 #日常",
        f"一觉醒来{t1_short}上热搜了，什么操作😂 还有{t2_short}也绝了 #吃瓜 #热搜",
        f"谁能想到{t1_short}和{t2_short}能同时上热搜🤣 评论区聊聊 #每日分享",
        f"今天刷到{t1_short}差点把手机笑掉📱 还有几个也很离谱 #热搜盘点 #日常碎碎念",
        f"被{t1_short}刷屏了...到底怎么回事？点进来看看👀 #热搜 #吃瓜日常",
        f"不是，{t1_short}这事也太抽象了吧😅 评论区炸了 #热门话题 #日常",
        f"今天这几条热搜含金量也太高了吧，特别是{t1_short}这个💫 #热搜 #分享",
    ]

    return random.choice(title_templates), random.choice(desc_templates)


def _generate_topic_context(title: str) -> tuple[str, str, str]:
    """根据话题智能生成：中文对话气泡、场景、额外人物。"""
    t = title

    # 科技/AI
    if any(kw in t for kw in ["AI", "GPT", "OpenAI", "人工智能", "模型", "芯片", "机器人", "算法", "大模型", "Claude"]):
        return ("AI太猛了！", "surrounded by floating holographic AI code and neural network visuals",
                "a sexy anime girl named '小月' with short pink hair, tight lab coat showing collarbone, perfect figure, name tag '小月', speech bubble '代码自己写好了~'")

    # 手机/数码
    if any(kw in t for kw in ["手机", "苹果", "华为", "小米", "iPhone", "发布会", "新品"]):
        return ("想买！💰", "holding a shiny new phone excitedly, tech store with neon lights",
                "a gorgeous anime girl named '小夏' with long black hair in tight dress showing figure, name tag '小夏', speech bubble '这也太好看了吧'")

    # 游戏/电竞
    if any(kw in t for kw in ["游戏", "电竞", "王者", "原神", "Steam", "英雄联盟", "吃鸡"]):
        return ("开冲！🎮", "wearing gaming headset in neon-lit gaming room with multiple screens",
                "a cute anime girl named '小悦' with twin tails, crop top showing waist, name tag '小悦', speech bubble '带我上分！'")

    # 体育/足球/篮球
    if any(kw in t for kw in ["足球", "篮球", "世界杯", "NBA", "男足", "女排", "运动", "奥运", "马刺", "尼克斯"]):
        return ("加油！⚽", "wearing sexy sporty crop top in a stadium with excited crowd",
                "a fit anime girl named '小夏' with ponytail in cheerleader outfit showing long legs, name tag '小夏', speech bubble '冲冲冲！'")

    # 娱乐/影视
    if any(kw in t for kw in ["明星", "演员", "电影", "电视剧", "综艺", "演唱会", "票房", "导演"]):
        return ("好期待！🎬", "in a luxurious movie premiere red carpet scene",
                "a glamorous anime girl named '小月' with wavy purple hair in elegant off-shoulder dress showing collarbone, name tag '小月', speech bubble '太帅了吧！'")

    # 美食/饮品
    if any(kw in t for kw in ["美食", "吃", "奶茶", "火锅", "甜品", "餐厅", "咖啡", "粽", "菜", "辣", "姜"]):
        return ("馋死了！🤤", "in a dreamy food scene with delicious dishes floating around",
                "a cute anime girl named '小悦' with short brown hair in off-shoulder apron, name tag '小悦', speech bubble '我全都要！'")

    # 高考/学习
    if any(kw in t for kw in ["高考", "考试", "考研", "大学", "分数", "志愿", "作文", "考生", "地理"]):
        return ("加油鸭！📚", "in a pretty library giving encouraging thumbs up, books floating around",
                "a cute anime girl named '小月' with glasses and bob hair in school uniform short skirt, name tag '小月', speech bubble '终于解放了！'")

    # 天气/季节
    if any(kw in t for kw in ["天气", "高温", "下雨", "台风", "夏天", "降温"]):
        return ("好热！☀", "outdoors in sexy summer outfit fanning herself, bright sunny day",
                "a beautiful anime girl named '小夏' with sunhat in sundress showing shoulders, name tag '小夏', speech bubble '要融化了~'")

    # 经济/财经
    if any(kw in t for kw in ["股", "经济", "房价", "工资", "市值", "IPO", "上市"]):
        return ("涨了吗？📈", "looking at holographic stock charts with excitement",
                "a smart anime girl named '小夏' with long black hair in tight business blouse, name tag '小夏', speech bubble '买买买！'")

    # 社会/生活/搞笑/名场面
    if any(kw in t for kw in ["搞笑", "名场面", "谣言", "热议", "吐槽", "青春", "有爱"]):
        return ("笑死！😂", "laughing expressively in a cozy room with phone",
                "a pretty anime girl named '小悦' with red hair leaning close laughing, name tag '小悦', speech bubble '哈哈不行了'")

    # 默认
    return ("有意思！✨", "in a cozy modern room with warm lighting, reacting expressively to her phone",
            "")


def _build_image_prompt(topic: str, speech_text: str, scene: str, extra_characters: str = "") -> str:
    """构建统一风格图片提示词。

    主角：科技博主"小星" - 银发大眼、性感有魅力、表情丰富
    """
    main_char = (
        "a gorgeous anime girl named '小星' with long flowing silver hair and big sparkling blue eyes, "
        "beautiful detailed face, slightly sexy outfit with off-shoulder top showing collarbone, "
        "perfect figure, confident and cute expression"
    )

    extra = f", {extra_characters}" if extra_characters else ""
    bubble = f", large prominent speech bubble with bold Chinese text '{speech_text}'"

    return (
        f"Anime illustration, {main_char}, {scene}{extra}{bubble}, "
        f"vibrant colors, high quality anime art, dynamic angle, soft glow lighting, "
        f"16:9 aspect ratio"
    )


# ═══════════════════════════════════════════════════════════════════
# 模块3：AI图片生成
# ═══════════════════════════════════════════════════════════════════

class NewsImageGenerator:
    """使用 gpt-image-2 API 生成新闻配图。"""

    def __init__(
        self,
        api_url: str = IMAGE_GEN_URL,
        api_key: str = IMAGE_GEN_KEY,
        model: str = IMAGE_GEN_MODEL,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str, output_path: Path) -> Path:
        """生成一张图片并保存。"""
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": IMAGE_SIZE,
            "quality": IMAGE_QUALITY,
            "response_format": "b64_json",
        }).encode("utf-8")

        url_obj = urllib.parse.urlparse(self.api_url)
        context = ssl.create_default_context()
        conn = http.client.HTTPSConnection(url_obj.hostname, timeout=180, context=context)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
        }

        try:
            conn.request("POST", url_obj.path, body=payload, headers=headers)
            # 设置socket级超时
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
                else:
                    raise RuntimeError(f"图片API返回格式异常: {list(result.keys())}")
            else:
                raise RuntimeError(f"图片生成失败 (HTTP {resp.status}): {data[:300]}")
        except socket.timeout:
            raise RuntimeError("图片生成超时（180s）")
        finally:
            conn.close()

    def generate_batch(self, items: list[dict], output_dir: Path) -> list[Path]:
        """批量生成图片。"""
        paths = []
        for i, item in enumerate(items):
            prompt = item.get("image_prompt", "")
            if not prompt:
                paths.append(None)
                continue
            output_path = output_dir / f"slide_{i:02d}.png"
            print(f"    🎨 生成图片 {i+1}/{len(items)}: {prompt[:60]}...")
            try:
                path = self.generate(prompt, output_path)
                paths.append(path)
                print(f"       ✅ 完成 ({path.stat().st_size // 1024} KB)")
            except Exception as e:
                print(f"       ❌ 失败: {e}")
                paths.append(None)
            time.sleep(2)
        return paths


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="自动化资讯视频生成")
    parser.add_argument("--search", type=str, default="", help="搜索热点关键词（如：今日热点新闻 top 10）")
    parser.add_argument("--script", type=str, default="", help="指定脚本JSON文件路径")
    parser.add_argument("--json", type=str, default="", help="直接传入脚本JSON字符串")
    parser.add_argument("--manual-news", type=str, default="", help="手动指定新闻标题，用|分隔")
    parser.add_argument("--count", type=int, default=5, help="新闻条数（默认5）")
    parser.add_argument("--voice", type=str, default="zh_male_dayi_uranus_bigtts", help="TTS音色")
    parser.add_argument("--speed", type=float, default=1.0, help="语速倍率")
    parser.add_argument("--skip-images", action="store_true", help="跳过图片生成（调试用）")
    parser.add_argument("--output-name", type=str, default="", help="输出文件名（不含扩展名）")
    parser.add_argument("--search-only", action="store_true", help="仅搜索热点，不生成视频（输出JSON供AI助手使用）")
    args = parser.parse_args()

    task_id = uuid.uuid4().hex[:8]
    today_str = datetime.now().strftime("%m%d")
    output_dir = Path("output")
    slides_dir = Path(f"auto_slides/{task_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    slides_dir.mkdir(parents=True, exist_ok=True)

    config = ConfigManager().load()
    tts_cfg = config.get("tts", {}).get("volcano", {})

    print("=" * 60)
    print(f"🎬 自动化资讯视频生成 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # ══════════════════════════════════════════
    # 步骤1：获取脚本
    # ══════════════════════════════════════════

    script = None

    if args.script:
        # 从文件读取脚本
        script_path = Path(args.script)
        if not script_path.exists():
            print(f"❌ 脚本文件不存在: {script_path}")
            return
        script = json.loads(script_path.read_text(encoding="utf-8"))
        print(f"\n[1] 📄 读取脚本: {script_path}")

    elif args.json:
        # 从JSON字符串读取
        script = json.loads(args.json)
        print("\n[1] 📄 使用传入的JSON脚本")

    elif args.search:
        # 搜索热点新闻 — 优先用TikHub，备用社交搜索Agent
        print(f"\n[1] 📡 搜索热点新闻...")
        
        # 主力：TikHub抖音热搜
        collector = TikHubCollector()
        news_items = collector.collect_all()

        # 备用：社交搜索Agent（需要额度）
        if not news_items:
            print("  ⚠️  TikHub未返回数据，尝试社交搜索Agent...")
            agent = SocialSearchAgent()
            news_items = agent.search(args.search)

        if not news_items:
            print("❌ 未能获取到热点数据")
            return

        # 如果只是搜索模式，输出结果供AI助手使用
        if args.search_only:
            result_path = output_dir / f"{task_id}_hot_news.json"
            result_path.write_text(
                json.dumps(news_items, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"\n✅ 热点数据已保存: {result_path}")
            print(f"   共 {len(news_items)} 条，请让AI助手基于此生成脚本。")
            return

        # 自动生成简易脚本
        print(f"  ✅ 获取到 {len(news_items)} 条热点")
        script = build_script_from_news(news_items, count=args.count)
        # 保存脚本
        script_save_path = output_dir / f"{task_id}_script.json"
        script_save_path.write_text(
            json.dumps(script, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"  📄 脚本已保存: {script_save_path}")

    elif args.manual_news:
        # 手动模式
        print("\n[1] 📝 使用手动输入的新闻")
        titles = [t.strip() for t in args.manual_news.split("|") if t.strip()]
        news_items = [{"title": t, "desc": t, "source": "手动"} for t in titles]
        script = build_script_from_news(news_items, count=args.count)

    else:
        print("❌ 请指定运行模式:")
        print("  --search '今日热点新闻'    搜索热点并生成视频")
        print("  --script output/xxx.json  使用已有脚本")
        print("  --manual-news '标题1|标题2' 手动指定新闻")
        print("\n推荐工作流:")
        print("  1. python generate_auto_news.py --search '今日热点' --search-only")
        print("  2. 让AI助手根据热点数据生成专业脚本JSON")
        print("  3. python generate_auto_news.py --script output/xxx_script.json")
        return

    if not script:
        print("❌ 无有效脚本")
        return

    print(f"  📰 标题: {script.get('title', '未命名')}")
    print(f"  📝 描述: {script.get('description', '')}")

    # ══════════════════════════════════════════
    # 步骤2：构建段落列表
    # ══════════════════════════════════════════

    slide_items = []

    opening = script.get("opening", {})
    if opening and opening.get("narration"):
        slide_items.append({
            "narration": opening["narration"],
            "image_prompt": opening.get("image_prompt", ""),
            "headline": "开场",
        })

    for news in script.get("news", []):
        if news.get("narration"):
            slide_items.append({
                "narration": news["narration"],
                "image_prompt": news.get("image_prompt", ""),
                "headline": news.get("headline", ""),
            })

    closing = script.get("closing", {})
    if closing and closing.get("narration"):
        slide_items.append({
            "narration": closing["narration"],
            "image_prompt": closing.get("image_prompt", ""),
            "headline": "结尾",
        })

    if not slide_items:
        print("❌ 脚本中没有有效段落")
        return

    print(f"\n  共 {len(slide_items)} 个段落:")
    for i, item in enumerate(slide_items):
        label = item.get("headline", f"段落{i+1}")
        narr = item["narration"][:50] + "..." if len(item["narration"]) > 50 else item["narration"]
        print(f"    [{i+1}] {label}: {narr}")

    # ══════════════════════════════════════════
    # 步骤3：生成配图
    # ══════════════════════════════════════════

    if args.skip_images:
        print("\n[2] ⏭️  跳过图片生成")
        # 用现有图片作为占位
        existing_slides = list(Path("news_slides").glob("*.png"))
        if existing_slides:
            fallback = existing_slides[0]
            final_images = [fallback] * len(slide_items)
        else:
            # 创建纯色占位图
            from PIL import Image
            placeholder = slides_dir / "placeholder.png"
            img = Image.new("RGB", (1280, 720), color=(30, 30, 60))
            img.save(placeholder)
            final_images = [placeholder] * len(slide_items)
    else:
        print(f"\n[2] 🎨 AI生成配图（{len(slide_items)}张）...")
        img_gen = NewsImageGenerator()
        image_paths = img_gen.generate_batch(slide_items, slides_dir)

        valid_images = [p for p in image_paths if p is not None]
        if not valid_images:
            print("❌ 所有图片生成失败")
            return
        fallback = valid_images[0]
        final_images = [p if p is not None else fallback for p in image_paths]

    # ══════════════════════════════════════════
    # 步骤4：TTS语音合成
    # ══════════════════════════════════════════

    segments = [item["narration"] for item in slide_items]
    full_narration = "\n".join(segments)

    print(f"\n[3] 🔊 语音合成...")
    tts = VolcanoTTSProvider(
        appid=tts_cfg.get("appid", ""),
        access_token=tts_cfg.get("access_token", ""),
        cluster=tts_cfg.get("cluster", "volcano_tts"),
        resource_id=tts_cfg.get("resource_id"),
        default_voice=args.voice,
        default_speed_ratio=args.speed,
    )
    audio_path = output_dir / f"{task_id}_narration.mp3"
    tts_result = await tts.synthesize(
        text=full_narration,
        voice=args.voice,
        output_path=audio_path,
        speed_ratio=args.speed,
    )
    print(f"  ✅ 完成: {tts_result.duration:.1f}秒")

    # ══════════════════════════════════════════
    # 步骤5：视频合成
    # ══════════════════════════════════════════

    print(f"\n[4] 🎬 合成视频...")

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

    if args.output_name:
        output_filename = f"{args.output_name}.mp4"
    else:
        output_filename = f"auto_news_{today_str}_{task_id}.mp4"

    composer = VideoComposer()
    video_config = VideoConfig.from_aspect_ratio("16:9", fps=30, bitrate="4M")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.task_id = task_id
    ctx.images = final_images
    ctx.audio_path = tts_result.audio_path
    ctx.bgm_path = None
    ctx.subtitle_data = subtitle_data
    ctx.output_path = output_dir / output_filename

    final_path = composer.compose(
        ctx=ctx,
        video_config=video_config,
        subtitle_style=SubtitleStyle(font_size=28, outline_width=2),
        narration_segments=segments,
        word_timings=tts_result.word_timings,
        enable_pan=False,
    )

    # ══════════════════════════════════════════
    # 完成
    # ══════════════════════════════════════════

    print("\n" + "=" * 60)
    print("✅ 视频生成完成!")
    print(f"  📹 输出: {final_path}")
    print(f"  ⏱️  时长: {tts_result.duration:.1f}秒")
    print(f"  📊 段落: {len(slide_items)}个")
    print(f"  🎯 标题: {script.get('title', '')}")
    print(f"  📝 描述: {script.get('description', '')}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

# LLM 模块技术文档

## 1. 架构概览

```
src/llm/
├── __init__.py
├── base.py              # 抽象基类 BaseLLMProvider
├── adapter.py           # LLMAdapter 统一适配器
├── openai_compat.py     # OpenAI 兼容格式 Provider（通义千问/DeepSeek/智谱/自定义）
├── wenxin.py            # 百度文心一言 Provider（专有 API）
├── prompt_builder.py    # 提示词模板构建器
├── keyword_extractor.py # 图片关键词提取器
src/narration_mode.py    # 解说模式枚举
```

核心设计：**适配器模式 + 工厂模式**。`LLMAdapter` 作为统一入口，根据 provider 名称和 config.toml 配置动态创建对应的 Provider 实例。所有 Provider 实现 `BaseLLMProvider` 抽象接口。

## 2. 抽象基类 BaseLLMProvider

```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate_narration(self, images: list[Path], prompt: str) -> str:
        """根据图片列表和提示词生成解说词文本"""
        ...
```

所有 LLM Provider 必须实现此接口。输入为图片路径列表 + 提示词文本，输出为生成的文本。

## 3. Provider 实现

### 3.1 OpenAICompatibleProvider

适用于所有兼容 OpenAI `/chat/completions` 接口的模型后端。

**支持的服务商：**
| Provider 名称 | API Base | 说明 |
|---|---|---|
| qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 通义千问 |
| deepseek | `https://api.deepseek.com/v1` | DeepSeek |
| glm | `https://open.bigmodel.cn/api/paas/v4` | 智谱AI |
| openai_compatible | 用户自定义 | 任意 OpenAI 兼容接口 |

**请求流程：**

1. 图片编码为 base64 data URI（`data:image/png;base64,xxxx`）
2. 构建多模态 messages（system + user，user 包含 text + image_url）
3. 发送 POST 到 `/chat/completions`，启用 stream=True
4. 读取 SSE 流，逐行解析 `data:` 前缀的 JSON chunk
5. 拼接所有 `delta.content` 返回完整文本

**关键参数：**

- `stream: true` — 流式响应
- `response_format: {"type": "json_object"}` — 强制 JSON 输出
- 超时：120 秒
- 重试：429 速率限制最多 3 次，指数退避（1s → 2s → 4s）

**鉴权方式：** `Authorization: Bearer {api_key}`

**错误处理：**

- 401 → 抛出 `PermissionError`（API 密钥无效）
- 429 → 指数退避重试
- 超时 → 抛出 `TimeoutError`
- 其他 HTTP 错误 → 抛出 `RuntimeError`

**System Prompt：**

```
你是一个纯JSON输出接口。你只输出合法的JSON对象，不输出任何其他文字、解释、推荐或建议。
用户会给你图片和一个JSON模板，你只需要填写模板中的value并返回完整JSON。
```

### 3.2 WenxinProvider

百度文心一言专有接口，不兼容 OpenAI 格式。

**鉴权流程：**

1. POST `https://aip.baidubce.com/oauth/2.0/token`
2. 参数：`grant_type=client_credentials`, `client_id={api_key}`, `client_secret={secret_key}`
3. 返回 `access_token`，缓存复用
4. 后续请求通过 URL 参数传递：`?access_token=xxx`

**API 端点：** `https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/{model}`

**请求体格式：**

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "提示词" },
        { "type": "image", "image": "base64编码" }
      ]
    }
  ]
}
```

**响应解析：** 从 `response["result"]` 提取文本

**错误处理：**

- HTTP 200 但 `error_code=110` → access_token 过期，清除缓存
- 429 → 指数退避重试（同 OpenAI）

## 4. LLMAdapter 适配器

统一入口，负责 Provider 的创建和管理。

### 4.1 初始化

```python
adapter = LLMAdapter(config["llm"])
```

### 4.2 获取 Provider

```python
provider = adapter.get_provider("openai_compatible", "gpt-5.4")
```

- 如果 model 为 None，使用 config 中的 `default_model`
- 通过工厂函数动态创建 Provider 实例

### 4.3 列出已配置的 Provider

```python
adapter.list_providers()  # 返回 api_key 非空的 provider 列表
```

### 4.4 列出模型

```python
adapter.list_models("qwen")  # 合并默认列表 + config 自定义列表
```

### 4.5 渲染提示词

```python
prompt = adapter.render_prompt(
    mode=NarrationMode.DESCRIBE_IMAGES,
    image_count=3,
    duration=60,
)
```

## 5. 提示词系统

### 5.1 解说模式

| 模式     | 枚举值            | 说明                           |
| -------- | ----------------- | ------------------------------ |
| 按图说话 | `describe_images` | 根据图片内容直接生成解说词     |
| 新闻解说 | `news_commentary` | 结合网络搜索生成新闻风格解说词 |

### 5.2 提示词模板

**按图说话模式：**

- 第一人称口吻
- 指定风格/语气/时长
- 输出 JSON 格式：`{"narration_1": "...", "narration_2": "..."}`

**新闻解说模式（有搜索上下文）：**

- 新闻解说员口吻
- 包含 `【相关新闻参考】` 搜索结果
- 客观专业风格

**新闻解说模式（无搜索上下文）：**

- 回退到仅基于图片的新闻风格

### 5.3 JSON 模板

```json
{
  "narration_1": "在此填写解说词正文",
  "narration_2": "在此填写解说词正文"
}
```

## 6. 关键词提取器

`KeywordExtractor` 用于新闻解说模式，从图片中提取关键词用于网络搜索。

**流程：**

1. 发送图片到 LLM，提示词要求提取 3-10 个关键词
2. 解析返回的 JSON：`{"keywords": ["关键词1", "关键词2"]}`
3. 关键词传给 `WebSearcher` 进行网络搜索
4. 搜索结果注入提示词模板

**容错：** LLM 调用失败或 JSON 解析失败时返回空列表，不中断流程。

## 7. 配置说明（config.toml）

```toml
[llm.qwen]
api_key = ""                    # 通义千问 API Key
default_model = "qwen-vl-max"   # 默认模型
models = ["qwen-vl-max", "qwen-vl-plus"]  # 可选模型列表

[llm.deepseek]
api_key = ""
default_model = "deepseek-chat"
models = ["deepseek-chat", "deepseek-reasoner"]

[llm.glm]
api_key = ""
default_model = "glm-4v"
models = ["glm-4v", "glm-4v-plus", "glm-4v-flash"]

[llm.wenxin]
api_key = ""
secret_key = ""                 # 文心一言需要额外的 secret_key
default_model = "ernie-bot-4"

[llm.openai_compatible]
api_base = "https://your-api.com/v1"  # 自定义 API 地址
api_key = "your-key"
default_model = "gpt-4"
models = ["gpt-4", "gpt-3.5-turbo"]
```

## 8. 调用示例

```python
import asyncio
from src.llm.adapter import LLMAdapter
from src.narration_mode import NarrationMode
from pathlib import Path

# 初始化
config = {"openai_compatible": {"api_base": "...", "api_key": "...", "default_model": "gpt-4"}}
adapter = LLMAdapter(config)

# 获取 provider
provider = adapter.get_provider("openai_compatible")

# 生成解说词
prompt = adapter.render_prompt(mode=NarrationMode.DESCRIBE_IMAGES, image_count=2, duration=60)
result = asyncio.run(provider.generate_narration([Path("img1.jpg"), Path("img2.jpg")], prompt))
print(result)

# 关键词提取
from src.llm.keyword_extractor import KeywordExtractor
extractor = KeywordExtractor(provider)
keywords = asyncio.run(extractor.extract([Path("news.jpg")]))
print(keywords)  # ["特朗普", "白宫", "关税"]
```

## 9. 扩展新 Provider

1. 创建 `src/llm/your_provider.py`，继承 `BaseLLMProvider`
2. 实现 `generate_narration` 方法
3. 在 `adapter.py` 的 `PROVIDERS` 和 `DEFAULT_MODELS` 中注册
4. 在 `config.toml` 中添加对应配置段

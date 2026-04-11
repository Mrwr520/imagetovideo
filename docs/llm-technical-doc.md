# LLM 第三方 API 调用文档

## 当前使用的 API

项目通过 OpenAI 兼容接口调用 LLM，当前配置：

```
API 地址：https://api-vip.codex-for.me/v1
模型：gpt-5.4
```

## 最终 HTTP 请求

### 请求

```
POST https://api-vip.codex-for.me/v1/chat/completions

Headers:
  Authorization: Bearer {api_key}
  Content-Type: application/json
```

### 请求体

```json
{
  "model": "gpt-5.4",
  "stream": true,
  "response_format": { "type": "json_object" },
  "messages": [
    {
      "role": "system",
      "content": "你是一个纯JSON输出接口。你只输出合法的JSON对象，不输出任何其他文字、解释、推荐或建议。用户会给你图片和一个JSON模板，你只需要填写模板中的value并返回完整JSON。"
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "我是一个内容创作者...我给你3张图片...按以下JSON格式填写value：\n{\"narration_1\": \"在此填写解说词正文\", \"narration_2\": \"在此填写解说词正文\", \"narration_3\": \"在此填写解说词正文\"}"
        },
        {
          "type": "image_url",
          "image_url": { "url": "data:image/png;base64,iVBORw0KGgo..." }
        },
        {
          "type": "image_url",
          "image_url": { "url": "data:image/png;base64,/9j/4AAQSk..." }
        },
        {
          "type": "image_url",
          "image_url": { "url": "data:image/png;base64,UklGRlYA..." }
        }
      ]
    }
  ]
}
```

### 响应（SSE 流式）

```
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"{"}}]}
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"\"narration_1\""}}]}
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":": \"大家好..."}}]}
...
data: [DONE]
```

客户端逐行读取 `delta.content` 拼接成完整 JSON 字符串。

### 期望的返回结果

```json
{
  "narration_1": "第一张图的解说词正文",
  "narration_2": "第二张图的解说词正文",
  "narration_3": "第三张图的解说词正文"
}
```

## 配置位置

`config.toml` 中的 `[llm.openai_compatible]` 段：

```toml
[llm.openai_compatible]
api_base = "https://api-vip.codex-for.me/v1"
api_key = "your-api-key"
default_model = "gpt-5.4"
models = ["gpt-5.4"]
```

## 超时与重试

- 请求超时：120 秒
- 429 速率限制：指数退避重试，最多 3 次（1s → 2s → 4s）
- 401 无效密钥：直接报错

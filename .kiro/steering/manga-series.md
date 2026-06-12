---
inclusion: manual
---

# 漫画连载视频生成工作流

当用户说"做下一集凡人"、"凡人修仙传下一集"、"继续漫画连载"时，执行此工作流。

## 与资讯视频的区别
- 资讯视频用 `generate_auto_news.py`，风格轻松日常
- 漫画连载也用 `generate_auto_news.py --script xxx.json`，但风格是仙侠漫画

## 工作流步骤

### 0. 检查进度
- 读取 `characters/fanren/progress.json` 查看当前做到哪一集、对应原著哪一章
- 读取 `characters/fanren/characters.json` 获取角色固定提示词
- 根据进度确定下一集要讲的章节范围

### 1. 读取原著内容
- 从 `src/《凡人修仙传》（校对版全本+番外）作者：忘语.txt`（GBK编码）读取对应章节
- 提炼出关键剧情：谁做了什么、打斗场面、情感转折
- 每集覆盖2-4章原著内容（根据剧情密度调整）

### 2. 编写脚本JSON
- **时长**：30-60秒（台词短促，图片多，动态漫画节奏）
- **图片**：8-12张（每张3-6秒，像翻漫画）
- **语音**：`zh_male_ruyayichen_uranus_bigtts`（儒雅逸辰，仙侠感）
- **风格**：动态漫画，不是旁白叙事

**解说词规则：**
- **动态漫画模式：语音 = 角色台词**
- 图片气泡写什么，语音就说什么，完全一一对应
- 台词要简短有力，像漫画分镜里的对话（不超过20字为佳）
- 可以有少量旁白过渡（如"百年后""就在这时"），但主体是角色说话
- **打斗场景要拆细，不要一笔带过**：挑衅→出手→反击→结果，每张都有台词
- 情感场景也要拆：铺垫→关键台词→对方反应
- 每集结尾留悬念钩子

**图片提示词规则：**
- 风格统一：Chinese xianxia manga panel, dramatic lighting, high quality
- **构图服务剧情：特写、半身、中景、远景都可以，哪个合适用哪个**
- 每张像漫画分镜：脸部特写、半身对话、动作中景交替
- 每张必须有**大字中文对话气泡**，内容就是该帧语音的台词
- 角色外观从 characters.json 复制，不自己编
- 打斗：中景动作+速度线+冲击波，拆成多张表现过程
- 情感：脸部特写+光影对比+表情细节
- 反派/配角也要有 name tag 标识身份

### 3. 生成视频
```bash
python generate_auto_news.py --script output/fanren_epXX.json --output-name fanren_epXX
```
注意：默认voice参数已不重要，因为每个段落JSON中都指定了voice字段。

### 多角色语音说明
脚本JSON中每个段落可以带 `"voice": "xxx"` 字段指定该段用哪个语音。
角色语音对应关系在 characters.json 中定义：
- 旁白：zh_male_ruyayichen_uranus_bigtts（儒雅逸辰）
- 韩立：zh_male_m191_uranus_bigtts（云舟）
- 老年男性（雷万鹤/墨大夫）：zh_male_dayi_uranus_bigtts（大壹）
- 反派/张狂角色：zh_male_shaonianzixin_uranus_bigtts（少年梓辛）
- 南宫婉：zh_female_cancan_uranus_bigtts（知性灿灿）
- 聂盈/年轻女性：zh_female_qingxinnvsheng_uranus_bigtts（清新女声）

### 4. 更新进度
- 更新 `characters/fanren/progress.json`：记录集数、章节范围、标题
- 确保下次能无缝衔接

## 文件结构
```
characters/fanren/
├── characters.json    # 角色设定（外观/性格/提示词）
└── progress.json      # 连载进度记录

output/
├── fanren_ep01.json   # 每集脚本
├── fanren_ep01.mp4    # 每集视频
└── ...
```

## 角色提示词引用
写脚本时从 characters.json 的 appearance 字段复制角色描述，不要自己编，保持一致。

## 注意事项
- 不要剧透太远，每集只讲2-4章
- 结尾必须留悬念钩子
- 标题要有吸引力（悬念/反转/情感）
- 图片分辨率用 768x432（和资讯视频一样）

# vn-tiktok-content-kit

面向越南 TikTok 竖屏短视频的**命令行工具集**：抽帧、抓取、投喂包生成、结构与合规校验。
只包含可执行工具与数据格式示例，不含任何方法论文档、样本数据或运营经验。

## 环境

| 依赖 | 版本 | 用在哪 |
|---|---|---|
| Python | 3.9+ | `frame_extract.py` / `gen_kit.py` / `validate.py`（全标准库，无 pip 依赖） |
| Node.js | 18+ | `harvest_v2.js` / `harvest_author.js`（依赖 `playwright-core`） |
| ffmpeg | 任意近期版本 | `frame_extract.py` 抽帧（需在 PATH 中） |

```bash
# JS 工具需要 playwright-core（在你自己的项目目录里装，不要装进本仓库）
npm i playwright-core
```

## 工具清单

| 脚本 | 作用 | 依赖 | 用法 |
|---|---|---|---|
| `scripts/frame_extract.py` | 视频抽帧：均匀帧 + 蒙太奇 + 钩子/中段/收尾特写 | ffmpeg | `python scripts/frame_extract.py --videos-dir videos --out frames` |
| `scripts/harvest_v2.js` | 按关键词批量抓站内爆款（播放/赞/评/转，走站内 API） | playwright-core + 已登录浏览器 | `node scripts/harvest_v2.js "kw1,kw2" --pages=3` |
| `scripts/harvest_author.js` | 抓指定账号全部作品（滚页渲染，含描述与播放） | playwright-core + 已登录浏览器 | `node scripts/harvest_author.js <账号1> <账号2>` |
| `scripts/gen_kit.py` | 从文案 JSON 一次产出 `内容包/`（md，给人看）与 `投喂包/`（txt，给模型吃） | 无 | `python scripts/gen_kit.py --lib <你的库>.json --out ./交付` |
| `scripts/validate.py` | 结构与合规质检，退出码 0=全过 / 1=有 error / 2=库读不了 | 无 | `python scripts/validate.py --lib <你的库>.json` |

### 常用参数

**frame_extract.py**
```bash
python scripts/frame_extract.py --videos-dir videos --out frames \
  --short-n 12 --long-step 12 --max-n 40
# --short-n 短视频抽帧数（<90s，默认 12）｜--long-step 长视频每 N 秒一帧（默认 12）｜--max-n 单视频上限（默认 40）
```

**harvest_v2.js / harvest_author.js 前置条件**
1. Chrome 以 `--remote-debugging-port=9222` 启动，并已登录目标平台账号；
2. 浏览器出口 IP 与目标市场一致（抓取结果强依赖地域）；
3. 产出 JSON 落在**当前工作目录**，不写进本仓库。
4. `harvest_v2.js` 的关键词**必须自己给**，脚本不自带任何默认词：
   `node scripts/harvest_v2.js "关键词1,关键词2" [--pages=N]`

**gen_kit.py / validate.py**
```bash
python scripts/validate.py --lib assets/scripts_lib.example.json          # 先过闸
python scripts/gen_kit.py  --lib assets/scripts_lib.example.json --out ./交付
# --only S01,S07 只做指定条目｜--no-feed 只要内容包｜--no-content 只要投喂包
# validate 额外支持 --banned custom_banned.txt（一行一个禁用词）、--config 外部配置
```

## 数据格式

`assets/scripts_lib.example.json` 是一份**字段演示**：`config`（规则）+ `field_note`（字段约束）+ 一条示例脚本。
复制它改成你自己的库即可，**没有任何形态或行业预设**。

### `config`——规则全在这里

代码里不写死任何东西：几镜、怎么交替、语速、禁用词、人物设定、配色、标注文案，全部读 `config`。换形态只改它，不动代码。

| 键 | 作用 |
|---|---|
| `structure.segment_seconds` | 每镜基准秒数（槽位按镜数 × 该值估算） |
| `structure.shot_count` / `pattern` | 镜头总数 / 人像(`P`)与卡片(`C`)排列，如 `PCPCP`。留空则不校验结构 |
| `speech.rate` | 语速（音节/秒），按你的语言实测填 |
| `speech.max_text_ratio` | 单行字幕上限 = 该值 ÷ 字号 |
| `speech.slot_slack` | 槽位允许超出的倍数 |
| `compliance.banned` | 禁用词数组（匹配前去音标，防变体规避） |
| `compliance.case_sensitive` | 需区分大小写的词 |
| `compliance.required_context` | 语境词规则：`{word, any_of, conflict_with, ...}`——词出现且撞 `conflict_with` 报错，缺 `any_of` 提示 |
| `compliance.max_hashtags` / `required_overlay` | 标签上限 / 画面须常驻的标注文案 |
| `compliance.digit_note_keyword` | 口播含数字时，`note_zh` 里出现该词即视为已核实 |
| `render.*` | 画幅、强调色、卡片底色、人物设定（中英）、禁用词提示语、口播语言与音色 |
| `require_zh` | 是否强制每条口播都有对照句 |

### `scripts[]`——逐条脚本

| 字段 | 说明 |
|---|---|
| `id` / `pillar` / `type` / `angle_zh` | 编号 / 分类 / 目标 / 角度（自由填，生成器会带到交付物里） |
| `segments[]` | 逐镜：`img`（人像景别）、`move`（运镜）、`l1`/`l2`（屏幕字幕）、`say1`（口播）、`size`（字号）、`card`（卡片镜） |
| `card.kind` | `bigword` / `list` / `strike` / `check` / `compare` |
| `title` / `hashtags` / `voiceover_vi` | 发布信息 |
| `zh_lines` / `note_zh` | 逐句对照 / 制作备注（`require_zh` 开启时必填） |

字段的逐条约束写在示例文件的 `field_note` 里。

## 边界与合规

- 本仓库**不含**：内容方法论、选题库、对标账号数据、成品文案、投放与增长经验。
- 抓取工具只处理**公开页面**；请使用独立浏览器实例，**不要挂业务账号的登录态**做批量抓取，避免账号风控。
- 生成的文案若含数字/效果类表述，发布前须自行核实并遵守当地广告法与平台规则。

## License

工具代码可自由改造自用；使用风险自负。

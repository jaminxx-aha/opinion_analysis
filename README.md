# 舆情分析工具

基于 LLM 的智能舆情数据分析工具，读取 Excel 中的用户反馈数据，自动分类性能问题，并生成交互式可视化 HTML 报告。

## 功能特性

- **自动识别**：智能推断 Excel 中的应用名列和问题描述列
- **三级分类**：基于应用专属知识库，将性能问题分为一级→二级→三级层级分类
- **可视化报告**：生成交互式 HTML 报告，包含：
  - Chart.js 柱状图与环形图
  - 一级/二级/三级级联下拉筛选
  - 分页数据表格与搜索
  - 点击查看分类推理详情弹窗
- **可靠处理**：支持续跑、重试失败、重试未知问题，适配大规模数据集

## 分类体系

采用三级层级分类（一级→二级→三级），分类体系由应用专属知识库决定，不同应用的分类维度和细分内容各不相同。每个应用的知识库包含：

- **info.md** — 应用描述与模块划分
- **classification.md** — 该应用的三级分类树
- **examples.md** — 分类示例与推理过程

示例分类路径（抖音）：

```
卡顿 > 滑动卡顿 > 首页推荐视频流上下滑动卡顿
闪退/崩溃 > 播放闪退 > 首页推荐视频播放闪退
```

示例分类路径（微信）：

```
卡顿 > 聊天卡顿 > 聊天消息列表滑动卡顿
响应慢/延迟 > 搜索延迟 > 聊天搜索响应慢
```

## 快速开始

### 1. 环境配置

复制 `.env.example` 为 `.env` 并填入 LLM API 信息：

```bash
cp .env.example .env
```

```ini
LLM_PROVIDER=openai          # openai 或 anthropic
LLM_MODEL=deepseek-chat      # 模型名称
LLM_API_KEY=your-api-key     # API 密钥
LLM_BASE_URL=https://api.deepseek.com/v1  # API 地址
```

### 2. 安装依赖

```bash
pip install pandas openpyxl python-dotenv
# SDK 方式还需安装对应包：
pip install openai      # LLM_PROVIDER=openai 时
pip install anthropic   # LLM_PROVIDER=anthropic 时
```

### 3. 运行分析

通过 Claude Code 技能触发（推荐）：

```
/opinion-analysis 分析 test/douyin_100.xlsx
```

或手动执行脚本：

```bash
# 步骤1：查看 Excel 列信息
python .claude/skills/opinion-analysis/scripts/analyze_excel.py test/douyin_100.xlsx --info

# 步骤2：分类并生成报告
python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --app-name 抖音 --app-index 2 --problem-index 5 \
  --excel-path test/douyin_100.xlsx --output-dir output/douyin_100

# 步骤3（可选）：重试失败或未知问题
python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --app-name 抖音 --app-index 2 --problem-index 5 \
  --excel-path test/douyin_100.xlsx --output-dir output/douyin_100 \
  --retry [failed/unknow]    # 重试推理【失败/未知】的数据
```

不带 `--retry` 时为续跑模式，从数据库最大 ID 之后继续处理。

## 项目结构

```
├── .env.example                        # 环境变量模板
├── test/                                # 测试 Excel 数据
├── output/                              # 生成的报告与数据库
└── .claude/skills/opinion-analysis/
    ├── SKILL.md                         # 技能定义与工作流
    ├── assets/
    │   └── report_template.html         # HTML 报告模板
    ├── references/apps/                 # 应用知识库
    │   ├── 抖音/ { info.md, classification.md, examples.md }
    │   ├── 微信/ { info.md, classification.md, examples.md }
    │   ├── 淘宝/ { info.md, classification.md, examples.md }
    │   ├── 快手/ { info.md, classification.md, examples.md }
    │   └── 小红书/ { info.md, classification.md, examples.md }
    └── scripts/
        ├── config.py                    # 配置、应用别名、列解析
        ├── classify_data.py             # LLM 分类核心脚本
        ├── analyze_excel.py             # Excel 分析 + 报告生成
        └── generate_report.py           # DB/JSON → HTML 报告渲染
```

## 支持的应用

| 应用 | 知识库 | 别名示例 |
|------|--------|----------|
| 抖音 | ✅ 完整分类 | douyin、字节、头条 |
| 微信 | ✅ 完整分类 | wechat、鹅厂、腾讯 |
| 淘宝 | ✅ 完整分类 | taobao、阿里 |
| 快手 | ✅ 完整分类 | kuaishou |
| 小红书 | ✅ 完整分类 | xiaohongshu、red、红书 |

其他应用（哔哩哩哩、京东、美团、拼多多等）会保留应用名称但标记为"未知问题"。

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `LLM_PROVIDER` | 是 | API 格式：`openai` 或 `anthropic` |
| `LLM_MODEL` | 是 | 模型名称 |
| `LLM_API_KEY` | 是 | API 密钥 |
| `LLM_BASE_URL` | 是 | API 基地址 |
| `LLM_MAX_CONCURRENT` | 否 | 最大并发数，默认 1 |
| `LLM_MAX_TOKENS` | 否 | 最大输出 token，默认 1024 |
| `LLM_BATCH_SIZE` | 否 | 每次请求处理行数，默认 1 |
| `LLM_MAX_RETRIES` | 否 | 最大重试次数，默认 3 |
| `LLM_TIMEOUT` | 否 | 超时秒数，默认 30 |
| `LLM_TEMPERATURE` | 否 | 温度参数，默认 0.7 |
| `LLM_VERIFY_SSL` | 否 | SSL 验证，默认 true |
| `LLM_LOG_LEVEL` | 否 | 日志级别，默认 INFO |

## 许可

MIT
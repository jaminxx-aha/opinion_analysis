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

本工具支持两条并行的分类轴，用户运行时通过 `--domain` 选择本次分析哪条轴：

- **功能域（function）**：按性能/功能问题维度分类（卡顿、闪退、启动异常……）。
- **业务域（business）**：按业务模块维度分类（短视频内容、直播、电商、社交……）。

两条轴采用相同的三级层级分类（一级→二级→三级），由应用专属知识库决定。两个域**各自独立运行、互不影响**：同一输出目录下分别生成 `function_report.db` 与 `business_report.db`，续跑/重试按域隔离。报告会读取目录下已存在的所有域 DB，合并成一份双标签页报告，可在「功能域 / 业务域」之间切换查看。

每个应用的每个域知识库包含：

- **info.md** — 应用描述与模块划分（两域共享）
- **classification_function.md** / **classification_business.md** — 功能域 / 业务域的三级分类树
- **examples_function.md** / **examples_business.md** — 分类示例与推理过程
- **error_examples_function.md** / **error_examples_business.md** — 错误推理示例

示例分类路径（抖音·功能域）：

```
卡顿 > 滑动卡顿 > 首页推荐视频流上下滑动卡顿
闪退/崩溃 > 播放闪退 > 首页推荐视频播放闪退
```

示例分类路径（抖音·业务域）：

```
短视频内容 > 内容浏览 > 推荐视频流
电商交易 > 交易流程 > 下单/支付
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
LLM_API_KEY=your-api-key     # API 密钥 (多个key用逗号分隔)
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
python .claude/skills/opinion-analysis/scripts/excel_info.py test/douyin_100.xlsx

# 步骤2：查看当前支持的应用列表
python .claude/skills/opinion-analysis/scripts/app_list.py

# 步骤3：分类并生成报告（功能域）
python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --domain function --app-name 抖音 --problem-index 5 \
  --excel-path test/douyin_100.xlsx --output-dir output/douyin_100

# 步3'（可选）：业务域分析（同一份数据、同一输出目录）
python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --domain business --app-name 抖音 --problem-index 5 \
  --excel-path test/douyin_100.xlsx --output-dir output/douyin_100

# 步骤3（可选）：改走 Claude Agent SDK + 抖音舆情 skill（需在 .env 配 LLM_AGENT_*）
LLM_PROVIDER=claude-agent-sdk python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --domain function --app-name 抖音 --problem-index 5 \
  --excel-path test/douyin_100.xlsx --output-dir output/douyin_100

# 步骤4（可选）：重试失败或未知问题（只作用于指定 --domain）
python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --domain function --app-name 抖音 --problem-index 5 \
  --excel-path test/douyin_100.xlsx --output-dir output/douyin_100 \
  --retry [failed/unknow]    # 重试推理【失败/未知】的数据
```

`--domain` 必填：`function`=功能域/性能问题，`business`=业务域。不带 `--retry` 时为续跑模式，从对应域 DB 的最大 ID 之后继续处理。报告会自动合并同一输出目录下已运行的所有域。

## 项目结构

```
├── .env.example                        # 环境变量模板
├── test/                                # 测试 Excel 数据
├── output/                              # 生成的报告与数据库
└── .claude/skills/opinion-analysis/
    ├── SKILL.md                         # 技能定义与工作流
    ├── assets/
    │   └── report_template.html         # HTML 报告模板（功能域/业务域双标签页）
    │       (dashboard_template.html / compare_period_template.html / chart.js)
    ├── references/apps/                 # 应用知识库
    │   └── 抖音/ {
    │         info.md,                              # 应用描述（两域共享）
    │         classification_function.md / examples_function.md / error_examples_function.md,        # 功能域
    │         classification_business.md / examples_business.md / error_examples_business.md         # 业务域
    │       }
    └── scripts/
        ├── app_list.py                  # 当前支持的应用列表
        ├── excel_info.py                # Excel 前几行预览
        ├── classify_data.py             # LLM 分类核心脚本（--domain 必填 / 续跑 / --retry）
        ├── generate_report.py           # 目录或 DB → 单篇 HTML 报告（自动合并双域）
        ├── generate_dashboard.py        # 扫描 output/ 生成汇总仪表盘（--domain）
        ├── compare_period.py            # 两期分类报告对比（传对应域 DB）
        ├── export_db_to_excel.py        # DB → Excel，带校准分类与正确率校验
        └── fix_invalid_classifications.py  # 修复 DB 中不在编码表的脏数据
```

## 支持的应用

| 应用 | 知识库 | 别名示例 |
|------|--------|----------|
| 抖音 | ✅ 完整分类 | douyin、字节、头条 |

其他应用会保留应用名称但标记为"未知问题"。

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `LLM_PROVIDER` | 是 | API 格式：`openai` 或 `anthropic` |
| `LLM_MODEL` | 是 | 模型名称 |
| `LLM_API_KEY` | 是 | API 密钥（多个key用逗号分隔） |
| `LLM_BASE_URL` | 是 | API 基地址 |
| `LLM_MAX_CONCURRENT` | 否 | 每个key的最大并发数（总并发=key数×此值），默认 1 |
| `LLM_MAX_TOKENS` | 否 | 最大输出 token，默认 1024 |
| `LLM_BATCH_SIZE` | 否 | 每次请求处理行数，默认 1 |
| `LLM_MAX_RETRIES` | 否 | 最大重试次数，默认 3 |
| `LLM_TIMEOUT` | 否 | 超时秒数，默认 30 |
| `LLM_TEMPERATURE` | 否 | 温度参数，默认 0.7 |
| `LLM_VERIFY_SSL` | 否 | SSL 验证，默认 true |
| `LLM_LOG_LEVEL` | 否 | 日志级别，默认 INFO |

### Claude Agent SDK provider

设 `LLM_PROVIDER=claude-agent-sdk` 时改走 headless Claude Code agent 加载「抖音舆情分析」skill 做分类（需 `pip install claude-agent-sdk` + 已安装 `claude` CLI）。此时使用以下变量：

| 变量 | 必需 | 说明 |
|------|------|------|
| `LLM_AGENT_SKILL_DIR` | 是 | 含 `.claude/skills/<skill>/SKILL.md` 的项目根目录 |
| `LLM_AGENT_SKILL_NAME` | 否 | skill 名称，默认 `抖音舆情分析` |
| `LLM_AGENT_MODEL` | 否 | 模型 ID，如 `claude-opus-4-8` |
| `LLM_AGENT_API_KEY` | 否 | Anthropic API key；留空则用 `claude /login` 的 OAuth 凭据 |
| `LLM_AGENT_BASE_URL` | 否 | 走代理时填写 |
| `LLM_AGENT_MAX_TURNS` | 否 | agent 最大轮次，默认 10 |

skill 单条问题→单个 JSON、一次性返回完整分类编码，batch/layered reason mode 自动退化为每条一次 agent 调用；并发仍由 `LLM_MAX_CONCURRENT` 控制。skill 返回的编码须对齐 `references/apps/抖音/classification_*.md` 编码表，否则该条落「推理失败」。

## 许可

MIT
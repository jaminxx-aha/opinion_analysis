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

每个应用的每个域知识库只保留分类树，用于对 agent 返回的分类结果做编码校验（推理本身由 skill 自带的 references 完成）：

- **classification_function.md** — 功能域分类树
- **classification_business.md** — 业务域分类树

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
LLM_MODEL=glm-5.2             # 模型名称
LLM_API_KEY=your-api-key      # API 密钥 (多个key用逗号分隔；留空则用 claude CLI 的 OAuth 登录)
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  # API 地址
LLM_AGENT_SKILL_DIR=.         # 含 .claude/skills/<skill>/SKILL.md 的项目根目录（必填）
```

### 2. 安装依赖

```bash
pip install -r .claude/skills/opinion-analysis/scripts/requirements.txt
# 另需已安装 claude CLI（agent 通过 claude-agent-sdk 调起 headless agent）
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
├── scripts/                             # 运维脚本（脱离 skill 核心）
│   ├── export_db_to_excel.py            # DB → Excel，带校准分类与正确率校验
│   ├── fix_invalid_classifications.py   # 修复 DB 中不在编码表的脏数据
│   └── print_classifications.py         # 打印 DB 中问题描述与分类（TSV）
└── .claude/skills/opinion-analysis/
    ├── SKILL.md                         # 技能定义与工作流
    ├── assets/
    │   └── report_template.html         # HTML 报告模板（功能域/业务域双标签页）
    │       (dashboard_template.html / compare_period_template.html / chart.js)
    ├── references/apps/                 # 应用知识库
    │   └── 抖音/ {
    │         classification_function.md,             # 功能域分类树（agent 结果校验）
    │         classification_business.md              # 业务域分类树
    │       }
    └── scripts/
        ├── app_list.py                  # 当前支持的应用列表
        ├── excel_info.py                # Excel 前几行预览
        ├── classify_data.py             # 入口：4 阶段编排（args→prepare_data→run→generate_report）
        ├── args.py                      # Phase 1：参数/配置/参考库加载
        ├── db_utils.py                  # DB 初始化/连接复用/入库/文本清洗
        ├── processor.py                 # Phase 2 prepare_data + Phase 3 run 分派
        ├── runtime.py                   # 运行时状态（输出目录/进度）+ 响应解析
        ├── classify_agent.py            # Claude Agent SDK 单条分类推理
        ├── claude_agent_client.py       # claude-agent-sdk 流式封装
        ├── generate_report.py           # 目录或 DB → 单篇 HTML 报告（自动合并双域）
        ├── generate_dashboard.py        # 扫描 output/ 生成汇总仪表盘（--domain）
        └── compare_period.py            # 两期分类报告对比（传对应域 DB）
```

## 支持的应用

| 应用 | 知识库 | 别名示例 |
|------|--------|----------|
| 抖音 | ✅ 完整分类 | douyin、字节、头条 |

其他应用会保留应用名称但标记为"未知问题"。

## 环境变量

推理路径唯一：Claude Agent SDK（headless Claude Code agent 加载「抖音舆情分析」skill 做分类，单条问题→单次 agent 调用）。需 `pip install claude-agent-sdk` + 已安装 `claude` CLI。

| 变量 | 必需 | 说明 |
|------|------|------|
| `LLM_AGENT_SKILL_DIR` | 是 | 含 `.claude/skills/<skill>/SKILL.md` 的项目根目录 |
| `LLM_AGENT_SKILL_NAME` | 否 | skill 名称，默认 `douyin-performance-problem-classifier` |
| `LLM_MODEL` | 否 | 模型名称；留空用 claude CLI 默认 |
| `LLM_API_KEY` | 否 | API 密钥（多个key用逗号分隔）；留空则用 `claude /login` 的 OAuth 凭据 |
| `LLM_BASE_URL` | 否 | API 基地址（走代理时填写） |
| `LLM_MAX_CONCURRENT` | 否 | 每个key的最大并发数（总并发=key数×此值），默认 1 |
| `LLM_AGENT_MAX_TURNS` | 否 | agent 最大轮次，默认 10 |
| `LLM_AGENT_TIMEOUT` | 否 | agent 单次调用超时秒数，默认 120（需多轮读 skill 文件） |
| `LLM_MAX_RETRIES` | 否 | 最大重试次数，默认 3 |
| `LLM_LOG_LEVEL` | 否 | 日志级别，默认 DEBUG |

skill 单条问题→单个 JSON、一次性返回完整分类编码，并发由 `LLM_MAX_CONCURRENT` 控制。skill 返回的编码须对齐 `references/apps/抖音/classification_*.md` 编码表，否则该条落「推理失败」。

## 许可

MIT
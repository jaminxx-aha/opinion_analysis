# 舆情分析工具

基于 Claude Agent SDK 的智能舆情数据分析工具：读取 Excel 中的用户反馈数据，通过 headless Claude Code agent 加载「抖音舆情分析」子 skill 对每条问题做分类，生成交互式可视化 HTML 报告。

## 功能特性

- **agent 推理**：每条问题描述发起一次 agent 调用，skill 一次性返回完整分类编码；失败时自动 `json_repair` 修复 + 把错误信息/分类树带回 agent 重试
- **双域分类**：功能域（性能问题）与业务域各自独立运行，同一输出目录共用 `report.db`，报告合并为双标签页
- **断点续跑**：从该表最大 id 之后继续处理新行，中断后重跑不重复劳动
- **失败重试**：独立的 `retry_failed.py` 对推理失败(status=2)的数据重跑，只需给一个目录
- **可视化报告**：交互式 HTML，含 Chart.js 图表、级联下拉筛选、分页表格、推理详情弹窗
- **多 key 并发**：逗号分隔多个 API key，总并发 = key 数 × `LLM_MAX_CONCURRENT`

## 分类体系

两条并行的分类轴，运行时通过 `--domain` 选择本次分析哪条轴：

- **功能域（function，默认）**：按性能/功能问题维度分类（卡顿、闪退、启动异常……）
- **业务域（business）**：按业务模块维度分类（短视频内容、直播、电商、社交……）

每个应用的每个域知识库只保留分类树（`classification_function.md` / `classification_business.md`），用于校验 agent 返回的分类路径是否合法。推理本身由子 skill 自带的 references 完成。

示例分类路径（抖音·功能域）：

```
卡顿 > 滑动卡顿 > 首页推荐视频流上下滑动卡顿
闪退/崩溃 > 播放闪退 > 首页推荐视频播放闪退
```

## 快速开始

### 1. 环境配置

复制 `.env.example` 为 `.env` 并填入配置：

```bash
cp .env.example .env
```

```ini
LLM_MODEL=glm-5.2             # 模型名称
LLM_API_KEY=your-api-key      # API 密钥 (多个key用逗号分隔；留空则用 claude CLI 的 OAuth 登录)
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
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
/opinion-analysis 分析 test/2025-05-05.xlsx
```

或手动执行脚本：

```bash
# 步骤1：查看 Excel 列信息（确定问题描述列索引等）
python .claude/skills/opinion-analysis/scripts/excel_info.py test/2025-05-05.xlsx

# 步骤2：查看当前支持的应用列表
python .claude/skills/opinion-analysis/scripts/app_list.py

# 步骤3：分类并生成报告（功能域，默认）
python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --app-name 抖音 --problem-index 4 --version-index 12 \
  --excel-path test/2025-05-05.xlsx --output-dir output/2025-05-05

# 步骤3'（可选）：业务域分析（同一份数据、同一输出目录）
python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --app-name 抖音 --problem-index 4 --version-index 12 \
  --excel-path test/2025-05-05.xlsx --output-dir output/2025-05-05 \
  --domain business

# 步骤4（可选）：重试推理失败的数据（只需给输出目录，不需 Excel）
python .claude/skills/opinion-analysis/scripts/retry_failed.py output/2025-05-05
```

`--domain` 可选，默认 `function`。不带 `--retry` 时为续跑模式，从对应域表的最大 id 之后继续处理。报告会自动合并同一输出目录下已运行的所有域。

## 项目结构

```
├── .env.example                        # 环境变量模板
├── test/                                # 测试 Excel 数据（按周）
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
    ├── references/apps/                 # 应用知识库（分类树，用于结果校验）
    │   └── 抖音/ {
    │         classification_function.md,             # 功能域分类树
    │         classification_business.md              # 业务域分类树
    │       }
    └── scripts/
        ├── classify_data.py             # 入口：4 阶段编排（参数→数据准备→执行→报告）
        ├── args.py                      # 参数/配置/参考库加载
        ├── db_utils.py                  # DB 初始化/连接复用/入库/文本清洗
        ├── processor.py                 # 数据准备(prepare_data) + 执行分派(run)
        ├── runtime.py                   # 运行时状态(输出目录/进度) + 响应解析
        ├── classify_agent.py            # agent 单条分类推理 + 重试(json_repair/分类树纠偏)
        ├── claude_agent_client.py       # claude-agent-sdk 流式封装
        ├── retry_failed.py              # 重试 DB 中推理失败(status=2)的数据
        ├── generate_report.py           # 目录或 DB → 单篇 HTML 报告（自动合并双域）
        ├── generate_dashboard.py        # 扫描 output/ 生成汇总仪表盘（--domain）
        ├── compare_period.py            # 两期分类报告对比（传对应域 DB）
        ├── excel_info.py                # Excel 前几行预览
        └── app_list.py                  # 当前支持的应用列表
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
| `LLM_MAX_RETRIES` | 否 | 单条数据最大重试次数，默认 3 |
| `LLM_LOG_LEVEL` | 否 | 日志级别，默认 DEBUG |

每条数据最多重试 `LLM_MAX_RETRIES` 次：JSON 解析失败先 `json_repair` 修复（修复成功不消耗重试），修不了把错误信息带回 agent；分类不在树里则把分类树带回 agent 让其重新选择。仍失败则落「推理失败」(status=2)，可用 `retry_failed.py` 再次重试。

## 数据状态

DB 中每行 `status` 字段：

| 值 | 含义 |
|----|------|
| 0 | 成功（已分类） |
| 1 | 未知问题（agent 返回"未知问题"） |
| 2 | 推理失败（重试耗尽） |
| 3 | 描述过长（超过 500 字，跳过分类） |

## 许可

MIT

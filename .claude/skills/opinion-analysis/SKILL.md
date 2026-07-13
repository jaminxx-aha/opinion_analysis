---
name: opinion-analysis
description: 分析Excel舆情数据，自动分类性能问题并生成交互式可视化HTML报告。当用户提供Excel舆情数据文件时触发。
dependencies: python>=3.8, pandas>=1.5.0, openpyxl, python-dotenv, json_repair, opencode-ai
---

# 舆情分析技能

分析 Excel 舆情数据，识别应用名和问题描述列，通过 agent 加载「抖音舆情分析」子 skill 对每条问题做分类，生成可视化 HTML 报告。推理后端由 `agent_client` 基类与工厂统一抽象，默认实现为 opencode（`opencode_agent_client`，作为 `agent_client` 子类；基类与工厂保留以便后续拓展其它后端）。

## 前置条件

- 安装依赖：`pip install -r <skill_path>/scripts/requirements.txt`

## 执行步骤

### 步骤1：获取 excel 文件信息

```bash
python <skill_path>/scripts/excel_info.py <Excel文件路径>
```

### 步骤2：获取应用列表

```bash
python <skill_path>/scripts/app_list.py
```

### 步骤3：获取字段信息

根据 excel 文件信息和应用列表，获取以下信息（索引下标从 0 开始）

| 字段 | 说明 |
|------|------|
| app_name | 应用名，从 excel 文件信息中获取，需要映射为应用列表中的值 |
| problem_index | 问题描述列号 |
| version_index | 版本号列号（无则不传） |

**注意**：若无法获取应用名和问题描述列号，或应用名无法映射到应用列表中，终止步骤！

### 步骤4：分类并生成报告

```bash
python <skill_path>/scripts/classify_data.py \
  --app-name <app_name> \
  --problem-index <problem_index> \
  --excel-path <Excel文件路径> \
  --output-dir <output_dir> \
  [--version-index <version_index>]
```

- 只对功能域做一次分类推理；业务域分类由「功能域→业务页面标签」映射自动派生，无需二次推理。
- `--output-dir` 输出路径，用户未指定则用 `./output/<excel_name>`。
- `--version-index` 可选，`-1` 或不传表示无版本号列。
- 同一 `--output-dir` 下单个 `report.db`，单张 `report` 表，每行同时存功能域 `full_path`(- 分隔) 与业务域 `business_classification`。

**执行时间过长时**：分类脚本持续运行直到所有数据处理完成。若长时间无进展输出，请检查日志 `<output_dir>/log/report.log` 与 `<output_dir>/log/response_*_agent*.log`。

### 步骤5（可选）：单独重试失败数据

若只想对某个已分析目录里推理失败(status=2)的数据重跑（不需 Excel、不重试未知问题）：

```bash
python <skill_path>/scripts/retry_failed.py <output_dir> [--app-name <app_name>]
```

`--app-name` 不传则从 DB 的 `app` 列推断；完成后重新生成报告。

## 资源文件

- [references/apps/](references/apps/) — 各应用知识库：功能域分类树 `classification_function.md`（校验 agent 返回的分类路径）+ `classification_function_to_business.json`（功能域路径→业务页面标签映射，派生 `business_classification`）。
- [assets/report_template.html](assets/report_template.html) — HTML 报告模板（功能域/业务域同报告视图切换；功能域按 `full_path` 最大深度动态渲染级联筛选级数）
- 入口与脚本（`<skill_path>/scripts/`）：
  - [classify_data.py](scripts/classify_data.py) — 分类入口，4 阶段编排（参数配置 → 数据准备 → 执行 → 报告）
  - [excel_info.py](scripts/excel_info.py) — Excel 前几行预览
  - [app_list.py](scripts/app_list.py) — 当前支持的应用列表
  - [generate_report.py](scripts/generate_report.py) — DB → HTML 报告（目录或 DB 输入，功能域/业务域同报告视图切换）
  - [retry_failed.py](scripts/retry_failed.py) — 重试 DB 中推理失败(status=2)的数据（给目录即可）
  - 内部模块：`args.py`（参数/配置/参考库）、`db_utils.py`（DB/入库）、`processor.py`（数据准备+执行分派）、`runtime.py`（运行时状态+响应解析）、`classify_agent.py`（agent 单条分类+重试）、`agent_client.py`（后端基类与工厂，按 `cfg.backend` 分派）、`opencode_agent_client.py`（默认 agent 后端实现，作为 `agent_client` 子类）


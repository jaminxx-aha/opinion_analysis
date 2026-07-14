---
name: opinion-analysis
description: 分析Excel舆情数据，自动分类性能问题并生成交互式可视化HTML报告。当用户提供Excel舆情数据文件时触发。
dependencies: python>=3.8, pandas>=1.5.0, openpyxl, python-dotenv, json_repair, opencode-ai
---

# 舆情分析技能

分析 Excel 舆情数据，识别应用名和问题描述列，通过 agent 加载「抖音舆情分析」子 skill 对每条问题做分类，生成可视化 HTML 报告。

## 重要规则（必须遵守）

- **告知用户**：必须告知用户步骤4中的分类任务的启动命令；
- **禁止直接启动步骤4中的分类任务**：步骤4中的分类任务耗时很长，必须经过用户确认才能后台启动。

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

### 步骤4：询问是否启动分类任务

明确告知用户分类任务的启动命令（确认好脚本的参数），包括前台执行命令和后台执行命令，然后询问用户是否允许后台启动任务。

**注意**：此步骤**只负责提供启动** `classify_data.py` 任务的命令或后台启动该任务，不会等待任务结束（因为数据量大时可能需要数分钟到数十分钟）。智能体启动任务后即可继续，用户会通过其他途径查看进度。

**前台启动命令**（前台启动命令**必须**由用户来执行）：

```bash
python <skill_path>/scripts/classify_data.py \
  --app-name <app_name> \
  --problem-index <problem_index> \
  --excel-path <Excel文件路径> \
  --output-dir <output_dir> \
  [--version-index <version_index>]
```

**后台启动命令**（**必须**经过用户确认后执行，后台运行避免智能体超时）：

> **执行前请先告知用户以下信息并征询确认：**
> - 将以后台方式启动分类任务
> - 任务运行期间请勿关闭终端
> - 可通过日志和 DB 查看进度

```powershell
# Windows (PowerShell) 后台启动
Start-Process -FilePath "python" -ArgumentList "<skill_path>\scripts\classify_data.py --app-name <app_name> --problem-index <problem_index> --excel-path <Excel文件路径> --output-dir <output_dir> -WindowStyle Hidden
```

```bash
# Linux / Mac 后台启动
nohup python <skill_path>/scripts/classify_data.py --app-name <app_name> --problem-index <problem_index> --excel-path <Excel文件路径> --output-dir <output_dir> /dev/null 2>&1 &
```

**命令参数说明**：
| 参数 | 必填 | 说明 |
|------|------|------|
| `--app-name` | 是 | 应用名，需与步骤2应用列表中的名称一致 |
| `--problem-index` | 是 | 问题描述列号（索引从0开始） |
| `--excel-path` | 是 | Excel 文件路径 |
| `--output-dir` | 否 | 输出路径，默认为 `./output/<excel_name>` |
| `--version-index` | 否 | 版本号列号，`-1` 或不传表示无版本号列 |

**查看任务进度**：

| 方式 | 路径 | 说明 |
|------|------|------|
| 日志文件 | `<output_dir>/log/report.log` | 记录总体进度（条数、成功率） |
| 响应日志 | `<output_dir>/log/response_*_agent*.log` | 每条数据的 agent 响应详情 |
| DB 记录数 | `<output_dir>/report.db` | 查询对应表记录数，可判断已完成条数 |

**判断任务完成**：日志中出现`分类完成` 相关字样，或 `report.db` 中记录数等于 Excel 总行数。

### 步骤5（可选）：单独重试失败数据

若只想对某个已分析目录里推理失败(status=2)的数据重跑（不需 Excel、不重试未知问题）：

```bash
python <skill_path>/scripts/retry_failed.py <output_dir> [--app-name <app_name>]
```

`--app-name` 不传则从 DB 的 `app` 列推断；完成后重新生成报告。

## 资源文件

- [references/apps/](references/apps/) — 各应用知识库：功能域分类树 `classification_function.md`（校验 agent 返回的分类路径）+ `classification_function_to_business.json`（功能域路径→业务页面标签映射）。
- [assets/report_template.html](assets/report_template.html) — HTML 报告模板（功能域/业务域同报告视图切换）
- 入口与脚本（`<skill_path>/scripts/`）：
  - [classify_data.py](scripts/classify_data.py) — 分类入口，4 阶段编排（参数配置 → 数据准备 → 执行 → 报告）
  - [excel_info.py](scripts/excel_info.py) — Excel 前几行预览
  - [app_list.py](scripts/app_list.py) — 当前支持的应用列表
  - [generate_report.py](scripts/generate_report.py) — DB → HTML 报告（目录或 DB 输入，功能域/业务域同报告视图切换）
  - [retry_failed.py](scripts/retry_failed.py) — 重试 DB 中推理失败(status=2)的数据（给目录即可）
  - 内部模块：`args.py`（参数/配置/参考库）、`db_utils.py`（DB/入库）、`processor.py`（数据准备+执行分派）、`runtime.py`（运行时状态+响应解析）、`classify_agent.py`（agent 单条分类+重试）、`agent_client.py`（后端基类与工厂，按 `cfg.backend` 分派）、`opencode_agent_client.py`（默认 agent 后端实现，作为 `agent_client` 子类）


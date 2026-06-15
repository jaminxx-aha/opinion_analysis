---
name: opinion-analysis
description: 分析Excel舆情数据，自动分类性能问题并生成交互式可视化HTML报告。当用户提供Excel舆情数据文件时触发。
dependencies: python>=3.8, pandas>=1.5.0, openpyxl, python-dotenv
---

# 舆情分析技能

分析Excel舆情数据，识别应用名和问题描述列，调用LLM API分类性能问题，生成可视化HTML报告。

## 执行步骤

### 步骤1：获取excel文件信息

```bash
python <skill_path>/scripts/excel_info.py <Excel文件路径>
```

### 步骤2：获取应用列表

```bash
python <skill_path>/scripts/app_list
```

### 步骤3：获取字段信息

根据excel文件信息，和应用列表，获取以下信息（索引下标从0开始）

| 字段 | 说明 |
|------|------|
| app_col_index | 应用名列号 |
| app_name | 应用名，从excel文件信息中获取应用名，需要映射为应用列表中的值 |
| problem_index | 问题描述列号 |
| problem_col_name | 问题描述列名 |
| version_index | 版本号列号 |
| version_col_name | 版本号名称 |

**注意**：若无法获取应用名和问题描述列号，或应用名无法映射到应用列表中，终止步骤！

### 步骤4：分类并生成报告

```bash
python <skill_path>/scripts/classify_data.py \
  --app-name <app_name> \
  --problem-index <problem_index> \
  --excel-path <Excel文件路径> \
  --output-dir <output_dir> \
  [--version-index <version_index>] \
  [--retry <retry_mode>]
```

`--output-dir` 输出路径，如果用户指定了输出路径，output_dir=用户指定路径，否则out_dir=`./output/<excel_name>`。

`--version-index` 可选，0 或不传表示无版本号列。分类完成后自动生成HTML报告。

`--retry` 可选，当用户需要分析其他问题或推理失败的问题时添加。retry_mode=`failed`继续分析推理失败的数据，retry_mode=`unknown`继续分析未知数据

**执行时间过长时**：分类脚本会持续运行直到所有数据处理完成。若长时间无进展输出，请检查日志文件 `<output_dir>/report.log` 分析原因（如API超时、连接失败等）。

## 资源文件

- [references/apps/](references/apps/) — 各应用知识库
- [assets/report_template.html](assets/report_template.html) — HTML报告模板
- [scripts/classify_data.py](scripts/classify_data.py) — 分类脚本（支持续跑和 `--retry` 重试）
- [scripts/excel_info.py](scripts/excel_info.py) — 获取excel表格的前几行数据
- [scripts/app_list.py](scripts/app_list.py) — 获取当前支持的应用列表

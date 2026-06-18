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
| domain | 分类域：`function`=功能域/性能问题（默认），`business`=业务域。由用户选择本次分析哪个域 |

**注意**：若无法获取应用名和问题描述列号，或应用名无法映射到应用列表中，终止步骤！

### 步骤4：分类并生成报告

```bash
python <skill_path>/scripts/classify_data.py \
  --domain <function|business> \
  --app-name <app_name> \
  --problem-index <problem_index> \
  --excel-path <Excel文件路径> \
  --output-dir <output_dir> \
  [--version-index <version_index>] \
  [--retry <retry_mode>]
```

`--domain` **必填**：`function`=功能域/性能问题，`business`=业务域。两个域各自独立运行、互不影响；同一 `--output-dir` 下分别生成 `function_report.db` 与 `business_report.db`。

`--output-dir` 输出路径，如果用户指定了输出路径，output_dir=用户指定路径，否则out_dir=`./output/<excel_name>`。

`--version-index` 可选，0 或不传表示无版本号列。分类完成后自动生成HTML报告。报告读取该目录下**已存在的所有域 DB**，合并成一份双标签页报告（已运行哪个域就显示哪个标签页；两个域都跑过则可在「功能域/业务域」标签间切换）。

`--retry` 可选，当用户需要分析其他问题或推理失败的问题时添加，只作用于当前 `--domain` 对应的 DB。retry_mode=`failed`继续分析推理失败的数据，retry_mode=`unknown`继续分析未知数据

**执行时间过长时**：分类脚本会持续运行直到所有数据处理完成。若长时间无进展输出，请检查日志文件 `<output_dir>/report.log` 分析原因（如API超时、连接失败等）。

## 资源文件

- [references/apps/](references/apps/) — 各应用知识库（每应用含功能域 `classification_function.md`/`examples_function.md`/`error_examples_function.md` 与业务域 `classification_business.md`/`examples_business.md`/`error_examples_business.md`，共享 `info.md`）
- [assets/report_template.html](assets/report_template.html) — HTML报告模板（支持功能域/业务域双标签页切换）
- [scripts/classify_data.py](scripts/classify_data.py) — 分类脚本（支持续跑和 `--retry` 重试）
- [scripts/excel_info.py](scripts/excel_info.py) — 获取excel表格的前几行数据
- [scripts/app_list.py](scripts/app_list.py) — 获取当前支持的应用列表

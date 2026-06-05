---
name: opinion-analysis
description: 分析Excel舆情数据，自动分类性能问题并生成交互式可视化HTML报告。当用户提供Excel舆情数据文件时触发。
dependencies: python>=3.8, pandas>=1.5.0, openpyxl, python-dotenv
---

# 舆情分析技能

分析Excel舆情数据，识别应用名和问题描述列，调用LLM API分类性能问题，生成可视化HTML报告。

## 执行步骤

### 步骤1：识别列信息

```bash
python <skill_path>/scripts/analyze_excel.py <Excel文件路径> --info [--app-column <列号>]
```

根据输出判断：

- **应用名**：内容为已知应用名（抖音或别名），记 `app_name`
- **问题描述列**：内容为问题描述文本，记 `problem_index` 和 `row_count`
- **版本号列**（可选）：内容为版本号（如 "3.5.0"、"v1.2.3"），记 `version_index`。若数据中无版本号相关字段则不传此参数
- 验证 `references/apps/<app_name>/` 存在；不存在的应用所有数据归为"未知问题"，需告知用户

### 步骤2：分类并生成报告

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

`--retry` 可选，当用户需要分析未知问题或推理失败的问题时添加。retry_mode=`failed`继续分析推理失败的数据，retry_mode=`unknown`继续分析未知数据

**执行时间过长时**：分类脚本会持续运行直到所有数据处理完成。若长时间无进展输出，请检查日志文件 `<output_dir>/report.log` 分析原因（如API超时、连接失败等）。

## 资源文件

- [references/apps/](references/apps/) — 各应用知识库
- [assets/report_template.html](assets/report_template.html) — HTML报告模板
- [scripts/classify_data.py](scripts/classify_data.py) — 分类脚本（支持续跑和 `--retry` 重试）
- [scripts/analyze_excel.py](scripts/analyze_excel.py) — Excel分析 + 报告生成
- [scripts/config.py](scripts/config.py) — 配置与公共函数

## 支持的应用

抖音
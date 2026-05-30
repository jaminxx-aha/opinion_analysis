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

- **应用名列**：内容为已知应用名（抖音/微信/淘宝/快手/小红书或别名），记 `app_name` 和 `app_index`
- **问题描述列**：内容为问题描述文本，记 `problem_index` 和 `row_count`
- 验证 `references/apps/<app_name>/` 存在；不存在的应用所有数据归为"未知问题"，需告知用户

### 步骤2：分类并生成报告

```bash
python <skill_path>/scripts/classify_data.py \
  --app-name <app_name> --app-index <app_index> \
  --problem-index <problem_index> \
  --excel-path <Excel文件路径> --output-dir <output_dir>
```

分类完成后自动生成HTML报告。输出目录默认 `./output/<excel_name>`，也可用户指定。

**执行时间过长时**：分类脚本会持续运行直到所有数据处理完成。若长时间无进展输出，请检查日志文件 `<output_dir>/report.log` 分析原因（如API超时、连接失败等）。

### 步骤3：重试失败或遗漏的数据

多并发场景下脚本中断会导致数据库行缺失，或因超时、解析错误等原因产生推理失败（status=2）和未知问题（status=1）的数据。使用 `--retry` 参数重新推理这些数据：

```bash
python <skill_path>/scripts/classify_data.py \
  --app-name <app_name> --app-index <app_index> \
  --problem-index <problem_index> \
  --excel-path <Excel文件路径> --output-dir <output_dir> \
  --retry <模式>
```

| 模式 | 重试范围 |
|------|----------|
| `failed` | 缺失行（数据库id不连续） + 推理失败（status=2） |
| `unknown` | 缺失行 + 未知问题（status=1） — 适用于换模型或更新知识库后重新分类 |
| `all` | 缺失行 + 未知问题 + 推理失败（全部非成功数据） |

不带 `--retry` 时为续跑模式，从数据库最大id之后继续处理。

## 资源文件

- [references/apps/](references/apps/) — 各应用知识库
- [assets/report_template.html](assets/report_template.html) — HTML报告模板
- [scripts/classify_data.py](scripts/classify_data.py) — 分类脚本（支持续跑和 `--retry` 重试）
- [scripts/analyze_excel.py](scripts/analyze_excel.py) — Excel分析 + 报告生成
- [scripts/config.py](scripts/config.py) — 配置与公共函数

## 支持的应用

抖音、微信、淘宝、快手、小红书
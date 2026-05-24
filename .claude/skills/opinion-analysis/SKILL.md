---
name: opinion-analysis
description: 分析Excel舆情数据，自动分类性能问题并生成交互式可视化HTML报告。当用户提供Excel舆情数据文件时触发。
dependencies: python>=3.8, pandas>=1.5.0, openpyxl
---

# 舆情分析技能

分析Excel表格中的舆情数据，自动识别应用名和问题描述列，通过子agent批量分类性能问题，最终生成交互式可视化HTML报告。

## 执行步骤

严格按照以下步骤顺序执行：

### 步骤1：确定路径和输出目录

- 确定技能路径：记 `skill_path = 技能目录绝对路径`
- 确定输出路径：若用户提供则 `output_dir = 用户路径/excel_name`，否则 `output_dir = ./output/excel_name`
- 将原始Excel文件复制到 `output_dir`

### 步骤2：获取应用名、问题描述列和行数

运行脚本获取Excel信息：

```bash
python <skill_path>/scripts/analyze_excel.py <Excel文件路径> --info
```

根据返回的列名和样本数据判断：

**应用名列识别依据：**
- 列内容包含已知应用名（"抖音"、"微信"、"淘宝"、"快手"、"小红书"或其别名如"wechat"、"douyin"等）
- 列内容较短，通常只有应用名称
- 列名可能包含"应用"、"app"、"平台"、"软件"等关键词
- 获取后需转化为 [references/apps/](references/apps/) 下对应的应用名，如"wechat"→"微信"

记 `app_name = "微信"`

**问题描述列识别依据：**
- 列内容包含问题描述文本（如"抖音刷视频卡顿"、"微信发不出消息"）
- 列内容较长，包含具体问题描述
- 列名可能包含"问题"、"描述"、"反馈"、"投诉"、"内容"等关键词

记 `problem_index = 1`（列索引），记 `row_count = 行数`

**无法识别时返回错误：**
- 识别不出应用名：返回"Excel格式错误：无法识别应用名"
- 找不到问题描述列：返回"Excel格式错误：无法识别问题描述列"

### 步骤3：生成分类数据

数据由子agent生成。若数据量超过100条，按 `row_count` 平均分成最多20个子agent并行执行，每个子agent处理 `beg_index` 到 `end_index` 茏的数据。

父agent只关注所有子agent是否完成，不需要知道执行结果。子agent完成后再进入步骤4。

**当前agent禁止读 classify.md**，子agent提示词如下：

```
### 参数
- app_name: <app_name>
- problem_index: <problem_index>
- beg_index: <beg_index>
- end_index: <end_index>
- excel_path: <excel文件路径>
- output_dir: <output_dir>

### 步骤
1. 按照文件内容 <skill_path>/references/classify.md 执行，参数如上所示
```

### 步骤4：生成可视化文档

```bash
python <skill_path>/scripts/analyze_excel.py <report_db> --output-dir <output_dir>
```

## 资源文件

- [references/classify.md](references/classify.md) — 子agent分类任务指引（包含读取数据、推理分类、保存结果三步骤）
- [references/apps/](references/apps/) — 各应用知识库，每个应用包含 `info.md`（应用描述）、`classification.md`（分类树）、`examples.md`（分类推理示例）
- [scripts/](scripts/) — 执行脚本目录
  - `analyze_excel.py` — 主脚本，获取Excel信息 + 生成HTML报告
  - `get_rows.py` — 读取Excel指定行数据
  - `save_results.py` — 保存分类结果到SQLite数据库
  - `generate_report.py` — 生成交互式HTML可视化报告
  - `config.py` — 应用名配置和别名映射
  - `read_excel.py` — 通用Excel读取工具

## 支持的应用

抖音、微信、淘宝、快手、小红书
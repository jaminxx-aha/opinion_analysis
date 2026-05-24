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
- 初始化输出目录并复制Excel文件：
  ```bash
  python <skill_path>/scripts/analyze_excel.py <Excel文件路径> --init-output <output_dir>
  ```

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

**验证应用名是否支持：**

识别出 `app_name` 后，必须验证 `references/apps/<app_name>/` 目录是否存在。若不存在，说明该应用不在支持列表（抖音、微信、淘宝、快手、小红书）中，所有数据将被归为"未知问题"，需要告知用户。

**无法识别时返回错误：**
- 识别不出应用名：返回"Excel格式错误：无法识别应用名"
- 找不到问题描述列：返回"Excel格式错误：无法识别问题描述列"

### 步骤3：生成分类数据

数据由子agent生成。若数据量超过100条，按 `row_count` 平均分成最多20个子agent并行执行，每个子agent处理 `beg_index` 到 `end_index` 茏的数据。

父agent只关注所有子agent是否完成，不需要知道执行结果。子agent完成后再进入步骤4。

**当前agent禁止读 classify.md**，子agent提示词如下：

```
### 参数
- skill_path: <skill_path实际值>
- app_name: <app_name>
- problem_index: <problem_index>
- beg_index: <beg_index>
- end_index: <end_index>
- excel_path: <excel文件路径>
- output_dir: <output_dir>

### 步骤
按照 <skill_path>/references/classify.md 执行，注意：
1. classify.md 中所有 <skill_path> 占位符的值均为上方参数中的 skill_path
2. classify.md 中所有 <app_name> 占位符的值均为上方参数中的 app_name
3. 步骤3保存结果时，将JSON写入 <output_dir>/batch_<beg_index>_<end_index>.json 文件，再调用脚本处理该文件
```

### 步骤4：验证分类完整性

子agent全部完成后，检查数据库行数是否与原始数据行数一致：

```bash
python <skill_path>/scripts/analyze_excel.py <output_dir>/report.db --verify <row_count>
```

若行数不一致，提示用户有数据丢失，但继续生成报告。

### 步骤5：生成可视化文档

```bash
python <skill_path>/scripts/analyze_excel.py <output_dir>/report.db --output-dir <output_dir>
```

## 资源文件

- [references/classify.md](references/classify.md) — 子agent分类任务指引（包含读取数据、推理分类、保存结果三步骤）
- [references/apps/](references/apps/) — 各应用知识库，每个应用包含 `info.md`（应用描述）、`classification.md`（分类树）、`examples.md`（分类推理示例）
- [assets/report_template.html](assets/report_template.html) — 可视化HTML报告模板
- [scripts/](scripts/) — 执行脚本目录
  - `analyze_excel.py` — 主脚本，初始化输出目录、获取Excel信息、验证完整性、生成HTML报告
  - `get_rows.py` — 读取Excel指定行数据
  - `save_results.py` — 保存分类结果到SQLite数据库
  - `generate_report.py` — 基于模板生成交互式HTML可视化报告
  - `config.py` — 应用名配置、别名映射、公共函数
  - `read_excel.py` — 通用Excel读取工具

## 支持的应用

抖音、微信、淘宝、快手、小红书（其他应用的舆情数据将全部归为"未知问题"）
---
name: opinion-analysis
description: 分析Excel舆情数据，自动分类性能问题并生成交互式可视化HTML报告。当用户提供Excel舆情数据文件时触发。
dependencies: python>=3.8, pandas>=1.5.0, openpyxl, openai, anthropic, python-dotenv
---

# 舆情分析技能

分析Excel表格中的舆情数据，自动识别应用名和问题描述列，通过LLM API批量分类性能问题，最终生成交互式可视化HTML报告。

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

记 `app_name = "微信"`，记 `app_index = 2`（应用名列号）

**问题描述列识别依据：**
- 列内容包含问题描述文本（如"抖音刷视频卡顿"、"微信发不出消息"）
- 列内容较长，包含具体问题描述
- 列名可能包含"问题"、"描述"、"反馈"、"投诉"、"内容"等关键词

记 `problem_index = 5`（列索引），记 `row_count = 行数`

**验证应用名是否支持：**

识别出 `app_name` 后，必须验证 `references/apps/<app_name>/` 目录是否存在。若不存在，说明该应用不在支持列表（抖音、微信、淘宝、快手、小红书）中，所有数据将被归为"未知问题"，需要告知用户。

**无法识别时返回错误：**
- 识别不出应用名：返回"Excel格式错误：无法识别应用名"
- 找不到问题描述列：返回"Excel格式错误：无法识别问题描述列"

### 步骤3：调用分类脚本

运行分类脚本，每条数据单独调用LLM并直接写入数据库：

```bash
python <skill_path>/scripts/classify_data.py \
  --app-name <app_name> \
  --app-index <app_index> \
  --problem-index <problem_index> \
  --excel-path <Excel文件路径> \
  --output-dir <output_dir>
```

LLM API配置从项目根目录的 `.env` 文件自动加载，也可通过命令行参数覆盖：
- `--provider` / `LLM_PROVIDER` — API类型：`openai` 或 `anthropic`（默认openai）
- `--model` / `LLM_MODEL` — 模型名称
- `--api-key` / `LLM_API_KEY` — API密钥
- `--base-url` / `LLM_BASE_URL` — API基础URL（仅openai类型）

可选调优参数：`--max-concurrent`（并发数，默认5）、`--max-tokens`（默认8192）、`--max-retries`（默认3）

脚本完成后进入步骤4。

### 步骤4：验证分类完整性

检查数据库行数是否与原始数据行数一致：

```bash
python <skill_path>/scripts/analyze_excel.py <output_dir>/report.db --verify <row_count>
```

若行数不一致，提示用户有数据丢失，但继续生成报告。

### 步骤5：生成可视化文档

```bash
python <skill_path>/scripts/analyze_excel.py <output_dir>/report.db --output-dir <output_dir>
```

## 资源文件

- [references/apps/](references/apps/) — 各应用知识库，每个应用包含 `info.md`（应用描述）、`classification.md`（分类树）、`examples.md`（分类推理示例）
- [assets/report_template.html](assets/report_template.html) — 可视化HTML报告模板
- [scripts/](scripts/) — 执行脚本目录
  - `analyze_excel.py` — 主脚本，初始化输出目录、获取Excel信息、验证完整性、生成HTML报告
  - `classify_data.py` — LLM分类脚本，每条数据单独调用LLM并直接写入数据库
  - `save_results.py` — 保存分类结果到SQLite数据库
  - `generate_report.py` — 基于模板生成交互式HTML可视化报告
  - `config.py` — 应用名配置、别名映射、公共函数
  - `read_excel.py` — 通用Excel读取工具

## 支持的应用

抖音、微信、淘宝、快手、小红书（其他应用的舆情数据将全部归为"未知问题"）
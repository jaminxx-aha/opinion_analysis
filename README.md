# 舆情分析工具

基于 Claude Code 的智能舆情数据分析工具，可对用户反馈进行自动分类并生成可视化报告。

## 功能特性

- **智能分类**：通过 Claude 子 Agent 自动推断应用名、问题场景，进行层级化分类
- **可视化报告**：生成交互式 HTML 报告，包含：
  - 级联下拉筛选（应用→模块→页面→问题类型）
  - 动态饼图随筛选层级变化
  - 分页表格展示分类详情
  - 点击问题描述查看原始数据
- **批量处理**：支持大规模 Excel 数据批量分析

## 快速开始

### 1. 准备数据

Excel 文件需包含 `问题描述` 列（必需），可选包含 `应用名` 列：

| 问题描述 | 应用名 |
|----------|--------|
| 刷抖音视频卡顿 | 抖音 |
| 微信发消息失败 | 微信 |

### 2. 运行分析

使用 Claude Code 的 `/opinion_analysis` 技能：

```
/opinion_analysis 分析 test/舆情数据示例.xlsx
```

或手动执行脚本：

```bash
# 准备数据
python3 .claude/skills/opinion_analysis/scripts/analyze_excel.py test/舆情数据示例.xlsx --prepare-only

# 分类后生成报告
python3 .claude/skills/opinion_analysis/scripts/analyze_excel.py 舆情数据示例/舆情数据示例_prepared.json
```

## 项目结构

```
.claude/skills/opinion_analysis/
├── SKILL.md              # 技能说明文档
├── references/apps/      # 应用背景知识库
│   ├── 抖音/
│   ├── 微信/
│   ├── 淘宝/
│   ├── 快手/
│   └── 小红书/
├── assets/               # 报告模板
└── scripts/
    ├── classify_data.py  # LLM分类脚本（原生urllib/SDK双模式）
    ├── analyze_excel.py  # Excel分析+报告生成
    ├── generate_report.py # 报告生成脚本
    └── config.py         # 配置与公共函数

test/                     # 测试数据
```

## 分类输出

分类结果为五级层级结构：

```
应用 > 模块 > 页面 > 问题类型 > 具体问题
```

示例：
```
抖音 > 短视频 > 视频播放页 > 性能问题 > 播放卡顿
微信 > 聊天 > 聊天对话页 > 功能问题 > 消息发送失败
```

## 支持的应用

当前支持以下应用的详细分类：

- 抖音
- 微信
- 淘宝
- 快手
- 小红书

其他应用会标记为"应用无描述"，但仍会保留应用名称。

## 依赖

- Python 3.8+
- pandas
- openpyxl
- python-dotenv
- 可选（SDK方式）：openai, anthropic

## 许可

MIT
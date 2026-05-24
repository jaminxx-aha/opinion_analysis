# 舆情数据分类任务指引

## ⚠️ 最高优先级约束（必须遵守）

**禁止创建任何新文件，禁止编写任何脚本或代码来处理分类。分类必须通过你的直接推理完成。**

原因：分类需要理解每个问题描述的语义、上下文和应用特定场景，关键词匹配脚本无法做到这一点。你必须逐条阅读问题描述，结合应用知识库进行推理。

必须严格按照以下步骤顺序执行，禁止跳过、合并或绕过任何步骤。

注意：每轮最多读取100条数据，如果超过100条，则轮询步骤1到步骤3，row_count=<beg_index> - <end_index>，**执行前确定技能的路径**，记`skill_path = 技能路径`，执行脚本不要切换工作目录

## 步骤1：读取数据

调用脚本读取当前批次数据：

```bash
python <skill_path>/scripts/get_rows.py <Excel文件路径> --problem-column <problem_index> --app-name <app_name> --start <beg_index> --end <end_index>
```

返回JSON格式：
```json
{
  "excel_path": "...",
  "total_rows": 100,
  "start": 1,
  "end": 100,
  "app": "<app_name>",
  "problem_column": 5,
  "data": [
    {"num": 1, "desc": "问题描述1"},
    {"num": 2, "desc": "问题描述2"},
    {"num": 3, "desc": "问题描述3"}
  ]
}
```

提取步骤1返回的 `data` 数组，仅将 `data` 数组传入步骤2的推理提示词，不要传入完整JSON（元信息对分类无用）。

## 步骤2：对问题进行推导
推导返回格式如下：
```json
{
  "excel_path": "...",
  "total_rows": 100,
  "start": 1,
  "end": 100,
  "app": "<app_name>",
  "problem_column": 5,
  "output_dir": "...",
  "data": [
    {"num": 1, "classification": ["一级分类","二级分类","三级分类"], "reasoning": "关键词→一级分类，场景→二级分类→三级分类"},
    {"num": 2, "classification": ["一级分类","二级分类"], "reasoning": "关键词→一级分类，场景→二级分类，未指明具体页面无法推导三级分类"},
    {"num": 3, "classification": ["一级分类"], "reasoning": "关键词→一级分类，无具体场景无法推导二级分类"},
    {"num": 4, "classification": ["未知问题"], "reasoning": "不属于8类性能问题，无法归类"}
  ]
}
```

推理提示词如下：

这是<app_name>的舆情问题，问题描述如下：

---DATA---
<步骤1返回的data数组JSON>
---DATA_END---

请根据以下参考资料推导分类：
- 应用描述：<skill_path>/references/apps/<app_name>/info.md
- 问题分类树：<skill_path>/references/apps/<app_name>/classification.md
- 分类推理示例：<skill_path>/references/apps/<app_name>/examples.md

分类格式：一级分类.二级分类.三级分类

逐层推导规则：
1. 先从用户描述中提取关键词，推断一级分类
2. 根据一级分类下的二级分类，结合场景关键词推断二级分类
3. 根据二级分类下的三级分类，结合页面/功能推断三级分类

如果无法推导出一级分类，则返回"classification": ["未知问题"]，如果无法推导出二级分类"classification": ["一级分类值"]，如果无法推出三级分类，则返回"classification": ["一级分类值", "二级分类值"]，如果全部推理出，则返回"classification": ["一级分类值", "二级分类值", "三级分类值"]

推理说明格式要求：每个分类层级必须说明推导依据，格式为"关键词→一级分类原因，场景→二级分类原因→三级分类原因"。不允许只写结论不写推导过程。

## 步骤3：保存分类结果

分类完成后，将完整结果JSON写入临时文件，然后调用脚本处理：

```bash
# 先将JSON写入临时文件
cat > <output_dir>/batch_<start>_<end>.json << 'JSONEOF'
<完整JSON字符串>
JSONEOF

# 再调用脚本读取文件
python <skill_path>/scripts/save_results.py <output_dir>/batch_<start>_<end>.json --output-dir <output_dir>
```

注意：不要将JSON作为命令行参数直接传入（有长度限制），必须通过文件传递。
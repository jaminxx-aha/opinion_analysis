# 舆情数据分类任务指引

本文件定义子Agent分类舆情数据的完整流程。必须严格按照以下步骤顺序执行，禁止跳过、合并或绕过任何步骤，禁止编写新脚本进行分类。

---
注意：每轮最多读取100条数据，如果超过100条，则轮询步骤1到步骤5，row_count=<beg_index> - <end_index>，**执行前确定技能的路径**，记`skill_path = 技能路径`，执行脚本不要切换工作目录
## 步骤1：读取数据

调用脚本读取当前批次数据：

```
python <skill_path>/scripts/get_rows.py <Excel文件路径> --problem-column <problem_index> --app-name <app_name> --start <beg_index> --end <end_index>
```

返回JSON格式：
```json
{
  "excel_path": "...",
  "total_rows": 10000,
  "start": 1,
  "end": 100,
  "app": "抖音",
  "problem_column": 5,
  "data": [
    {"num": 1, "desc": "问题描述"},
    {"num": 2, "desc": "问题描述"}
  ]
}
```

## 步骤2：读取应用描述

读取 <skill_path>/apps/<app_name>/ 目录下的3个文件获取分类依据：

1. `<skill_path>/apps/<app_name>/info.md` — 应用描述（模块、页面结构）
2. `<skill_path>/apps/<app_name>/classification.md` — 完整分类树（8个一级分类下的二级、三级分类）
3. `<skill_path>/apps/<app_name>/examples.md` — 分类推理示例（逐层推导参考）

## 步骤3：逐层推导分类

分类格式：`{一级分类}.{二级分类}.{三级分类}`

逐层推导：
1. 先从用户描述中提取关键词，推断一级分类
2. 根据一级分类下的二级分类，结合场景关键词推断二级分类
3. 根据二级分类下的三级分类，结合页面/功能推断三级分类

⚠️ 当推断的一级分类下找不到匹配的三级节点时，必须跨一级分类寻找语义相近的节点。例如"搜索卡顿"在卡顿分支下无对应节点，应映射到"响应慢/延迟.交互响应延迟.搜索响应延迟"。禁止将可归类数据标记为unrecognized。

8个一级分类：卡顿、响应慢/延迟、闪退/崩溃、启动异常、发热、内存异常、渲染异常、网络异常

⚠️ 禁止编写Python脚本进行自动分类，必须逐条人工推导。

## 步骤4：输出分类结果

组装JSON格式（保留步骤1返回的metadata字段，增加output_dir）：

```json
{
  "excel_path": "...",
  "total_rows": 10000,
  "start": 1,
  "end": 100,
  "app": "抖音",
  "problem_column": 5,
  "output_dir": "...",
  "data": [
    {"num": 1, "desc": ["卡顿","滑动卡顿","首页推荐视频流上下滑动卡顿"], "reasoning": "用户描述含'刷视频卡顿'，关键词'刷视频'对应滑动操作，'卡顿'对应一级分类卡顿，推断为首页推荐视频流上下滑动卡顿"},
    {"num": 2, "desc": ["unrecognized"], "reasoning": ""},
    {"num": 3, "desc": ["闪退/崩溃","使用过程闪退","视频播放过程闪退"], "reasoning": "用户描述含'看视频突然闪退'，'闪退'对应一级分类闪退/崩溃，'看视频时'对应使用过程闪退场景"}
  ]
}
```

⚠️ 禁止将JSON保存为本地文件，直接通过命令行参数传递给save_results.py。

## 步骤5：保存分类结果

分类完成后，调用脚本将结果和原始数据写入数据库，直接将JSON字符串作为命令行参数传入：

```
python <skill_path>/scripts/save_results.py '<JSON字符串>' --output-dir <output_dir>
```

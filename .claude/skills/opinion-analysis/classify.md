# 舆情数据分类任务指引

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
  "app": "抖音",
  "problem_column": 5,
  "data": [
    {"num": 1, "desc": "抖音刷视频卡顿严重"},
    {"num": 2, "desc": "看视频突然闪退"},
    {"num": 3, "desc": "抖音很卡"},
    {"num": 4, "desc": "视频播放卡顿"},
    {"num": 5, "desc": "抖音充值失败"}
  ]
}
```

## 步骤2：对问题进行推导
推导返回格式如下：
```json
{
  "excel_path": "...",
  "total_rows": 100,
  "start": 1,
  "end": 100,
  "app": "抖音",
  "problem_column": 5,
  "output_dir": "...",
  "data": [
    {"num": 1, "classification": ["卡顿","滑动卡顿","首页推荐视频流上下滑动卡顿"], "reasoning": "\"卡顿\"→一级分类卡顿，\"刷视频\"→二级分类滑动卡顿→三级分类首页推荐视频流上下滑动卡顿"},
    {"num": 2, "classification": ["闪退/崩溃","使用过程闪退","视频播放过程闪退"], "reasoning": "描述不含应用名但app_name已知为抖音，\"闪退\"→一级分类闪退/崩溃，\"看视频\"→二级分类使用过程闪退→三级分类视频播放过程闪退"},
    {"num": 3, "classification": ["卡顿"], "reasoning": "\"很卡\"→一级分类卡顿，无具体场景信息无法推导二级分类"},
    {"num": 4, "classification": ["卡顿","视频播放卡顿"], "reasoning": "\"卡顿\"→一级分类卡顿，\"视频播放\"→二级分类视频播放卡顿，未指明具体页面无法推导三级分类"},
    {"num": 5, "classification": ["未知问题"], "reasoning": "\"充值失败\"不属于8类性能问题，无法归类"}
  ]
}
```

禁止编写脚本对问题模糊匹配，推导提示词如下三个反引号（```）分隔：
```
这是<app_name>的舆情问题'''<json数据>'''，描述在data[i].desc中，请根据应用描述`<skill_path>/apps/<app_name>/info.md`、问题分类树`<skill_path>/apps/<app_name>/classification.md`和`<skill_path>/apps/<app_name>/examples.md`分类推理示例，推导出该问题属于哪一个分类

分类格式：`{一级分类}.{二级分类}.{三级分类}`

逐层推导：
1. 先从用户描述中提取关键词，推断一级分类
2. 根据一级分类下的二级分类，结合场景关键词推断二级分类
3. 根据二级分类下的三级分类，结合页面/功能推断三级分类

如果无法推导出一级分类，则返回`"classification": ["未知问题"]`，如果无法推导出二级分类`"classification": [{一级分类}]`，如果无法推出三级分类，则返回`classification": [{一级分类}, {二级分类}]`，如果全部推理出，则返回`classification": [{一级分类}, {二级分类}, {三级分类}]`
```

## 步骤3：保存分类结果

分类完成后，调用脚本将结果和原始数据写入数据库，直接将JSON字符串作为命令行参数传入：

```
python <skill_path>/scripts/save_results.py '<JSON字符串>' --output-dir <output_dir>
```

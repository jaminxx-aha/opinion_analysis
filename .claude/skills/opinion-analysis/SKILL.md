---
name: opinion-analysis
description: 分析excel表格中的舆情数据，生成可视化界面。当用户提供excel舆情数据，需要进行舆情分析时触发。
---

# 舆情分析技能

## 执行步骤
请严格按照以下步骤执行任务：
1. **确定技能的路径**，记`skill_path = 技能路径`，执行脚本不要切换工作目录
2. **确定输出路径**：如果用户提供了输出路径，则`output_path = 用户提供路径`, 否则`output_path = ./output`，提取用户提供的excel表格的名称，记`output_dir = output_path/excel_name`，将原始Excel文件复制到`output_dir`
2. **获取应用名、问题描述index和行数**：见”获取应用名和问题描述index步骤”
3. **生成分类数据**：见“生成分类数据步骤”
4. **生成可视化文档**：
   ```bash
   python <skill_path>/scripts/analyze_excel.py <report_db> --output-dir <output_dir>
   ```

## 获取应用名和问题描述index步骤
需严格按照一下步骤执行
1. **调用脚本获取Excel信息**：
   ```bash
   python <skill_path>/scripts/analyze_excel.py <Excel文件路径> --info
   ```

2. **根据返回的列名和样本数据，判断应用名是什么**
   
   **应用名列识别依据：**
   - 列内容包含已知应用名（如"抖音"、"微信"、"淘宝"、"wechat"、"douyin"等）
   - 列内容较短，通常只有应用名称
   - 列名可能包含"应用"、"app"、"平台"、"软件"等关键词
   - 应用名获取后需转化为apps文件夹下对应的应用名，比如获取的是"wechat"，则应用名为"微信"
   
   记`app_name = "微信"`

3. **根据返回的列名和样本数据，判断问题描述idnex**

   **问题描述列识别依据：**
   - 列内容包含问题描述文本（如"抖音刷视频卡顿"、"微信发不出消息"）
   - 列内容较长，包含具体问题描述
   - 列内容包含问题关键词（如"卡顿"、"慢"、"失败"、"加载"、"打不开"等）
   - 列名可能包含"问题"、"描述"、"反馈"、"投诉"、"内容"等关键词

   如识别到问题描述index为1，记`problem_index = 1`

4. **根据返回的列名和样本数据，判断问题描述idnex**

   读取行数，记`row_count = 行数`

   如识别到问题描述index为1，记`problem_index = 1` 

4. **如果无法识别：**
   - 如果识别不出应用名，返回 **"Excel格式错误：无法识别应用名"**
   - 如果找不到包含问题描述index，返回 **"Excel格式错误：无法识别问题描述列"**

## 生成分类数据步骤
数据由子agent生成，如果数据量超过100，将根据<row_count>平均分成20个子agent执行，起始和结束行号如`beg_index = 1`, `end_index = 20`。
注意：注意父agent只需要知道所有子agent是否执行完成，不需要知道子agent是否执行成功，子agent全部执行完成后便执行下一步！
当前agent禁止读classify.md，子agent提示词三个反引号所示：
```
### 参数
- app_name: <app_name>
- problem_index: <problem_index>
- beg_index: <beg_index>
- end_index: <end_index>
- excel_path: <excel文件路径>
- output_dir: <output_dir>

### 步骤
1.按照文件内容<skill_path>/classify.md执行，参数如上所示
```


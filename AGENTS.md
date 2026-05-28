# AGENTS.md

## Project type

This is a **Claude Code skill** repository, not a standard application. The core deliverable is the `opinion-analysis` skill at `.claude/skills/opinion-analysis/`. There is no build system, no test suite runner, and no CI.

## Key paths

- Skill definition: `.claude/skills/opinion-analysis/SKILL.md`
- Scripts: `.claude/skills/opinion-analysis/scripts/` — `classify_data.py` (LLM分类, 含init+verify), `analyze_excel.py` (info+report), `generate_report.py`, `config.py`
- Per-app knowledge bases: `.claude/skills/opinion-analysis/references/apps/{抖音,微信,淘宝,快手,小红书}/`
- LLM config: `.env` (gitignored) — LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL
- Test data: `test/` | Output (gitignored): `output/`

## Dependencies

Python 3.8+, pandas, openpyxl, python-dotenv. SDK方式额外需要: openai, anthropic. Install: `pip3 install pandas openpyxl python-dotenv` 或 `pip3 install pandas openpyxl python-dotenv openai anthropic`

## Workflow (3 steps)

1. `analyze_excel.py <excel> --info` — identify columns, determine app_name/app_index/problem_index
2. `classify_data.py --app-name <N> --app-index <N> --problem-index <N> --excel-path <path> --output-dir <dir>` — init + classify + verify in one command
3. `analyze_excel.py <report.db> --output-dir <dir>` — generate HTML report

## classify_data.py details

- Each item: 1 LLM call → 1 DB INSERT, no intermediate files
- LLM client: openai/anthropic SDK
- Empty descriptions skipped with "空描述" status
- Progress shown with percentage counter
- LLM config from `.env` (priority: CLI args > env vars > .env)

## Critical constraints

- `.env`, `output/` at repo root are gitignored


逐层推导规则：
1. 分析问题描述，根据”应用描述“、”问题分类树“，结合”分类推理示例“，推理问题的一级分类
2. 分析问题描述，根据”应用描述“、”问题分类树“，结合第一步分析出来的一级分类下的二级分类，推理问题的二级分类
3. 分析问题描述，根据”应用描述“、”问题分类树“，结合第二步分析出来的二级分类下的三级分类，推理问题的三级分类

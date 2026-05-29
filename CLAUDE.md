# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Claude Code skill** repository — a Chinese public opinion (舆情) analysis tool that classifies app performance issues from Excel data using LLM APIs, then generates interactive HTML reports. The core skill lives at `.claude/skills/opinion-analysis/`.

There is no build system, no test suite, and no CI.

## Common Commands

### Install dependencies
```bash
pip3 install pandas openpyxl python-dotenv openai anthropic
```

### Step 1: Inspect Excel columns
```bash
python .claude/skills/opinion-analysis/scripts/analyze_excel.py <excel_file> --info
```
Outputs column names, sample data, app distribution. Use this to determine `app_index` and `problem_index`.

### Step 2: Classify data (the main work)
```bash
python .claude/skills/opinion-analysis/scripts/classify_data.py \
  --app-name <name> --app-index <N> --problem-index <N> \
  --excel-path <path> --output-dir <dir>
```
Calls LLM per row, stores results in SQLite (`report.db`). Automatically triggers report generation when done.

### Step 3: Generate report (standalone)
```bash
python .claude/skills/opinion-analysis/scripts/analyze_excel.py <report.db_path>
```

### Primary invocation
Through the `/opinion-analysis` skill command, which orchestrates the 3-step workflow automatically.

## Architecture

### 3-step pipeline
1. **Inspect** (`analyze_excel.py --info`) → human determines column indices
2. **Classify** (`classify_data.py`) → LLM classifies each row into level1 > level2 > level3 hierarchy, stores in SQLite
3. **Report** (`generate_report.py`) → fills HTML template with Chart.js visualizations, cascading dropdown filters, paginated detail table

### Data flow
```
Excel → analyze_excel.py --info → classify_data.py (LLM per row → SQLite) → generate_report.py → report.html
```

### Module relationships
- `classify_data.py` imports from `config.py` and calls `analyze_excel.generate_report()` at completion
- `analyze_excel.py` imports from `config.py`; handles --info, --init-output, --verify, and report generation
- `generate_report.py` is standalone — reads SQLite/JSON, fills template placeholders
- `config.py` is standalone — app alias map, column resolution, `SUPPORTED_APPS` list

### Per-app knowledge bases (`references/apps/<app>/`)
Each supported app has 3 files that feed into LLM prompts:
- `info.md` — app modules, pages, usage scenarios
- `classification.md` — level1/2/3 performance issue tree (8 categories: 卡顿, 响应慢, 闪退, 启动异常, 发热, 内存异常, 渲染异常, 网络异常)
- `examples.md` — few-shot reasoning examples

### Key design decisions
- **Layer-by-layer reasoning**: LLM deduces level1 first, then level2 under that level1, then level3 under that level2 (documented in AGENTS.md)
- **SQLite as intermediate**: enables resume-from-last-ID when re-running classification
- **Dual SDK client**: `classify_data.py` supports both openai and anthropic SDKs with streaming and reasoning_content capture
- **Template rendering**: `{{VAR}}` placeholders and `{{IF_X}}...{{ENDIF_X}}` conditionals in `report_template.html`
- **App aliases**: `config.py` maps colloquial names to canonical ones (e.g., "狗东"→"京东", "拼夕夕"→"拼多多")

## Configuration

LLM config comes from `.env` (gitignored). Copy `.env.example` and set:
- `LLM_PROVIDER` (openai or anthropic)
- `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` (required)
- Optional: `LLM_MAX_CONCURRENT`, `LLM_MAX_TOKENS`, `LLM_BATCH_SIZE`, `LLM_MAX_RETRIES`, `LLM_TIMEOUT`, `LLM_TEMPERATURE`, `LLM_VERIFY_SSL`, `LLM_LOG_LEVEL`, `LLM_DISABLE_PROXY`

## Important Constraints

- `.env` and `output/` are gitignored — never commit API keys or generated reports
- All three scripts have Windows UTF-8 stdout/stderr re-encoding at the top (required for Chinese text)
- `classify_data.py` inserts one DB row per LLM call; empty descriptions are skipped with "空描述" status
- Unsupported apps (not in `references/apps/`) get "未知问题" classification
- Test data of varying sizes (5 to 100k rows) lives in `test/` for manual testing
# AGENTS.md

## Project type

This is a **Claude Code skill** repository, not a standard application. The core deliverable is the `opinion-analysis` skill at `.claude/skills/opinion-analysis/`. There is no build system, no test suite runner, and no CI.

## Key paths

- Skill definition: `.claude/skills/opinion-analysis/SKILL.md` — the entrypoint and workflow spec
- Scripts: `.claude/skills/opinion-analysis/scripts/` — `analyze_excel.py` (main), `classify_data.py` (LLM分类), `save_results.py`, `generate_report.py`, `config.py`, `read_excel.py`
- Per-app knowledge bases: `.claude/skills/opinion-analysis/references/apps/{抖音,微信,淘宝,快手,小红书}/` — each has `info.md`, `classification.md`, `examples.md`
- HTML report template: `.claude/skills/opinion-analysis/assets/report_template.html`
- LLM config: `.env` (gitignored) — LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL
- Test Excel data: `test/` (no automated tests; these are sample input files)
- Output (gitignored): `output/`

## Dependencies

Python 3.8+, `pandas`, `openpyxl`, `openai`, `anthropic`, `python-dotenv`. Install: `pip3 install pandas openpyxl openai anthropic python-dotenv`

## Running the skill

Invoke via OpenCode: `/opinion_analysis 分析 <excel_path>`

Or manually with `classify_data.py`. All script paths must be **absolute**. Do not `cd` into the scripts directory before running them.

LLM API config auto-loads from `.env` in project root. Priority: CLI args > env vars > `.env` file.

## Workflow (5 steps, strict order)

1. `analyze_excel.py --init-output <output_dir>` — set up output dir and copy Excel
2. `analyze_excel.py <excel> --info` — identify app name column and problem description column; verify app is in `references/apps/`
3. `classify_data.py --app-name <name> --app-index <N> --problem-index <N> --excel-path <path> --output-dir <dir>` — each row is a single LLM call, result written directly to `report.db`
4. `analyze_excel.py <report.db> --verify <row_count>` — check all rows classified
5. `analyze_excel.py <report.db> --output-dir <output_dir>` — generate HTML report

## classify_data.py details

- Each item: 1 LLM call → 1 DB INSERT (no intermediate JSON files)
- Prompt: role + single description + app knowledge base (info/classification/examples)
- LLM output format: `{"classification": [...], "reason": "..."}`
- Concurrent via `--max-concurrent` (default 5)
- Supports `openai` and `anthropic` providers via `--provider`
- App aliases mapped in `config.py`. Unsupported apps → all data classified as "未知问题"

## Critical constraints

- `classify.md` at repo root and `output/` and `.env` are gitignored
- Output dir convention: `output/<excel_filename>/` by default, or user-specified path
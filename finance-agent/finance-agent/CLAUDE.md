# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-agent business assistant (RAG pipeline) for company managers. Covers inventory, HR, and finance domains. A natural language query flows through a 5-step pipeline:

1. **Finance LLM** decomposes the query into a structured data retrieval plan (JSON)
2. **Orchestrator** fetches data from PostgreSQL using parameterized queries (never raw LLM SQL)
3. **Finance LLM** analyzes retrieved data, produces narrative + coding instructions (JSON)
4. **Coding LLM** generates a self-contained Python script to create PDF/PPTX/XLSX reports
5. **Sandbox** executes the generated script in a subprocess

All LLM calls go through **OpenRouter** (`qwen/qwen3.5-27b`), using `temperature=0.1` and stripping `<think>` blocks and markdown fences from responses.

## Database

The agent connects to the local `postgres` database (password: `JMD333`) with 3 schemas from the shipathon_JMD project:

**inventory schema** (6 tables): products(75), warehouses(7), inventory_levels(525), stock_movements(5000), product_pricing(75), price_history(1497)

**hr schema** (4 tables): employees(100), employee_skills(526), performance_reviews(200), leave_records(349)

**finance schema** (2 tables + 2 materialized views): offices(7), sales_transactions(10000), mv_daily_office_profit_loss(1259), mv_daily_product_revenue(5520)

Key data dimensions:
- Cities: Mumbai, Delhi, Bangalore, Hyderabad, Chennai, Pune, Kolkata
- Product categories: electronics, clothing, food_beverages, home_office, pharma_health
- Departments: engineering, data_science, design, finance_ops, hr_admin, marketing, product, sales
- Date range: 2025-09-01 to 2026-02-28

The SQL schema files are in `shipathon_JMD/` (00_extensions.sql through 03_finance.sql). The database also has pgvector embeddings and tsvector indexes for hybrid search, though the current pipeline uses structured queries only.

## Commands

```bash
# Validate database + install deps
python setup.py

# Start server + open browser at http://localhost:8501
python main.py
```

## Environment Configuration

`.env` in project root:
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — LLM access via OpenRouter
- `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` — database (postgres DB, password JMD333)
- `SERVER_HOST` / `SERVER_PORT` — FastAPI server (default `0.0.0.0:8501`)
- `SANDBOX_TIMEOUT` / `GENERATED_DIR` — code execution config

## Architecture: Key Design Decisions

- **No raw LLM SQL**: `core/db.py` validates all table/column names against whitelists (`ALLOWED_COLUMNS` with 14 schema-qualified entries) and builds parameterized queries with `psycopg2.sql.Identifier("schema", "table")`. The LLM outputs a structured JSON data plan, not SQL.
- **Schema-qualified table names**: Tables use dot-notation (`"finance.offices"`, `"hr.employees"`). The query builder splits on `.` to produce proper `sql.Identifier` pairs.
- **Generic filter system**: Filter keys are column names directly. Supports scalar equality, list IN-clauses, and operator dicts for ranges (`{"gte": "2025-01-01", "lte": "2025-03-31"}`).
- **No JOIN support**: Each data_requirement queries one table. The LLM requests data from multiple tables separately; the analysis step correlates them. Materialized views pre-join common cross-schema relationships.
- **Two LLM calls per query**: First decomposes the question into data requirements, second analyzes retrieved data and produces narrative + coding instructions. Both return JSON.
- **Coding agent output is raw Python code**, not JSON. Written to temp file, executed in subprocess sandbox.
- **8 few-shot examples** in DECOMPOSE_SYSTEM_PROMPT covering all 3 domains to ground the LLM.
- **Web UI is a single HTML file** (`ui/index.html`) with embedded CSS/JS, served by FastAPI. No build step.

## Critical Patterns

- Always strip `<think>...</think>` blocks from Qwen3 responses before parsing
- Always strip markdown code fences from LLM output before JSON/code parsing
- LLM calls retry up to 3 times with 2s backoff on HTTP errors
- The coding agent must never define a variable named `colors` (shadows reportlab import)
- Chart images saved as flat files in cwd (not tempfile), deleted after embedding in document
- Connection pooling via `psycopg2.pool.ThreadedConnectionPool` (1-10 connections)
- Prefer materialized views (`mv_daily_office_profit_loss`, `mv_daily_product_revenue`) for analytics queries — they are pre-aggregated

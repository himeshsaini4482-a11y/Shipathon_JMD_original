# Finance Agent — Project Specification

> **For Claude Code**: Read this entire file before writing any code. Follow the architecture exactly. Ask no clarifying questions — everything you need is here.

## What We Are Building

A multi-agent finance assistant for company managers. A manager asks a natural language question (e.g., "How did our Mumbai region perform this quarter?") and the system:

1. **Finance LLM** decomposes the query into a data retrieval plan (which tables, what filters, what aggregations)
2. **Orchestrator** fetches data from PostgreSQL using parameterized queries (NEVER raw LLM-generated SQL)
3. **Finance LLM** analyzes the retrieved data and produces: (a) a narrative answer, (b) structured instructions for document generation
4. **Coding LLM** generates Python code to create a PDF/PPTX/XLSX report with charts, tables, and narrative
5. **Sandbox** executes the generated code and produces the final document
6. **Web UI** shows the narrative, findings, recommendations, and an inline document preview (PDF renders in iframe, PPTX/XLSX get download links)

Both the finance and coding tasks use the same model: **Qwen/Qwen3.5-27B** via OpenRouter (Apache 2.0). When you have your own hardware (3× RTX A6000), switch to self-hosted Qwen3.5-27B via vLLM — just change the API URL in `.env`.

---

## Architecture Overview

```
┌─────────────┐
│  Browser UI  │  (localhost:8501)
│  (HTML/JS)   │
└──────┬───────┘
       │ POST /api/query
       ▼
┌──────────────┐     ┌──────────────────┐
│  service.py  │────▶│  PostgreSQL      │
│  (FastAPI)   │     │  finance_agent   │
│  Orchestrator│     │  (5 tables)      │
└──────┬───────┘     └──────────────────┘
       │
       │ Calls OpenRouter API twice:
       │   1. Decompose query → data plan
       │   2. Analyze data → narrative + coding spec
       │
       ▼
┌──────────────┐
│  Coding LLM  │  (OpenRouter, same model)
│  Generates   │
│  Python code │
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌──────────────┐
│  Sandbox     │────▶│  Generated   │
│  (subprocess)│     │  PDF/PPTX/   │
│              │     │  XLSX file   │
└──────────────┘     └──────────────┘
```

---

## File Structure

```
finance-agent/
├── PROJECT.md          ← This file (do not modify)
├── .env                ← Created by setup.py
├── setup.py            ← Run FIRST: creates DB, tables, mock data
├── main.py             ← Run SECOND: starts service.py, opens browser
├── service.py          ← FastAPI server (orchestrator + web UI)
├── agents/
│   ├── __init__.py
│   ├── finance_agent.py    ← Finance LLM calls (decompose + analyze)
│   ├── coding_agent.py     ← Coding LLM calls (generate document code)
│   └── prompts.py          ← All system prompts (centralized)
├── core/
│   ├── __init__.py
│   ├── config.py           ← All configuration (reads .env)
│   ├── db.py               ← PostgreSQL connection + query executor
│   ├── orchestrator.py     ← Pipeline coordinator
│   ├── sandbox.py          ← Safe code execution
│   └── schemas.py          ← Pydantic models for inter-agent messages
├── ui/
│   └── index.html          ← Web UI (single HTML file, served by FastAPI)
├── generated/              ← Output directory for generated documents
│   └── .gitkeep
└── requirements.txt
```

---

## Environment Configuration

Create `.env` in the project root:

```env
# OpenRouter
OPENROUTER_API_KEY=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
OPENROUTER_MODEL=qwen/qwen3.5-27b

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=220504
POSTGRES_DB=finance_agent

# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8501

# Sandbox
SANDBOX_TIMEOUT=60
GENERATED_DIR=./generated
```

> **SECURITY NOTE**: In production, rotate these credentials and use a secrets manager. Never commit `.env` to Git. Add `.env` to `.gitignore`.

---

## Database Schema

Database name: `finance_agent`

### Table 1: `sales`
Revenue data by product, region, and month.

```sql
CREATE TABLE sales (
    id SERIAL PRIMARY KEY,
    region VARCHAR(50) NOT NULL,
    product_line VARCHAR(100) NOT NULL,
    month DATE NOT NULL,              -- first day of month (e.g., 2025-01-01)
    revenue NUMERIC(15,2) NOT NULL,
    units_sold INTEGER NOT NULL,
    target_revenue NUMERIC(15,2) NOT NULL,
    sales_rep VARCHAR(100),
    channel VARCHAR(50) DEFAULT 'direct'  -- direct, online, distributor
);

CREATE INDEX idx_sales_region ON sales(region);
CREATE INDEX idx_sales_month ON sales(month);
CREATE INDEX idx_sales_product ON sales(product_line);
```

### Table 2: `expenses`
Operating costs by category, region, and month.

```sql
CREATE TABLE expenses (
    id SERIAL PRIMARY KEY,
    region VARCHAR(50) NOT NULL,
    cost_category VARCHAR(100) NOT NULL,  -- Logistics, Marketing, Salaries, Rent, Utilities, R&D
    month DATE NOT NULL,
    amount NUMERIC(15,2) NOT NULL,
    budget NUMERIC(15,2) NOT NULL,
    notes TEXT
);

CREATE INDEX idx_expenses_region ON expenses(region);
CREATE INDEX idx_expenses_month ON expenses(month);
```

### Table 3: `returns`
Product returns and refunds.

```sql
CREATE TABLE returns (
    id SERIAL PRIMARY KEY,
    region VARCHAR(50) NOT NULL,
    product_line VARCHAR(100) NOT NULL,
    month DATE NOT NULL,
    return_count INTEGER NOT NULL,
    refund_amount NUMERIC(15,2) NOT NULL,
    reason_code VARCHAR(50) NOT NULL,     -- defective, wrong_item, not_as_described, changed_mind, damaged_shipping
    batch_number VARCHAR(50)
);

CREATE INDEX idx_returns_month ON returns(month);
CREATE INDEX idx_returns_product ON returns(product_line);
```

### Table 4: `inventory`
Stock levels by product and warehouse.

```sql
CREATE TABLE inventory (
    id SERIAL PRIMARY KEY,
    region VARCHAR(50) NOT NULL,
    product_line VARCHAR(100) NOT NULL,
    warehouse VARCHAR(100) NOT NULL,
    month DATE NOT NULL,
    stock_quantity INTEGER NOT NULL,
    reorder_level INTEGER NOT NULL,
    days_of_supply INTEGER NOT NULL,
    storage_cost NUMERIC(12,2) NOT NULL
);

CREATE INDEX idx_inventory_product ON inventory(product_line);
CREATE INDEX idx_inventory_region ON inventory(region);
```

### Table 5: `sales_reps`
Sales team details and performance.

```sql
CREATE TABLE sales_reps (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    region VARCHAR(50) NOT NULL,
    designation VARCHAR(50) NOT NULL,    -- Junior, Senior, Lead, Manager
    hire_date DATE NOT NULL,
    quarterly_quota NUMERIC(15,2) NOT NULL,
    quarterly_achieved NUMERIC(15,2) NOT NULL,
    active BOOLEAN DEFAULT TRUE
);
```

---

## Mock Data Specification

Generate **12 months of data** (January 2025 — December 2025) across **4 regions** (Mumbai, Delhi, Kolkata, Bangalore) and **5 product lines** (Product A, Product B, Product C, Product D, Product E).

### Sales Data Rules:
- **~960 rows** (4 regions × 5 products × 12 months × ~4 channels)
- Revenue ranges: Product A (₹12L-₹20L/month), Product B (₹5L-₹8L/month), Product C (₹7L-₹12L/month), Product D (₹4L-₹7L/month), Product E (₹3L-₹5L/month)
- Mumbai region is the top performer (110% of base), Kolkata is weakest (85% of base)
- Q4 has a seasonal uplift of ~15% over Q2
- Product B has a deliberate dip in Q3 (July-Sep) — simulates a supply chain issue
- Include channels: "direct" (50%), "online" (30%), "distributor" (20%)
- Targets should be set so overall achievement is ~90-95% (some products overshoot, some miss)
- Sales reps: 3-4 per region, randomly assigned

### Expense Data Rules:
- **~288 rows** (4 regions × 6 categories × 12 months)
- Categories: Logistics, Marketing, Salaries, Rent, Utilities, R&D
- Logistics has a spike in Q3 (+18% over Q2) to match the Product B supply chain issue
- Salaries grow ~2% per quarter (annual increments)
- Rent is constant per region: Mumbai ₹2.2L/mo, Delhi ₹1.8L/mo, Kolkata ₹1.5L/mo, Bangalore ₹1.7L/mo
- Marketing has a Q4 spike (festive season spend)

### Returns Data Rules:
- **~240 rows** (4 regions × 5 products × 12 months)
- Normal return rate: 2-4% of units sold
- March has a deliberate spike (8-12% return rate) — simulates a batch quality issue
- Spike concentrated in Product C, batch number "BATCH-4421"
- Reason codes distribution: defective (30%), wrong_item (15%), not_as_described (20%), changed_mind (25%), damaged_shipping (10%)
- March spike is mostly "defective" reason code

### Inventory Data Rules:
- **~240 rows** (4 regions × 5 products × 12 months, 1 warehouse per region)
- Warehouses: "Mumbai Warehouse", "Delhi Warehouse", "Kolkata Warehouse", "Bangalore Warehouse"
- Days of supply ranges 15-45 days normally
- Product B in Delhi shows dangerously low stock (5-10 days) in Q3 — ties to the supply chain issue
- Reorder levels set at 15 days of average monthly sales

### Sales Reps Data:
- **16 reps** (4 per region)
- Mix of Junior (hired 2024), Senior (hired 2022-2023), Lead (hired 2021), Manager (hired 2019-2020)
- Quotas range ₹35L-₹80L/quarter depending on designation
- Achievement ranges 75%-120% — 2-3 reps clearly underperforming (<85%), 2-3 overperforming (>110%)

---

## Inter-Agent Communication Protocol

All LLM calls go through OpenRouter's `/api/v1/chat/completions` endpoint (OpenAI-compatible).

### Finance Agent — Step 1: Query Decomposition

**System prompt** (in `agents/prompts.py`):
```
You are a senior financial analyst AI. Given a manager's question about business performance,
decompose it into a structured data retrieval plan.

Available database tables:
- sales (columns: region, product_line, month, revenue, units_sold, target_revenue, sales_rep, channel)
- expenses (columns: region, cost_category, month, amount, budget)
- returns (columns: region, product_line, month, return_count, refund_amount, reason_code, batch_number)
- inventory (columns: region, product_line, warehouse, month, stock_quantity, reorder_level, days_of_supply, storage_cost)
- sales_reps (columns: name, region, designation, hire_date, quarterly_quota, quarterly_achieved, active)

RULES:
1. Output ONLY valid JSON. No markdown, no explanation, no code fences.
2. Identify which tables and columns are needed.
3. Specify filters (date ranges, regions, products) precisely.
4. Use ISO date format (YYYY-MM-DD) for all dates.
5. The current date is {current_date}. "This quarter" = most recent complete quarter.
6. Always include at least one comparison dimension (QoQ, YoY, region vs region, etc.)

Output JSON schema:
{
  "intent": "performance_review | comparison | forecasting | anomaly_diagnosis | strategic_recommendation | cost_analysis | operational_status | resource_allocation",
  "data_requirements": [
    {
      "req_id": "dr-001",
      "table": "sales | expenses | returns | inventory | sales_reps",
      "columns": ["column1", "column2"],
      "filters": {
        "region": ["Mumbai"],
        "month_from": "2025-07-01",
        "month_to": "2025-09-30",
        "product_line": ["Product A"]
      },
      "group_by": ["product_line", "month"],
      "order_by": "revenue DESC",
      "aggregate": {
        "revenue": "SUM",
        "units_sold": "SUM"
      },
      "priority": "required | nice_to_have"
    }
  ],
  "analysis_plan": "Brief description of what computations to perform on the retrieved data",
  "output_sections": ["executive_summary", "chart:grouped_bar:Revenue by Product", "table:Product Details", "recommendations"]
}
```

**User message format**:
```
Manager's question: "{raw_query}"
User's role: {user_role}
Preferred output format: {format}
```

### Orchestrator — Data Retrieval

The orchestrator takes the `data_requirements` from Step 1 and builds **parameterized SQL queries**. It NEVER executes raw SQL from the LLM. The mapping is:

```python
# Allowed operations per table (whitelist)
ALLOWED_COLUMNS = {
    "sales": ["region", "product_line", "month", "revenue", "units_sold", "target_revenue", "sales_rep", "channel"],
    "expenses": ["region", "cost_category", "month", "amount", "budget"],
    "returns": ["region", "product_line", "month", "return_count", "refund_amount", "reason_code", "batch_number"],
    "inventory": ["region", "product_line", "warehouse", "month", "stock_quantity", "reorder_level", "days_of_supply", "storage_cost"],
    "sales_reps": ["name", "region", "designation", "hire_date", "quarterly_quota", "quarterly_achieved", "active"],
}

ALLOWED_AGGREGATES = ["SUM", "AVG", "COUNT", "MIN", "MAX"]
ALLOWED_TABLES = list(ALLOWED_COLUMNS.keys())
```

The query builder:
1. Validates table name against `ALLOWED_TABLES`
2. Validates all column names against `ALLOWED_COLUMNS[table]`
3. Validates aggregate functions against `ALLOWED_AGGREGATES`
4. Builds parameterized query using `%s` placeholders
5. Executes via `psycopg2` with parameters tuple (never string interpolation)

### Finance Agent — Step 2: Analysis

**System prompt** (in `agents/prompts.py`):
```
You are a senior financial analyst AI. You have received the data you requested.
Analyze it and produce a narrative answer plus structured coding instructions.

RULES:
1. Output ONLY valid JSON. No markdown, no explanation.
2. Every number in coding_instructions must be pre-computed by you. The coding agent is a code GENERATOR, not an analyst.
3. Chart series must contain actual numerical values, not formulas or references.
4. Table rows must contain actual data values.
5. Currency values should be in INR (₹). Use "L" for lakhs, "Cr" for crores.

Output JSON schema:
{
  "narrative": {
    "executive_summary": "2-3 sentence TL;DR",
    "key_findings": [
      {"finding": "text", "sentiment": "positive|negative|neutral|warning", "metric": "+23%"}
    ],
    "recommendations": [
      {"action": "text", "priority": "critical|high|medium|low", "impact": "expected impact text"}
    ],
    "caveats": ["caveat text"]
  },
  "coding_instructions": {
    "output_format": "pdf|pptx|xlsx",
    "title": "Report Title",
    "sections": [
      {
        "type": "title_page|heading|paragraph|metric_cards|table|chart|recommendations|page_break",
        "content": { ... }
      }
    ]
  }
}

Section content schemas:

For type="metric_cards":
  {"cards": [{"label": "Total Revenue", "value": "₹4.5Cr", "change": "+12%", "direction": "up|down|flat"}]}

For type="chart":
  {"chart_type": "grouped_bar|line|bar|pie|waterfall|stacked_bar",
   "title": "Chart Title",
   "x_labels": ["A", "B", "C"],
   "series": [{"name": "Q3", "values": [100, 200, 300]}, {"name": "Q4", "values": [120, 180, 350]}],
   "y_label": "Revenue (₹ Lakhs)"}

For type="table":
  {"title": "Table Title",
   "headers": ["Product", "Q3", "Q4", "Change"],
   "rows": [["Product A", "14.6L", "18.0L", "+23%"]],
   "highlight_column": 3,
   "highlight_positive_green": true}

For type="paragraph":
  {"text": "paragraph text"}

For type="recommendations":
  {"items": [{"action": "text", "priority": "high", "impact": "text"}]}
```

### Coding Agent

**System prompt** (in `agents/prompts.py`):
```
You are a Python code generation agent. Given structured instructions, generate a COMPLETE,
EXECUTABLE Python script that produces the requested document.

RULES:
1. Use ONLY these libraries: matplotlib, reportlab, python-pptx, openpyxl.
2. The script must be SELF-CONTAINED. All data is in the instructions — do not import external files.
3. Save the output to the exact path specified in output_path.
4. Use matplotlib with Agg backend for all charts: matplotlib.use("Agg")
5. Use tight_layout() and savefig at 150 DPI for charts.
6. Color scheme: primary=#1a365d, accent=#2b6cb0, positive=#276749, negative=#c53030, muted=#718096
7. Handle errors gracefully — if a chart fails, skip it and continue.
8. Output ONLY Python code. No explanation, no markdown fences.
9. Clean up any temporary chart image files after embedding them.

For PDF: use reportlab with platypus (SimpleDocTemplate, Paragraph, Table, Image, Spacer, PageBreak).
For PPTX: use python-pptx with blank slide layouts (layout index 6). Slide size: 13.333 x 7.5 inches.
For XLSX: use openpyxl with formatted headers, conditional coloring, and embedded charts.
```

**User message format**:
```json
{
  "coding_instructions": { ... },
  "narrative": { ... },
  "output_path": "/absolute/path/to/output.pdf"
}
```

---

## Implementation Details

### `setup.py`

This script:
1. Reads `.env` for PostgreSQL credentials
2. Connects to PostgreSQL as the postgres user
3. Creates the `finance_agent` database if it doesn't exist
4. Creates all 5 tables
5. Generates and inserts mock data following the rules above
6. Prints a summary of inserted rows
7. Installs Python dependencies from `requirements.txt`

Run: `python setup.py`

### `service.py`

This is the FastAPI server. It:
1. Serves the web UI at `GET /`
2. Handles queries at `POST /api/query` with body `{"query": "...", "format": "pdf|pptx|xlsx"}`
3. Serves generated files at `GET /api/download/{filename}`
4. Coordinates the full pipeline via the orchestrator

The web UI (`ui/index.html`) is a single HTML file with embedded CSS and JS (no build step). It must include:
- A text input for the query
- A format selector (PDF/PPTX/XLSX dropdown)
- Example query chips that auto-fill the input
- A "Run pipeline" button
- A results area showing: pipeline status indicator, executive summary, color-coded findings with metrics, prioritized recommendations, caveats, follow-up suggestions, timing/metadata
- For PDF: an inline iframe preview
- For PPTX/XLSX: a download button
- Follow-up chips that re-trigger the pipeline

### `main.py`

This script:
1. Checks that `.env` exists
2. Checks that PostgreSQL is reachable and `finance_agent` database exists
3. Checks that the `generated/` directory exists
4. Starts `service.py` as a subprocess
5. Waits for the server to be ready (polls `http://localhost:8501/` until 200)
6. Opens the browser to `http://localhost:8501`
7. Waits for Ctrl+C and gracefully shuts down

Run: `python main.py`

### `core/config.py`

Reads `.env` using `python-dotenv`. Exposes a `Config` dataclass:
```python
@dataclass
class Config:
    openrouter_api_key: str
    openrouter_model: str
    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str
    server_host: str
    server_port: int
    sandbox_timeout: int
    generated_dir: str
```

### `core/db.py`

PostgreSQL interface:
- `get_connection()` → returns a `psycopg2` connection
- `execute_query(table, columns, filters, group_by, order_by, aggregate)` → validates all inputs against whitelists, builds parameterized query, returns `{"columns": [...], "data": [{...}, ...]}`
- All identifiers use `psycopg2.sql.Identifier` for safe quoting
- Connection pooling with `psycopg2.pool.ThreadedConnectionPool`

### `core/orchestrator.py`

Pipeline coordinator:
```python
async def process_query(raw_query: str, output_format: str) -> dict:
    # Step 1: Finance LLM decomposes query
    decomposition = await finance_agent.decompose(raw_query, output_format)

    # Step 2: Fetch data from PostgreSQL
    data_results = fetch_all_data(decomposition["data_requirements"])

    # Step 3: Finance LLM analyzes data
    analysis = await finance_agent.analyze(raw_query, decomposition, data_results, output_format)

    # Step 4: Coding LLM generates document code
    code = await coding_agent.generate(analysis, output_path)

    # Step 5: Execute generated code in sandbox
    output_file = sandbox.execute(code, output_path)

    # Step 6: Assemble response
    return {
        "query_id": ...,
        "status": "complete",
        "narrative": analysis["narrative"],
        "file": {"name": ..., "download_url": ..., "size_kb": ...},
        "follow_ups": [...],
        "time_ms": ...,
    }
```

### `agents/finance_agent.py`

Two async functions:
- `decompose(query, format)` → calls OpenRouter with the decomposition system prompt, returns parsed JSON
- `analyze(query, decomposition, data, format)` → calls OpenRouter with the analysis system prompt, returns parsed JSON

Both use `httpx.AsyncClient` with timeout=120s. JSON parsing includes stripping markdown fences.

### `agents/coding_agent.py`

One async function:
- `generate(analysis, output_path)` → calls OpenRouter with the coding system prompt, returns raw Python code string

### `core/sandbox.py`

Executes generated code safely:
```python
def execute(code: str, expected_output: str) -> str:
    script_path = write_temp_script(code)
    proc = subprocess.run(
        [sys.executable, script_path],
        capture_output=True, text=True,
        timeout=config.sandbox_timeout,
        cwd=config.generated_dir,
    )
    if proc.returncode != 0:
        raise SandboxError(proc.stderr[-500:])
    if not Path(expected_output).exists():
        raise SandboxError("Output file not created")
    return expected_output
```

### `core/schemas.py`

Pydantic models for type safety:
```python
class QueryRequest(BaseModel):
    query: str
    format: Literal["pdf", "pptx", "xlsx"] = "pdf"

class DataRequirement(BaseModel):
    req_id: str
    table: Literal["sales", "expenses", "returns", "inventory", "sales_reps"]
    columns: list[str]
    filters: dict = {}
    group_by: list[str] = []
    order_by: str | None = None
    aggregate: dict = {}
    priority: Literal["required", "nice_to_have"] = "required"

class Finding(BaseModel):
    finding: str
    sentiment: Literal["positive", "negative", "neutral", "warning"]
    metric: str

class Recommendation(BaseModel):
    action: str
    priority: Literal["critical", "high", "medium", "low"]
    impact: str = ""

class Narrative(BaseModel):
    executive_summary: str
    key_findings: list[Finding]
    recommendations: list[Recommendation]
    caveats: list[str] = []

class PipelineResponse(BaseModel):
    query_id: str
    status: Literal["complete", "error"]
    narrative: Narrative | None
    file: dict | None
    follow_ups: list[str]
    time_ms: int
    error: str | None = None
```

---

## OpenRouter API Call Pattern

```python
import httpx

async def call_llm(system_prompt: str, user_message: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.openrouter_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": 8192,
                "temperature": 0.1,
                "top_p": 0.95,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        # Strip <think>...</think> blocks (Qwen3 thinking mode — CONFIRMED: model uses 175 reasoning tokens even with temp=0.1)
        import re
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        # Strip markdown code fences
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]

        return content.strip()
```

---

## requirements.txt

```
fastapi==0.115.6
uvicorn==0.34.0
httpx==0.28.1
psycopg2-binary==2.9.10
python-dotenv==1.0.1
pydantic==2.10.4
matplotlib==3.10.0
reportlab==4.2.5
python-pptx==1.0.2
openpyxl==3.1.5
```

---

## Example Queries the Manager Can Ask

These queries MUST work end-to-end. Test each one:

1. **"How did our Delhi region perform this quarter?"** → Performance review with revenue charts, product breakdown, and recommendations
2. **"Compare sales performance across all regions"** → Side-by-side regional comparison (Mumbai, Delhi, Kolkata, Bangalore) with grouped bar charts
3. **"Why did returns spike in March?"** → Anomaly diagnosis identifying Product C, batch BATCH-4421, defective reason code
4. **"What is eating into our margins?"** → Cost analysis showing logistics spike, QoQ cost comparison
5. **"Project next quarter revenue based on current trends"** → Trend chart with projected line, confidence discussion
6. **"Show me overdue inventory items"** → Products with days_of_supply < 15, flagging Product B in Delhi
7. **"Which sales reps are underperforming?"** → Rep table sorted by achievement %, flagging <85%
8. **"Give me a monthly revenue breakdown for the year"** → 12-month line chart with monthly table

---

## Critical Implementation Rules

1. **NEVER execute raw SQL from LLM output.** Always validate table/column names against whitelists and use parameterized queries.
2. **Strip `<think>` blocks** from Qwen3 responses before parsing JSON. The model may use chain-of-thought wrapped in `<think>...</think>` tags.
3. **Strip markdown code fences** (`\`\`\`json ... \`\`\``) from LLM responses before JSON parsing.
4. **All LLM calls use temperature=0.1** for consistent structured output.
5. **The coding agent output is Python code, not JSON.** Parse it as a raw string and write to a temp file.
6. **Generated files go in `./generated/` directory.** Clean up files older than 1 hour on each request.
7. **The web UI is a single HTML file** served by FastAPI. No React, no build step, no npm.
8. **Error handling**: if any LLM call fails or returns invalid JSON, return a graceful error to the UI with the error message. Don't crash.
9. **Retry logic**: retry LLM calls up to 2 times with 2s backoff on HTTP errors.
10. **The PDF must render inline in the browser** via `<iframe src="/api/download/...">`. Set `Content-Type: application/pdf` and `Content-Disposition: inline`.

---

## Running the System

```bash
# Step 1: One-time setup
python setup.py

# Step 2: Start the server and open browser
python main.py
```

That's it. `main.py` starts `service.py` and opens the browser. The manager types a question, picks a format, clicks "Run pipeline", and gets a narrative + downloadable report.

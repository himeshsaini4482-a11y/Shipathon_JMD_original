# Nasiko Business Intelligence Agent

A multi-agent RAG pipeline that lets company managers ask natural-language questions about **finance**, **inventory**, **HR**, and **employee onboarding** — and receive professional PDF/PPTX/XLSX reports with charts, tables, and actionable recommendations.

Built for the IIT Delhi Shipathon.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Database](#database)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Option A: Docker (Recommended)](#option-a-docker-recommended)
  - [Option B: Local Setup](#option-b-local-setup)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Pipeline Deep Dive](#pipeline-deep-dive)
- [Security](#security)
- [Project Structure](#project-structure)
- [Configuration](#configuration)

---

## How It Works

A manager types a question like *"Compare profit margins across all offices for the last quarter"* and the system:

1. **Decomposes** the query into a structured data retrieval plan (JSON)
2. **Fetches** data from PostgreSQL using safe, parameterized queries
3. **Analyzes** the data and produces a narrative with coding instructions
4. **Generates** a Python script that creates a professional PDF/PPTX/XLSX report with charts
5. **Executes** the script in a sandboxed subprocess and returns the report

All LLM calls go through **OpenRouter** (default model: `qwen/qwen3.5-27b`). No raw LLM-generated SQL ever touches the database.

---

## Architecture

```
                          +------------------+
       User Query ------->|   FastAPI Server  |
                          |   (service.py)    |
                          +--------+---------+
                                   |
                     +-------------+-------------+
                     |                           |
              Finance Pipeline          Onboarding Pipeline
                     |                           |
            +--------v---------+       +---------v----------+
            |  1. Decompose    |       |  Extract Employee  |
            |  (Finance LLM)   |       |  Search & Match    |
            +--------+---------+       |  Provision Accounts|
                     |                 |  Draft Email       |
            +--------v---------+       |  Schedule Meeting  |
            |  2. Fetch Data   |       |  Generate Doc      |
            |  (PostgreSQL)    |       +--------------------+
            +--------+---------+
                     |
            +--------v---------+
            |  3. Analyze      |
            |  (Finance LLM)   |
            +--------+---------+
                     |
            +--------v---------+
            |  4. Code Gen     |
            |  3-Agent Pipeline|
            |  Coder -> Syntax |
            |  -> Reviewer     |
            +--------+---------+
                     |
            +--------v---------+
            |  5. Sandbox Exec |
            |  (subprocess)    |
            +--------+---------+
                     |
            +--------v---------+
            |  Quality Loop    |
            |  Score >= 70/100 |
            |  Up to 3 iters   |
            +------------------+
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **LLM** | OpenRouter API (Qwen 3.5-27B default) |
| **Backend** | FastAPI + Uvicorn (async) |
| **Database** | PostgreSQL 16 + pgvector |
| **Report Gen** | ReportLab (PDF), python-pptx (PPTX), openpyxl (XLSX) |
| **Charts** | Matplotlib |
| **Frontend** | Single HTML file with vanilla JS/CSS |
| **Containerization** | Docker + Docker Compose |

---

## Database

The agent connects to a PostgreSQL database with **4 schemas**:

### Inventory Schema (6 tables)
| Table | Rows | Description |
|-------|------|-------------|
| `products` | 75 | Product catalog across 5 categories |
| `warehouses` | 7 | Warehouse locations (7 cities) |
| `inventory_levels` | 525 | Stock per product per warehouse |
| `stock_movements` | 5,000 | Inbound/outbound/transfer records |
| `product_pricing` | 75 | Current cost and selling prices |
| `price_history` | 1,497 | Historical price changes |

### HR Schema (4 tables)
| Table | Rows | Description |
|-------|------|-------------|
| `employees` | 100 | Employee directory (8 departments) |
| `employee_skills` | 526 | Skills per employee |
| `performance_reviews` | 200 | Quarterly reviews with ratings |
| `leave_records` | 349 | Leave history |

### Finance Schema (2 tables + 2 materialized views)
| Table | Rows | Description |
|-------|------|-------------|
| `offices` | 7 | Office locations with cost structure |
| `sales_transactions` | 10,000 | Individual sale records |
| `mv_daily_office_profit_loss` | 1,259 | Pre-aggregated daily P&L per office |
| `mv_daily_product_revenue` | 5,520 | Pre-aggregated daily revenue per product |

### Onboarding Schema (4 tables)
| Table | Description |
|-------|-------------|
| `onboarding_records` | New hire tracking with status/steps |
| `manager_schedule` | Manager availability for meetings |
| `email_drafts` | Welcome email drafts and revisions |
| `system_accounts` | Provisioned tool accounts |

**Key dimensions:**
- **Cities:** Mumbai, Delhi, Bangalore, Hyderabad, Chennai, Pune, Kolkata
- **Product categories:** electronics, clothing, food_beverages, home_office, pharma_health
- **Departments:** engineering, data_science, design, finance_ops, hr_admin, marketing, product, sales
- **Date range:** 2025-09-01 to 2026-02-28

---

## Getting Started

### Prerequisites

- **OpenRouter API key** — get one at [openrouter.ai](https://openrouter.ai)
- **Docker & Docker Compose** (for Docker setup), OR
- **Python 3.12+** and **PostgreSQL 16** (for local setup)

### Option A: Docker (Recommended)

This is the fastest way to get everything running. Docker Compose sets up PostgreSQL with all schemas, seeds the data, and starts the app.

**1. Clone and configure:**

```bash
git clone <repo-url>
cd finance-agent

# Create your environment file from the template
cp .env.example .env
```

**2. Edit `.env` with your credentials:**

```env
# Required: your OpenRouter API key
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Optional: change the default DB password
POSTGRES_PASSWORD=changeme
```

**3. Start the stack:**

```bash
docker compose up -d
```

This starts 3 services:

| Service | What it does |
|---------|-------------|
| `db` | PostgreSQL 16 with pgvector. Runs the 4 SQL schema files on first boot. |
| `db-seed` | One-shot container that populates all tables with synthetic data (runs once, then exits). |
| `app` | FastAPI server. Creates onboarding tables on startup, then serves on port 8501. |

**4. Wait for seeding to complete (first run only, ~2-3 minutes):**

```bash
# Watch the seed progress
docker compose logs -f db-seed

# You'll see:
#   Seeding products... 75 products inserted.
#   Seeding sales transactions... 10000 sales transactions inserted.
#   === DB seed complete ===
```

**5. Open the app:**

```
http://localhost:8501
```

**Useful Docker commands:**

```bash
# View app logs
docker compose logs -f app

# Stop everything
docker compose down

# Full reset (wipes database volume, re-seeds on next start)
docker compose down -v

# Rebuild after code changes
docker compose build app && docker compose up -d app
```

### Option B: Local Setup

**1. Install PostgreSQL 16** and create the database schemas:

```bash
psql -U postgres -d postgres -f shipathon_JMD/00_extensions.sql
psql -U postgres -d postgres -f shipathon_JMD/01_inventory.sql
psql -U postgres -d postgres -f shipathon_JMD/02_hr.sql
psql -U postgres -d postgres -f shipathon_JMD/03_finance.sql
```

**2. Seed the data:**

```bash
pip install asyncpg numpy faker
set DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/postgres
python shipathon_JMD/seed_data.py
```

**3. Configure environment:**

```bash
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY and POSTGRES_PASSWORD
# Keep POSTGRES_HOST=localhost for local setup
```

**4. Validate database and install dependencies:**

```bash
python setup.py
```

You should see:

```
[OK] Schema 'inventory' exists
[OK] Schema 'hr' exists
[OK] Schema 'finance' exists
[OK] inventory.products — 75 rows
...
[OK] All schemas, tables, and views are present
[OK] Onboarding setup complete
```

**5. Start the server:**

```bash
python main.py
```

The server starts at `http://localhost:8501` and opens your browser automatically.

---

## Usage

### Finance & Analytics Queries

Type natural-language questions in the chat interface. The agent handles queries across all three business domains:

**Finance:**
- *"Compare profit margins across all offices for Q4 2025"*
- *"Which office had the highest revenue last month?"*
- *"Show me the daily profit/loss trend for Mumbai office"*

**Inventory:**
- *"What are the top 10 products by stock movement volume?"*
- *"Which warehouses are running low on electronics?"*
- *"Show price history trends for the pharma category"*

**HR:**
- *"List employees in engineering with Python skills"*
- *"Compare average performance ratings across departments"*
- *"Show leave utilization by department this quarter"*

The agent returns:
- A **narrative analysis** with executive summary, key findings, and recommendations
- A **downloadable report** (PDF, PPTX, or XLSX) with charts and tables
- **Follow-up questions** you can click to explore further

### Employee Onboarding

The agent also handles onboarding workflows. Trigger it with messages like:

- *"Start onboarding for Rahul Sharma in engineering"*
- *"Onboard the new hire joining data science"*

The onboarding pipeline:
1. Extracts employee details from your message
2. Finds matching pending records in the system
3. Provisions system accounts (email, Slack, GitHub, Jira, etc.)
4. Drafts a welcome email for your review
5. Finds available meeting slots on the manager's calendar
6. Generates an onboarding document (PDF)
7. Marks the onboarding as complete

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serves the web UI |
| `/api/query` | POST | Main query endpoint (routes to finance or onboarding) |
| `/api/onboarding/dashboard` | GET | Returns all onboarding records with summary stats |
| `/api/onboarding/select-employee` | POST | Disambiguate when multiple employees match |
| `/api/onboarding/{id}/email-action` | POST | Approve, revise, send, or skip welcome email |
| `/api/onboarding/{id}/select-slot` | POST | Book a kickoff meeting slot |
| `/api/download/{filename}` | GET | Download a generated report file |

### POST `/api/query`

**Request:**
```json
{
  "query": "Compare revenue across all offices",
  "format": "pdf",
  "conversation_history": [
    {"role": "user", "content": "previous message"},
    {"role": "assistant", "content": "previous response"}
  ]
}
```

**Response:**
```json
{
  "status": "complete",
  "narrative": {
    "executive_summary": "...",
    "detailed_analysis": "...",
    "key_findings": [...],
    "recommendations": [...]
  },
  "file": {
    "name": "report_abc123.pdf",
    "url": "/api/download/report_abc123.pdf",
    "size_kb": 142
  },
  "follow_ups": ["Which office showed the most growth?", "..."],
  "time_ms": 45000,
  "quality_score": 82,
  "iterations": 1
}
```

---

## Pipeline Deep Dive

### Step 1: Query Decomposition

The Finance LLM receives the user's question along with the database schema and 8 few-shot examples. It outputs a structured JSON plan:

```json
{
  "intent": "comparison",
  "data_requirements": [
    {
      "table": "finance.mv_daily_office_profit_loss",
      "columns": ["city", "total_revenue", "total_profit"],
      "filters": {"report_date": {"gte": "2025-10-01", "lte": "2025-12-31"}},
      "group_by": ["city"],
      "aggregate": {"total_revenue": "SUM", "total_profit": "SUM"}
    }
  ]
}
```

### Step 2: Data Fetching

The orchestrator executes each data requirement as a parameterized SQL query. All table names, column names, and aggregates are validated against whitelists. No raw SQL from the LLM ever reaches the database.

### Step 3: Data Analysis

The Finance LLM receives the retrieved data and produces:
- **Narrative**: Executive summary, detailed analysis, key findings (with sentiment tags), recommendations (with priority levels)
- **Coding instructions**: What charts to create, what tables to include, document structure

### Step 4: Document Generation (3-Agent Pipeline)

| Agent | Role |
|-------|------|
| **Coder** | Generates a self-contained Python script using ReportLab/python-pptx/openpyxl |
| **Syntax Checker** | LLM-based review for API misuse, missing imports, common pitfalls |
| **Code Reviewer** | Executes the code, verifies output file exists and is valid |

The pipeline runs up to **2 cycles**. If cycle 1 fails, the reviewer's fix is used for cycle 2.

### Step 5: Quality Evaluation

The orchestrator scores the output on 4 dimensions (each 0-25, total 0-100):

| Dimension | What it measures |
|-----------|-----------------|
| Data Completeness | Were all relevant tables queried? |
| Analysis Depth | Are calculations precise? Trends identified? |
| Visual Quality | Are charts present and varied? |
| Document Quality | Is the report well-structured and formatted? |

If the score is below **70**, the pipeline reruns with improvement feedback (up to 3 iterations). The best-scoring result is returned.

---

## Security

- **No raw LLM SQL**: The LLM outputs structured JSON plans, never SQL. All queries are built server-side with parameterized `psycopg2.sql` identifiers.
- **Table/Column whitelists**: Only 14+ pre-approved tables and their specific columns can be queried. Embedding and vector columns are excluded.
- **Aggregate whitelist**: Only `SUM`, `AVG`, `COUNT`, `MIN`, `MAX` are allowed.
- **Sandboxed execution**: Generated Python scripts run in a subprocess with a configurable timeout (default 60s), restricted to the `generated/` directory.
- **Path traversal prevention**: The download endpoint rejects filenames containing `/`, `\`, or `..`.
- **Connection pooling**: `psycopg2.pool.ThreadedConnectionPool` with 1-10 connections.

---

## Project Structure

```
finance-agent/
├── service.py                  # FastAPI app with all endpoints
├── main.py                     # Startup script (checks + server launch)
├── setup.py                    # DB validation + onboarding table setup
├── requirements.txt            # Python dependencies
├── Dockerfile                  # App container image
├── docker-compose.yml          # Full stack: db + seed + app
├── .env.example                # Environment variable template
├── .gitignore                  # Excludes credentials and generated files
├── .dockerignore               # Excludes unnecessary files from build
│
├── core/
│   ├── config.py               # Loads .env into Config dataclass
│   ├── db.py                   # Database layer (whitelist, query builder, pool)
│   ├── orchestrator.py         # 5-step pipeline with quality loop
│   ├── onboarding_orchestrator.py  # Multi-step onboarding workflow
│   ├── sandbox.py              # Subprocess execution with timeout
│   └── schemas.py              # Pydantic request/response models
│
├── agents/
│   ├── finance_agent.py        # Decompose + Analyze LLM calls
│   ├── coding_agent.py         # 3-agent code gen pipeline
│   ├── syntax_checker.py       # LLM-based syntax review
│   ├── code_reviewer.py        # LLM-based execution review
│   ├── onboarding_agent.py     # Onboarding-specific LLM calls
│   └── prompts.py              # All system prompts + few-shot examples
│
├── onboarding/
│   ├── provisioner.py          # System account provisioning
│   ├── calendar_scheduler.py   # Manager calendar availability
│   ├── email_composer.py       # Welcome email drafting
│   └── doc_generator.py        # Onboarding document generation
│
├── ui/
│   └── index.html              # Single-file web UI (HTML + CSS + JS)
│
├── docker/
│   └── entrypoint.sh           # App container entrypoint
│
├── shipathon_JMD/
│   ├── 00_extensions.sql       # pgvector + schema creation
│   ├── 01_inventory.sql        # Inventory tables + indexes
│   ├── 02_hr.sql               # HR tables + indexes
│   ├── 03_finance.sql          # Finance tables + materialized views
│   └── seed_data.py            # Synthetic data generator
│
└── generated/                  # Runtime output (reports, charts)
```

---

## Configuration

All configuration is via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | *(required)* | Your OpenRouter API key |
| `OPENROUTER_MODEL` | `qwen/qwen3.5-27b` | Model for decomposition and analysis |
| `OPENROUTER_CODING_MODEL` | `qwen/qwen3-coder-next` | Model for code generation |
| `POSTGRES_HOST` | `localhost` / `db` (Docker) | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | *(required)* | PostgreSQL password |
| `POSTGRES_DB` | `postgres` | PostgreSQL database name |
| `SERVER_HOST` | `0.0.0.0` | Server bind address |
| `SERVER_PORT` | `8501` | Server port |
| `SANDBOX_TIMEOUT` | `60` | Max seconds for code execution |
| `GENERATED_DIR` | `./generated` | Directory for generated reports |

---

## License

IIT Delhi Shipathon 2026 project.

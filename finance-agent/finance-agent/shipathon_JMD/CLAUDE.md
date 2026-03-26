# CLAUDE.md — Nasiko RAG Pipeline

## Project overview

Enterprise RAG pipeline deployed on Nasiko (AI agent orchestration platform).
Single PostgreSQL database (Supabase, pgvector enabled) with 3 schemas:
`inventory`, `hr`, `finance`. Three A2A-protocol agents query this database.

**Stack**: Python 3.12+, asyncpg, Supabase PostgreSQL 16 + pgvector,
BGE-M3 embeddings (1024 dimensions), Nasiko A2A agent template.

**Connection**: All agents connect via `DATABASE_URL` environment variable
(Supabase pooler connection string).

---

## Database schema

SQL files are in `sql/` and must be run in order:

1. `sql/00_extensions.sql` — enables pgvector, creates schemas
2. `sql/01_inventory.sql` — 6 tables (products, warehouses, inventory_levels, stock_movements, product_pricing, price_history)
3. `sql/02_hr.sql` — 4 tables (employees, employee_skills, performance_reviews, leave_records)
4. `sql/03_finance.sql` — 2 tables + 2 materialized views (offices, sales_transactions, mv_daily_office_profit_loss, mv_daily_product_revenue)

**Total: 12 tables, 2 materialized views, 5 HNSW vector indexes, 4 GIN full-text indexes.**

---

## Task 1: Generate seed data (`seed_data.py`)

Write a single Python script `seed_data.py` that populates ALL tables with
realistic synthetic data. Use `asyncpg` for database operations and `faker`
for realistic names/addresses.

### Data volumes

| Table | Row count | Notes |
|-------|-----------|-------|
| inventory.products | 500 | 5 categories × ~100 products each |
| inventory.warehouses | 10 | 10 Indian cities |
| inventory.inventory_levels | 5,000 | 500 products × 10 warehouses |
| inventory.stock_movements | 50,000 | ~6 months of daily movements |
| inventory.product_pricing | 500 | 1 per product |
| inventory.price_history | 10,000 | ~20 price changes per product |
| hr.employees | 2,500 | across 8 departments |
| hr.employee_skills | 12,000 | avg 5 skills per employee |
| hr.performance_reviews | 5,000 | 2 reviews per employee |
| hr.leave_records | 8,000 | ~3 leave records per employee |
| finance.offices | 10 | same 10 cities as warehouses |
| finance.sales_transactions | 100,000 | ~6 months daily sales |

### Product categories (for inventory.products)

Use these 5 categories with realistic subcategories:

```
electronics:    smartphones, laptops, tablets, headphones, chargers, smartwatches, cables, speakers, cameras, monitors
clothing:       shirts, trousers, dresses, jackets, shoes, socks, belts, scarves, caps, sunglasses
food_beverages: snacks, beverages, dairy, grains, spices, frozen, canned, bakery, sauces, oils
pharma_health:  painkillers, vitamins, sanitizers, bandages, thermometers, masks, supplements, syrups, creams, drops
home_office:    furniture, stationery, lighting, storage, cleaning, tools, decoration, kitchenware, bedding, curtains
```

### Warehouse / office cities

Use these 10 Indian cities (shared between `inventory.warehouses` and `finance.offices`):

```
Mumbai, Delhi, Bangalore, Hyderabad, Chennai, Pune, Kolkata, Ahmedabad, Jaipur, Lucknow
```

### Employee departments and skills mapping

Generate employees across these 8 departments. Skills must cluster
realistically by department — do NOT randomly assign skills.

```
engineering (30%):      Python, Java, JavaScript, TypeScript, React, Node.js, PostgreSQL, Docker, Kubernetes, AWS, GCP, Git, REST APIs, GraphQL, CI/CD, Redis, MongoDB, System Design, Microservices, Linux
data_science (10%):     Python, R, SQL, TensorFlow, PyTorch, Pandas, NumPy, Scikit-learn, Statistics, Machine Learning, Deep Learning, NLP, Computer Vision, Data Visualization, Spark, Hadoop, Jupyter, A/B Testing
product (10%):          Product Strategy, Roadmapping, User Research, A/B Testing, Jira, Figma, SQL, Data Analysis, Stakeholder Management, Agile, Scrum, PRD Writing, Competitive Analysis, Wireframing
design (8%):            Figma, Sketch, Adobe XD, Illustrator, Photoshop, UI Design, UX Research, Prototyping, Design Systems, Typography, Color Theory, Interaction Design, Accessibility, Motion Design
marketing (12%):        SEO, SEM, Google Analytics, Content Strategy, Copywriting, Social Media, Email Marketing, Marketing Automation, Brand Strategy, PR, Influencer Marketing, CRM, HubSpot, Paid Ads
sales (12%):            CRM, Salesforce, Lead Generation, Cold Calling, Negotiation, Pipeline Management, Account Management, Presentation Skills, Consultative Selling, Revenue Forecasting
hr_admin (8%):          Recruitment, Onboarding, Performance Management, Payroll, Compliance, Employee Engagement, Training, HRIS, Labour Law, Conflict Resolution, Benefits Administration
finance_ops (10%):      Financial Modelling, Excel, SAP, Tally, GST, Accounting, Budgeting, Forecasting, Audit, Tax Planning, Accounts Payable, Accounts Receivable, Cost Analysis, Treasury
```

### Generating embeddings

Use the BGE-M3 model to generate 1024-dimensional embeddings.

**If BGE-M3 is not available locally**, use this fallback approach:
1. Install `sentence-transformers` and use `BAAI/bge-m3` model.
2. OR use OpenAI `text-embedding-3-small` with `dimensions=1024`.
3. OR as a last resort for speed, generate normalised random vectors
   (clearly mark this as placeholder in logs).

**What to embed for each table:**

| Table | Column | Input text to embed |
|-------|--------|---------------------|
| inventory.products | product_name_embedding | `"{product_name}. {product_description}. Category: {category}, {subcategory}"` |
| inventory.product_pricing | pricing_context_embedding | `"{product_name}. Cost: {cost_price}. Selling: {current_selling_price}. Margin: {margin}%. Competitors avg: {competitor_avg}. Elasticity: {elasticity}. Normal day units: {normal_units}. Sale day units: {sale_units}."` |
| hr.employees | employee_profile_embedding | `"{full_name}, {designation} in {department} department at {office_location}. Skills: {comma_separated_skills}"` |
| hr.employee_skills | skill_name_embedding | `"{skill_name} ({skill_category})"` |
| hr.performance_reviews | review_text_embedding | The full `review_text` content directly |

### Realistic data patterns

- **Inventory levels**: 15% of products should be below safety stock. 5% should have zero stock (dead stock). Popular products (electronics) should have higher movement volumes.
- **Stock movements**: Follow a realistic pattern — more outbound than inbound, seasonal spikes in November-December, some adjustment/return movements.
- **Sales transactions**: Follow power-law distribution — 20% of products generate 80% of revenue. Weekend sales should be higher for retail-type products. Set `is_sale_day = true` for ~10% of days (random promotional days).
- **Pricing**: Competitor prices should be within ±15% of our price. Margins should range from 5% (commodities) to 60% (electronics accessories). Elasticity between -0.3 (inelastic staples) and -2.5 (elastic luxury items).
- **Employees**: Salary should correlate with designation seniority and department. Engineering salaries higher than HR/admin. Generate realistic Indian names using Faker with `en_IN` locale.
- **Performance reviews**: Generate realistic 3-5 sentence review text. Ratings should follow normal distribution centered at 3.5 with std 0.7. Reviews should mention specific skills and projects.
- **Leave records**: More casual leave than sick leave. 80% approved, 10% pending, 5% rejected, 5% cancelled.
- **Finance offices**: Capital invested should range from ₹50L (small branch) to ₹5Cr (headquarters). Monthly opex ₹5L to ₹80L. Working capital components should be realistic for the office size.

### Script structure

```python
# seed_data.py
import asyncio
import asyncpg
import os
from faker import Faker

fake = Faker('en_IN')

DATABASE_URL = os.environ["DATABASE_URL"]

async def main():
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)

    # Run SQL schema files first
    await run_schema_files(pool)

    # Seed in dependency order
    await seed_products(pool)
    await seed_warehouses(pool)
    await seed_inventory_levels(pool)
    await seed_stock_movements(pool)
    await seed_product_pricing(pool)
    await seed_price_history(pool)
    await seed_employees(pool)
    await seed_employee_skills(pool)
    await seed_performance_reviews(pool)
    await seed_leave_records(pool)
    await seed_offices(pool)
    await seed_sales_transactions(pool)

    # Refresh materialized views
    await pool.execute("SELECT finance.refresh_all_materialized_views()")

    # Generate and update embeddings
    await generate_all_embeddings(pool)

    await pool.close()
    print("Seeding complete.")

asyncio.run(main())
```

Use `asyncpg.copy_records_to_table()` for bulk inserts (10-100x faster than individual INSERTs).

---

## Task 2: Build 3 agent toolsets

Each agent is a Docker container following Nasiko's A2A protocol template.
Each has a toolset class with async methods that query PostgreSQL.

### Directory structure per agent

```
inventory-agent/
├── src/
│   ├── __init__.py
│   ├── __main__.py                 # Boilerplate from A2A template
│   ├── openai_agent.py             # Boilerplate from A2A template
│   ├── openai_agent_executor.py    # Boilerplate from A2A template
│   └── inventory_toolset.py        # YOUR CODE — tool functions
├── AgentCard.json
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

### Agent 1: Inventory Agent (`inventory_toolset.py`)

Tools to implement:

| Tool function | What it queries | Hybrid search? |
|---------------|-----------------|----------------|
| `get_stock_levels(warehouse_name, category)` | inventory_levels JOIN products JOIN warehouses | No — structured SQL |
| `get_below_safety_stock(warehouse_name)` | inventory_levels WHERE current_quantity < safety_stock_quantity | No — structured SQL |
| `get_reorder_recommendations()` | inventory_levels WHERE current_quantity < reorder_point_quantity | No — structured SQL |
| `get_dead_stock(days_threshold)` | stock_movements — products with zero outbound in N days | No — structured SQL |
| `get_stock_movement_history(product_name, date_range)` | stock_movements JOIN products | No — structured SQL |
| `search_products(query)` | products — hybrid: tsvector keyword + pgvector semantic | **Yes** |
| `get_pricing_analysis(product_name)` | product_pricing JOIN products | No — structured SQL |
| `get_price_comparison(category)` | product_pricing — our price vs competitor prices | No — structured SQL |
| `search_pricing_opportunities(query)` | product_pricing — pgvector semantic search | **Yes** |

**Hybrid search pattern** (use for `search_products` and `search_pricing_opportunities`):

```python
async def search_products(self, query: str) -> str:
    """Search products by name or description using hybrid keyword + semantic search."""
    query_embedding = await self.embed(query)
    pool = await self._get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                stock_keeping_unit,
                product_name,
                category,
                subcategory,
                -- Hybrid score: 60% semantic + 40% keyword
                (0.6 * (1 - (product_name_embedding <=> $1::vector))
                 + 0.4 * COALESCE(ts_rank(full_text_search_vector,
                          websearch_to_tsquery('english', $2)), 0)
                ) AS relevance_score
            FROM inventory.products
            WHERE
                (product_name_embedding <=> $1::vector) < 0.5
                OR full_text_search_vector @@ websearch_to_tsquery('english', $2)
            ORDER BY relevance_score DESC
            LIMIT 15
        """, query_embedding, query)
        # Format and return as string
```

### Agent 2: HR / Skills Agent (`hr_skills_toolset.py`)

Tools to implement:

| Tool function | What it queries | Hybrid search? |
|---------------|-----------------|----------------|
| `find_employees_by_skills(skill_query, location, department)` | employee_skills + employees — hybrid search on skills | **Yes** |
| `get_employee_profile(name_or_email)` | employees LEFT JOIN employee_skills | No — direct lookup |
| `get_department_summary(department)` | employees — headcount, avg tenure, avg salary, skill distribution | No — aggregate SQL |
| `search_performance_reviews(query)` | performance_reviews — pgvector semantic search | **Yes** |
| `get_leave_summary(employee_name, date_range)` | leave_records JOIN employees | No — structured SQL |
| `get_salary_statistics(department, location)` | employees — avg, min, max, median salary | No — aggregate SQL |

**Hybrid skill search pattern** (the most important query):

```python
async def find_employees_by_skills(self, skill_query: str,
                                    location: str = "",
                                    department: str = "") -> str:
    """Find employees matching a skill description.
    Uses hybrid semantic + keyword search across skills,
    then joins to employee profiles."""
    query_embedding = await self.embed(skill_query)
    pool = await self._get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            WITH matched_skills AS (
                SELECT
                    es.employee_id,
                    es.skill_name,
                    es.skill_category,
                    es.proficiency_level,
                    es.years_of_experience,
                    1 - (es.skill_name_embedding <=> $1::vector) AS semantic_score,
                    COALESCE(ts_rank(es.full_text_search_vector,
                             websearch_to_tsquery('english', $2)), 0) AS keyword_score
                FROM hr.employee_skills es
                WHERE
                    (es.skill_name_embedding <=> $1::vector) < 0.5
                    OR es.full_text_search_vector @@ websearch_to_tsquery('english', $2)
            ),
            ranked AS (
                SELECT
                    e.employee_id,
                    e.full_name,
                    e.department,
                    e.designation,
                    e.office_location,
                    MAX(ms.semantic_score * 0.6 + ms.keyword_score * 0.4) AS match_score,
                    array_agg(
                        ms.skill_name || ' (' || ms.proficiency_level || ')'
                        ORDER BY ms.semantic_score DESC
                    ) AS matched_skills
                FROM matched_skills ms
                JOIN hr.employees e ON e.employee_id = ms.employee_id
                WHERE e.is_active = true
                    AND ($3 = '' OR e.office_location ILIKE '%%' || $3 || '%%')
                    AND ($4 = '' OR e.department ILIKE '%%' || $4 || '%%')
                GROUP BY e.employee_id, e.full_name, e.department,
                         e.designation, e.office_location
            )
            SELECT * FROM ranked ORDER BY match_score DESC LIMIT 15
        """, query_embedding, skill_query, location, department)
        # Format and return
```

### Agent 3: Finance Agent (`finance_toolset.py`)

Tools to implement:

| Tool function | What it queries | Hybrid search? |
|---------------|-----------------|----------------|
| `get_office_profit_loss(office_name, date_range)` | mv_daily_office_profit_loss | No — aggregate SQL |
| `compare_offices(metric, date_range)` | mv_daily_office_profit_loss — cross-office comparison | No — aggregate SQL |
| `get_office_financial_summary(office_name)` | offices — capital, opex, working capital | No — direct lookup |
| `get_product_revenue_detail(product_name, office_name, date_range)` | mv_daily_product_revenue | No — aggregate SQL |
| `get_top_products_by_profit(office_name, date_range, limit)` | mv_daily_product_revenue — ranked by profit | No — aggregate SQL |
| `get_sale_day_impact(office_name, date_range)` | mv_daily_product_revenue — sale day vs normal day comparison | No — aggregate SQL |
| `get_working_capital_position(office_name)` | offices — working capital fields | No — direct lookup |

---

## Task 3: AgentCard.json files

Each agent needs an `AgentCard.json` for Nasiko's LangChain router:

### Inventory Agent

```json
{
  "protocolVersion": "0.2.9",
  "name": "Inventory and Pricing Agent",
  "description": "Manages product inventory, stock levels, reorder alerts, pricing analysis, and competitor price tracking across all warehouses and stores.",
  "capabilities": { "streaming": true, "chat_agent": true },
  "skills": [{
    "id": "inventory_pricing",
    "name": "Inventory and Pricing Management",
    "description": "Query stock levels, safety stock alerts, dead stock, reorder recommendations, product search, pricing analysis, competitor price comparison, and margin optimization across all warehouses.",
    "tags": ["inventory", "stock", "warehouse", "pricing", "products", "reorder", "margin", "competitor"],
    "examples": [
      "What products are below safety stock in Mumbai warehouse?",
      "Show me dead stock across all warehouses",
      "Which products have high margins but low competitor pressure?",
      "Compare our pricing vs competitors for electronics",
      "Search for wireless charging products"
    ]
  }]
}
```

### HR Agent

```json
{
  "protocolVersion": "0.2.9",
  "name": "HR and Skills Agent",
  "description": "Manages employee profiles, skill-based search, performance reviews, leave records, salary analytics, and department summaries.",
  "capabilities": { "streaming": true, "chat_agent": true },
  "skills": [{
    "id": "hr_skills",
    "name": "HR and Skills Management",
    "description": "Find employees by skills using semantic search, view profiles, search performance reviews, check leave balances, salary statistics, and department analytics.",
    "tags": ["employees", "skills", "HR", "performance", "salary", "leave", "department"],
    "examples": [
      "Find Python developers with AWS experience in Bangalore",
      "What is the average salary in the engineering department?",
      "Who got praised for leadership in their reviews?",
      "Show leave summary for Priya Sharma",
      "Department summary for data science"
    ]
  }]
}
```

### Finance Agent

```json
{
  "protocolVersion": "0.2.9",
  "name": "Finance and Revenue Agent",
  "description": "Manages office profit and loss, revenue analytics, working capital, capital investment, product-level revenue breakdowns, and sale day impact analysis.",
  "capabilities": { "streaming": true, "chat_agent": true },
  "skills": [{
    "id": "finance_revenue",
    "name": "Finance and Revenue Management",
    "description": "Query daily office P&L, compare offices by revenue or margin, view working capital position, capital invested, product-level revenue with sale day vs normal day breakdown, and top products by profit.",
    "tags": ["finance", "revenue", "profit", "P&L", "office", "working capital", "sales"],
    "examples": [
      "What is the gross margin for the Delhi office this month?",
      "Compare revenue across all offices for last quarter",
      "Show working capital position for Mumbai",
      "Top 10 most profitable products in Bangalore office",
      "How much more do we sell on sale days vs normal days?"
    ]
  }]
}
```

---

## Conventions

- **Commits**: Use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`).
- **Branch naming**: `feat/inventory-agent`, `feat/seed-data`, etc.
- **Python**: Use `async/await` everywhere. Type hints on all functions.
- **SQL**: All table/column names use `snake_case` with full English words (no abbreviations).
- **Embeddings**: BGE-M3 at 1024 dimensions. HNSW indexes with `m=16, ef_construction=64`.
- **Error handling**: Every tool function must have try/except returning a user-friendly error string.
- **Tool docstrings**: Must be detailed — OpenAI uses them to decide when to call each tool.

---

## Deployment

```bash
# Deploy each agent to Nasiko
nasiko agent upload-directory ./inventory-agent --name inventory-pricing
nasiko agent upload-directory ./hr-skills-agent --name hr-skills
nasiko agent upload-directory ./finance-agent --name finance-revenue

# Test routing
curl "http://localhost:9100/router/route?query=what products are below safety stock"
curl "http://localhost:9100/router/route?query=find python developers in bangalore"
curl "http://localhost:9100/router/route?query=gross margin for delhi office"
```

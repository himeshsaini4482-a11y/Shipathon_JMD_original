"""
Finance Agent — Database Validation & Dependency Installer
Run this FIRST: python setup.py

Validates that the postgres database has the required schemas and tables
from the shipathon_JMD database, then installs Python dependencies.
"""
import os
import sys
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "")
DB_NAME = os.getenv("POSTGRES_DB", "postgres")

EXPECTED_SCHEMAS = ["inventory", "hr", "finance"]

EXPECTED_TABLES = {
    "inventory": ["products", "warehouses", "inventory_levels", "stock_movements", "product_pricing", "price_history"],
    "hr": ["employees", "employee_skills", "performance_reviews", "leave_records"],
    "finance": ["offices", "sales_transactions"],
}

EXPECTED_VIEWS = {
    "finance": ["mv_daily_office_profit_loss", "mv_daily_product_revenue"],
}


def install_dependencies():
    req_path = Path(__file__).parent / "requirements.txt"
    if req_path.exists():
        print("\nInstalling Python dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_path)])
        print("Dependencies installed successfully")
    else:
        print("WARNING: requirements.txt not found, skipping dependency install")


def validate_database():
    import psycopg2

    print(f"\n--- Connecting to database '{DB_NAME}' at {DB_HOST}:{DB_PORT} ---")
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER,
            password=DB_PASS, database=DB_NAME,
        )
    except Exception as e:
        print(f"ERROR: Cannot connect to PostgreSQL: {e}")
        print("Make sure PostgreSQL is running and credentials are correct in .env")
        sys.exit(1)
    print("[OK] Connected to PostgreSQL")

    cur = conn.cursor()
    errors = []

    # Check schemas
    print("\n--- Checking schemas ---")
    cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(%s)", (EXPECTED_SCHEMAS,))
    found_schemas = {row[0] for row in cur.fetchall()}
    for schema in EXPECTED_SCHEMAS:
        if schema in found_schemas:
            print(f"  [OK] Schema '{schema}' exists")
        else:
            print(f"  [MISSING] Schema '{schema}' not found")
            errors.append(f"Missing schema: {schema}")

    # Check tables
    print("\n--- Checking tables ---")
    for schema, tables in EXPECTED_TABLES.items():
        if schema not in found_schemas:
            continue
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (schema,),
        )
        found_tables = {row[0] for row in cur.fetchall()}
        for table in tables:
            if table in found_tables:
                cur.execute(f'SELECT count(*) FROM "{schema}"."{table}"')
                count = cur.fetchone()[0]
                print(f"  [OK] {schema}.{table} — {count} rows")
            else:
                print(f"  [MISSING] {schema}.{table}")
                errors.append(f"Missing table: {schema}.{table}")

    # Check materialized views
    print("\n--- Checking materialized views ---")
    for schema, views in EXPECTED_VIEWS.items():
        if schema not in found_schemas:
            continue
        cur.execute(
            "SELECT matviewname FROM pg_matviews WHERE schemaname = %s",
            (schema,),
        )
        found_views = {row[0] for row in cur.fetchall()}
        for view in views:
            if view in found_views:
                cur.execute(f'SELECT count(*) FROM "{schema}"."{view}"')
                count = cur.fetchone()[0]
                print(f"  [OK] {schema}.{view} — {count} rows")
            else:
                print(f"  [MISSING] {schema}.{view}")
                errors.append(f"Missing materialized view: {schema}.{view}")

    cur.close()
    conn.close()

    if errors:
        print(f"\n[WARNING] {len(errors)} issues found:")
        for e in errors:
            print(f"  - {e}")
        print("\nRun the shipathon_JMD SQL files to create missing objects:")
        print("  psql -U postgres -d postgres -f shipathon_JMD/00_extensions.sql")
        print("  psql -U postgres -d postgres -f shipathon_JMD/01_inventory.sql")
        print("  psql -U postgres -d postgres -f shipathon_JMD/02_hr.sql")
        print("  psql -U postgres -d postgres -f shipathon_JMD/03_finance.sql")
        print("Then run: DATABASE_URL=... python shipathon_JMD/seed_data.py")
    else:
        print("\n[OK] All schemas, tables, and views are present")


def ensure_generated_dir():
    generated = Path(__file__).parent / "generated"
    generated.mkdir(exist_ok=True)
    print(f"\n[OK] generated/ directory ready")


def setup_onboarding_tables():
    """Create onboarding schema, tables, indexes, and seed mock data. Idempotent."""
    import psycopg2
    import json
    from datetime import date, datetime, timedelta

    print(f"\n--- Setting up onboarding tables ---")
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER,
            password=DB_PASS, database=DB_NAME,
        )
        conn.autocommit = True
    except Exception as e:
        print(f"ERROR: Cannot connect to PostgreSQL for onboarding setup: {e}")
        return

    cur = conn.cursor()

    # Create schema
    cur.execute("CREATE SCHEMA IF NOT EXISTS onboarding;")
    print("  [OK] Schema 'onboarding' ready")

    # Create tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS onboarding.manager_schedule (
            schedule_id SERIAL PRIMARY KEY,
            manager_email VARCHAR(200) NOT NULL,
            day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            is_available BOOLEAN NOT NULL DEFAULT TRUE,
            block_label VARCHAR(100),
            CONSTRAINT valid_time_range CHECK (end_time > start_time)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_manager_schedule_email ON onboarding.manager_schedule(manager_email);")
    print("  [OK] Table 'onboarding.manager_schedule' ready")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS onboarding.onboarding_records (
            onboarding_id SERIAL PRIMARY KEY,
            employee_name VARCHAR(200) NOT NULL,
            employee_email VARCHAR(200),
            department VARCHAR(100),
            designation VARCHAR(100),
            region VARCHAR(100),
            manager_name VARCHAR(200),
            manager_email VARCHAR(200),
            buddy_name VARCHAR(200),
            buddy_email VARCHAR(200),
            start_date DATE,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            current_step INTEGER NOT NULL DEFAULT 0,
            failed_at_step INTEGER,
            error_message TEXT,
            accounts_provisioned JSONB DEFAULT '[]'::jsonb,
            welcome_email_body TEXT,
            welcome_email_status VARCHAR(30) DEFAULT 'pending',
            welcome_email_sent_at TIMESTAMP,
            kickoff_meeting_time TIMESTAMP,
            kickoff_meeting_attendees JSONB DEFAULT '[]'::jsonb,
            onboarding_doc_path VARCHAR(500),
            created_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_onboarding_status ON onboarding.onboarding_records(status);")
    print("  [OK] Table 'onboarding.onboarding_records' ready")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS onboarding.email_drafts (
            draft_id SERIAL PRIMARY KEY,
            onboarding_id INTEGER REFERENCES onboarding.onboarding_records(onboarding_id),
            draft_number INTEGER NOT NULL DEFAULT 1,
            email_body TEXT NOT NULL,
            manager_feedback TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_email_drafts_onboarding ON onboarding.email_drafts(onboarding_id);")
    print("  [OK] Table 'onboarding.email_drafts' ready")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS onboarding.system_accounts (
            account_id SERIAL PRIMARY KEY,
            onboarding_id INTEGER REFERENCES onboarding.onboarding_records(onboarding_id),
            system_name VARCHAR(100) NOT NULL,
            account_identifier VARCHAR(200),
            status VARCHAR(30) DEFAULT 'active',
            provisioned_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_system_accounts_onboarding ON onboarding.system_accounts(onboarding_id);")
    print("  [OK] Table 'onboarding.system_accounts' ready")

    # Check if mock data already exists
    cur.execute("SELECT COUNT(*) FROM onboarding.onboarding_records")
    count = cur.fetchone()[0]
    if count > 0:
        print(f"  [SKIP] Mock data already exists ({count} onboarding records)")
        cur.close()
        conn.close()
        return

    print("\n--- Seeding onboarding mock data ---")

    # ── Get 5 managers from hr.employees ──
    cur.execute("""
        SELECT employee_id, full_name, email_address, department
        FROM hr.employees
        WHERE designation IN ('Lead', 'Principal', 'Director') AND is_active = true
        ORDER BY employee_id
        LIMIT 5
    """)
    managers = cur.fetchall()
    if not managers:
        print("  [WARN] No managers found in hr.employees, using placeholder data")
        managers = [
            (1, "Priya Mehta", "priya.mehta@horizon.com", "engineering"),
            (2, "Rahul Sharma", "rahul.sharma@horizon.com", "data_science"),
            (3, "Ananya Gupta", "ananya.gupta@horizon.com", "design"),
            (4, "Vikram Singh", "vikram.singh@horizon.com", "marketing"),
            (5, "Sneha Patel", "sneha.patel@horizon.com", "sales"),
        ]

    # ── Insert manager schedules ──
    # Weekly schedule pattern for each manager
    schedule_pattern = [
        # Monday (day 0)
        (0, "09:00", "09:30", False, "Team standup"),
        (0, "09:30", "12:00", True, None),
        (0, "12:00", "13:00", False, "Lunch"),
        (0, "13:00", "15:00", True, None),
        (0, "15:00", "16:00", False, "1:1s"),
        (0, "16:00", "18:00", True, None),
        # Tuesday (day 1)
        (1, "09:00", "12:00", True, None),
        (1, "12:00", "13:00", False, "Lunch"),
        (1, "13:00", "18:00", True, None),
        # Wednesday (day 2)
        (2, "09:00", "10:00", False, "All-hands"),
        (2, "10:00", "12:00", True, None),
        (2, "12:00", "13:00", False, "Lunch"),
        (2, "13:00", "18:00", True, None),
        # Thursday (day 3)
        (3, "09:00", "12:00", True, None),
        (3, "12:00", "13:00", False, "Lunch"),
        (3, "13:00", "15:00", True, None),
        (3, "15:00", "17:00", False, "Sprint review"),
        (3, "17:00", "18:00", True, None),
        # Friday (day 4)
        (4, "09:00", "12:00", True, None),
        (4, "12:00", "13:00", False, "Lunch"),
        (4, "13:00", "16:00", True, None),
        (4, "16:00", "18:00", False, "Team social"),
        # Saturday (day 5) — all busy
        (5, "09:00", "18:00", False, "Weekend"),
        # Sunday (day 6) — all busy
        (6, "09:00", "18:00", False, "Weekend"),
    ]

    for mgr in managers:
        mgr_email = mgr[2] or f"{mgr[1].lower().replace(' ', '.')}@horizon.com"
        for day, start, end, avail, label in schedule_pattern:
            cur.execute("""
                INSERT INTO onboarding.manager_schedule (manager_email, day_of_week, start_time, end_time, is_available, block_label)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (mgr_email, day, start, end, avail, label))
    print(f"  [OK] Inserted schedules for {len(managers)} managers")

    # ── Department → systems mapping ──
    dept_systems = {
        "engineering": ["email", "slack", "github", "jira", "confluence"],
        "data_science": ["email", "slack", "github", "jira", "jupyter"],
        "design": ["email", "slack", "figma", "jira", "confluence"],
        "marketing": ["email", "slack", "hubspot", "canva", "analytics"],
        "sales": ["email", "slack", "hubspot", "crm", "analytics"],
        "finance_ops": ["email", "slack", "erp", "jira"],
        "hr_admin": ["email", "slack", "hrms", "jira"],
        "product": ["email", "slack", "jira", "confluence", "figma"],
    }

    # ── Onboarding records ──
    employees_data = [
        # 5 completed
        ("Arjun Nair", "arjun.nair@horizon.com", "engineering", "Senior Associate", "Mumbai", "complete", 6),
        ("Kavita Reddy", "kavita.reddy@horizon.com", "data_science", "Associate", "Bangalore", "complete", 6),
        ("Rohan Das", "rohan.das@horizon.com", "design", "Junior Associate", "Kolkata", "complete", 6),
        ("Meera Iyer", "meera.iyer@horizon.com", "marketing", "Associate", "Chennai", "complete", 6),
        ("Aditya Joshi", "aditya.joshi@horizon.com", "sales", "Senior Associate", "Pune", "complete", 6),
        # 3 in-progress
        ("Neha Kapoor", "neha.kapoor@horizon.com", "engineering", "Associate", "Delhi", "email_reviewed", 2),
        ("Siddharth Malhotra", "siddharth.malhotra@horizon.com", "product", "Senior Associate", "Mumbai", "scheduled", 3),
        ("Pooja Bhatt", "pooja.bhatt@horizon.com", "finance_ops", "Junior Associate", "Hyderabad", "doc_generated", 4),
        # 2 failed
        ("Raj Kumar", "raj.kumar@horizon.com", "hr_admin", "Associate", "Delhi", "failed", 2),
        ("Deepa Menon", "deepa.menon@horizon.com", "data_science", "Senior Associate", "Bangalore", "failed", 5),
        # 5 pending
        ("Amit Trivedi", "amit.trivedi@horizon.com", "engineering", "Intern", "Mumbai", "pending", 0),
        ("Shreya Ghosh", "shreya.ghosh@horizon.com", "design", "Junior Associate", "Kolkata", "pending", 0),
        ("Varun Khanna", "varun.khanna@horizon.com", "sales", "Associate", "Delhi", "pending", 0),
        ("Priyanka Sen", "priyanka.sen@horizon.com", "marketing", "Intern", "Chennai", "pending", 0),
        ("Karthik Rajan", "karthik.rajan@horizon.com", "product", "Associate", "Bangalore", "pending", 0),
    ]

    onboarding_ids = []
    for i, (name, email, dept, desg, region, status, step) in enumerate(employees_data):
        mgr = managers[i % len(managers)]
        mgr_name = mgr[1]
        mgr_email = mgr[2] or f"{mgr[1].lower().replace(' ', '.')}@horizon.com"
        buddy_name = managers[(i + 1) % len(managers)][1]
        buddy_email = managers[(i + 1) % len(managers)][2] or f"{buddy_name.lower().replace(' ', '.')}@horizon.com"

        start_dt = date(2026, 3, 1) + timedelta(days=i * 3)
        completed_at = (datetime(2026, 3, 10) + timedelta(days=i * 2)) if status == "complete" else None
        failed_step = None
        error_msg = None
        email_status = "pending"
        accounts_json = "[]"

        if status == "complete":
            email_status = "sent"
            systems = dept_systems.get(dept, ["email", "slack"])
            accts = [{"system": s, "account_id": f"{name.split()[0].lower()}.{name.split()[-1].lower()}@{s}.horizon.com"} for s in systems]
            accounts_json = json.dumps(accts)
        elif status in ("email_reviewed", "scheduled", "doc_generated"):
            email_status = "sent"
            systems = dept_systems.get(dept, ["email", "slack"])
            accts = [{"system": s, "account_id": f"{name.split()[0].lower()}.{name.split()[-1].lower()}@{s}.horizon.com"} for s in systems]
            accounts_json = json.dumps(accts)
        elif status == "failed":
            if step == 2:
                failed_step = 2
                error_msg = "SMTP timeout"
            else:
                failed_step = 5
                error_msg = "PDF generation failed"
            systems = dept_systems.get(dept, ["email", "slack"])
            accts = [{"system": s, "account_id": f"{name.split()[0].lower()}.{name.split()[-1].lower()}@{s}.horizon.com"} for s in systems]
            accounts_json = json.dumps(accts)

        meeting_time = None
        if status in ("complete", "scheduled", "doc_generated"):
            meeting_time = datetime(2026, 3, 15, 10, 0) + timedelta(days=i)

        doc_path = None
        if status in ("complete", "doc_generated"):
            doc_path = f"generated/onboarding_{name.lower().replace(' ', '_')}.pdf"

        cur.execute("""
            INSERT INTO onboarding.onboarding_records
            (employee_name, employee_email, department, designation, region,
             manager_name, manager_email, buddy_name, buddy_email, start_date,
             status, current_step, failed_at_step, error_message,
             accounts_provisioned, welcome_email_status,
             kickoff_meeting_time, onboarding_doc_path, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING onboarding_id
        """, (name, email, dept, desg, region,
              mgr_name, mgr_email, buddy_name, buddy_email, start_dt,
              status, step, failed_step, error_msg,
              accounts_json, email_status,
              meeting_time, doc_path, completed_at))
        oid = cur.fetchone()[0]
        onboarding_ids.append((oid, name, email, dept, status, step))

    print(f"  [OK] Inserted {len(employees_data)} onboarding records")

    # ── System accounts for completed + in-progress + failed ──
    acct_count = 0
    for oid, name, email, dept, status, step in onboarding_ids:
        if status in ("pending",):
            continue
        systems = dept_systems.get(dept, ["email", "slack"])
        first = name.split()[0].lower()
        last = name.split()[-1].lower()
        for sys_name in systems:
            if sys_name == "email":
                acct_id = f"{first}.{last}@horizon.com"
            elif sys_name == "slack":
                acct_id = f"@{first}.{last}"
            elif sys_name == "github":
                acct_id = f"github.com/{first}-{last}"
            else:
                acct_id = f"{first}.{last}@{sys_name}.horizon.com"
            cur.execute("""
                INSERT INTO onboarding.system_accounts (onboarding_id, system_name, account_identifier)
                VALUES (%s, %s, %s)
            """, (oid, sys_name, acct_id))
            acct_count += 1
    print(f"  [OK] Inserted {acct_count} system accounts")

    # ── Email drafts for completed onboardings ──
    draft_count = 0
    for oid, name, email, dept, status, step in onboarding_ids:
        if status != "complete":
            continue
        first = name.split()[0]
        # Draft 1
        cur.execute("""
            INSERT INTO onboarding.email_drafts (onboarding_id, draft_number, email_body)
            VALUES (%s, 1, %s)
        """, (oid, f"Dear {first},\n\nWelcome to Horizon! We are thrilled to have you join our {dept} team. Your start date is confirmed and we look forward to seeing you.\n\nBest regards,\nHR Team"))
        draft_count += 1
        # Draft 2 (revision) for some
        if draft_count % 2 == 0:
            cur.execute("""
                INSERT INTO onboarding.email_drafts (onboarding_id, draft_number, email_body, manager_feedback)
                VALUES (%s, 2, %s, %s)
            """, (oid,
                  f"Dear {first},\n\nWelcome aboard to Horizon's {dept} team! We are excited to have you join us. Your buddy and manager will be reaching out shortly to help you get started.\n\nWarm regards,\nHR Team",
                  "Make it more warm and mention the buddy"))
            draft_count += 1
    print(f"  [OK] Inserted {draft_count} email drafts")

    cur.close()
    conn.close()
    print("  [OK] Onboarding setup complete")


def main():
    print("=" * 50)
    print("  Finance Agent — Setup & Validation")
    print("=" * 50)

    install_dependencies()
    validate_database()
    setup_onboarding_tables()
    ensure_generated_dir()

    print("\n" + "=" * 50)
    print("  Setup Complete!")
    print("=" * 50)
    print("\nRun 'python main.py' to start the server.")


if __name__ == "__main__":
    main()

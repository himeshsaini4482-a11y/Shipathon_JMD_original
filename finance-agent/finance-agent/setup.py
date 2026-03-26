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


def main():
    print("=" * 50)
    print("  Finance Agent — Setup & Validation")
    print("=" * 50)

    install_dependencies()
    validate_database()
    ensure_generated_dir()

    print("\n" + "=" * 50)
    print("  Setup Complete!")
    print("=" * 50)
    print("\nRun 'python main.py' to start the server.")


if __name__ == "__main__":
    main()

import logging
import time
import psycopg2
from psycopg2 import sql, pool
from core.config import config

log = logging.getLogger("db")

# ---------------------------------------------------------------------------
# Whitelists — schema-qualified table names → allowed columns
# Embedding and tsvector columns are excluded (not useful for structured queries)
# ---------------------------------------------------------------------------
ALLOWED_COLUMNS = {
    # ── inventory schema ──
    "inventory.products": [
        "product_id", "stock_keeping_unit", "product_name", "product_description",
        "category", "subcategory", "unit_of_measure", "is_active", "created_at",
    ],
    "inventory.warehouses": [
        "warehouse_id", "warehouse_name", "city", "state",
        "warehouse_type", "capacity_square_feet",
    ],
    "inventory.inventory_levels": [
        "product_id", "warehouse_id", "current_quantity", "safety_stock_quantity",
        "reorder_point_quantity", "reorder_order_quantity", "maximum_stock_quantity",
        "last_updated_at",
    ],
    "inventory.stock_movements": [
        "movement_id", "product_id", "warehouse_id", "movement_type", "quantity",
        "reference_identifier", "unit_cost_at_movement", "moved_at",
    ],
    "inventory.product_pricing": [
        "pricing_id", "product_id", "cost_price_per_unit", "base_selling_price_per_unit",
        "current_selling_price_per_unit", "floor_price_per_unit", "ceiling_price_per_unit",
        "margin_percentage", "competitor_minimum_price", "competitor_maximum_price",
        "competitor_average_price", "number_of_competitors_tracked",
        "last_competitor_check_date", "demand_elasticity_coefficient",
        "average_daily_units_normal_day", "average_daily_units_sale_day",
        "typical_sale_discount_price", "last_sale_event_date", "updated_at",
    ],
    "inventory.price_history": [
        "history_id", "product_id", "price_amount", "price_type", "recorded_at",
    ],
    # ── hr schema ──
    "hr.employees": [
        "employee_id", "full_name", "email_address", "phone_number", "department",
        "designation", "office_location", "date_of_joining", "is_active",
        "base_salary_amount", "salary_currency", "pay_band",
        "last_salary_revision_date", "created_at",
    ],
    "hr.employee_skills": [
        "employee_skill_id", "employee_id", "skill_name", "skill_category",
        "proficiency_level", "years_of_experience", "last_used_date",
    ],
    "hr.performance_reviews": [
        "review_id", "employee_id", "review_period", "reviewer_name",
        "rating_score", "review_text", "created_at",
    ],
    "hr.leave_records": [
        "leave_record_id", "employee_id", "leave_type", "start_date",
        "end_date", "approval_status",
    ],
    # ── finance schema ──
    "finance.offices": [
        "office_id", "office_name", "city", "state", "office_type", "date_opened",
        "operational_status", "one_time_capital_invested", "monthly_operating_expense",
        "operating_expense_period_month", "accounts_receivable_amount",
        "inventory_value_amount", "cash_on_hand_amount", "accounts_payable_amount",
        "net_working_capital", "working_capital_period_month", "last_updated_at",
    ],
    "finance.sales_transactions": [
        "transaction_id", "office_id", "product_id", "customer_name", "quantity_sold",
        "cost_price_per_unit", "selling_price_per_unit", "total_selling_amount",
        "total_cost_amount", "discount_amount", "profit_amount", "payment_method",
        "is_sale_day", "transaction_date", "created_at",
    ],
    "finance.mv_daily_office_profit_loss": [
        "date", "office_id", "office_name", "city", "gross_revenue",
        "total_discounts", "net_revenue", "total_cost_of_goods_sold",
        "gross_profit", "gross_margin_percentage", "total_transaction_count",
        "total_units_sold", "units_sold_on_sale_days", "units_sold_on_normal_days",
        "estimated_daily_operating_expense",
    ],
    "finance.mv_daily_product_revenue": [
        "date", "office_id", "office_name", "office_city", "product_id",
        "stock_keeping_unit", "product_name", "product_category",
        "product_subcategory", "cost_price_per_unit", "selling_price_per_unit",
        "average_profit_per_unit", "total_units_sold", "number_of_transactions",
        "gross_sales_amount", "total_discount_amount", "net_sales_amount",
        "total_cost_amount", "total_profit_amount", "profit_margin_percentage",
        "had_sale_event", "units_sold_on_sale_days", "units_sold_on_normal_days",
        "profit_on_sale_days", "profit_on_normal_days",
        "units_currently_in_inventory", "safety_stock_quantity",
        "is_below_safety_stock",
    ],
}

ALLOWED_AGGREGATES = ["SUM", "AVG", "COUNT", "MIN", "MAX"]
ALLOWED_TABLES = list(ALLOWED_COLUMNS.keys())

# Operator mapping for range filters
_FILTER_OPERATORS = {
    "eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
}

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        log.info("[DB] Creating connection pool (host=%s, port=%s, db=%s)",
                 config.postgres_host, config.postgres_port, config.postgres_db)
        _pool = pool.ThreadedConnectionPool(
            1, 10,
            host=config.postgres_host,
            port=config.postgres_port,
            user=config.postgres_user,
            password=config.postgres_password,
            database=config.postgres_db,
        )
    return _pool


def get_connection():
    return get_pool().getconn()


def put_connection(conn):
    get_pool().putconn(conn)


def _is_wildcard(val) -> bool:
    """Check if a filter value means 'all' (i.e. no filter needed)."""
    if isinstance(val, list):
        return any(v is None or str(v).upper() in ("ALL", "*", "", "NONE") for v in val)
    if val is None:
        return True
    if isinstance(val, str) and val.upper() in ("ALL", "*", "", "NONE"):
        return True
    return False


def _table_identifier(table: str) -> sql.Composable:
    """Convert 'schema.table' to sql.Identifier('schema', 'table')."""
    parts = table.split(".", 1)
    if len(parts) == 2:
        return sql.Identifier(parts[0], parts[1])
    return sql.Identifier(parts[0])


def _coerce_bool(val):
    """Coerce string booleans to Python bool."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _build_where_clause(table: str, filters: dict, allowed: list[str]):
    """Build WHERE clauses from a generic filters dict.

    Filter keys are column names. Values can be:
    - scalar: equality (col = val)
    - list: IN (col IN (val1, val2, ...))
    - dict with operator keys: range ({gte: X, lte: Y} → col >= X AND col <= Y)
    """
    where_clauses = []
    params = []

    if not filters:
        return where_clauses, params

    for col, val in filters.items():
        # Drop filters on columns not in this table
        if col not in allowed:
            log.info("[DB]   Dropping filter on '%s' — not in allowed columns for '%s'", col, table)
            continue

        if val is None:
            continue

        # Dict with operators: {"gte": "2025-01-01", "lte": "2025-03-31"}
        if isinstance(val, dict):
            for op_key, op_val in val.items():
                sql_op = _FILTER_OPERATORS.get(op_key)
                if sql_op and op_val is not None:
                    where_clauses.append(
                        sql.SQL("{col} {op} {ph}").format(
                            col=sql.Identifier(col),
                            op=sql.SQL(sql_op),
                            ph=sql.Placeholder(),
                        )
                    )
                    params.append(op_val)
                else:
                    log.info("[DB]   Dropping unknown operator '%s' for column '%s'", op_key, col)
            continue

        # Boolean columns — coerce and use equality
        if isinstance(val, bool) or (isinstance(val, str) and val.lower() in ("true", "false")):
            where_clauses.append(
                sql.SQL("{} = {}").format(sql.Identifier(col), sql.Placeholder())
            )
            params.append(_coerce_bool(val))
            continue

        # List: IN clause
        if isinstance(val, list):
            # Filter out wildcard values
            clean = [v for v in val if not _is_wildcard(v)]
            if not clean:
                continue
            placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(clean))
            where_clauses.append(
                sql.SQL("{} IN ({})").format(sql.Identifier(col), placeholders)
            )
            params.extend(clean)
            continue

        # Scalar: equality
        if _is_wildcard(val):
            continue
        where_clauses.append(
            sql.SQL("{} = {}").format(sql.Identifier(col), sql.Placeholder())
        )
        params.append(val)

    return where_clauses, params


def execute_query(table: str, columns: list[str], filters: dict = None,
                  group_by: list[str] = None, order_by: str = None,
                  aggregate: dict = None) -> dict:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid table: {table}")

    allowed = ALLOWED_COLUMNS[table]

    # Sanitize columns — drop any that don't exist on this table
    original_columns = columns
    columns = [c for c in columns if c in allowed]
    dropped_cols = set(original_columns) - set(columns)
    if dropped_cols:
        log.info("[DB]   Dropping invalid columns for '%s': %s", table, dropped_cols)
    if not columns:
        columns = list(allowed)
        log.info("[DB]   No valid columns left, falling back to all: %s", columns)

    # Sanitize group_by
    if group_by:
        group_by = [c for c in group_by if c in allowed]
        if not group_by:
            group_by = None

    # Sanitize aggregates
    if aggregate:
        aggregate = {c: f for c, f in aggregate.items() if c in allowed and f.upper() in ALLOWED_AGGREGATES}
        if not aggregate:
            aggregate = None

    log.info("[DB] Building query: table=%s, columns=%s", table, columns)
    if filters:
        log.info("[DB]   Filters: %s", filters)
    if group_by:
        log.info("[DB]   Group by: %s", group_by)
    if aggregate:
        log.info("[DB]   Aggregates: %s", aggregate)
    if order_by:
        log.info("[DB]   Order by: %s", order_by)

    # When group_by is present, ensure all non-aggregated columns are in group_by
    agg_cols = set(aggregate.keys()) if aggregate else set()
    if group_by:
        extra = [c for c in columns if c not in group_by and c not in agg_cols]
        if extra:
            log.info("[DB]   Auto-adding columns to GROUP BY: %s", extra)
            group_by = list(group_by) + extra

    # Build SELECT clause
    select_parts = []
    if aggregate and group_by:
        for col in group_by:
            select_parts.append(sql.Identifier(col))
        for col, func in aggregate.items():
            agg_sql = sql.SQL("{func}({col})").format(
                func=sql.SQL(func.upper()),
                col=sql.Identifier(col),
            )
            select_parts.append(sql.SQL("{} AS {}").format(agg_sql, sql.Identifier(f"{func.lower()}_{col}")))
    elif group_by and not aggregate:
        log.info("[DB]   GROUP BY without aggregates — ignoring GROUP BY")
        group_by = None
        for col in columns:
            select_parts.append(sql.Identifier(col))
    else:
        for col in columns:
            select_parts.append(sql.Identifier(col))

    query = sql.SQL("SELECT {fields} FROM {table}").format(
        fields=sql.SQL(", ").join(select_parts),
        table=_table_identifier(table),
    )

    # Build WHERE clause using generic filter builder
    where_clauses, params = _build_where_clause(table, filters or {}, allowed)

    if where_clauses:
        query = sql.SQL("{} WHERE {}").format(query, sql.SQL(" AND ").join(where_clauses))

    # GROUP BY
    if group_by:
        group_parts = [sql.Identifier(col) for col in group_by]
        query = sql.SQL("{} GROUP BY {}").format(query, sql.SQL(", ").join(group_parts))

    # ORDER BY
    if order_by:
        parts = order_by.strip().split()
        order_col = parts[0]
        direction = parts[1].upper() if len(parts) > 1 else "ASC"
        if direction not in ("ASC", "DESC"):
            direction = "ASC"

        # If ordering by a column that is being aggregated, use the aggregate alias
        if aggregate and order_col in aggregate:
            alias = f"{aggregate[order_col].lower()}_{order_col}"
            log.info("[DB]   ORDER BY rewritten: %s -> %s (aggregate alias)", order_col, alias)
            order_col = alias

        if aggregate and any(f"{f.lower()}_{c}" == order_col for c, f in aggregate.items()):
            query = sql.SQL("{} ORDER BY {} {}").format(query, sql.Identifier(order_col), sql.SQL(direction))
        elif order_col in allowed:
            query = sql.SQL("{} ORDER BY {} {}").format(query, sql.Identifier(order_col), sql.SQL(direction))

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            compiled = query.as_string(conn)
            log.info("[DB] Executing: %s", compiled)
            log.info("[DB] Params: %s", params)

            t0 = time.time()
            cur.execute(query, params)
            elapsed = (time.time() - t0) * 1000

            col_names = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            log.info("[DB] Query returned %d rows in %.1fms (columns: %s)", len(rows), elapsed, col_names)

            data = []
            for row in rows:
                record = {}
                for i, val in enumerate(row):
                    v = val
                    if hasattr(val, "isoformat"):
                        v = val.isoformat()
                    elif isinstance(val, (int, float, str, bool, type(None))):
                        v = val
                    else:
                        v = float(val) if val is not None else None
                    record[col_names[i]] = v
                data.append(record)
            return {"columns": col_names, "data": data}
    finally:
        put_connection(conn)

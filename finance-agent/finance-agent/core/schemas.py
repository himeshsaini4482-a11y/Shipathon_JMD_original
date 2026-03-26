from pydantic import BaseModel
from typing import Literal


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class QueryRequest(BaseModel):
    query: str
    format: str = "auto"
    conversation_history: list[ConversationTurn] = []


class DataRequirement(BaseModel):
    req_id: str
    table: Literal[
        "inventory.products", "inventory.warehouses", "inventory.inventory_levels",
        "inventory.stock_movements", "inventory.product_pricing", "inventory.price_history",
        "hr.employees", "hr.employee_skills", "hr.performance_reviews", "hr.leave_records",
        "finance.offices", "finance.sales_transactions",
        "finance.mv_daily_office_profit_loss", "finance.mv_daily_product_revenue",
    ]
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
    detailed_analysis: str = ""
    key_findings: list[Finding]
    recommendations: list[Recommendation]
    caveats: list[str] = []


class PipelineResponse(BaseModel):
    query_id: str
    status: Literal["complete", "error"]
    narrative: Narrative | None = None
    file: dict | None = None
    follow_ups: list[str] = []
    time_ms: int = 0
    error: str | None = None

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SheetInfo(BaseModel):
    name: str


class InspectResponse(BaseModel):
    filename: str
    sheets: list[SheetInfo]


class DatasetMetadata(BaseModel):
    id: str
    name: str
    source_type: Literal["csv", "excel"]
    sheet_name: str | None = None
    rows: int
    columns: int
    created_at: datetime
    updated_at: datetime | None = None
    current_version: int = 0
    storage_format: str = "parquet"
    status: str = "ready"
    last_analyzed_at: datetime | None = None
    workspace_id: str | None = None
    uploader_user_id: str | None = None
    storage_bytes: int = 0


class DatasetRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ColumnProfile(BaseModel):
    name: str
    data_type: str
    category: Literal["numeric", "categorical", "date", "boolean"]
    missing_count: int
    missing_percentage: float
    unique_count: int
    physical_type: Literal["number", "integer", "string", "datetime", "boolean"] = "string"
    semantic_role: Literal["measure", "categorical_dimension", "temporal_dimension", "identifier", "high_cardinality_dimension", "boolean_dimension", "unknown"] = "unknown"
    temporal_helper: Literal["month", "quarter", "week", "day"] | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    allowed_aggregations: list[str] = Field(default_factory=list)
    uniqueness_ratio: float = 0
    minimum: Any | None = None
    maximum: Any | None = None
    mean: float | None = None
    median: float | None = None
    sum: float | None = None
    standard_deviation: float | None = None


class DatasetProfile(BaseModel):
    dataset_id: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    numeric_columns: list[str]
    categorical_columns: list[str]
    date_columns: list[str]
    measure_columns: list[str] = Field(default_factory=list)
    dimension_columns: list[str] = Field(default_factory=list)
    missing_values: int
    duplicate_rows: int
    date_range: dict[str, str] | None = None


FilterOperator = Literal[
    "equals", "not_equals", "greater_than", "greater_than_or_equal",
    "less_than", "less_than_or_equal", "contains", "starts_with",
    "ends_with", "between", "in", "not_in", "before", "after",
    "is_null", "is_not_null", "not_contains",
]


class FilterCondition(BaseModel):
    column: str
    operator: FilterOperator
    value: Any = None

    @model_validator(mode="after")
    def validate_value_shape(self) -> "FilterCondition":
        if self.operator in {"between", "in", "not_in"} and not isinstance(self.value, list):
            raise ValueError(f"Filter '{self.operator}' requires a list value")
        if self.operator == "between" and len(self.value) != 2:
            raise ValueError("Between requires exactly two values")
        return self


Operation = Literal[
    "aggregate", "group_and_aggregate", "filter", "sort", "top_n",
    "bottom_n", "count", "distinct_count", "trend", "compare_groups",
    "compare_periods", "percent_of_total", "rank", "running_total",
    "percentage_change", "contribution", "moving_average", "variance",
    "correlation", "consecutive_growth", "consecutive_decline",
    "compare_segments", "pipeline",
]
Aggregation = Literal["sum", "mean", "min", "max", "count", "median"]


RelativePeriod = Literal[
    "today", "yesterday", "this_week", "previous_week", "this_month",
    "previous_month", "last_3_months", "last_6_months", "last_12_months",
    "this_quarter", "previous_quarter", "this_year", "previous_year",
]


class DateFilter(BaseModel):
    column: str
    period: RelativePeriod


class SortRule(BaseModel):
    column: str
    direction: Literal["asc", "desc"] = "asc"


class PipelineStep(BaseModel):
    operation: Literal["trend", "calculate_change", "consecutive_growth", "consecutive_decline", "rank", "moving_average"]
    metric: str | None = None
    group_by: list[str] = Field(default_factory=list)
    date_column: str | None = None
    time_granularity: Literal["day", "week", "month", "quarter", "year"] | None = None
    periods: int = Field(default=3, ge=1, le=24)
    window: int = Field(default=3, ge=2, le=24)


class AnalysisPlan(BaseModel):
    operation: Operation
    metric: str | None = None
    aggregation: Aggregation | None = None
    group_by: list[str] = Field(default_factory=list)
    filters: list[FilterCondition] = Field(default_factory=list)
    sort: Literal["asc", "desc"] | list[SortRule] | None = None
    limit: int = Field(default=10, ge=1, le=100)
    date_column: str | None = None
    time_granularity: Literal["day", "week", "month", "quarter", "year"] | None = None
    compare_values: list[str] = Field(default_factory=list, max_length=20)
    period_mode: Literal["month", "quarter", "year"] | None = None
    date_filter: DateFilter | None = None
    secondary_metric: str | None = None
    secondary_aggregation: Aggregation | None = None
    partition_by: list[str] = Field(default_factory=list)
    window: int = Field(default=3, ge=2, le=24)
    periods: int = Field(default=3, ge=1, le=24)
    steps: list[PipelineStep] = Field(default_factory=list, max_length=10)

    @field_validator("group_by", mode="before")
    @classmethod
    def normalize_group_by(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return [value] if isinstance(value, str) else value

    @field_validator("aggregation", mode="before")
    @classmethod
    def normalize_average(cls, value: Any) -> Any:
        return "mean" if value == "average" else value


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    session_id: str | None = None


class ChartSuggestion(BaseModel):
    type: Literal["bar", "column", "line", "pie", "scatter"]


class AskResponse(BaseModel):
    question: str
    plan: AnalysisPlan
    answer: str
    result: Any
    chart_suggestion: ChartSuggestion | None = None
    explanation: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class Insight(BaseModel):
    type: str
    severity: Literal["info", "warning", "critical"]
    title: str
    description: str
    metric: str | None = None
    value: float | int | str | None = None


class ChartRequest(BaseModel):
    question: str | None = Field(default=None, min_length=2, max_length=500)
    plan: AnalysisPlan | None = None
    chart_type: Literal["bar", "column", "line", "pie", "scatter"] | None = None
    title: str | None = Field(default=None, max_length=120)
    x_axis_label: str | None = Field(default=None, max_length=80)
    y_axis_label: str | None = Field(default=None, max_length=80)
    show_legend: bool = True
    drill_down: FilterCondition | None = None

    @model_validator(mode="after")
    def require_question_or_plan(self) -> "ChartRequest":
        if not self.question and not self.plan:
            raise ValueError("A chart question or query plan is required")
        return self


class ChartResponse(BaseModel):
    type: Literal["bar", "column", "line", "pie", "scatter"]
    title: str
    x_axis: str
    y_axis: str
    data: list[dict[str, Any]]
    plan: AnalysisPlan
    interpreted_request: str
    show_legend: bool = True
    drill_down: dict[str, Any] | None = None
    x_axis_label: str | None = None
    y_axis_label: str | None = None
    tooltip_label: str | None = None
    interpretation: dict[str, Any] = Field(default_factory=dict)
    recommended_chart_type: Literal["bar", "column", "line", "pie", "scatter"]
    selected_chart_type: Literal["bar", "column", "line", "pie", "scatter"]


class QualityIssue(BaseModel):
    issue_type: str
    column: str | None = None
    count: int
    examples: list[str] = Field(default_factory=list)
    severity: Literal["info", "warning", "critical"] = "warning"
    confidence: Literal["low", "medium", "high"] = "medium"
    message: str | None = None


CleaningType = Literal[
    "remove_duplicates", "trim_whitespace", "standardize_lowercase",
    "standardize_uppercase", "standardize_titlecase", "remove_missing_rows",
    "fill_missing_mean", "fill_missing_median", "fill_missing_value",
]


class CleaningOperation(BaseModel):
    type: CleaningType
    column: str | None = None
    value: Any | None = None


class CleaningRequest(BaseModel):
    operations: list[CleaningOperation] = Field(min_length=1, max_length=20)
    confirmed: bool = False


class CleaningChange(BaseModel):
    operation: CleaningOperation
    affected_rows: int
    affected_cells: int
    before_examples: list[str] = Field(default_factory=list)
    after_examples: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CleaningPreview(BaseModel):
    changes: list[CleaningChange]
    affected_rows: int
    affected_cells: int
    resulting_rows: int
    warnings: list[str] = Field(default_factory=list)


class CleaningApplyResponse(BaseModel):
    preview: CleaningPreview
    audit_entries: list[dict[str, Any]]
    profile: DatasetProfile
    version: int | None = None


class DatasetVersion(BaseModel):
    version: int
    created_at: datetime
    operation: str
    description: str
    affected_rows: int = 0
    source_version: int | None = None
    is_current: bool = False


class VersionListResponse(BaseModel):
    current_version: int
    versions: list[DatasetVersion]


class ReportRequest(BaseModel):
    title: str = Field(default="DataPilot AI Analysis Report", min_length=1, max_length=120)
    include_profile: bool = True
    include_insights: bool = True
    include_quality: bool = True
    include_charts: bool = True
    include_version_history: bool = False
    format: Literal["html", "pdf"] = "html"
    async_job: bool = False


class AnalyzeRequest(BaseModel):
    plan: AnalysisPlan
    session_id: str | None = None
    question: str | None = Field(default=None, max_length=500)


class AnalysisResponse(BaseModel):
    plan: AnalysisPlan
    result: Any
    explanation: dict[str, Any]
    metadata: dict[str, Any]


class SessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class SessionResponse(BaseModel):
    id: str
    dataset_id: str
    title: str | None = None
    current_dataset_version: int
    created_at: datetime
    last_activity_at: datetime


class AnalysisRunResponse(BaseModel):
    id: str
    session_id: str | None
    dataset_id: str
    dataset_version: int
    question: str | None
    query_plan: dict[str, Any]
    result_summary: Any | None
    execution_engine: str | None
    execution_duration_ms: float | None
    ai_provider: str | None
    ai_explanation: str | None
    success: bool
    error_code: str | None
    created_at: datetime


class SavedAnalysisRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    plan: AnalysisPlan
    chart_config: dict[str, Any] | None = None


class SavedAnalysisResponse(BaseModel):
    id: str
    dataset_id: str
    name: str
    query_plan: dict[str, Any]
    chart_config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class JobResponse(BaseModel):
    id: str
    type: str
    dataset_id: str | None
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    stage: str
    progress: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    result_reference: str | None


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str = "queued"


class DrillDownRequest(BaseModel):
    base_plan: AnalysisPlan
    clicked_dimension: str
    clicked_value: Any
    next_dimension: str
    breadcrumb: list[str] = Field(default_factory=list, max_length=10)


class DrillDownResponse(BaseModel):
    plan: AnalysisPlan
    result: Any
    breadcrumb: list[str]
    metadata: dict[str, Any]

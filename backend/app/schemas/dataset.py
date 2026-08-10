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


class ColumnProfile(BaseModel):
    name: str
    data_type: str
    category: Literal["numeric", "categorical", "date", "boolean"]
    missing_count: int
    missing_percentage: float
    unique_count: int
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
    missing_values: int
    duplicate_rows: int
    date_range: dict[str, str] | None = None


FilterOperator = Literal[
    "equals", "not_equals", "greater_than", "greater_than_or_equal",
    "less_than", "less_than_or_equal", "contains", "starts_with",
    "ends_with", "between", "in", "before", "after",
]


class FilterCondition(BaseModel):
    column: str
    operator: FilterOperator
    value: Any

    @model_validator(mode="after")
    def validate_value_shape(self) -> "FilterCondition":
        if self.operator in {"between", "in"} and not isinstance(self.value, list):
            raise ValueError(f"Filter '{self.operator}' requires a list value")
        if self.operator == "between" and len(self.value) != 2:
            raise ValueError("Between requires exactly two values")
        return self


Operation = Literal[
    "aggregate", "group_and_aggregate", "filter", "sort", "top_n",
    "bottom_n", "count", "distinct_count", "trend", "compare_groups",
    "compare_periods",
]
Aggregation = Literal["sum", "mean", "min", "max", "count", "median"]


class AnalysisPlan(BaseModel):
    operation: Operation
    metric: str | None = None
    aggregation: Aggregation | None = None
    group_by: list[str] = Field(default_factory=list)
    filters: list[FilterCondition] = Field(default_factory=list)
    sort: Literal["asc", "desc"] | None = None
    limit: int = Field(default=10, ge=1, le=100)
    date_column: str | None = None
    time_granularity: Literal["day", "week", "month", "quarter", "year"] | None = None
    compare_values: list[str] = Field(default_factory=list, max_length=20)
    period_mode: Literal["month", "quarter", "year"] | None = None

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


class ChartSuggestion(BaseModel):
    type: Literal["bar", "column", "line", "pie", "scatter"]


class AskResponse(BaseModel):
    question: str
    plan: AnalysisPlan
    answer: str
    result: Any
    chart_suggestion: ChartSuggestion | None = None


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


class QualityIssue(BaseModel):
    issue_type: str
    column: str | None = None
    count: int
    examples: list[str] = Field(default_factory=list)
    severity: Literal["info", "warning", "critical"] = "warning"


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

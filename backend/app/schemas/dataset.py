from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class AnalysisPlan(BaseModel):
    operation: Literal["aggregate", "count", "top_n", "bottom_n"]
    metric: str | None = None
    aggregation: Literal["sum", "mean", "min", "max", "count"] | None = None
    group_by: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class AskResponse(BaseModel):
    question: str
    plan: AnalysisPlan
    answer: str
    result: Any

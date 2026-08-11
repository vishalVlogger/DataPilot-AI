export type DatasetMetadata = {
  id: string;
  name: string;
  source_type: "csv" | "excel";
  sheet_name: string | null;
  rows: number;
  columns: number;
  created_at: string;
  updated_at?: string | null;
  current_version?: number;
  storage_format?: string;
  status?: string;
  last_analyzed_at?: string | null;
};

export type ColumnProfile = {
  name: string;
  data_type: string;
  category: "numeric" | "categorical" | "date" | "boolean";
  missing_count: number;
  missing_percentage: number;
  unique_count: number;
  minimum?: string | number | null;
  maximum?: string | number | null;
  mean?: number | null;
  sum?: number | null;
};

export type DatasetProfile = {
  dataset_id: string;
  row_count: number;
  column_count: number;
  columns: ColumnProfile[];
  numeric_columns: string[];
  categorical_columns: string[];
  date_columns: string[];
  missing_values: number;
  duplicate_rows: number;
  date_range: { minimum: string; maximum: string } | null;
};

export type AskResponse = {
  question: string;
  answer: string;
  result: unknown;
  plan: Record<string, unknown>;
  chart_suggestion?: { type: ChartType } | null;
  explanation?: { metric?: string | null; aggregation?: string | null; grouped_by?: string[]; filters?: unknown[]; date_filter?: unknown } | null;
  metadata?: { execution_engine?: string; dataset_version?: number; execution_ms?: number; provider_fallback?: boolean; cached?: boolean; session_id?: string; run_id?: string } | null;
};

export type Insight = { type: string; severity: "info" | "warning" | "critical"; title: string; description: string; metric?: string | null; value?: number | string | null };
export type QualityIssue = { issue_type: string; column: string | null; count: number; examples: string[]; severity: "info" | "warning" | "critical" };
export type ChartType = "bar" | "column" | "line" | "pie" | "scatter";
export type ChartResponse = { type: ChartType; title: string; x_axis: string; y_axis: string; x_axis_label?: string | null; y_axis_label?: string | null; show_legend?: boolean; drill_down?: Record<string, unknown> | null; data: Record<string, string | number | null>[]; plan: Record<string, unknown>; interpreted_request: string };
export type CleaningType = "remove_duplicates" | "trim_whitespace" | "standardize_lowercase" | "standardize_uppercase" | "standardize_titlecase" | "remove_missing_rows" | "fill_missing_mean" | "fill_missing_median" | "fill_missing_value";
export type CleaningOperation = { type: CleaningType; column?: string; value?: string | number };
export type CleaningPreview = { changes: { operation: CleaningOperation; affected_rows: number; affected_cells: number; before_examples: string[]; after_examples: string[]; warnings: string[] }[]; affected_rows: number; affected_cells: number; resulting_rows: number; warnings: string[] };
export type DatasetVersion = { version: number; created_at: string; operation: string; description: string; affected_rows: number; source_version: number | null; is_current: boolean };
export type VersionList = { current_version: number; versions: DatasetVersion[] };
export type ReportOptions = { title: string; include_profile: boolean; include_insights: boolean; include_quality: boolean; include_charts: boolean; include_version_history: boolean; format: "html" | "pdf"; async_job: boolean };
export type AnalysisSession = { id: string; dataset_id: string; title: string | null; current_dataset_version: number; created_at: string; last_activity_at: string };
export type SavedAnalysis = { id: string; dataset_id: string; name: string; query_plan: Record<string, unknown>; chart_config: Record<string, unknown> | null; created_at: string; updated_at: string };
export type Job = { id: string; type: string; dataset_id: string | null; status: "queued" | "running" | "completed" | "failed" | "cancelled"; stage: string; progress: number | null; error_message: string | null; result_reference: string | null };
export type DrillDownResponse = { plan: Record<string, unknown>; result: Record<string, string | number | null>[]; breadcrumb: string[]; metadata: Record<string, unknown> };

export type DatasetMetadata = {
  id: string;
  name: string;
  source_type: "csv" | "excel";
  sheet_name: string | null;
  rows: number;
  columns: number;
  created_at: string;
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
};

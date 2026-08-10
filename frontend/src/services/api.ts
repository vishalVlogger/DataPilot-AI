import type { AskResponse, ChartResponse, ChartType, CleaningOperation, CleaningPreview, DatasetMetadata, DatasetProfile, Insight, QualityIssue } from "@/types/dataset";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

async function parse<T>(response: Response): Promise<T> {
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message ?? "Request failed");
  return payload as T;
}

export async function inspectWorkbook(file: File): Promise<string[]> {
  const body = new FormData();
  body.append("file", file);
  const result = await parse<{ sheets: { name: string }[] }>(await fetch(`${API_URL}/datasets/inspect`, { method: "POST", body }));
  return result.sheets.map((sheet) => sheet.name);
}

export async function uploadDataset(file: File, sheetName?: string): Promise<DatasetMetadata> {
  const body = new FormData();
  body.append("file", file);
  if (sheetName) body.append("sheet_name", sheetName);
  return parse(await fetch(`${API_URL}/datasets/upload`, { method: "POST", body }));
}

export async function getProfile(id: string): Promise<DatasetProfile> {
  return parse(await fetch(`${API_URL}/datasets/${id}/profile`));
}

export async function askDataset(id: string, question: string): Promise<AskResponse> {
  return parse(await fetch(`${API_URL}/datasets/${id}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) }));
}

export async function getInsights(id: string): Promise<Insight[]> {
  return parse(await fetch(`${API_URL}/datasets/${id}/insights`));
}

export async function getQuality(id: string): Promise<QualityIssue[]> {
  return parse(await fetch(`${API_URL}/datasets/${id}/quality`));
}

export async function createChart(id: string, question: string, chartType?: ChartType): Promise<ChartResponse> {
  return parse(await fetch(`${API_URL}/datasets/${id}/chart`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, chart_type: chartType }) }));
}

export async function previewCleaning(id: string, operations: CleaningOperation[]): Promise<CleaningPreview> {
  return parse(await fetch(`${API_URL}/datasets/${id}/clean/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operations }) }));
}

export async function applyCleaning(id: string, operations: CleaningOperation[]): Promise<{ preview: CleaningPreview; profile: DatasetProfile }> {
  return parse(await fetch(`${API_URL}/datasets/${id}/clean/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operations, confirmed: true }) }));
}

export async function resetDataset(id: string): Promise<DatasetProfile> {
  return parse(await fetch(`${API_URL}/datasets/${id}/reset`, { method: "POST" }));
}

export async function downloadExport(id: string, format: "csv" | "xlsx", version: "current" | "original" = "current"): Promise<void> {
  const response = await fetch(`${API_URL}/datasets/${id}/export?format=${format}&version=${version}`);
  if (!response.ok) return parse<never>(response);
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? `dataset.${format}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
}

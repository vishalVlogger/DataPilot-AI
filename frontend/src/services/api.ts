import type { AnalysisSession, AskResponse, ChartResponse, ChartType, CleaningOperation, CleaningPreview, DatasetMetadata, DatasetProfile, DrillDownResponse, Insight, Job, QualityIssue, ReportOptions, SavedAnalysis, VersionList } from "@/types/dataset";

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

export async function listDatasets(): Promise<DatasetMetadata[]> { return parse(await fetch(`${API_URL}/datasets`)); }
export async function getDataset(id: string): Promise<DatasetMetadata> { return parse(await fetch(`${API_URL}/datasets/${id}`)); }
export async function deleteDataset(id: string): Promise<void> { const response = await fetch(`${API_URL}/datasets/${id}`, { method: "DELETE" }); if (!response.ok) return parse<never>(response); }
export async function createSession(id: string, title?: string): Promise<AnalysisSession> { return parse(await fetch(`${API_URL}/datasets/${id}/sessions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) })); }

export async function askDataset(id: string, question: string, sessionId?: string): Promise<AskResponse> {
  return parse(await fetch(`${API_URL}/datasets/${id}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, session_id: sessionId }) }));
}

export async function getInsights(id: string): Promise<Insight[]> {
  return parse(await fetch(`${API_URL}/datasets/${id}/insights`));
}

export async function getQuality(id: string): Promise<QualityIssue[]> {
  return parse(await fetch(`${API_URL}/datasets/${id}/quality`));
}

export async function createChart(id: string, question: string, chartType?: ChartType, title?: string): Promise<ChartResponse> {
  return parse(await fetch(`${API_URL}/datasets/${id}/chart`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, chart_type: chartType, title }) }));
}

export async function getVersions(id: string): Promise<VersionList> {
  return parse(await fetch(`${API_URL}/datasets/${id}/versions`));
}

export async function restoreVersion(id: string, version: number): Promise<{ profile: DatasetProfile; version: number }> {
  return parse(await fetch(`${API_URL}/datasets/${id}/versions/${version}/restore`, { method: "POST" }));
}

export async function generateReport(id: string, options: ReportOptions): Promise<string> {
  const response = await fetch(`${API_URL}/datasets/${id}/report`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options) });
  if (!response.ok) return parse<never>(response);
  return response.text();
}

export async function createReportJob(id: string, options: ReportOptions): Promise<{ job_id: string; status: string }> {
  return parse(await fetch(`${API_URL}/datasets/${id}/report`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...options, async_job: true }) }));
}
export async function getJob(id: string): Promise<Job> { return parse(await fetch(`${API_URL}/jobs/${id}`)); }
export async function downloadJobResult(job: Job): Promise<void> { if (!job.result_reference) return; const response = await fetch(`${API_URL.replace(/\/api$/, "")}${job.result_reference}`); if (!response.ok) return parse<never>(response); const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `DataPilot_Report.${blob.type === "application/pdf" ? "pdf" : "html"}`; anchor.click(); URL.revokeObjectURL(url); }

export async function listSavedAnalyses(id: string): Promise<SavedAnalysis[]> { return parse(await fetch(`${API_URL}/datasets/${id}/saved-analyses`)); }
export async function saveAnalysis(id: string, name: string, plan: Record<string, unknown>, chartConfig?: Record<string, unknown>): Promise<SavedAnalysis> { return parse(await fetch(`${API_URL}/datasets/${id}/saved-analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, plan, chart_config: chartConfig }) })); }
export async function runSavedAnalysis(id: string): Promise<{ plan: Record<string, unknown>; result: unknown; chart_config: Record<string, unknown> | null }> { return parse(await fetch(`${API_URL}/saved-analyses/${id}/run`, { method: "POST" })); }
export async function deleteSavedAnalysis(id: string): Promise<void> { const response = await fetch(`${API_URL}/saved-analyses/${id}`, { method: "DELETE" }); if (!response.ok) return parse<never>(response); }
export async function drillDown(id: string, basePlan: Record<string, unknown>, clickedDimension: string, clickedValue: unknown, nextDimension: string, breadcrumb: string[]): Promise<DrillDownResponse> { return parse(await fetch(`${API_URL}/datasets/${id}/drilldown`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_plan: basePlan, clicked_dimension: clickedDimension, clicked_value: clickedValue, next_dimension: nextDimension, breadcrumb }) })); }

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

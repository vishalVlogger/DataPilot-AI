import type { AskResponse, DatasetMetadata, DatasetProfile } from "@/types/dataset";

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
